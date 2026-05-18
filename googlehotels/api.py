from __future__ import annotations

import asyncio
import json
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .service import ScraperService, ServiceConfig, build_optional_query, build_query, parse_panels


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    artifacts_root: str = "artifacts",
    database_path: str = "googlehotels.sqlite3",
) -> None:
    service = ScraperService(ServiceConfig(artifacts_root=artifacts_root, database_path=database_path))
    server = create_server(host, port, service)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_server(host: str, port: int, service: ScraperService) -> ThreadingHTTPServer:
    handler = create_handler(service)
    return ThreadingHTTPServer((host, port), handler)


def create_handler(service: ScraperService):
    class ScraperAPIHandler(BaseHTTPRequestHandler):
        server_version = "GoogleHotelsAPI/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/health":
                    self._send_json(HTTPStatus.OK, {"status": "ok"})
                    return
                if path == "/api/runs":
                    params = parse_qs(parsed.query)
                    limit = _parse_int(params.get("limit", ["20"])[0], default=20)
                    self._send_json(HTTPStatus.OK, service.list_runs_payload(limit=limit))
                    return
                if path.startswith("/api/runs/"):
                    run_id = path.rsplit("/", 1)[-1]
                    payload = service.get_run_payload(run_id)
                    if payload is None:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Run '{run_id}' was not found."})
                        return
                    self._send_json(HTTPStatus.OK, payload)
                    return
                if path.startswith("/api/properties/"):
                    property_id = path.rsplit("/", 1)[-1]
                    params = parse_qs(parsed.query)
                    check_in = _parse_date(params.get("check_in", [None])[0])
                    check_out = _parse_date(params.get("check_out", [None])[0])
                    payload = service.get_property_payload(property_id, check_in=check_in, check_out=check_out)
                    if payload is None:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Property '{property_id}' was not found."})
                        return
                    self._send_json(HTTPStatus.OK, {"place": payload})
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Route '{path}' was not found."})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                payload = self._read_json_body()
                if path == "/api/search":
                    query = _query_from_payload(payload)
                    result = asyncio.run(service.run_search(query, headful=bool(payload.get("headful", False))))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if path == "/api/detail":
                    query = _query_from_payload(payload)
                    detail_url = _require_str(payload, "detail_url")
                    result = asyncio.run(
                        service.run_detail(
                            query,
                            detail_url,
                            property_id=_optional_str(payload, "property_id"),
                            headful=bool(payload.get("headful", False)),
                        )
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if path == "/api/probe":
                    query = _query_from_payload(payload)
                    panels = parse_panels(str(payload.get("panels", "prices,reviews,photos,about")))
                    result = asyncio.run(
                        service.run_probe(
                            query,
                            property_name=_optional_str(payload, "property_name"),
                            panels=panels,
                            headful=bool(payload.get("headful", False)),
                        )
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if path == "/api/replay":
                    artifact_run = _require_str(payload, "artifact_run")
                    panels = parse_panels(str(payload.get("panels", "") or "")) if payload.get("panels") else None
                    result = asyncio.run(
                        service.run_replay(
                            artifact_run,
                            live=bool(payload.get("live", False)),
                            property_id=_optional_str(payload, "property_id"),
                            panels=panels,
                            query_override=build_optional_query(payload),
                        )
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Route '{path}' was not found."})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def log_message(self, format: str, *args) -> None:
            return

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            if not raw.strip():
                return {}
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def _send_json(self, status: HTTPStatus, payload: dict) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ScraperAPIHandler


def _query_from_payload(payload: dict):
    return build_query(
        destination=_require_str(payload, "destination"),
        check_in=_require_str(payload, "check_in"),
        check_out=_require_str(payload, "check_out"),
        adults=_parse_int(payload.get("adults", 2), default=2),
        children=_parse_int(payload.get("children", 0), default=0),
        rooms=_parse_int(payload.get("rooms", 1), default=1),
        currency=_optional_str(payload, "currency"),
        locale=_optional_str(payload, "locale"),
    )


def _require_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' is required.")
    return value.strip()


def _optional_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string.")
    value = value.strip()
    return value or None


def _parse_int(value, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _parse_date(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(value)
