"""A fake Spotify account, for developing and demonstrating the UI.

Enabled only when ``RBSYNC_FAKE_SPOTIFY=1`` and only by ``rbsync serve``, so
none of this reaches the packaged application.

The fake playlists are built from the user's real rekordbox collection with
realistic damage applied — Spotify-style featured-artist placement, slightly
different durations, plus tracks that deliberately do not exist locally. That
exercises all three match bands with data that behaves like the real thing.
"""

from __future__ import annotations

import os
import random

from .models import SpotifyPlaylist, SpotifyTrack

FAKE_PLAYLISTS = [
    ("fake-warmup", "Warm Up (demo)", 12),
    ("fake-peak", "Peak Time (demo)", 16),
    ("fake-closing", "Closing (demo)", 8),
]

# Tracks nobody has locally, so the wantlist is never empty in a demo.
UNOWNED = [
    ("Unreleased Dub Plate", "Anonymous Producer"),
    ("White Label 001", "Unknown Artist"),
    ("Forthcoming VIP", "Someone Else"),
]


DEMO_USER_ID = "demo-user"


class FakeSpotifyClient:
    def __init__(self, playlists, tracks):
        self._playlists = playlists
        self._tracks = tracks

    def list_playlists(self):
        return list(self._playlists)

    def current_user_id(self) -> str:
        return DEMO_USER_ID

    def playlist_tracks(self, playlist_id):
        return list(self._tracks.get(playlist_id, []))

    def close(self) -> None:
        return None


def _to_spotify(track, index: int, rng: random.Random) -> SpotifyTrack:
    name = track.title
    artist = track.artist
    # Spotify tends to carry the featured artist in a separate field rather
    # than inside the artist string, which is exactly what the matcher has to
    # cope with.
    for separator in (" Ft. ", " ft. ", " feat. ", " & "):
        if separator in artist:
            artist = artist.split(separator)[0]
            break
    return SpotifyTrack(
        id=f"fake-{index}",
        name=name,
        artists=[artist],
        album="",
        duration_ms=int(track.length_seconds * 1000) + rng.randint(-2000, 2000),
        isrc="",
        url="https://open.spotify.com/track/fake",
    )


def build_fake_client(service) -> FakeSpotifyClient:
    rng = random.Random(11)
    pool = [t for t in service.index.tracks if t.title and t.length_seconds > 60]
    rng.shuffle(pool)

    playlists = []
    tracks: dict[str, list[SpotifyTrack]] = {}
    cursor = 0
    for playlist_id, name, size in FAKE_PLAYLISTS:
        chosen = pool[cursor : cursor + size]
        cursor += size
        entries = [_to_spotify(track, cursor + i, rng) for i, track in enumerate(chosen)]
        for offset, (title, artist) in enumerate(UNOWNED[: max(1, size // 6)]):
            entries.append(
                SpotifyTrack(
                    id=f"fake-missing-{playlist_id}-{offset}",
                    name=title,
                    artists=[artist],
                    album="",
                    duration_ms=210_000,
                    isrc="",
                    url="https://open.spotify.com/track/missing",
                )
            )
        rng.shuffle(entries)
        tracks[playlist_id] = entries
        playlists.append(
            SpotifyPlaylist(
                id=playlist_id, name=name, track_count=len(entries),
                owner="demo", owner_id=DEMO_USER_ID,
            )
        )
    return FakeSpotifyClient(playlists, tracks)


def enabled() -> bool:
    return os.environ.get("RBSYNC_FAKE_SPOTIFY") == "1"


def install(service) -> None:
    """Point the service at the fake account and mark it signed in.

    Run this with an isolated ``RBSYNC_HOME`` so the placeholder token never
    lands in a real profile.
    """
    import time

    from .app import AppService
    from .spotify import Tokens

    service.tokens.save(Tokens("fake-access", "fake-refresh", time.time() + 3600))
    AppService.spotify = lambda self: build_fake_client(self)  # type: ignore[method-assign]
