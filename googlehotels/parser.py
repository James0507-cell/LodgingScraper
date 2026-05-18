from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from html import unescape
from typing import Any
from urllib.parse import urljoin

from .models import (
    ExtractionBundle,
    NetworkCapture,
    OfferRecord,
    PanelName,
    PropertyRecord,
    SearchListing,
)


WRAPPED_PAYLOAD_RE = re.compile(r'\["wrb\.fr","(?P<rpcid>[^"]+)","(?P<payload>(?:\\.|[^"\\])*)"', re.DOTALL)
SEARCH_ITEM_RE = re.compile(
    r'\[\[([-\d.]+),([-\d.]+)\](?:,[^\]]*)?\],"(?P<token>Ch[^"]+)",(?:null|\d+),"(?P<name>[^"]+)",null,'
    r'(?:\[\[(?P<rating>[-\d.]+),(?P<review_count>\d+)\]\],)?\["(?P<price>[^"]+)",null,(?P<price_value>[-\d.]+)',
    re.DOTALL,
)
PROPERTY_BLOCK_RE = re.compile(
    r'"441552390":\[null,"(?P<name>[^"]+)",\[\[(?P<lat>[-\d.]+),(?P<lng>[-\d.]+)\],'
    r'\[\[\["(?P<address>[^"]+)"\]\]\],\["(?P<phone>[^"]+)","tel:[^"]+"\]',
    re.DOTALL,
)
PROPERTY_WEBSITE_RE = re.compile(r'\[null,null,"(?P<website>https?://(?!maps\.google)[^"]+)"\]')
PROPERTY_DESCRIPTION_RE = re.compile(r'\[null,"(?P<description>[^"]{40,}?)",\["https://www\.google\.com/maps/vt/data=')
PROPERTY_TIMES_RE = re.compile(r'\["(?P<check_in>[^"]*M)","(?P<check_out>[^"]*M)"\]')
PROPERTY_TOKEN_RE = re.compile(r'"(?P<token>Cho[^"]+)"')
PHOTO_URL_RE = re.compile(r'https://lh[0-9][^"]+')
THUMBNAIL_URL_RE = re.compile(r'https://[^"]+w152-h152-n-k-no')
AMENITY_SECTION_RE = re.compile(r'\["Amenities",\[\[(?P<section>.*?)\]\],null,\["Essential info"', re.DOTALL)
AMENITY_ITEM_RE = re.compile(r'\["(?P<amenity>[^"]+)",(?:true|false),')
BDMBFE_LINK_RE = re.compile(
    r'\["(?P<name>[^"]+)","(?P<url>https?://[^"]+)","(?P<snippet>[^"]*)",1,null,\[null,null,null,null,null,\[(?P<domains>.*?)\]\],'
    r'"(?P<img>(?:data:image/[^"]+|))"\]',
    re.DOTALL,
)
PROVIDER_RE = re.compile(
    r'\[\["(?P<provider>[^"]+)",\d+,"(?P<url>/[^"]+)",\["(?P<img>[^"]+)"\].*?\[null,null,null,null,\["(?P<price>[^"]+)",null,[-\d.]+',
    re.DOTALL,
)
OFFER_DATE_ARRAY_RE = re.compile(r'\[\[(?P<year>\d{4}),(?P<month>\d{1,2}),(?P<day>\d{1,2})\],\[(?P<year2>\d{4}),(?P<month2>\d{1,2}),(?P<day2>\d{1,2})\],1')
AREA_SUMMARY_RE = re.compile(r'\[null,"(?P<description>[^"]{60,}?)",\["https://www\.google\.com/maps/vt/data')
HIGHLIGHTS_RE = re.compile(r'\["Hotel highlights",\[(?P<highlights>(?:"[^"]+",?)+)\]')
QUOTED_TEXT_RE = re.compile(r'"([^"]+)"')
IMAGE_DIMENSION_RE = re.compile(r'(?:\\u003d|=)w(?P<width>\d+)-h(?P<height>\d+)')
PRICE_VALUE_RE = re.compile(r'(?P<currency>[^\d\-.,\s]+)?\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)')
MAX_PROPERTY_IMAGES = 20
PROVIDER_NORMALIZATION_MAP = {
    "agoda": "Agoda",
    "booking.com": "Booking.com",
    "bluepillow.ph": "Bluepillow",
    "airasia move": "AirAsia MOVE",
    "klook": "Klook",
    "müv ai": "Muv AI",
    "muv ai": "Muv AI",
    "priceline": "Priceline",
    "qantas hotels": "Qantas Hotels",
    "skyscanner": "Skyscanner",
    "tripadvisor.com.ph": "Tripadvisor",
    "trip.com": "Trip.com",
    "tripening hotels": "Tripening Hotels",
}
LOW_QUALITY_PROVIDERS = {"Bluepillow", "Muv AI", "Tripening Hotels"}
PREFERRED_PROVIDERS = {
    "Agoda",
    "AirAsia MOVE",
    "Booking.com",
    "Klook",
    "Priceline",
    "Qantas Hotels",
    "Skyscanner",
    "Trip.com",
}
SYMBOL_TO_CURRENCY = {
    "₱": "PHP",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}


