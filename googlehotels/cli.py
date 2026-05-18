from __future__ import annotations

import argparse
import asyncio

from .api import run_server
from .service import ScraperService, ServiceConfig, build_optional_query, build_query, parse_panels, render_stdout_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="googlehotels")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Initialize the SQLite database.")
    init_db.add_argument("--db", default="googlehotels.sqlite3")

    search = subparsers.add_parser("search", help="Run one live search query.")
    _add_query_args(search)
    search.add_argument("--artifacts", default="artifacts")
    search.add_argument("--db", default="googlehotels.sqlite3")
    search.add_argument("--headful", action="store_true")

    detail = subparsers.add_parser("detail", help="Open one property detail page and traverse panels.")
    _add_query_args(detail)
    detail.add_argument("--detail-url", required=True)
    detail.add_argument("--property-id")
    detail.add_argument("--artifacts", default="artifacts")
    detail.add_argument("--db", default="googlehotels.sqlite3")
    detail.add_argument("--headful", action="store_true")

    probe = subparsers.add_parser("probe", help="Search, optionally open one property, and archive live RPC captures.")
    _add_query_args(probe)
    probe.add_argument("--property-name")
    probe.add_argument("--panels", default="prices,reviews,photos,about")
    probe.add_argument("--artifacts", default="artifacts")
    probe.add_argument("--db", default="googlehotels.sqlite3")
    probe.add_argument("--headful", action="store_true")

    replay = subparsers.add_parser("replay", help="Replay one saved artifact run offline or over live HTTP and print parsed JSON.")
    replay.add_argument("--artifact-run", required=True, help="Artifact run id or artifact directory path.")
    replay.add_argument("--live", action="store_true", help="Fetch fresh data by replaying saved RPC templates against a new HTTP session.")
    replay.add_argument("--property-id")
    replay.add_argument("--panels", default="")
    _add_optional_query_args(replay)
    replay.add_argument("--artifacts", default="artifacts")
    replay.add_argument("--db", default="googlehotels.sqlite3")

    serve = subparsers.add_parser("serve", help="Run the JSON API server for mobile or web clients.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--artifacts", default="artifacts")
    serve.add_argument("--db", default="googlehotels.sqlite3")
    return parser


def _add_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--destination", required=True)
    parser.add_argument("--check-in", required=True)
    parser.add_argument("--check-out", required=True)
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--rooms", type=int, default=1)
    parser.add_argument("--currency")
    parser.add_argument("--locale")


def _add_optional_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--destination")
    parser.add_argument("--check-in")
    parser.add_argument("--check-out")
    parser.add_argument("--adults", type=int)
    parser.add_argument("--children", type=int)
    parser.add_argument("--rooms", type=int)
    parser.add_argument("--currency")
    parser.add_argument("--locale")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-db":
        service = ScraperService(ServiceConfig(artifacts_root="artifacts", database_path=args.db))
        print(f"Initialized database at {service.database.path}")
        return 0

    if args.command == "serve":
        run_server(host=args.host, port=args.port, artifacts_root=args.artifacts, database_path=args.db)
        return 0

    return asyncio.run(_run_command(args))


async def _run_command(args) -> int:
    service = ScraperService(ServiceConfig(artifacts_root=args.artifacts, database_path=args.db))

    if args.command == "replay":
        payload = await service.run_replay(
            args.artifact_run,
            live=args.live,
            property_id=args.property_id,
            panels=parse_panels(args.panels) if args.panels.strip() else None,
            query_override=build_optional_query(vars(args)),
        )
    else:
        query = build_query(
            destination=args.destination,
            check_in=args.check_in,
            check_out=args.check_out,
            adults=args.adults,
            children=args.children,
            rooms=args.rooms,
            currency=args.currency,
            locale=args.locale,
        )
        if args.command == "search":
            payload = await service.run_search(query, headful=args.headful)
        elif args.command == "detail":
            payload = await service.run_detail(query, args.detail_url, args.property_id, headful=args.headful)
        else:
            payload = await service.run_probe(
                query,
                property_name=args.property_name,
                panels=parse_panels(args.panels),
                headful=args.headful,
            )

    print(render_stdout_json(payload))
    return 0
