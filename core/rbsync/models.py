"""Shared value objects.

These are deliberately plain dataclasses with no behaviour: they cross the
Spotify / matcher / rekordbox / RPC boundaries, and keeping them dumb keeps
those layers independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SpotifyTrack:
    id: str
    name: str
    artists: list[str]
    album: str
    duration_ms: int
    isrc: str = ""
    url: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def display(self) -> str:
        return f"{', '.join(self.artists)} - {self.name}"


@dataclass(frozen=True, slots=True)
class LocalTrack:
    """A row of rekordbox ``DjmdContent``."""

    id: str
    title: str
    artist: str
    length_seconds: float
    isrc: str = ""
    folder_path: str = ""
    file_name: str = ""
    bit_rate: int = 0
    file_size: int = 0
    analysed: int = 0

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def quality_rank(self) -> tuple[int, int, int]:
        """Preference order among duplicate copies of the same track.

        The user's library carries multiple copies for 82.8% of rows, so which
        copy lands in a playlist has to be a deliberate, repeatable choice
        rather than whichever row the index happened to visit first.
        """
        return (self.analysed, self.bit_rate, self.file_size)


@dataclass(frozen=True, slots=True)
class SpotifyPlaylist:
    id: str
    name: str
    track_count: int
    owner: str = ""
    snapshot_id: str = ""


@dataclass(frozen=True, slots=True)
class RbPlaylist:
    id: str
    name: str
    parent_id: str = "root"


@dataclass(slots=True)
class Coverage:
    matched: int = 0
    review: int = 0
    missing: int = 0

    @property
    def total(self) -> int:
        return self.matched + self.review + self.missing

    @property
    def percent(self) -> float:
        """Share of tracks confidently present in the local collection."""
        if self.total == 0:
            return 0.0
        return round(100.0 * self.matched / self.total, 1)

    def as_dict(self) -> dict:
        return {
            "matched": self.matched,
            "review": self.review,
            "missing": self.missing,
            "total": self.total,
            "percent": self.percent,
        }