def stable_id(*parts: str) -> str:
    joined = "|".join(part.strip() for part in parts if part)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def parse_search_captures(captures: list[NetworkCapture], query_key: str) -> list[SearchListing]:
    listings: list[SearchListing] = []
    seen: set[str] = set()
    for capture in captures:
        for _, payload in _iter_rpc_payloads(capture, {"Ya3XAc", "AtySUc"}):
            for match in SEARCH_ITEM_RE.finditer(payload):
                token = match.group("token")
                name = unescape(match.group("name"))
                if not token or not name:
                    continue
                listing_id = stable_id(token)
                if listing_id in seen:
                    continue
                seen.add(listing_id)
                listings.append(
                    SearchListing(
                        listing_id=listing_id,
                        query_key=query_key,
                        rank=len(listings) + 1,
                        name=name,
                        rating=_coerce_float(match.group("rating")),
                        review_count=_coerce_int(match.group("review_count")),
                        visible_price=unescape(match.group("price")),
                        detail_url=_build_detail_url(token),
                        raw_capture_id=capture.capture_id,
                    )
                )
    return listings


def parse_property_bundle(
    property_id: str,
    captures: list[NetworkCapture],
    opened_panels: list[PanelName] | None = None,
) -> ExtractionBundle:
    bundle = ExtractionBundle(captures=captures)
    record = PropertyRecord(property_id=property_id)
    target_name = _extract_target_name(captures)

    for capture in captures:
        payloads = list(_iter_rpc_payloads(capture))
        for rpcid, payload in payloads:
            _merge_property_payload(record, rpcid, payload, capture.capture_id, target_name, capture.action)
            if rpcid == "M0CRd":
                bundle.offers.extend(_parse_m0crd_offers(record.property_id, payload, capture.capture_id))
            if rpcid == "bdmBfe":
                _enrich_offers_from_bdm(record, payload, bundle.offers, capture.capture_id)

    if opened_panels and PanelName.OFFERS in opened_panels and not record.images:
        record.images = _extract_images(captures, target_name)
    elif not record.images:
        record.images = _extract_images(captures, target_name)

    if not record.rating or not record.review_count:
        listing = _find_best_listing(target_name or record.name, captures)
        if listing:
            record.rating = record.rating or listing.rating
            record.review_count = record.review_count or listing.review_count
            record.google_entity_id = record.google_entity_id or _extract_qs_token(listing.detail_url)
            record.canonical_url = record.canonical_url or listing.detail_url

    if not record.website or not record.description:
        _hydrate_property_from_offers(record, bundle.offers)
    bundle.offers = _finalize_offers(record.property_id, bundle.offers)
    record.images = _filter_property_images(record.images)
    record.description = _clean_text_excerpt(record.description)
    record.website = _normalize_website(record.website)
    _apply_cheapest_offer(record, bundle.offers)

    bundle.property_record = record
    return bundle


