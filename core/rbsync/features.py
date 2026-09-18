"""Audio features (energy, danceability, ...) for tracks.

Spotify closed its own audio-features endpoint to new apps (it answers 403), so
features come from ReccoBeats, a free public API that accepts Spotify track
IDs or ISRCs. It needs no key.

rekordbox tracks carry no Spotify ID. ``resolve_spotify_track`` finds the
Spotify track a local file is, via search, reusing the matcher's scoring so a
wrong-artist or wrong-version hit is not trusted.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, replace
from typing import Callable

import httpx

from .keys import camelot_from_pitch
from .matcher import TrackIndex
from .models import LocalTrack, SpotifyTrack
from .normalize import normalize_artist, normalize_title

log = logging.getLogger(__name__)

RECCOBEATS_URL = "https://api.reccobeats.com/v1"
BATCH_SIZE = 40
MAX_RETRIES = 3

# Resolution through search is only trusted when it clearly is the same record.
RESOLVE_MIN_SCORE = 0.8
RESOLVE_MIN_ARTIST = 0.5


def energy_level(energy: float) -> int:
    """Map a 0..1 energy value onto the 1..10 scale DJs tag with."""
    clamped = min(max(energy, 0.0), 1.0)
    return min(10, max(1, int(clamped * 10 + 0.5)))


def feature_levels(data: dict | None) -> dict:
    """energyLevel, danceLevel and moodLevel (1..10) for whichever values are known."""
    if not data:
        return {}
    levels = {}
    for source, key in (("energy", "energyLevel"), ("danceability", "danceLevel"), ("valence", "moodLevel")):
        if data.get(source) is not None:
            levels[key] = energy_level(float(data[source]))
    return levels


def tag_levels(data: dict | None) -> dict[str, int]:
    """The same levels keyed by My Tag kind: {"Energy": 7, "Dance": 6, "Mood": 3}."""
    levels = feature_levels(data)
    names = {"energyLevel": "Energy", "danceLevel": "Dance", "moodLevel": "Mood"}
    return {names[key]: value for key, value in levels.items()}


def camelot_of(data: dict | None) -> str:
    """Camelot key for a features dict, or empty when Spotify gave none."""
    if not data:
        return ""
    return camelot_from_pitch(data.get("key"), data.get("mode"))


@dataclass(frozen=True, slots=True)
class AudioFeatures:
    energy: float
    danceability: float | None = None
    valence: float | None = None
    tempo: float | None = None
    key: int | None = None
    mode: int | None = None
    loudness: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    liveness: float | None = None

    @property
    def energy_level(self) -> int:
        return energy_level(self.energy)

    def as_dict(self) -> dict:
        data = asdict(self)
        data.update(feature_levels(data))
        data["camelot"] = camelot_of(data)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AudioFeatures | None":
        if data.get("energy") is None:
            return None
        fields = cls.__dataclass_fields__
        return cls(**{name: data.get(name) for name in fields})


def _spotify_id_from_href(href: str) -> str:
    marker = "/track/"
    if marker not in (href or ""):
        return ""
    return href.split(marker, 1)[1].split("?", 1)[0].strip("/")


class ReccoBeatsClient:
    def __init__(self, transport=None) -> None:
        self._http = transport or httpx.Client(timeout=20.0)

    def audio_features(self, ids: list[str]) -> dict[str, AudioFeatures]:
        """Features keyed by the id asked for (Spotify ID or ISRC).

        Unknown ids are absent. A failing batch is logged and skipped so a
        long scan keeps what it already has.
        """
        wanted = [i for i in dict.fromkeys(ids) if i]
        result: dict[str, AudioFeatures] = {}
        for start in range(0, len(wanted), BATCH_SIZE):
            batch = wanted[start : start + BATCH_SIZE]
            try:
                rows = self._fetch(batch)
            except Exception as exc:  # noqa: BLE001 - one batch must not sink the scan
                log.warning("audio features batch failed: %s", exc)
                continue
            asked = set(batch)
            for row in rows:
                features = AudioFeatures.from_dict(row)
                if features is None:
                    continue
                for key in (_spotify_id_from_href(row.get("href", "")), (row.get("isrc") or "").upper()):
                    if key and key in asked:
                        result[key] = features
                # ISRCs may come back in a different case than they were asked.
                isrc = (row.get("isrc") or "").upper()
                for asked_id in batch:
                    if isrc and asked_id.upper() == isrc:
                        result[asked_id] = features
        return result

    def _fetch(self, batch: list[str]) -> list[dict]:
        for attempt in range(MAX_RETRIES + 1):
            response = self._http.get(f"{RECCOBEATS_URL}/audio-features", params={"ids": ",".join(batch)})
            if response.status_code == 429 and attempt < MAX_RETRIES:
                time.sleep(float(response.headers.get("Retry-After", "2") or 2))
                continue
            if response.status_code != 200:
                raise RuntimeError(f"ReccoBeats answered {response.status_code}")
            return response.json().get("content") or []
        return []

    def close(self) -> None:
        close = getattr(self._http, "close", None)
        if close:
            close()


def _clean_local(track: LocalTrack) -> LocalTrack:
    """Drop the artist when it is repeated inside the title ("Red Scan - Red Scan - X")."""
    title, artist = track.title.strip(), track.artist.strip()
    if artist:
        prefix = f"{artist} - ".lower()
        while title.lower().startswith(prefix):
            title = title[len(prefix):].strip()
    return replace(track, title=title) if title != track.title else track


def search_queries(track: LocalTrack) -> list[str]:
    """Field-filtered search first, then plain words, which forgives mix names and odd spellings."""
    # Search with the cleaned title: "(Official Video)" noise makes Spotify miss.
    title = normalize_title(track.title) or track.title.strip()
    artist = track.artist.strip()
    strict = f"track:{title} artist:{artist}" if artist else f"track:{title}"
    loose = f"{title} {normalize_artist(artist)}".strip()
    return [strict, loose] if loose != strict else [strict]


def search_query(track: LocalTrack) -> str:
    return search_queries(track)[0]


def resolve_spotify_track(
    track: LocalTrack, search: Callable[[str], list[SpotifyTrack]]
) -> SpotifyTrack | None:
    """The Spotify track that a local file is, or None when unsure."""
    track = _clean_local(track)
    if not track.title.strip():
        return None
    index = TrackIndex([track])
    for query in search_queries(track):
        found = _best_hit(index, search(query))
        if found is not None:
            return found
    return None


def _best_hit(index: TrackIndex, hits: list[SpotifyTrack]) -> SpotifyTrack | None:
    best: tuple[float, SpotifyTrack] | None = None
    for hit in hits:
        for candidate in index.search(hit):
            if candidate.reason == "isrc":
                return hit
            if candidate.artist_score < RESOLVE_MIN_ARTIST or candidate.score < RESOLVE_MIN_SCORE:
                continue
            if best is None or candidate.score > best[0]:
                best = (candidate.score, hit)
    return best[1] if best else None
