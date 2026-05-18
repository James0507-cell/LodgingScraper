from __future__ import annotations

import json
import random
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date

from .models import HotelQuery, NetworkCapture, Stage


DATE_RANGE_RE = re.compile(
    r"\[\[(?P<y1>\d{4}),(?P<m1>\d{1,2}),(?P<d1>\d{1,2})\],\[(?P<y2>\d{4}),(?P<m2>\d{1,2}),(?P<d2>\d{1,2})\],1(?P<tail>(?:,null,0|,1)?)\]"
)


@dataclass(slots=True)
class ReplayTemplate:
    stage: Stage
    request_url: str
    request_method: str
    request_body: str | None
    action: str
    request_headers: dict[str, str]


@dataclass(slots=True)
class BootstrapState:
    fsid: str
    build_label: str
    page_url: str
    hl: str


def build_replay_template(capture: NetworkCapture) -> ReplayTemplate:
    return ReplayTemplate(
        stage=capture.stage,
        request_url=capture.request_url,
        request_method=capture.request_method,
        request_body=capture.request_body,
        action=capture.action,
        request_headers=capture.request_headers,
    )


def patch_request_body(
    request_body: str | None,
    source_query: HotelQuery | None,
    target_query: HotelQuery | None,
) -> str | None:
    if not request_body or target_query is None:
        return request_body
    params = urllib.parse.parse_qs(request_body, keep_blank_values=True)
    f_req_values = params.get("f.req")
    if not f_req_values:
        return request_body
    f_req = f_req_values[0]
    if source_query is not None and source_query.destination:
        f_req = f_req.replace(source_query.destination, target_query.destination)
    f_req = DATE_RANGE_RE.sub(lambda match: _replacement_date_range(match, target_query), f_req)
    params["f.req"] = [f_req]
    return urllib.parse.urlencode(params, doseq=True)


def build_live_request_url(template_url: str, bootstrap: BootstrapState, reqid: int) -> str:
    parsed = urllib.parse.urlsplit(template_url)
    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    updated: list[tuple[str, str]] = []
    for key, value in params:
        if key == "f.sid":
            updated.append((key, bootstrap.fsid))
        elif key == "bl":
            updated.append((key, bootstrap.build_label))
        elif key == "hl":
            updated.append((key, bootstrap.hl))
        elif key == "_reqid":
            updated.append((key, str(reqid)))
        else:
            updated.append((key, value))
    query = urllib.parse.urlencode(updated)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def build_live_headers(
    template: ReplayTemplate,
    bootstrap: BootstrapState,
    target_query: HotelQuery | None,
) -> dict[str, str]:
    source_headers = {key.lower(): value for key, value in template.request_headers.items()}
    locale = target_query.locale if target_query and target_query.locale else bootstrap.hl
    currency = target_query.currency if target_query and target_query.currency else "PHP"
    headers = {
        "accept": "*/*",
        "accept-language": locale,
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "origin": "https://www.google.com",
        "referer": bootstrap.page_url,
        "user-agent": source_headers.get(
            "user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        ),
        "x-same-domain": "1",
        "x-goog-ext-190139975-jspb": source_headers.get("x-goog-ext-190139975-jspb", "[\"PH\",\"ZZ\",\"yol64A==\"]"),
        "x-goog-ext-259736195-jspb": _build_ext_context(locale, currency),
    }
    for optional_header in ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
        if optional_header in source_headers:
            headers[optional_header] = source_headers[optional_header]
    if "x-goog-batchexecute-bgr" in source_headers:
        headers["x-goog-batchexecute-bgr"] = source_headers["x-goog-batchexecute-bgr"]
    return headers


def next_reqid(seed: int | None = None) -> int:
    if seed is not None:
        return seed
    return random.randint(100000, 999999)


def _replacement_date_range(match: re.Match[str], query: HotelQuery) -> str:
    tail = match.group("tail") or ""
    return (
        f"[[{query.check_in.year},{query.check_in.month},{query.check_in.day}],"
        f"[{query.check_out.year},{query.check_out.month},{query.check_out.day}],1{tail}]"
    )


def _build_ext_context(locale: str, currency: str) -> str:
    return json.dumps([locale, "PH", currency, 1, None, [-480], None, None, 7, []], separators=(",", ":"))
