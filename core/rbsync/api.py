"""Binds the service layer to JSON-RPC method names."""

from __future__ import annotations

from pathlib import Path

from . import paths
from .app import AppService
from .spotify import PlaylistAccessDenied
from .rpc import RpcServer
from .serialize import playlist_to_dict, sync_plan_to_dict, track_to_dict
from .spotify import Tokens, build_authorize_url, exchange_code, make_verifier
from .sync import SyncPlan, wantlist_rows, wantlist_text


def build_server(service: AppService | None = None, out=None) -> RpcServer:
    service = service or AppService()
    server = RpcServer(service=service, out=out)
    # Plans are held between plan and apply so the UI applies exactly what the
    # user previewed, rather than a freshly computed plan that may differ.
    state: dict = {"plan": None, "verifier": None}

    def status(**_):
        return service.status()

    def settings_get(**_):
        return {
            "clientId": service.client_id(),
            "autoAccept": service.match_config().auto_accept,
            "reject": service.match_config().reject,
            "allowRemovals": service.allow_removals(),
            "onlySyncable": service.only_syncable(),
        }

    def settings_set(clientId=None, autoAccept=None, reject=None, allowRemovals=None,
                     onlySyncable=None, **_):
        if clientId is not None:
            service.cache.set_setting("spotify_client_id", str(clientId))
        if autoAccept is not None:
            service.cache.set_setting("auto_accept", str(float(autoAccept)))
        if reject is not None:
            service.cache.set_setting("reject", str(float(reject)))
        if allowRemovals is not None:
            service.cache.set_setting("allow_removals", "1" if allowRemovals else "0")
        if onlySyncable is not None:
            service.cache.set_setting("only_syncable", "1" if onlySyncable else "0")
        return settings_get()

    def auth_begin(redirectUri="http://127.0.0.1:8888/callback", **_):
        verifier = make_verifier()
        state["verifier"] = verifier
        return {
            "url": build_authorize_url(service.client_id(), redirectUri, verifier),
            "redirectUri": redirectUri,
        }

    def auth_complete(code="", redirectUri="http://127.0.0.1:8888/callback", **_):
        if not state.get("verifier"):
            raise RuntimeError("no sign-in in progress")
        tokens = exchange_code(service.client_id(), redirectUri, code, state["verifier"])
        service.tokens.save(tokens)
        state["verifier"] = None
        return {"authenticated": True}

    def auth_set_tokens(accessToken="", refreshToken="", expiresAt=0, **_):
        """Let the Tauri shell own token storage in the OS keychain."""
        service.tokens.save(Tokens(accessToken, refreshToken, float(expiresAt)))
        return {"authenticated": True}

    def auth_clear(**_):
        service.tokens.clear()
        return {"authenticated": False}

    def library_load(**_):
        count = service.load_library(progress=server.progress)
        return {"tracks": count}

    def playlists_list(**_):
        server.progress("Fetching playlists from Spotify")
        playlists = service.list_playlists()
        selected = set(service.cache.get_selected_playlists())
        return {
            "playlists": [
                {**playlist_to_dict(p), "selected": p.id in selected} for p in playlists
            ]
        }

    def playlists_cached(**_):
        """The last known playlist list, with no network access.

        Used to paint the sidebar on launch; the UI follows it with a live
        playlists.list and replaces the result.
        """
        selected = set(service.cache.get_selected_playlists())
        return {
            "playlists": [
                {**playlist_to_dict(p), "selected": p.id in selected}
                for p in service.cached_playlists()
            ]
        }

    def playlists_set_selected(playlistIds=None, **_):
        ids = list(playlistIds or [])
        service.cache.set_selected_playlists(ids)
        return {"selected": ids}

    def playlists_tracks(playlistId=None, **_):
        """A playlist's Spotify contents, with no matching involved.

        Lets the user look inside a playlist before committing to a sync.
        """
        if not playlistId:
            raise RuntimeError("playlistId is required")
        client = service.spotify()
        try:
            tracks = client.playlist_tracks(playlistId)
        except PlaylistAccessDenied as exc:
            return {"tracks": [], "error": str(exc)}
        finally:
            client.close()
        return {"tracks": [track_to_dict(t) for t in tracks], "error": None}

    def sync_plan(playlistIds=None, force=False, **_):
        ids = list(playlistIds or service.cache.get_selected_playlists())
        if not ids:
            raise RuntimeError("No playlists selected. Choose playlists first.")
        plan = service.plan(ids, progress=server.progress, force=bool(force))
        state["plan"] = plan
        return sync_plan_to_dict(plan)

    def plans_cached(playlistIds=None, **_):
        """Plans stored from an earlier run, loaded without any network access.

        Lets the app show the last result immediately on launch instead of
        making the user re-plan every time.
        """
        ids = list(playlistIds or service.cache.get_selected_playlists())
        plans = service.cached_plans(ids)
        state["plan"] = SyncPlan(playlists=plans) if plans else state.get("plan")
        return {
            **sync_plan_to_dict(SyncPlan(playlists=plans)),
            "stored": service.stored_plan_state(ids),
        }

    def sync_apply(**_):
        plan = state.get("plan")
        if plan is None:
            raise RuntimeError("Nothing to apply. Run sync.plan first.")
        results = service.apply(plan, progress=server.progress)
        state["plan"] = None
        return {
            "results": [
                {
                    "playlistId": r.playlist_id,
                    "playlistName": r.playlist_name,
                    "added": r.added,
                    "removed": r.removed,
                    "backupPath": r.backup_path,
                    "matched": r.matched,
                    "review": r.review,
                    "missing": r.missing,
                    "total": r.total,
                }
                for r in results
            ]
        }

    def history_list(playlistId=None, limit=50, **_):
        entries = service.history(playlist_id=playlistId, limit=int(limit))
        return {
            "entries": [
                {
                    "playlistId": entry.playlist_id,
                    "playlistName": entry.playlist_name,
                    "added": entry.added,
                    "removed": entry.removed,
                    "matched": entry.matched,
                    "total": entry.total,
                    "coveragePercent": entry.coverage_percent,
                    "syncedAt": entry.synced_at,
                    "backupPath": entry.backup_path,
                }
                for entry in entries
            ]
        }

    def tracks_verify(contentIds=None, **_):
        """Which matched files are actually still on disk."""
        return {"files": service.verify_files(list(contentIds or []))}

    def backups_list(**_):
        return {"backups": service.list_backups()}

    def backups_create(**_):
        server.progress("Backing up your rekordbox library")
        return service.create_backup()

    def backups_restore(path=None, **_):
        if not path:
            raise RuntimeError("path is required")
        server.progress("Restoring rekordbox library")
        return service.restore_backup(str(path))

    def rekordbox_tree(**_):
        """The full rekordbox playlist tree, not just the Spotify folder."""
        return {"nodes": service.rekordbox_tree()}

    def rekordbox_repair(**_):
        """Re-register playlists rekordbox cannot see because the tree file
        was never updated."""
        server.progress("Checking the rekordbox playlist tree")
        return service.repair_playlist_tree()

    def library_health(**_):
        """Whole-collection file availability, split by cause."""
        return service.library_health()

    def rekordbox_playlists(**_):
        """The playlists inside rekordbox's Spotify folder, plus whether the
        playlist tree file agrees with the database."""
        return {
            "playlists": service.rekordbox_playlists(),
            **service.playlist_tree_status(),
        }

    def review_decide(decisions=None, **_):
        return {"decided": service.decide_bulk(list(decisions or []))}

    def wantlist_get(**_):
        plan = state.get("plan")
        if plan is None:
            return {"rows": [], "text": ""}
        return {
            "rows": wantlist_rows(plan.playlists, deduplicate=True),
            "text": wantlist_text(plan.playlists),
        }

    def wantlist_export(path=None, format="both", **_):
        # Validate the argument before the state check, so a bad format reports
        # the bad format rather than blaming the missing plan.
        if format not in ("csv", "txt", "both"):
            raise ValueError(f"unsupported wantlist format: {format}")
        plan = state.get("plan")
        if plan is None:
            raise RuntimeError("Nothing to export. Run sync.plan first.")

        formats = ("csv", "txt") if format == "both" else (format,)
        written: list[str] = []
        for fmt in formats:
            target = Path(path) if path else None
            if target is not None and len(formats) > 1:
                target = target.with_suffix(f".{fmt}")
            elif target is None:
                target = paths.exports_dir() / f"wantlist.{fmt}"
            written.append(str(service.export_wantlist(plan, target, fmt=fmt)))
        return {"paths": written, "path": written[0]}

    for name, handler in (
        ("status", status),
        ("settings.get", settings_get),
        ("settings.set", settings_set),
        ("auth.begin", auth_begin),
        ("auth.complete", auth_complete),
        ("auth.setTokens", auth_set_tokens),
        ("auth.clear", auth_clear),
        ("library.load", library_load),
        ("playlists.list", playlists_list),
        ("playlists.cached", playlists_cached),
        ("playlists.setSelected", playlists_set_selected),
        ("playlists.tracks", playlists_tracks),
        ("sync.plan", sync_plan),
        ("plans.cached", plans_cached),
        ("sync.apply", sync_apply),
        ("review.decide", review_decide),
        ("tracks.verify", tracks_verify),
        ("rekordbox.playlists", rekordbox_playlists),
        ("library.health", library_health),
        ("rekordbox.repair", rekordbox_repair),
        ("rekordbox.tree", rekordbox_tree),
        ("backups.list", backups_list),
        ("backups.create", backups_create),
        ("backups.restore", backups_restore),
        ("history.list", history_list),
        ("wantlist.get", wantlist_get),
        ("wantlist.export", wantlist_export),
    ):
        server.register(name, handler)

    return server
