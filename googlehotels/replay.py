from __future__ import annotations

from dataclasses import dataclass

from .models import HotelQuery, NetworkCapture, Stage


@dataclass(slots=True)
class ReplayTemplate:
    stage: Stage
    request_url: str
    request_method: str
    request_body: str | None


def build_replay_template(capture: NetworkCapture) -> ReplayTemplate:
    return ReplayTemplate(
        stage=capture.stage,
        request_url=capture.request_url,
        request_method=capture.request_method,
        request_body=capture.request_body,
    )


def apply_query(template: ReplayTemplate, query: HotelQuery) -> ReplayTemplate:
    body = template.request_body
    if body:
        body = (
            body.replace("__CHECK_IN__", query.check_in.isoformat())
            .replace("__CHECK_OUT__", query.check_out.isoformat())
            .replace("__DESTINATION__", query.destination)
        )
    return ReplayTemplate(
        stage=template.stage,
        request_url=template.request_url,
        request_method=template.request_method,
        request_body=body,
    )