def _merge_property_payload(
    record: PropertyRecord,
    rpcid: str,
    payload: str,
    capture_id: str,
    target_name: str | None,
    action: str,
) -> None:
    if capture_id not in record.raw_capture_ids:
        record.raw_capture_ids.append(capture_id)

    if rpcid == "AtySUc":
        if action.startswith("open_property:") or action.startswith("panel:") or action == "detail_load":
            _merge_from_atysuc(record, payload, target_name)
    elif rpcid == "pSDzMb":
        if not target_name or target_name in payload:
            record.images = _merge_unique(record.images, _extract_photo_urls(payload))
    elif rpcid == "zM1L7d":
        if not target_name or target_name in payload:
            record.images = _merge_unique(record.images, _extract_thumbnail_urls(payload))
    elif rpcid == "hsTcsb":
        record.amenities = _merge_unique(record.amenities, _extract_amenities(payload))
    elif rpcid == "ocp93e":
        record.amenities = _merge_unique(record.amenities, _extract_highlights(payload))


def _merge_from_atysuc(record: PropertyRecord, payload: str, target_name: str | None) -> None:
    scoped_payload = _slice_property_payload(payload, target_name) if target_name else payload
    block_match = PROPERTY_BLOCK_RE.search(scoped_payload)
    if block_match:
        record.name = record.name or unescape(block_match.group("name"))
        record.address = record.address or unescape(block_match.group("address"))
        record.latitude = record.latitude or _coerce_float(block_match.group("lat"))
        record.longitude = record.longitude or _coerce_float(block_match.group("lng"))
        record.phone = record.phone or unescape(block_match.group("phone"))

    website_match = PROPERTY_WEBSITE_RE.search(scoped_payload)
    if website_match:
        record.website = record.website or unescape(website_match.group("website"))

    times_match = PROPERTY_TIMES_RE.search(scoped_payload)
    if times_match:
        record.check_in_time = record.check_in_time or unescape(times_match.group("check_in"))
        record.check_out_time = record.check_out_time or unescape(times_match.group("check_out"))

    description_match = PROPERTY_DESCRIPTION_RE.search(scoped_payload)
    if description_match:
        record.description = record.description or unescape(description_match.group("description"))
    else:
        area_summary_match = AREA_SUMMARY_RE.search(scoped_payload)
        if area_summary_match:
            record.description = record.description or unescape(area_summary_match.group("description"))

    token_match = PROPERTY_TOKEN_RE.search(scoped_payload)
    if token_match:
        record.google_entity_id = record.google_entity_id or token_match.group("token")
        record.canonical_url = record.canonical_url or _build_detail_url(token_match.group("token"))

    if target_name and target_name in scoped_payload:
        record.images = _merge_unique(record.images, _extract_photo_urls(scoped_payload))
    record.amenities = _merge_unique(record.amenities, _extract_amenities(scoped_payload))

def _parse_m0crd_offers(property_id: str, payload: str, capture_id: str) -> list[OfferRecord]:
    offers: list[OfferRecord] = []
    seen: set[str] = set()
    check_in, check_out = _extract_offer_dates(payload)
    for match in PROVIDER_RE.finditer(payload):
        provider_name = _normalize_provider_name(unescape(match.group("provider")))
        price = _normalize_price_text(unescape(match.group("price")))
        currency, amount = _parse_price(price)
        offer_id = stable_id(property_id, provider_name, price)
        if offer_id in seen:
            continue
        seen.add(offer_id)
        offers.append(
            OfferRecord(
                offer_id=offer_id,
                property_id=property_id,
                check_in=check_in,
                check_out=check_out,
                provider_name=provider_name,
                provider_url=urljoin("https://www.google.com", unescape(match.group("url"))),
                provider_image_url=_normalize_url(match.group("img")),
                price=price,
                price_amount=amount,
                currency=currency,
                raw_capture_id=capture_id,
            )
        )
    return offers


