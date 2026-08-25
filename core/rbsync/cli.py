"""Command line interface.

The desktop app is the primary surface, but a CLI is worth its keep: it makes
the core usable without the shell, gives support a way to reproduce problems,
and is the fastest way to check whether the library reads correctly.
"""

from __future__ import annotations

import argparse
import sys

from .app import AppService
from .sync import wantlist_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rbsync",
        description="Sync Spotify playlists into your rekordbox collection.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="show library, auth and selection state")

    config = sub.add_parser("config", help="view or change settings")
    config.add_argument("--client-id", dest="client_id")
    config.add_argument("--auto-accept", dest="auto_accept", type=float)
    config.add_argument("--reject", dest="reject", type=float)
    config.add_argument(
        "--allow-removals", dest="allow_removals", action="store_true", default=None
    )

    sub.add_parser("playlists", help="list your Spotify playlists")

    select = sub.add_parser("select", help="choose which playlists to sync")
    select.add_argument("playlist_ids", nargs="*")

    sub.add_parser("plan", help="preview what a sync would do")

    apply_cmd = sub.add_parser("apply", help="write the planned changes to rekordbox")
    apply_cmd.add_argument(
        "--yes", action="store_true",
        help="confirm writing to master.db (required)",
    )

    serve = sub.add_parser(
        "serve", help="run the JSON-RPC bridge on localhost (development only)"
    )
    serve.add_argument("--port", type=int, default=8765)

    history = sub.add_parser("history", help="show past syncs")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--playlist", dest="playlist", default=None)

    wantlist = sub.add_parser("wantlist", help="export tracks you are missing")
    wantlist.add_argument("--out", dest="out")
    wantlist.add_argument(
        "--format", dest="format", choices=("csv", "txt"), default=None,
        help="csv for a spreadsheet, txt for pasting into a search tool",
    )

    return parser


def _print_status(service: AppService) -> None:
    status = service.status()
    print(f"database:   {status['db_path'] or 'not found'}")
    print(f"rekordbox:  {'RUNNING (writes blocked)' if status['rekordbox_running'] else 'closed'}")
    print(f"spotify:    {'connected' if status['authenticated'] else 'not connected'}")
    print(f"client id:  {'set' if status['client_id_set'] else 'not set'}")
    print(f"selected:   {len(status['selected_playlists'])} playlist(s)")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # Writing to master.db is irreversible in practice, so it needs an explicit
    # confirmation rather than being the default behaviour of a bare command.
    if args.command == "apply" and not args.yes:
        print("Refusing to write to rekordbox without --yes.")
        print("Run 'rbsync plan' first, then 'rbsync apply --yes'.")
        return 2

    service = AppService()
    try:
        return _dispatch(args, service)
    except Exception as exc:  # noqa: BLE001 - CLI should report, not traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        service.close()


def _dispatch(args, service: AppService) -> int:
    if args.command == "status":
        _print_status(service)
        return 0

    if args.command == "config":
        if args.client_id is not None:
            service.cache.set_setting("spotify_client_id", args.client_id)
        if args.auto_accept is not None:
            service.cache.set_setting("auto_accept", str(args.auto_accept))
        if args.reject is not None:
            service.cache.set_setting("reject", str(args.reject))
        if args.allow_removals is not None:
            service.cache.set_setting("allow_removals", "1" if args.allow_removals else "0")
        config = service.match_config()
        print(f"client id:      {service.client_id() or '(not set)'}")
        print(f"auto accept:    {config.auto_accept}")
        print(f"reject below:   {config.reject}")
        print(f"allow removals: {service.allow_removals()}")
        return 0

    if args.command == "serve":
        from . import devfixtures
        from .httpbridge import serve as serve_bridge

        if devfixtures.enabled():
            print("RBSYNC_FAKE_SPOTIFY=1 - serving a fake Spotify account (demo data)")
            service.load_library()
            devfixtures.install(service)

        serve_bridge(service, port=args.port)
        return 0

    if args.command == "history":
        entries = service.history(playlist_id=args.playlist, limit=args.limit)
        if not entries:
            print("No syncs recorded yet.")
            return 0
        for entry in entries:
            name = entry.playlist_name or entry.playlist_id
            print(
                f"{entry.synced_at}  {name}: +{entry.added} -{entry.removed}  "
                f"{entry.coverage_percent}% matched ({entry.matched}/{entry.total})"
            )
        newest = entries[0]
        if newest.backup_path:
            print(f"\nmost recent backup: {newest.backup_path}")
        return 0

    if args.command == "playlists":
        selected = set(service.cache.get_selected_playlists())
        for playlist in service.list_playlists():
            mark = "x" if playlist.id in selected else " "
            print(f"[{mark}] {playlist.id}  {playlist.track_count:>4} tracks  {playlist.name}")
        return 0

    if args.command == "select":
        service.cache.set_selected_playlists(args.playlist_ids)
        print(f"selected {len(args.playlist_ids)} playlist(s)")
        return 0

    if args.command in ("plan", "apply", "wantlist"):
        selected = service.cache.get_selected_playlists()
        if not selected:
            print("No playlists selected. Run 'rbsync playlists' then 'rbsync select <id>...'.")
            return 2

        service.load_library(progress=lambda m: print(m, file=sys.stderr))
        plan = service.plan(selected, progress=lambda m: print(m, file=sys.stderr))

        if args.command == "wantlist":
            rows = wantlist_rows(plan.playlists, deduplicate=True)
            target = service.export_wantlist(plan, args.out, fmt=args.format)
            print(f"{len(rows)} missing track(s) written to {target}")
            return 0

        for playlist_plan in plan.playlists:
            coverage = playlist_plan.coverage
            print(
                f"{playlist_plan.playlist.name}: {coverage.percent}% matched "
                f"({coverage.matched}/{coverage.total}) "
                f"+{len(playlist_plan.to_add)} add, -{len(playlist_plan.to_remove)} remove, "
                f"{coverage.review} to review, {coverage.missing} missing"
            )

        if args.command == "plan":
            return 0

        results = service.apply(plan, progress=lambda m: print(m, file=sys.stderr))
        for result in results:
            print(f"{result.playlist_name}: +{result.added} -{result.removed}")
        if results:
            print(f"backup: {results[0].backup_path}")
        return 0

    return 0
