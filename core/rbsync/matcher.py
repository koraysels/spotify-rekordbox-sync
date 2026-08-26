"""Matching Spotify tracks to rekordbox collection rows.

Design notes worth keeping in view:

* The library survey found ISRC populated on only 4.2% of rows, so ISRC is a
  free exact-match fast path but cannot be the backbone. Normalized
  artist/title similarity discriminated by duration does the real work.
* Duration is the strongest guard available. A radio edit and an extended mix
  share a title and an artist; putting the wrong one in a DJ set is a real
  failure, so a large duration gap rejects outright.
* Brute-forcing every Spotify track against 12,630 rows is wasteful, so
  candidates are pre-filtered through a token inverted index and a duration
  window before any similarity is computed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from .models import LocalTrack, SpotifyTrack
from .normalize import (
    extract_mix_tags,
    normalize_artist,
    normalize_title,
    split_artists,
)


class Band(str, Enum):
    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class MatchConfig:
    auto_accept: float = 0.88
    reject: float = 0.62
    # Beyond this gap the tracks are different records, whatever the metadata says.
    max_duration_delta: float = 30.0
    # Full duration credit inside this window.
    duration_tolerance: float = 2.0
    # Zero duration credit at this gap.
    duration_falloff: float = 15.0
    weight_title: float = 0.55
    weight_artist: float = 0.30
    weight_duration: float = 0.15
    max_candidates: int = 10


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    track: LocalTrack
    score: float
    reason: str = "score"
    title_score: float = 0.0
    artist_score: float = 0.0
    duration_score: float = 0.0


@dataclass(slots=True)
class MatchResult:
    track: SpotifyTrack
    band: Band
    best: MatchCandidate | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)


def _looks_like_another_version(
    title: str, other_title: str, artists: list[str], other_artists: list[str]
) -> bool:
    """Whether two differently-long tracks are versions of the same record.

    An extended mix or edit carries the same name plus a descriptor and a very
    different length. Treating that as a plain duration mismatch reports "you do
    not own this" about a track sitting in the collection.
    """
    if not title or not other_title:
        return False

    shorter, longer = sorted((title, other_title), key=len)
    if not (longer.startswith(shorter) or _similarity(title, other_title) >= 0.75):
        return False

    # The artist still has to line up, or every long track sharing a common word
    # becomes a candidate.
    return _artist_similarity(artists, other_artists) >= 0.5


def _candidate_rank(candidate: MatchCandidate) -> tuple:
    """Order candidates best-first, breaking score ties deterministically.

    Duplicate copies of one track score identically, so without an explicit
    tie-break the chosen copy would depend on dictionary iteration order and
    could differ between runs. Prefer the analysed, higher-bitrate, larger file,
    then fall back to the id purely for stability.
    """
    analysed, bit_rate, file_size = candidate.track.quality_rank
    return (-candidate.score, -analysed, -bit_rate, -file_size, str(candidate.track.id))


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return 2.0 * overlap / (len(a) + len(b))


def _similarity(left: str, right: str) -> float:
    """Token-set similarity with a sequence fallback for near-spellings."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    dice = _dice(left_tokens, right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(dice, sequence)


def _artist_similarity(spotify_artists: list[str], local_artists: list[str]) -> float:
    """Mean over Spotify artists of their best match among the local artists.

    Rekordbox leaves the artist field empty on ~9% of rows. Scoring those as a
    flat zero would bury genuine matches, so they get a neutral score that is
    still low enough to keep the track out of the auto-accept band on its own.
    """
    if not local_artists:
        return 0.4
    if not spotify_artists:
        return 0.4
    best = [max(_similarity(a, b) for b in local_artists) for a in spotify_artists]
    return sum(best) / len(best)


def _duration_similarity(delta: float, config: MatchConfig) -> float:
    delta = abs(delta)
    if delta <= config.duration_tolerance:
        return 1.0
    if delta >= config.duration_falloff:
        return 0.0
    span = config.duration_falloff - config.duration_tolerance
    return 1.0 - (delta - config.duration_tolerance) / span


@dataclass(frozen=True, slots=True)
class _IndexedTrack:
    track: LocalTrack
    title: str
    artists: list[str]
    tags: frozenset[str]