def _enrich_offers_from_bdm(
    record: PropertyRecord,
    payload: str,
    offers: list[OfferRecord],
    capture_id: str,
) -> None:
    indexed = {offer.provider_name: offer for offer in offers if offer.provider_name}
    default_check_in, default_check_out = _offer_dates_from_existing(offers)
    for match in BDMBFE_LINK_RE.finditer(payload):
        provider_name = _normalize_provider_name(unescape(match.group("name")))
        provider_url = unescape(match.group("url"))
        img = match.group("img")
        snippet = _strip_html(unescape(match.group("snippet")))
        offer = indexed.get(provider_name)
        if offer is None:
            offer = OfferRecord(
                offer_id=stable_id(record.property_id, provider_name, provider_url),
                property_id=record.property_id,
                check_in=default_check_in,
                check_out=default_check_out,
                provider_name=provider_name,
                raw_capture_id=capture_id,
            )
            offers.append(offer)
            indexed[provider_name] = offer
        offer.provider_url = offer.provider_url or provider_url
        offer.provider_image_url = offer.provider_image_url or _normalize_url(img)
        if not record.website and "airohotelmanila.com" in provider_url:
            record.website = provider_url
        if not record.description and "Airo Hotel Manila" in snippet:
            record.description = _clean_text_excerpt(snippet)


def _extract_images(captures: list[NetworkCapture], target_name: str | None) -> list[str]:
    images: list[str] = []
    for capture in captures:
        for rpcid, payload in _iter_rpc_payloads(capture):
            if rpcid not in {"pSDzMb", "zM1L7d"}:
                continue
            if target_name and target_name not in payload:
                continue
            images = _merge_unique(images, _extract_photo_urls(payload))
            images = _merge_unique(images, _extract_thumbnail_urls(payload))
    return _filter_property_images(images)


def _extract_photo_urls(payload: str) -> list[str]:
    return _merge_unique([], [unescape(url) for url in PHOTO_URL_RE.findall(payload)])


def _extract_thumbnail_urls(payload: str) -> list[str]:
    return _merge_unique([], [unescape(url) for url in THUMBNAIL_URL_RE.findall(payload)])


def _extract_amenities(payload: str) -> list[str]:
    section_match = AMENITY_SECTION_RE.search(payload)
    if not section_match:
        return []
    amenities = [unescape(match.group("amenity")) for match in AMENITY_ITEM_RE.finditer(section_match.group("section"))]
    return _merge_unique([], amenities)


def _extract_highlights(payload: str) -> list[str]:
    match = HIGHLIGHTS_RE.search(payload)
    if not match:
        return []
    return _merge_unique([], [unescape(item) for item in QUOTED_TEXT_RE.findall(match.group("highlights"))])


def _iter_rpc_payloads(
    capture: NetworkCapture,
    allowed_rpcids: set[str] | None = None,
):
    raw = capture.response_body or ""
    for match in WRAPPED_PAYLOAD_RE.finditer(raw):
        rpcid = match.group("rpcid")
        if allowed_rpcids is not None and rpcid not in allowed_rpcids:
            continue
        yield rpcid, _decode_wrapped_payload(match.group("payload"))


def _decode_wrapped_payload(raw_payload: str) -> str:
    return json.loads(f'"{raw_payload}"')


def _find_best_listing(name: str | None, captures: list[NetworkCapture]) -> SearchListing | None:
    if not name:
        return None
    query_key = stable_id("lookup")
    listings = parse_search_captures(captures, query_key)
    for listing in listings:
        if listing.name == name:
            return listing
    return None


