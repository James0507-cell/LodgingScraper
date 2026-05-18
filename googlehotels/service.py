from __future__ import annotations

import asyncio
import json
import sys
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
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
    max_job_workers: int = 2


class ScraperService:
    def __init__(self, config: ServiceConfig | None = None) -> None:
        self.config = config or ServiceConfig()
        self.storage = ArtifactStore(self.config.artifacts_root)
        self.database = Database(self.config.database_path)
        self.database.initialize()
        self.replay_client = ReplayClient(self.config.replay_artifacts_root or self.config.artifacts_root)
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_job_workers, thread_name_prefix="scraper-job")
        self._futures: dict[str, Future] = {}
        self.cache_ttls = {
            "search": timedelta(hours=6),
            "detail": timedelta(hours=12),
            "probe": timedelta(hours=12),
            "replay": timedelta(days=7),
            "replay_live": timedelta(hours=3),
        }

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

    def submit_job(self, kind: str, request_payload: dict) -> dict:
        normalized_request = json.loads(json.dumps(request_payload, sort_keys=True))
        cache_key = self._build_cache_key(kind, normalized_request)
        force_refresh = bool(normalized_request.pop("force_refresh", False))
        if not force_refresh:
            cached = self._get_cached_payload(cache_key)
            if cached is not None:
                return self._create_completed_cached_job(kind, normalized_request, cache_key, cached)

        job_id = uuid.uuid4().hex
        now_iso = utc_now().isoformat()
        self.database.create_job(
            job_id,
            kind=kind,
            status=JobStatus.PENDING.value,
            request_json=json.dumps(normalized_request, sort_keys=True),
            cache_key=cache_key,
            created_at=now_iso,
        )
        future = self.executor.submit(self._run_job_sync, job_id, kind, normalized_request, cache_key)
        self._futures[job_id] = future
        return self.get_job_payload(job_id) or {"job_id": job_id, "status": JobStatus.PENDING.value}

    def get_job_payload(self, job_id: str) -> dict | None:
        self._sync_job_future(job_id)
        job = self.database.get_job(job_id)
        if job is None:
            return None
        payload = {
            "job_id": job["job_id"],
            "kind": job["kind"],
            "status": job["status"],
            "cache_key": job["cache_key"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "error": job["error"],
        }
        if job["result"]:
            payload["result"] = json.loads(job["result"])
        return payload

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

    def _run_job_sync(self, job_id: str, kind: str, request_payload: dict, cache_key: str) -> None:
        self.database.update_job(job_id, status=JobStatus.RUNNING.value, updated_at=utc_now().isoformat())
        try:
            result = self._execute_job(kind, request_payload)
        except Exception as exc:
            self.database.update_job(
                job_id,
                status=JobStatus.FAILED.value,
                error=str(exc),
                updated_at=utc_now().isoformat(),
            )
            raise
        result_json = json.dumps(result, sort_keys=True)
        self.database.update_job(
            job_id,
            status=JobStatus.SUCCESS.value,
            result_json=result_json,
            updated_at=utc_now().isoformat(),
        )
        self._save_cache(kind, cache_key, result)

    def _execute_job(self, kind: str, request_payload: dict) -> dict:
        if kind == "search":
            query = build_query_from_payload(request_payload)
            return asyncio.run(self.run_search(query, headful=bool(request_payload.get("headful", False))))
        if kind == "detail":
            query = build_query_from_payload(request_payload)
            detail_url = require_payload_str(request_payload, "detail_url")
            return asyncio.run(
                self.run_detail(
                    query,
                    detail_url,
                    property_id=optional_payload_str(request_payload, "property_id"),
                    headful=bool(request_payload.get("headful", False)),
                )
            )
        if kind == "probe":
            query = build_query_from_payload(request_payload)
            panels = parse_panels(str(request_payload.get("panels", "prices,reviews,photos,about")))
            return asyncio.run(
                self.run_probe(
                    query,
                    property_name=optional_payload_str(request_payload, "property_name"),
                    panels=panels,
                    headful=bool(request_payload.get("headful", False)),
                )
            )
        if kind == "replay":
            panels = parse_panels(str(request_payload.get("panels", "") or "")) if request_payload.get("panels") else None
            return asyncio.run(
                self.run_replay(
                    require_payload_str(request_payload, "artifact_run"),
                    live=bool(request_payload.get("live", False)),
                    property_id=optional_payload_str(request_payload, "property_id"),
                    panels=panels,
                    query_override=build_optional_query(request_payload),
                )
            )
        raise ValueError(f"Unsupported job kind '{kind}'.")

    def _build_cache_key(self, kind: str, payload: dict) -> str:
        encoded = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()

    def _get_cached_payload(self, cache_key: str) -> dict | None:
        cached = self.database.get_cache(cache_key, utc_now().isoformat())
        if cached is None:
            return None
        return json.loads(cached["payload_json"])

    def _save_cache(self, kind: str, cache_key: str, result: dict) -> None:
        now = utc_now()
        ttl = self.cache_ttls["replay_live" if kind == "replay" and result.get("command") == "replay" and result["run"]["captures"] < 20 else kind]
        self.database.save_cache(
            cache_key=cache_key,
            endpoint=kind,
            payload_json=json.dumps(result, sort_keys=True),
            run_id=result.get("run", {}).get("run_id"),
            property_id=result.get("run", {}).get("property_id"),
            created_at=now.isoformat(),
            expires_at=(now + ttl).isoformat(),
        )

    def _create_completed_cached_job(self, kind: str, request_payload: dict, cache_key: str, result: dict) -> dict:
        job_id = uuid.uuid4().hex
        now_iso = utc_now().isoformat()
        result_json = json.dumps(result, sort_keys=True)
        self.database.create_job(
            job_id,
            kind=kind,
            status=JobStatus.SUCCESS.value,
            request_json=json.dumps(request_payload, sort_keys=True),
            cache_key=cache_key,
            created_at=now_iso,
        )
        self.database.update_job(
            job_id,
            status=JobStatus.SUCCESS.value,
            result_json=result_json,
            updated_at=now_iso,
        )
        payload = self.get_job_payload(job_id) or {"job_id": job_id, "status": JobStatus.SUCCESS.value}
        payload["cached"] = True
        return payload

    def _sync_job_future(self, job_id: str) -> None:
        future = self._futures.get(job_id)
        if future is None:
            return
        if future.done():
            try:
                future.result()
            except Exception:
                pass
            self._futures.pop(job_id, None)


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


def build_query_from_payload(payload: dict) -> HotelQuery:
    return build_query(
        destination=require_payload_str(payload, "destination"),
        check_in=require_payload_str(payload, "check_in"),
        check_out=require_payload_str(payload, "check_out"),
        adults=int(payload.get("adults", 2)),
        children=int(payload.get("children", 0)),
        rooms=int(payload.get("rooms", 1)),
        currency=payload.get("currency"),
        locale=payload.get("locale"),
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


def require_payload_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' is required.")
    return value.strip()


def optional_payload_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string.")
    value = value.strip()
    return value or None


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
