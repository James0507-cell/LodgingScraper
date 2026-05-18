from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .database import Database
from .google_hotels import BrowserConfig, GoogleHotelsScraper
from .models import (
    ExtractionBundle,
    HotelQuery,
    JobStatus,
    PanelName,
    PropertyRecord,
    SearchListing,
    to_jsonable,
    utc_now,
)
from .replay_client import ReplayClient
from .storage import ArtifactStore


@dataclass(slots=True)
class ServiceConfig:
    artifacts_root: str | Path = "artifacts"
    database_path: str | Path = "googlehotels.sqlite3"
    replay_artifacts_root: str | Path | None = None


class ScraperService:
    def __init__(self, config: ServiceConfig | None = None) -> None:
        self.config = config or ServiceConfig()
        self.storage = ArtifactStore(self.config.artifacts_root)
        self.database = Database(self.config.database_path)
        self.database.initialize()
        self.replay_client = ReplayClient(self.config.replay_artifacts_root or self.config.artifacts_root)

    async def run_search(self, query: HotelQuery, headful: bool = False) -> dict:
        config = BrowserConfig(headless=not headful)
        async with GoogleHotelsScraper(config) as scraper:
            run, bundle = await scraper.run_search(query)
        return self._finalize_run("search", run, bundle)

    async def run_detail(
        self,
        query: HotelQuery,
        detail_url: str,
        property_id: str | None = None,
        headful: bool = False,
    ) -> dict:
        config = BrowserConfig(headless=not headful)
        async with GoogleHotelsScraper(config) as scraper:
            run, bundle = await scraper.run_property_detail(query, detail_url, property_id)
        return self._finalize_run("detail", run, bundle)

    async def run_probe(
        self,
        query: HotelQuery,
        property_name: str | None = None,
        panels: list[PanelName] | None = None,
        headful: bool = False,
    ) -> dict:
        config = BrowserConfig(headless=not headful)
        async with GoogleHotelsScraper(config) as scraper:
            run, bundle = await scraper.run_probe(query, property_name, panels or [])
        return self._finalize_run("probe", run, bundle)

    async def run_replay(
        self,
        artifact_run: str,
        *,
        live: bool = False,
        property_id: str | None = None,
        panels: list[PanelName] | None = None,
        query_override: HotelQuery | None = None,
    ) -> dict:
        if live:
            result = await self.replay_client.replay_live_artifact(
                artifact_run,
                query_override=query_override,
                property_id=property_id,
                panels=panels,
            )
        else:
            result = await self.replay_client.replay_artifact(
                artifact_run,
                property_id=property_id,
                panels=panels,
            )
        return self._finalize_run("replay", result.run, result.bundle)

    def get_run_payload(self, run_id: str) -> dict | None:
        run = self.database.get_run(run_id)
        if run is None:
            return None
        payload = {
            "run": run,
            "artifacts": {
                "bundle_json": str(self.storage.run_dir(run_id) / "bundle.json"),
                "run_json": str(self.storage.run_dir(run_id) / "run.json"),
            },
        }
        bundle_path = self.storage.run_dir(run_id) / "bundle.json"
        if bundle_path.exists():
            payload["bundle"] = json.loads(bundle_path.read_text(encoding="utf-8"))
        return to_jsonable(payload)

    def get_property_payload(
        self,
        property_id: str,
        *,
        check_in: date | None = None,
        check_out: date | None = None,
    ) -> dict | None:
        record = self.database.get_property(property_id)
        if record is None:
            return None
        offers = self.database.get_offers(property_id, check_in=check_in, check_out=check_out)
        bundle = ExtractionBundle(property_record=record, offers=offers)
        return build_place_payload(record, bundle)

    def list_runs_payload(self, limit: int = 20) -> dict:
        return {"runs": self.database.list_runs(limit=limit)}

    def _finalize_run(self, command: str, run, bundle: ExtractionBundle) -> dict:
        run.status = JobStatus.SUCCESS
        run.finished_at = utc_now()
        self.storage.write_run(run)
        for capture in bundle.captures:
            self.storage.write_capture(run.run_id, capture)
        bundle_path = self.storage.write_bundle(run.run_id, bundle)
        self.database.save_run(run)
        if bundle.property_record:
            self.database.save_property(bundle.property_record)
        if bundle.offers:
            self.database.save_offers(bundle.offers)
        return build_stdout_payload(command, run, bundle, bundle_path)


def build_query(
    *,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    currency: str | None = None,
    locale: str | None = None,
) -> HotelQuery:
    return HotelQuery(
        destination=destination,
        check_in=date.fromisoformat(check_in),
        check_out=date.fromisoformat(check_out),
        adults=adults,
        children=children,
        rooms=rooms,
        currency=currency,
        locale=locale,
    )


def build_optional_query(payload: dict) -> HotelQuery | None:
    if not any(payload.get(field) is not None for field in ("destination", "check_in", "check_out", "adults", "children", "rooms", "currency", "locale")):
        return None
    required = ("destination", "check_in", "check_out")
    if any(payload.get(field) in (None, "") for field in required):
        raise ValueError("Live replay query overrides require destination, check_in, and check_out together.")
    return build_query(
        destination=payload["destination"],
        check_in=payload["check_in"],
        check_out=payload["check_out"],
        adults=int(payload.get("adults", 2)),
        children=int(payload.get("children", 0)),
        rooms=int(payload.get("rooms", 1)),
        currency=payload.get("currency"),
        locale=payload.get("locale"),
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
    return {
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
