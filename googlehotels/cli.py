from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date

from .database import Database
from .google_hotels import BrowserConfig, GoogleHotelsScraper
from .models import ExtractionBundle, PanelName, PropertyRecord, SearchListing, to_jsonable
from .replay_client import ReplayClient
from .storage import ArtifactStore


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
        database = Database(args.db)
        database.initialize()
        print(f"Initialized database at {database.path}")
        return 0

    return asyncio.run(_run_command(args))


async def _run_command(args) -> int:
    from .models import HotelQuery, JobStatus, utc_now

    storage = ArtifactStore(args.artifacts)
    database = Database(args.db)
    database.initialize()

    if args.command == "replay":
        replay_client = ReplayClient(args.artifacts)
        replay_panels = parse_panels(args.panels) if args.panels.strip() else None
        query_override = build_optional_query(args)
        if args.live:
            replay_result = await replay_client.replay_live_artifact(
                args.artifact_run,
                query_override=query_override,
                property_id=args.property_id,
                panels=replay_panels,
            )
        else:
            replay_result = await replay_client.replay_artifact(
                args.artifact_run,
                property_id=args.property_id,
                panels=replay_panels,
            )
        run, bundle = replay_result.run, replay_result.bundle
    else:
        query = HotelQuery(
            destination=args.destination,
            check_in=date.fromisoformat(args.check_in),
            check_out=date.fromisoformat(args.check_out),
            adults=args.adults,
            children=args.children,
            rooms=args.rooms,
            currency=args.currency,
            locale=args.locale,
        )
        config = BrowserConfig(headless=not args.headful)
        async with GoogleHotelsScraper(config) as scraper:
            if args.command == "search":
                run, bundle = await scraper.run_search(query)
            elif args.command == "detail":
                run, bundle = await scraper.run_property_detail(query, args.detail_url, args.property_id)
            else:
                panels = parse_panels(args.panels)
                run, bundle = await scraper.run_probe(query, args.property_name, panels)

    run.status = JobStatus.SUCCESS
    run.finished_at = utc_now()
    storage.write_run(run)
    for capture in bundle.captures:
        storage.write_capture(run.run_id, capture)
    bundle_path = storage.write_bundle(run.run_id, bundle)
    database.save_run(run)
    if bundle.property_record:
        database.save_property(bundle.property_record)
    if bundle.offers:
        database.save_offers(bundle.offers)

    print(render_stdout_json(build_stdout_payload(args.command, run, bundle, bundle_path)))
    return 0


def build_optional_query(args):
    from .models import HotelQuery

    if not any(
        getattr(args, field, None) is not None
        for field in ("destination", "check_in", "check_out", "adults", "children", "rooms", "currency", "locale")
    ):
        return None
    if not args.destination or not args.check_in or not args.check_out:
        raise ValueError("Live replay query overrides require --destination, --check-in, and --check-out together.")
    return HotelQuery(
        destination=args.destination,
        check_in=date.fromisoformat(args.check_in),
        check_out=date.fromisoformat(args.check_out),
        adults=args.adults if args.adults is not None else 2,
        children=args.children if args.children is not None else 0,
        rooms=args.rooms if args.rooms is not None else 1,
        currency=args.currency,
        locale=args.locale,
    )


def parse_panels(raw: str) -> list[PanelName]:
    if not raw.strip():
        return []
    panels: list[PanelName] = []
    aliases = {
        "prices": PanelName.OFFERS,
        "offers": PanelName.OFFERS,
        "reviews": PanelName.REVIEWS,
        "photos": PanelName.PHOTOS,
        "about": PanelName.ABOUT,
        "amenities": PanelName.AMENITIES,
        "contact": PanelName.CONTACT,
        "policies": PanelName.POLICIES,
        "overview": PanelName.OVERVIEW,
    }
    for part in raw.split(","):
        key = part.strip().lower()
        if not key:
            continue
        panel = aliases.get(key)
        if panel is None:
            raise ValueError(f"Unsupported panel '{part}'.")
        panels.append(panel)
    return panels


def summarize_rpcids(captures) -> dict[str, int]:
    counts: dict[str, int] = {}
    for capture in captures:
        for rpcid in capture.rpcids:
            counts[rpcid] = counts.get(rpcid, 0) + 1
    return counts


def render_stdout_json(payload: dict) -> str:
    encoding = (sys.stdout.encoding or "").lower()
    ensure_ascii = encoding in {"", "cp1252", "windows-1252"}
    return json.dumps(payload, indent=2, ensure_ascii=ensure_ascii)


def build_stdout_payload(command: str, run, bundle: ExtractionBundle, bundle_path) -> dict:
    payload = {
        "command": command,
        "run": {
            "run_id": run.run_id,
            "stage": run.stage.value,
            "status": run.status.value,
            "property_id": run.property_id,
            "opened_panels": [panel.value for panel in run.opened_panels],
            "captures": len(bundle.captures),
            "rpcids": summarize_rpcids(bundle.captures),
        },
        "artifact_paths": {
            "bundle_json": str(bundle_path),
            "run_json": str(bundle_path.with_name("run.json")),
        },
    }
    if bundle.property_record is not None:
        payload["place"] = build_place_payload(bundle.property_record, bundle)
    if bundle.listings:
        payload["places"] = [build_listing_payload(listing) for listing in bundle.listings]
    if bundle.offers and bundle.property_record is None:
        payload["booking_options"] = [to_jsonable(offer) for offer in bundle.offers]
    return payload


def build_place_payload(record: PropertyRecord, bundle: ExtractionBundle) -> dict:
    place = {
        "property_id": record.property_id,
        "name": record.name,
        "rating": record.rating,
        "review_count": record.review_count,
        "address": record.address,
        "coordinates": {
            "latitude": record.latitude,
            "longitude": record.longitude,
        },
        "images": record.images,
        "cheapest_price": record.cheapest_price,
        "cheapest_price_amount": record.cheapest_price_amount,
        "cheapest_price_currency": record.cheapest_price_currency,
        "cheapest_price_provider": record.cheapest_price_provider,
        "booking_options": [to_jsonable(offer) for offer in bundle.offers],
        "contact": {
            "phone": record.phone,
            "website": record.website,
        },
        "check_in_time": record.check_in_time,
        "check_out_time": record.check_out_time,
        "description": record.description,
        "amenities": record.amenities,
        "amenity_groups": to_jsonable(record.amenity_groups),
        "canonical_url": record.canonical_url,
        "google_entity_id": record.google_entity_id,
    }
    return place


def build_listing_payload(listing: SearchListing) -> dict:
    return {
        "listing_id": listing.listing_id,
        "name": listing.name,
        "rating": listing.rating,
        "review_count": listing.review_count,
        "visible_price": listing.visible_price,
        "thumbnail_url": listing.thumbnail_url,
        "detail_url": listing.detail_url,
    }
