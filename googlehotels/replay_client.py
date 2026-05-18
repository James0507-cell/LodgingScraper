from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from http.cookiejar import CookieJar
from pathlib import Path

from .models import AmenityGroup, ExtractionBundle, HotelQuery, NetworkCapture, PanelName, ScrapeRun, Stage, utc_now
from .parser import parse_property_bundle, parse_search_captures, stable_id
from .replay import (
    BootstrapState,
    build_live_headers,
    build_live_request_url,
    build_replay_template,
    next_reqid,
    patch_request_body,
)


FDRFJE_RE = re.compile(r'"FdrFJe":"(?P<fsid>[^"]+)"')
BUILD_LABEL_RE = re.compile(r'"cfb2h":"(?P<build>[^"]+)"')


@dataclass(slots=True)
class ReplayResult:
    run: ScrapeRun
    bundle: ExtractionBundle
    source_run_id: str | None = None
    used_fallback: bool = False


class ReplayClient:
    def __init__(self, artifacts_root: str | Path = "artifacts") -> None:
        self.artifacts_root = Path(artifacts_root)

    async def replay_artifact(
        self,
        artifact_ref: str | Path,
        property_id: str | None = None,
        panels: list[PanelName] | None = None,
    ) -> ReplayResult:
        artifact_dir = self._resolve_artifact_dir(artifact_ref)
        run_payload = self._load_json(artifact_dir / "run.json")
        captures = self._load_captures(artifact_dir / "captures")
        query = self._load_query(run_payload.get("query"))
        source_property_id = property_id or run_payload.get("property_id") or self._load_property_id(artifact_dir)
        opened_panels = panels if panels is not None else self._load_opened_panels(run_payload.get("opened_panels"))
        replay_run = ScrapeRun(
            run_id=uuid.uuid4().hex,
            stage=Stage.REPLAY,
            query=query,
            property_id=source_property_id,
            opened_panels=opened_panels.copy(),
        )
        bundle = self._parse_bundle_from_captures(
            artifact_dir=artifact_dir,
            captures=captures,
            property_id=source_property_id,
            opened_panels=opened_panels,
            query=query,
        )
        return ReplayResult(
            run=replay_run,
            bundle=bundle,
            source_run_id=run_payload.get("run_id"),
            used_fallback=False,
        )

    async def replay_live_artifact(
        self,
        artifact_ref: str | Path,
        query_override: HotelQuery | None = None,
        property_id: str | None = None,
        panels: list[PanelName] | None = None,
    ) -> ReplayResult:
        artifact_dir = self._resolve_artifact_dir(artifact_ref)
        run_payload = self._load_json(artifact_dir / "run.json")
        source_query = self._load_query(run_payload.get("query"))
        target_query = self._merge_queries(source_query, query_override)
        if target_query is None:
            raise ValueError("Live replay requires a query from the source artifact or explicit replay query overrides.")
        source_property_id = property_id or run_payload.get("property_id") or self._load_property_id(artifact_dir)
        opened_panels = panels if panels is not None else self._load_opened_panels(run_payload.get("opened_panels"))
        source_captures = self._select_live_source_captures(
            self._load_captures(artifact_dir / "captures"),
            has_property=bool(source_property_id),
        )
        bootstrap = await asyncio.to_thread(self._bootstrap_session, target_query)
        live_captures = await asyncio.to_thread(self._execute_live_templates, source_captures, source_query, target_query, bootstrap)
        replay_run = ScrapeRun(
            run_id=uuid.uuid4().hex,
            stage=Stage.REPLAY,
            query=target_query,
            property_id=source_property_id,
            opened_panels=opened_panels.copy(),
        )
        bundle = self._parse_bundle_from_captures(
            artifact_dir=artifact_dir,
            captures=live_captures,
            property_id=source_property_id,
            opened_panels=opened_panels,
            query=target_query,
        )
        return ReplayResult(
            run=replay_run,
            bundle=bundle,
            source_run_id=run_payload.get("run_id"),
            used_fallback=False,
        )

    @staticmethod
    def _select_live_source_captures(captures: list[NetworkCapture], has_property: bool) -> list[NetworkCapture]:
        if not has_property:
            prioritized = [capture for capture in captures if capture.action.startswith("search_load")]
            return prioritized or captures
        prioritized = [
            capture
            for capture in captures
            if capture.action.startswith("search_load")
            or capture.action.startswith("open_property:")
            or capture.action.startswith("panel:")
        ]
        return prioritized or captures

    def _parse_bundle_from_captures(
        self,
        artifact_dir: Path,
        captures: list[NetworkCapture],
        property_id: str | None,
        opened_panels: list[PanelName],
        query: HotelQuery | None,
    ) -> ExtractionBundle:
        if property_id:
            bundle = parse_property_bundle(property_id, captures, opened_panels=opened_panels)
            self._hydrate_from_saved_bundle(bundle, artifact_dir)
            return bundle
        query_key = stable_id("replay", artifact_dir.name)
        if query is not None:
            query_key = stable_id(
                query.destination,
                query.check_in.isoformat(),
                query.check_out.isoformat(),
                str(query.adults),
                str(query.children),
                str(query.rooms),
            )
        return ExtractionBundle(
            listings=parse_search_captures(captures, query_key),
            captures=captures,
        )

    def _execute_live_templates(
        self,
        source_captures: list[NetworkCapture],
        source_query: HotelQuery | None,
        target_query: HotelQuery,
        bootstrap: BootstrapState,
    ) -> list[NetworkCapture]:
        cookie_jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        bootstrap_request = urllib.request.Request(
            bootstrap.page_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "Accept-Language": bootstrap.hl,
            },
        )
        with opener.open(bootstrap_request, timeout=30):
            pass
        reqid = next_reqid()
        captures: list[NetworkCapture] = []
        for source_capture in source_captures:
            template = build_replay_template(source_capture)
            request_body = patch_request_body(template.request_body, source_query, target_query)
            request_url = build_live_request_url(template.request_url, bootstrap, reqid)
            reqid += 100000
            headers = build_live_headers(template, bootstrap, target_query)
            request = urllib.request.Request(
                request_url,
                data=request_body.encode("utf-8") if request_body is not None else None,
                headers=headers,
                method=template.request_method,
            )
            try:
                with opener.open(request, timeout=30) as response:
                    body = response.read().decode("utf-8", "ignore")
                    response_headers = dict(response.info())
                    status = getattr(response, "status", None)
            except Exception:
                continue
            captures.append(
                NetworkCapture(
                    capture_id=uuid.uuid4().hex,
                    stage=Stage.REPLAY,
                    action=template.action,
                    page_url=bootstrap.page_url,
                    request_url=request_url,
                    request_method=template.request_method,
                    request_headers=headers,
                    request_body=request_body,
                    response_status=status,
                    response_headers=response_headers,
                    response_body=body,
                    captured_at=utc_now(),
                    parser_version="live-replay-1",
                    rpcids=source_capture.rpcids.copy(),
                )
            )
        return captures

    def _bootstrap_session(self, query: HotelQuery) -> BootstrapState:
        locale = query.locale or "en-US"
        page_url = f"https://www.google.com/travel/search?q={urllib.parse.quote(query.destination)}&hl={urllib.parse.quote(locale)}&ts=CAEqBwoFOgNQSFA&ap=MAA"
        request = urllib.request.Request(
            page_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "Accept-Language": locale,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", "ignore")
        fsid_match = FDRFJE_RE.search(html)
        build_match = BUILD_LABEL_RE.search(html)
        if fsid_match is None or build_match is None:
            raise RuntimeError("Could not bootstrap live replay session tokens from Google Travel.")
        return BootstrapState(
            fsid=fsid_match.group("fsid"),
            build_label=build_match.group("build"),
            page_url=page_url,
            hl=locale,
        )

    def _resolve_artifact_dir(self, artifact_ref: str | Path) -> Path:
        candidate = Path(artifact_ref)
        if candidate.is_dir():
            return candidate
        nested = self.artifacts_root / candidate
        if nested.is_dir():
            return nested
        raise FileNotFoundError(f"Could not find artifact directory for '{artifact_ref}'.")

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_query(payload: dict | None) -> HotelQuery | None:
        if not payload:
            return None
        try:
            return HotelQuery(
                destination=payload["destination"],
                check_in=date.fromisoformat(payload["check_in"]),
                check_out=date.fromisoformat(payload["check_out"]),
                adults=int(payload.get("adults", 2)),
                children=int(payload.get("children", 0)),
                rooms=int(payload.get("rooms", 1)),
                currency=payload.get("currency"),
                locale=payload.get("locale"),
                max_results=payload.get("max_results"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _merge_queries(source: HotelQuery | None, override: HotelQuery | None) -> HotelQuery | None:
        if override is None:
            return source
        if source is None:
            return override
        return HotelQuery(
            destination=override.destination or source.destination,
            check_in=override.check_in or source.check_in,
            check_out=override.check_out or source.check_out,
            adults=override.adults,
            children=override.children,
            rooms=override.rooms,
            currency=override.currency or source.currency,
            locale=override.locale or source.locale,
            max_results=override.max_results or source.max_results,
        )

    @staticmethod
    def _load_opened_panels(payload: list[str] | None) -> list[PanelName]:
        if not payload:
            return []
        panels: list[PanelName] = []
        for item in payload:
            try:
                panels.append(PanelName(item))
            except ValueError:
                continue
        return panels

    @staticmethod
    def _load_property_id(artifact_dir: Path) -> str | None:
        bundle_path = artifact_dir / "bundle.json"
        if not bundle_path.exists():
            return None
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        property_payload = payload.get("property_record")
        if isinstance(property_payload, dict):
            return property_payload.get("property_id")
        return None

    @staticmethod
    def _load_captures(captures_dir: Path) -> list[NetworkCapture]:
        captures: list[NetworkCapture] = []
        if not captures_dir.exists():
            return captures
        for path in sorted(captures_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            captures.append(
                NetworkCapture(
                    capture_id=payload["capture_id"],
                    stage=Stage(payload["stage"]),
                    action=payload["action"],
                    page_url=payload["page_url"],
                    request_url=payload["request_url"],
                    request_method=payload["request_method"],
                    request_headers=payload.get("request_headers", {}),
                    request_body=payload.get("request_body"),
                    response_status=payload.get("response_status"),
                    response_headers=payload.get("response_headers", {}),
                    response_body=payload.get("response_body"),
                    captured_at=datetime.fromisoformat(payload["captured_at"]),
                    parser_version=payload.get("parser_version", "0"),
                    rpcids=payload.get("rpcids", []),
                )
            )
        return captures

    @staticmethod
    def _hydrate_from_saved_bundle(bundle: ExtractionBundle, artifact_dir: Path) -> None:
        bundle_path = artifact_dir / "bundle.json"
        if bundle.property_record is None or not bundle_path.exists():
            return
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        source_record = payload.get("property_record")
        if not isinstance(source_record, dict):
            return
        record = bundle.property_record
        if not record.description:
            record.description = source_record.get("description")
        if not record.phone:
            record.phone = source_record.get("phone")
        if not record.website:
            record.website = source_record.get("website")
        if not record.amenities:
            record.amenities = [item for item in source_record.get("amenities", []) if isinstance(item, str)]
        if not record.amenity_groups:
            record.amenity_groups = [
                AmenityGroup(
                    title=str(group.get("title", "")).strip(),
                    items=[item for item in group.get("items", []) if isinstance(item, str)],
                )
                for group in source_record.get("amenity_groups", [])
                if isinstance(group, dict) and str(group.get("title", "")).strip()
            ]
