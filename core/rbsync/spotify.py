"""Spotify Web API access.

Authorization uses PKCE. A desktop application cannot keep a client secret —
anyone can unzip the bundle — so the secret-based flows are not an option here
regardless of convenience. PKCE is the supported answer for public clients.

The client accepts a ``transport`` so tests can serve canned pages: the test
suite must never depend on the network or on a live Spotify account.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .models import SpotifyPlaylist, SpotifyTrack

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = ("playlist-read-private", "playlist-read-collaborative")

# Spotify's PKCE verifier must be 43-128 characters of unreserved charset.
VERIFIER_BYTES = 64


@dataclass(frozen=True, slots=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def expired(self) -> bool:
        # Refresh slightly early so a long sync does not die mid-flight.
        return time.time() >= (self.expires_at - 30)

    def as_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }


def make_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(VERIFIER_BYTES)).decode("ascii").rstrip("=")


def verifier_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_authorize_url(client_id: str, redirect_uri: str, verifier: str, state: str = "") -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": verifier_challenge(verifier),
        "scope": " ".join(SCOPES),
    }
    if state:
        params["state"] = state
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _tokens_from_payload(payload: dict, fallback_refresh: str = "") -> Tokens:
    return Tokens(
        access_token=payload["access_token"],
        # A refresh response may omit the refresh token, meaning "keep the old one".
        refresh_token=payload.get("refresh_token") or fallback_refresh,
        expires_at=time.time() + float(payload.get("expires_in", 3600)),
    )


def exchange_code(client_id: str, redirect_uri: str, code: str, verifier: str) -> Tokens:
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    return _tokens_from_payload(response.json())


def refresh(client_id: str, tokens: Tokens) -> Tokens:
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return _tokens_from_payload(response.json(), fallback_refresh=tokens.refresh_token)


class _HttpxTransport:
    """Default transport: real HTTP, with 429 handling."""

    def __init__(self, access_token: str) -> None:
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {access_token}"}, timeout=30
        )

    def get(self, url: str, **kwargs) -> dict:
        for attempt in range(5):
            response = self._client.get(url)
            if response.status_code == 429:
                # Spotify tells us exactly how long to wait; obey it rather
                # than guessing, or the account gets throttled harder.
                delay = float(response.headers.get("Retry-After", "1"))
                time.sleep(min(delay, 30))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Spotify kept rate limiting the request")

    def close(self) -> None:
        self._client.close()


class PlaylistAccessDenied(RuntimeError):
    """Spotify refused to return a playlist's contents.

    Since the February 2026 API changes, playlist items are only served for
    playlists the user owns or collaborates on. A playlist the user merely
    follows answers 403, and that must not abort a sync of the others.
    """


class SpotifyClient:
    def __init__(self, tokens: Tokens, transport=None) -> None:
        self.tokens = tokens
        self._transport = transport or _HttpxTransport(tokens.access_token)

    def list_playlists(self) -> list[SpotifyPlaylist]:
        playlists: list[SpotifyPlaylist] = []
        url = f"{API_BASE}/me/playlists?limit=50"
        while url:
            payload = self._transport.get(url)
            for item in payload.get("items", []):
                if not item:
                    continue
                # Spotify moved the playlist size from ``tracks.total`` to
                # ``items.total`` and now returns ``tracks: null``. Read the new
                # field first and keep the old one as a fallback.
                counts = item.get("items") or item.get("tracks") or {}
                playlists.append(
                    SpotifyPlaylist(
                        id=item.get("id", ""),
                        name=item.get("name", "") or "",
                        track_count=int(counts.get("total", 0) or 0),
                        owner=((item.get("owner") or {}).get("display_name") or ""),
                        owner_id=((item.get("owner") or {}).get("id") or ""),
                        snapshot_id=item.get("snapshot_id", "") or "",
                    )
                )
            url = payload.get("next")
        return playlists

    def playlist_tracks(self, playlist_id: str) -> list[SpotifyTrack]:
        """Fetch a playlist's tracks.

        Uses the ``/items`` endpoint: ``/tracks`` now answers 403 Forbidden.
        """
        tracks: list[SpotifyTrack] = []
        url = f"{API_BASE}/playlists/{playlist_id}/items?limit=100"
        while url:
            try:
                payload = self._transport.get(url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    raise PlaylistAccessDenied(
                        f"Spotify will not share the contents of playlist {playlist_id}. "
                        "It only serves playlists you own or collaborate on."
                    ) from exc
                raise
            for item in payload.get("items", []):
                track = self._parse_track(item)
                if track is not None:
                    tracks.append(track)
            url = payload.get("next")
        return tracks

    @staticmethod
    def _parse_track(item: dict | None) -> SpotifyTrack | None:
        """Convert one playlist item, or None if it cannot be matched locally.

        Podcast episodes and Spotify "local files" are dropped: neither can be
        looked up as a record in the user's collection, and carrying them
        through would inflate the missing-track report with noise.
        """
        if not item:
            return None
        # The entry wraps the record under "item"; older payloads used "track".
        track = item.get("item") or item.get("track")
        if not track:
            return None
        if item.get("is_local") or track.get("is_local"):
            return None
        if track.get("type") not in (None, "track"):
            return None
        return SpotifyTrack(
            id=track.get("id", "") or "",
            name=track.get("name", "") or "",
            artists=[a.get("name", "") for a in (track.get("artists") or []) if a.get("name")],
            album=((track.get("album") or {}).get("name") or ""),
            duration_ms=int(track.get("duration_ms") or 0),
            isrc=((track.get("external_ids") or {}).get("isrc") or ""),
            url=((track.get("external_urls") or {}).get("spotify") or ""),
        )

    def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if close:
            close()