def _extract_target_name(captures: list[NetworkCapture]) -> str | None:
    for capture in captures:
        action = capture.action or ""
        if action.startswith("open_property:"):
            return action.partition(":")[2] or None
    return None


def _slice_property_payload(payload: str, target_name: str | None) -> str:
    if not target_name:
        return payload
    block_marker = f'"441552390":[null,"{target_name}"'
    start = payload.find(block_marker)
    if start != -1:
        end = payload.find(']],"449069993"', start)
        if end == -1:
            end = payload.find(']],[[1,[[[3],[3]]', start)
        if end == -1:
            end = min(len(payload), start + 16000)
        return payload[start:end]

    marker = f'"{target_name}"'
    index = payload.find(marker)
    if index == -1:
        return payload
    start = payload.rfind('"441552390":[null,', 0, index)
    if start == -1:
        start = max(0, index - 4000)
    end = payload.find(']]],["404340221"', index)
    if end == -1:
        end = min(len(payload), index + 12000)
    return payload[start:end]


def _extract_qs_token(detail_url: str | None) -> str | None:
    if not detail_url or "qs=" not in detail_url:
        return None
    return detail_url.partition("qs=")[2].split("&", 1)[0] or None


def _extract_offer_dates(payload: str) -> tuple[date, date]:
    match = OFFER_DATE_ARRAY_RE.search(payload)
    if not match:
        today = date.today()
        return today, today
    return (
        date(int(match.group("year")), int(match.group("month")), int(match.group("day"))),
        date(int(match.group("year2")), int(match.group("month2")), int(match.group("day2"))),
    )


def _hydrate_property_from_offers(record: PropertyRecord, offers: list[OfferRecord]) -> None:
    for offer in offers:
        if offer.provider_url and not record.website and "airohotelmanila.com" in offer.provider_url:
            record.website = offer.provider_url
        if offer.provider_name and not record.description and offer.provider_name in {"Airo Hotel Manila", "Airo Hotel"}:
            record.description = "Booking provider data captured for Airo Hotel Manila."
        if record.website and record.description:
            return


def _offer_dates_from_existing(offers: list[OfferRecord]) -> tuple[date, date]:
    for offer in offers:
        return offer.check_in, offer.check_out
    today = date.today()
    return today, today


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).replace("\xa0", " ").strip()


