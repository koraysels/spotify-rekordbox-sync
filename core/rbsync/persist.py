"""Storing a computed plan so it survives closing the app.

Planning is expensive: it fetches every selected playlist from Spotify and
matches each track against the whole collection. Re-doing that on every launch
is wasted work when nothing has changed.

This is deliberately a *full-fidelity* format rather than the UI wire format.
A restored plan is applied to the user's rekordbox library, so it has to carry
everything Apply and the review UI need — including each candidate's underlying
track — not just what the table happens to render.
"""

from __future__ import annotations

from .matcher import Band, MatchCandidate
from .models import Coverage, LocalTrack, SpotifyPlaylist, SpotifyTrack
from .sync import PlaylistPlan, TrackPlan

FORMAT_VERSION = 1


def _spotify_track_to_json(track: SpotifyTrack) -> dict:
    return {
        "id": track.id,
        "name": track.name,
        "artists": list(track.artists),
        "album": track.album,
        "duration_ms": track.duration_ms,
        "isrc": track.isrc,
        "url": track.url,
    }


def _spotify_track_from_json(data: dict) -> SpotifyTrack:
    return SpotifyTrack(
        id=data.get("id", ""),
        name=data.get("name", ""),
        artists=list(data.get("artists") or []),
        album=data.get("album", ""),
        duration_ms=int(data.get("duration_ms") or 0),
        isrc=data.get("isrc", ""),
        url=data.get("url", ""),
    )


def _local_track_to_json(track: LocalTrack) -> dict:
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "length_seconds": track.length_seconds,
        "isrc": track.isrc,
        "folder_path": track.folder_path,
        "file_name": track.file_name,
        "bit_rate": track.bit_rate,
        "file_size": track.file_size,
        "analysed": track.analysed,
    }


def _local_track_from_json(data: dict) -> LocalTrack:
    return LocalTrack(
        id=data.get("id", ""),
        title=data.get("title", ""),
        artist=data.get("artist", ""),
        length_seconds=float(data.get("length_seconds") or 0),
        isrc=data.get("isrc", ""),
        folder_path=data.get("folder_path", ""),
        file_name=data.get("file_name", ""),
        bit_rate=int(data.get("bit_rate") or 0),
        file_size=int(data.get("file_size") or 0),
        analysed=int(data.get("analysed") or 0),
    )


def _candidate_to_json(candidate: MatchCandidate) -> dict:
    return {
        "track": _local_track_to_json(candidate.track),
        "score": candidate.score,
        "reason": candidate.reason,
        "title_score": candidate.title_score,
        "artist_score": candidate.artist_score,
        "duration_score": candidate.duration_score,
    }


def _candidate_from_json(data: dict) -> MatchCandidate:
    return MatchCandidate(
        track=_local_track_from_json(data.get("track") or {}),
        score=float(data.get("score") or 0),
        reason=data.get("reason", "score"),
        title_score=float(data.get("title_score") or 0),
        artist_score=float(data.get("artist_score") or 0),
        duration_score=float(data.get("duration_score") or 0),
    )


def plan_to_json(plan: PlaylistPlan) -> dict:
    playlist = plan.playlist
    return {
        "version": FORMAT_VERSION,
        "playlist": {
            "id": playlist.id,
            "name": playlist.name,
            "track_count": playlist.track_count,
            "owner": playlist.owner,
            "snapshot_id": playlist.snapshot_id,
            "owner_id": playlist.owner_id,
            "collaborative": playlist.collaborative,
        },
        "tracks": [
            {
                "track": _spotify_track_to_json(t.track),
                "band": t.band.value,
                "content_id": t.content_id,
                "score": t.score,
                "reason": t.reason,
                "candidates": [_candidate_to_json(c) for c in t.candidates],
            }
            for t in plan.tracks
        ],
        "to_add": list(plan.to_add),
        "to_remove": list(plan.to_remove),
        "coverage": {
            "matched": plan.coverage.matched,
            "review": plan.coverage.review,
            "missing": plan.coverage.missing,
        },
        "error": plan.error,
    }


def plan_from_json(data: dict) -> PlaylistPlan:
    playlist_data = data.get("playlist") or {}
    coverage_data = data.get("coverage") or {}
    return PlaylistPlan(
        playlist=SpotifyPlaylist(
            id=playlist_data.get("id", ""),
            name=playlist_data.get("name", ""),
            track_count=int(playlist_data.get("track_count") or 0),
            owner=playlist_data.get("owner", ""),
            snapshot_id=playlist_data.get("snapshot_id", ""),
            owner_id=playlist_data.get("owner_id", ""),
            collaborative=bool(playlist_data.get("collaborative")),
        ),
        tracks=[
            TrackPlan(
                track=_spotify_track_from_json(t.get("track") or {}),
                band=Band(t.get("band", "reject")),
                content_id=t.get("content_id"),
                score=float(t.get("score") or 0),
                reason=t.get("reason", "score"),
                candidates=[_candidate_from_json(c) for c in (t.get("candidates") or [])],
            )
            for t in (data.get("tracks") or [])
        ],
        to_add=list(data.get("to_add") or []),
        to_remove=list(data.get("to_remove") or []),
        coverage=Coverage(
            matched=int(coverage_data.get("matched") or 0),
            review=int(coverage_data.get("review") or 0),
            missing=int(coverage_data.get("missing") or 0),
        ),
        error=data.get("error"),
    )
