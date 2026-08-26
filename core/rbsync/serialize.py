"""Plan → JSON conversion for the UI.

Kept apart from the planner so that the wire format can change without
touching matching logic, and so the UI's needs never leak into the core.
"""

from __future__ import annotations

from .matcher import MatchCandidate
from .models import SpotifyPlaylist, SpotifyTrack
from .sync import PlaylistPlan, SyncPlan, TrackPlan


def track_to_dict(track: SpotifyTrack) -> dict:
    return {
        "id": track.id,
        "name": track.name,
        "artists": list(track.artists),
        "album": track.album,
        "durationMs": track.duration_ms,
        "isrc": track.isrc,
        "url": track.url,
        "display": track.display,
    }


def candidate_to_dict(candidate: MatchCandidate) -> dict:
    return {
        "contentId": candidate.track.id,
        "display": candidate.track.display,
        "fileName": candidate.track.file_name,
        "folderPath": candidate.track.folder_path,
        "lengthSeconds": candidate.track.length_seconds,
        "bitRate": candidate.track.bit_rate,
        "score": candidate.score,
        "reason": candidate.reason,
        "titleScore": candidate.title_score,
        "artistScore": candidate.artist_score,
        "durationScore": candidate.duration_score,
    }


def track_plan_to_dict(plan: TrackPlan) -> dict:
    return {
        "track": track_to_dict(plan.track),
        "band": plan.band.value,
        "contentId": plan.content_id,
        "score": plan.score,
        "reason": plan.reason,
        "candidates": [candidate_to_dict(c) for c in plan.candidates],
    }


def playlist_to_dict(playlist: SpotifyPlaylist) -> dict:
    return {
        "id": playlist.id,
        "name": playlist.name,
        "trackCount": playlist.track_count,
        "owner": playlist.owner,
        "snapshotId": playlist.snapshot_id,
    }


def playlist_plan_to_dict(plan: PlaylistPlan) -> dict:
    return {
        "playlist": playlist_to_dict(plan.playlist),
        "tracks": [track_plan_to_dict(t) for t in plan.tracks],
        "toAdd": list(plan.to_add),
        "toRemove": list(plan.to_remove),
        "coverage": plan.coverage.as_dict(),
        "error": plan.error,
    }


def sync_plan_to_dict(plan: SyncPlan) -> dict:
    return {
        "playlists": [playlist_plan_to_dict(p) for p in plan.playlists],
        "coverage": plan.coverage.as_dict(),
    }