class TrackIndex:
    """Inverted token index over a rekordbox collection."""

    def __init__(self, tracks: list[LocalTrack], config: MatchConfig | None = None) -> None:
        self.config = config or MatchConfig()
        self._tracks: list[_IndexedTrack] = []
        self._by_token: dict[str, set[int]] = defaultdict(set)
        self._by_isrc: dict[str, list[int]] = defaultdict(list)
        self._by_id: dict[str, int] = {}

        for position, track in enumerate(tracks):
            title = normalize_title(track.title)
            artists = split_artists(track.artist) or (
                [normalize_artist(track.artist)] if track.artist else []
            )
            indexed = _IndexedTrack(
                track=track,
                title=title,
                artists=[a for a in artists if a],
                tags=frozenset(extract_mix_tags(track.title)),
            )
            self._tracks.append(indexed)
            self._by_id[str(track.id)] = position
            for token in set(title.split()):
                self._by_token[token].add(position)
            for artist in indexed.artists:
                for token in set(artist.split()):
                    self._by_token[token].add(position)
            isrc = (track.isrc or "").strip().upper()
            if isrc:
                self._by_isrc[isrc].append(position)

    def __len__(self) -> int:
        return len(self._tracks)

    def get(self, content_id) -> LocalTrack | None:
        """Look up an indexed track by its rekordbox content id."""
        position = self._by_id.get(str(content_id))
        return self._tracks[position].track if position is not None else None

    @property
    def tracks(self) -> list[LocalTrack]:
        """The indexed collection, in insertion order."""
        return [entry.track for entry in self._tracks]

    def search(self, track: SpotifyTrack) -> list[MatchCandidate]:
        """Return scored candidates, best first."""
        if not self._tracks:
            return []

        isrc = (track.isrc or "").strip().upper()
        if isrc and isrc in self._by_isrc:
            # Exact identifier equality outranks every heuristic, and is
            # deliberately not subject to the duration window.
            return [
                MatchCandidate(
                    track=self._tracks[position].track,
                    score=1.0,
                    reason="isrc",
                    title_score=1.0,
                    artist_score=1.0,
                    duration_score=1.0,
                )
                for position in self._by_isrc[isrc]
            ]

        title = normalize_title(track.name)
        artists = [normalize_artist(a) for a in track.artists]
        tags = extract_mix_tags(track.name)

        tokens = set(title.split())
        for artist in artists:
            tokens |= set(artist.split())

        positions: set[int] = set()
        for token in tokens:
            positions |= self._by_token.get(token, set())
        if not positions:
            return []

        duration = track.duration_seconds
        scored: list[MatchCandidate] = []
        for position in positions:
            indexed = self._tracks[position]
            delta = (indexed.track.length_seconds or 0.0) - duration
            if abs(delta) > self.config.max_duration_delta:
                # A different length usually means a different record. The
                # exception is another version of the same one — a DJ owning the
                # extended mix of a track Spotify lists at radio length. Show it
                # for review rather than reporting "you do not own this".
                if not _looks_like_another_version(
                    title, indexed.title, artists, indexed.artists
                ):
                    continue
            scored.append(self._score(indexed, title, artists, tags, delta))

        scored.sort(key=_candidate_rank)
        return scored[: self.config.max_candidates]

    def _score(
        self,
        indexed: _IndexedTrack,
        title: str,
        artists: list[str],
        tags: set[str],
        delta: float,
    ) -> MatchCandidate:
        config = self.config
        title_score = _similarity(title, indexed.title)
        artist_score = _artist_similarity(artists, indexed.artists)
        duration_score = _duration_similarity(delta, config)

        score = (
            config.weight_title * title_score
            + config.weight_artist * artist_score
            + config.weight_duration * duration_score
        )

        reason = "score"
        if abs(delta) > config.max_duration_delta:
            # Never auto-accept a different-length version, whatever it scores.
            ceiling = max(config.auto_accept - 0.01, 0.0)
            score = min(score, ceiling)
            reason = "other-version"
        if tags != set(indexed.tags):
            # Different mix descriptors mean different records. Keep it out of
            # the auto-accept band and let a human look.
            ceiling = max(config.auto_accept - 0.01, 0.0)
            if score > ceiling:
                score = ceiling
            reason = "mix-mismatch"

        return MatchCandidate(
            track=indexed.track,
            score=round(score, 4),
            reason=reason,
            title_score=round(title_score, 4),
            artist_score=round(artist_score, 4),
            duration_score=round(duration_score, 4),
        )


def match_track(
    track: SpotifyTrack, index: TrackIndex, config: MatchConfig | None = None
) -> MatchResult:
    """Match one Spotify track and assign it to a confidence band."""
    config = config or index.config
    candidates = index.search(track)
    if not candidates:
        return MatchResult(track=track, band=Band.REJECT, best=None, candidates=[])

    best = candidates[0]
    if best.score >= config.auto_accept:
        band = Band.ACCEPT
    elif best.score > config.reject:
        band = Band.REVIEW
    else:
        band = Band.REJECT
    return MatchResult(track=track, band=band, best=best, candidates=candidates)
