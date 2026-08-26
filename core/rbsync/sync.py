"""Turning Spotify playlists into a reviewable, appliable plan.

Nothing in this module writes anything. It produces a description of what a
sync *would* do, which the UI shows as a preview and the user approves. That
separation is what makes an irreversible operation safe to offer: the risky
step is a mechanical application of an already-inspected plan.

Two policies live here:

* **Additive by default.** A track missing from Spotify is not removed from
  rekordbox unless the user opts in, because the rekordbox playlist may contain
  deliberate local additions the user does not want destroyed.
* **Cached decisions win.** A judgement the user already made is applied
  without re-asking, including rejections.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cache import Cache
from .matcher import Band, MatchCandidate, MatchConfig, TrackIndex, match_track
from .models import Coverage, SpotifyPlaylist, SpotifyTrack
from .normalize import normalize_artist, normalize_title


@dataclass(slots=True)
class TrackPlan:
    track: SpotifyTrack
    band: Band
    content_id: str | None = None
    score: float = 0.0
    reason: str = "score"
    candidates: list[MatchCandidate] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.band is Band.ACCEPT and self.content_id is not None


@dataclass(slots=True)
class PlaylistPlan:
    playlist: SpotifyPlaylist
    tracks: list[TrackPlan] = field(default_factory=list)
    to_add: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    # Set when the playlist could not be read at all; it is then carried through
    # the plan so the UI can explain it rather than silently dropping it.
    error: str | None = None

    def tracks_in_band(self, band: Band) -> list[TrackPlan]:
        return [t for t in self.tracks if t.band is band]


@dataclass(slots=True)
class SyncPlan:
    playlists: list[PlaylistPlan] = field(default_factory=list)

    @property
    def coverage(self) -> Coverage:
        total = Coverage()
        for plan in self.playlists:
            total.matched += plan.coverage.matched
            total.review += plan.coverage.review
            total.missing += plan.coverage.missing
        return total


def plan_playlist(
    playlist: SpotifyPlaylist,
    tracks: list[SpotifyTrack],
    index: TrackIndex,
    cache: Cache,
    existing_content_ids: list[str] | None = None,
    *,
    config: MatchConfig | None = None,
    allow_removals: bool = False,
) -> PlaylistPlan:
    """Decide what syncing one playlist would do, without doing any of it."""
    config = config or MatchConfig()
    existing = list(existing_content_ids or [])
    existing_set = set(existing)

    plan = PlaylistPlan(playlist=playlist)
    desired: list[str] = []

    for track in tracks:
        decision = cache.get_decision(track.id)
        if decision is not None:
            # The user already ruled on this track; honour it silently.
            if decision.accepted:
                # Resolve the remembered id back to a real track, so the UI can
                # show which file the decision pointed at instead of an empty
                # cell. The track may since have been removed from rekordbox.
                local = index.get(decision.content_id)
                candidates = (
                    [
                        MatchCandidate(
                            track=local, score=1.0, reason="cached",
                            title_score=1.0, artist_score=1.0, duration_score=1.0,
                        )
                    ]
                    if local is not None
                    else []
                )
                track_plan = TrackPlan(
                    track=track, band=Band.ACCEPT,
                    content_id=decision.content_id, score=1.0, reason="cached",
                    candidates=candidates,
                )
            else:
                track_plan = TrackPlan(track=track, band=Band.REJECT, reason="cached")
            plan.tracks.append(track_plan)
        else:
            result = match_track(track, index, config)
            best = result.best
            track_plan = TrackPlan(
                track=track,
                band=result.band,
                content_id=best.track.id if (best and result.band is Band.ACCEPT) else None,
                score=best.score if best else 0.0,
                reason=best.reason if best else "no-candidates",
                candidates=result.candidates,
            )
            plan.tracks.append(track_plan)

        if track_plan.band is Band.ACCEPT:
            plan.coverage.matched += 1
            if track_plan.content_id:
                desired.append(track_plan.content_id)
        elif track_plan.band is Band.REVIEW:
            plan.coverage.review += 1
        else:
            plan.coverage.missing += 1

    seen: set[str] = set()
    for content_id in desired:
        if content_id in existing_set or content_id in seen:
            continue
        seen.add(content_id)
        plan.to_add.append(content_id)

    if allow_removals:
        desired_set = set(desired)
        plan.to_remove = [cid for cid in existing if cid not in desired_set]

    return plan


def plan_sync(
    playlist_tracks: list[tuple[SpotifyPlaylist, list[SpotifyTrack]]],
    index: TrackIndex,
    cache: Cache,
    existing: dict[str, list[str]] | None = None,
    *,
    config: MatchConfig | None = None,
    allow_removals: bool = False,
) -> SyncPlan:
    """Plan every selected playlist."""
    existing = existing or {}
    return SyncPlan(
        playlists=[
            plan_playlist(
                playlist, tracks, index, cache,
                existing.get(playlist.id, []),
                config=config, allow_removals=allow_removals,
            )
            for playlist, tracks in playlist_tracks
        ]
    )


def wantlist_rows(plans: list[PlaylistPlan], deduplicate: bool = False) -> list[dict]:
    """Tracks the user does not have locally, ready for export.

    This is the shopping list: what to go buy or download so the rekordbox
    playlist finally matches the Spotify one.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for plan in plans:
        for track_plan in plan.tracks:
            if track_plan.band is not Band.REJECT:
                continue
            track = track_plan.track
            if deduplicate:
                # Keyed on the normalized name rather than the Spotify id: the
                # same record appears under different ids across playlists and
                # releases, and the wantlist is a shopping list, not an index.
                artists = ",".join(sorted(normalize_artist(a) for a in track.artists))
                key = f"{normalize_title(track.name)}|{artists}"
                if key in seen:
                    continue
                seen.add(key)
            rows.append(
                {
                    "playlist": plan.playlist.name,
                    "artist": ", ".join(track.artists),
                    "title": track.name,
                    "album": track.album,
                    "duration_seconds": round(track.duration_seconds, 1),
                    "isrc": track.isrc,
                    "url": track.url,
                }
            )
    return rows


def wantlist_text(plans: list[PlaylistPlan], deduplicate: bool = True) -> str:
    """The wantlist as plain ``Artist - Title`` lines.

    Search tools like Soulseek take a pasted query, not a CSV, so the shopping
    list has to exist in a form that can be pasted straight into one.
    """
    rows = wantlist_rows(plans, deduplicate=deduplicate)
    return "\n".join(f"{row['artist']} - {row['title']}".strip(" -") for row in rows)
