from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stage(StrEnum):
    SEARCH = "search"
    DETAIL = "detail"
    PANEL = "panel"
    OFFER_REFRESH = "offer_refresh"
    PROBE = "probe"


class PanelName(StrEnum):
    OVERVIEW = "overview"
    REVIEWS = "reviews"
    PHOTOS = "photos"
    AMENITIES = "amenities"
    ABOUT = "about"
    POLICIES = "policies"
    CONTACT = "contact"
    OFFERS = "offers"


class JobStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(slots=True)
class HotelQuery:
    destination: str
    check_in: date
    check_out: date
    adults: int = 2
    children: int = 0
    rooms: int = 1
    currency: str | None = None
    locale: str | None = None
    max_results: int | None = None


@dataclass(slots=True)
class SearchListing:
    listing_id: str
    query_key: str
    rank: int
    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    visible_price: str | None = None
    thumbnail_url: str | None = None
    detail_url: str | None = None
    raw_capture_id: str | None = None


@dataclass(slots=True)
class AmenityGroup:
    title: str
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PropertyRecord:
    property_id: str
    canonical_url: str | None = None
    google_entity_id: str | None = None
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    description: str | None = None
    images: list[str] = field(default_factory=list)
    cheapest_price: str | None = None
    cheapest_price_amount: float | None = None
    cheapest_price_currency: str | None = None
    cheapest_price_provider: str | None = None
    amenities: list[str] = field(default_factory=list)
    amenity_groups: list[AmenityGroup] = field(default_factory=list)
    phone: str | None = None
    website: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    property_type: str | None = None
    raw_capture_ids: list[str] = field(default_factory=list)
    last_seen_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class OfferRecord:
    offer_id: str
    property_id: str
    check_in: date
    check_out: date
    provider_name: str | None = None
    provider_url: str | None = None
    provider_image_url: str | None = None
    price: str | None = None
    price_amount: float | None = None
    currency: str | None = None
    room_type: str | None = None
    cancellation_policy: str | None = None
    scraped_at: datetime = field(default_factory=utc_now)
    raw_capture_id: str | None = None


@dataclass(slots=True)
class NetworkCapture:
    capture_id: str
    stage: Stage
    action: str
    page_url: str
    request_url: str
    request_method: str
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str | None = None
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    captured_at: datetime = field(default_factory=utc_now)
    parser_version: str = "0"
    artifact_dir: Path | None = None
    rpcids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScrapeRun:
    run_id: str
    stage: Stage
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: JobStatus = JobStatus.PENDING
    query: HotelQuery | None = None
    property_id: str | None = None
    listing_id: str | None = None
    opened_panels: list[PanelName] = field(default_factory=list)
    error: str | None = None
    artifact_dir: Path | None = None


@dataclass(slots=True)
class ExtractionBundle:
    listings: list[SearchListing] = field(default_factory=list)
    property_record: PropertyRecord | None = None
    offers: list[OfferRecord] = field(default_factory=list)
    captures: list[NetworkCapture] = field(default_factory=list)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value