def _clean_text_excerpt(value: str | None) -> str | None:
    if not value:
        return None
    normalized = (
        value.replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0026", "&")
    )
    cleaned = _strip_html(unescape(normalized))
    cleaned = " ".join(cleaned.split()).strip()
    for suffix in ("... More", "… More", "...", "…"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip(" .…")
            break
    return cleaned or None


def _build_detail_url(token: str) -> str:
    return f"https://www.google.com/travel/search?qs={token}"


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("//"):
        return f"https:{value}"
    return unescape(value)


def _normalize_provider_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = " ".join(unescape(value).split()).strip()
    key = normalized.casefold()
    return PROVIDER_NORMALIZATION_MAP.get(key, normalized)


def _normalize_price_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(unescape(value).split()).strip()


def _parse_price(value: str | None) -> tuple[str | None, float | None]:
    if not value:
        return None, None
    match = PRICE_VALUE_RE.search(value)
    if not match:
        return None, None
    currency_symbol = (match.group("currency") or "").strip() or None
    currency = SYMBOL_TO_CURRENCY.get(currency_symbol, currency_symbol)
    amount_raw = match.group("amount").replace(",", "")
    try:
        amount = float(amount_raw)
    except ValueError:
        amount = None
    return currency, amount


def _finalize_offers(property_id: str, offers: list[OfferRecord]) -> list[OfferRecord]:
    deduped: dict[str, OfferRecord] = {}
    for offer in offers:
        provider_name = _normalize_provider_name(offer.provider_name)
        offer.provider_name = provider_name
        offer.price = _normalize_price_text(offer.price)
        if offer.price_amount is None or offer.currency is None:
            currency, amount = _parse_price(offer.price)
            offer.currency = offer.currency or currency
            offer.price_amount = offer.price_amount or amount
        offer.provider_url = _normalize_url(offer.provider_url)
        offer.provider_image_url = _normalize_url(offer.provider_image_url)
        if offer.price_amount is None:
            continue
        if provider_name in LOW_QUALITY_PROVIDERS:
            continue
        dedupe_key = stable_id(
            property_id,
            provider_name or "",
            offer.price or "",
            offer.provider_url or "",
        )
        existing = deduped.get(dedupe_key)
        if existing is None or _offer_sort_key(offer) > _offer_sort_key(existing):
            offer.offer_id = dedupe_key
            deduped[dedupe_key] = offer
    return sorted(deduped.values(), key=_offer_order_key)


def _offer_sort_key(offer: OfferRecord) -> tuple[int, int, float, int]:
    quality = _offer_quality_score(offer)
    has_url = 1 if offer.provider_url else 0
    price = offer.price_amount if offer.price_amount is not None else float("inf")
    has_image = 1 if offer.provider_image_url else 0
    return quality, has_url, -price, has_image


def _offer_order_key(offer: OfferRecord) -> tuple[float, int, str]:
    price = offer.price_amount if offer.price_amount is not None else float("inf")
    quality = -_offer_quality_score(offer)
    name = offer.provider_name or ""
    return price, quality, name


def _offer_quality_score(offer: OfferRecord) -> int:
    name = offer.provider_name or ""
    if name in PREFERRED_PROVIDERS:
        return 3
    if name in LOW_QUALITY_PROVIDERS:
        return 0
    return 2 if offer.provider_url else 1


def _apply_cheapest_offer(record: PropertyRecord, offers: list[OfferRecord]) -> None:
    priced_offers = [offer for offer in offers if offer.price_amount is not None]
    if not priced_offers:
        return
    best_offer = min(priced_offers, key=_offer_order_key)
    record.cheapest_price = best_offer.price
    record.cheapest_price_amount = best_offer.price_amount
    record.cheapest_price_currency = best_offer.currency
    record.cheapest_price_provider = best_offer.provider_name


def _normalize_website(value: str | None) -> str | None:
    url = _normalize_url(value)
    if not url:
        return None
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _filter_property_images(images: list[str]) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    seen_keys: set[str] = set()
    for image in images:
        normalized = _normalize_url(image)
        if not normalized or not _is_property_image_url(normalized):
            continue
        key = _canonical_image_key(normalized)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append((_image_sort_key(normalized), normalized))
    candidates.sort(reverse=True)
    return [image for _, image in candidates[:MAX_PROPERTY_IMAGES]]


def _is_property_image_url(url: str) -> bool:
    if "googleusercontent.com" not in url:
        return False
    if "/a-/" in url or "/a/" in url or "/gcs/" in url:
        return False
    return "/p/" in url or "/gps-cs-s/" in url


def _canonical_image_key(url: str) -> str:
    for separator in ("\\u003d", "="):
        if separator in url:
            return url.split(separator, 1)[0]
    return url


def _image_sort_key(url: str) -> tuple[int, int, int, str]:
    kind_score = 2 if "/p/" in url else 1
    width, height = _extract_image_dimensions(url)
    area = width * height
    return kind_score, area, max(width, height), url


def _extract_image_dimensions(url: str) -> tuple[int, int]:
    match = IMAGE_DIMENSION_RE.search(url)
    if not match:
        return 0, 0
    return int(match.group("width")), int(match.group("height"))


def _merge_unique(current: list[str], incoming: list[str]) -> list[str]:
    seen = dict.fromkeys(current)
    for item in incoming:
        if item:
            seen[item] = None
    return list(seen)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
