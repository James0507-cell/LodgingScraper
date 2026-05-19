from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from urllib.parse import parse_qs, urlparse
import uuid
from typing import Any

from .models import (
    AmenityGroup,
    ExtractionBundle,
    HotelQuery,
    NetworkCapture,
    PanelName,
    PropertyRecord,
    ScrapeRun,
    SearchListing,
    Stage,
)
from .parser import parse_property_bundle, parse_search_captures, stable_id
from .planners import include_offer_panel, plan_missing_panels

try:
    from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright, async_playwright
except ImportError:  # pragma: no cover - optional dependency in the scaffold stage
    Browser = BrowserContext = Locator = Page = Playwright = Any  # type: ignore[assignment]
    async_playwright = None


@dataclass(slots=True)
class BrowserConfig:
    headless: bool = True
    timeout_ms: int = 30_000
    locale: str = "en-US"
    blocked_resource_types: tuple[str, ...] = ("font", "media")
    capture_url_filters: tuple[str, ...] = ("/_/TravelFrontendUi/data/batchexecute",)


@dataclass(slots=True)
class CapturedSession:
    run: ScrapeRun
    page_url: str
    captures: list[NetworkCapture] = field(default_factory=list)


class GoogleHotelsScraper:
    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "GoogleHotelsScraper":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if async_playwright is None:
            raise RuntimeError("Playwright is not installed. Add `playwright` to project dependencies first.")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.config.headless)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def run_search(self, query: HotelQuery) -> tuple[ScrapeRun, ExtractionBundle]:
        run = ScrapeRun(run_id=uuid.uuid4().hex, stage=Stage.SEARCH, query=query)
        session = await self._open_session(run, lean=True)
        try:
            page = session.page
            await page.goto(self.build_search_url(query), wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            await self._mark_action(session, "search_load")
            await self._submit_search(page, query)
            await self._validate_search_state(page, query)
            await self._wait_for_search_results(page)
            listings = parse_search_captures(session.captures, self.query_key(query))
            dom_listings = await self._extract_search_listing_dom(page, self.query_key(query))
            listings = self._merge_search_listings(listings, dom_listings)
            return run, ExtractionBundle(listings=listings, captures=session.captures)
        finally:
            await self._close_session(session)

    async def run_property_detail(
        self,
        query: HotelQuery,
        detail_url: str,
        property_id: str | None = None,
    ) -> tuple[ScrapeRun, ExtractionBundle]:
        normalized_property_id = property_id or stable_id(detail_url)
        run = ScrapeRun(
            run_id=uuid.uuid4().hex,
            stage=Stage.DETAIL,
            query=query,
            property_id=normalized_property_id,
        )
        session = await self._open_session(run, lean=False)
        try:
            page = session.page
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            await self._mark_action(session, "detail_load")
            await self._settle(page)
            bundle = parse_property_bundle(normalized_property_id, session.captures)
            record = bundle.property_record
            if record is None:
                return run, bundle

            panels = plan_missing_panels(record)
            if PanelName.ABOUT not in panels:
                panels.append(PanelName.ABOUT)
            panels += include_offer_panel()
            if panels:
                panel_bundle = await self.run_property_panels(query, detail_url, normalized_property_id, panels)
                bundle.captures.extend(panel_bundle[1].captures)
                bundle.offers.extend(panel_bundle[1].offers)
                bundle.property_record = panel_bundle[1].property_record or bundle.property_record
                run.opened_panels.extend(panel_bundle[0].opened_panels)
            return run, bundle
        finally:
            await self._close_session(session)

    async def run_property_panels(
        self,
        query: HotelQuery,
        detail_url: str,
        property_id: str,
        panels: list[PanelName],
    ) -> tuple[ScrapeRun, ExtractionBundle]:
        run = ScrapeRun(
            run_id=uuid.uuid4().hex,
            stage=Stage.PANEL,
            query=query,
            property_id=property_id,
            opened_panels=panels.copy(),
        )
        session = await self._open_session(run, lean=False)
        try:
            page = session.page
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            await self._mark_action(session, "panel_load")
            await self._settle(page)
            for panel in panels:
                opened = await self._open_panel(page, session, panel)
                if opened:
                    await self._settle(page)
                    if panel is PanelName.ABOUT:
                        await self._expand_about_description(page)
                    run.opened_panels.append(panel)
            bundle = parse_property_bundle(property_id, session.captures, opened_panels=run.opened_panels)
            if bundle.property_record is not None:
                dom_record = await self._extract_property_dom(page, property_id)
                self._merge_dom_record(bundle.property_record, dom_record)
            return run, bundle
        finally:
            await self._close_session(session)

    async def run_probe(
        self,
        query: HotelQuery,
        property_name: str | None = None,
        panels: list[PanelName] | None = None,
    ) -> tuple[ScrapeRun, ExtractionBundle]:
        run = ScrapeRun(run_id=uuid.uuid4().hex, stage=Stage.PROBE, query=query)
        session = await self._open_session(run, lean=False)
        try:
            page = session.page
            await self._goto_search(page, query)
            await self._mark_action(session, "search_load")
            await self._settle(page)

            if property_name:
                await self._open_property_from_results(page, session, property_name)
                await self._settle(page)
                run.property_id = self._extract_property_id_from_url(page.url)

            opened_panels: list[PanelName] = []
            for panel in panels or []:
                opened = await self._open_panel(page, session, panel)
                if opened:
                    await self._settle(page)
                    if panel is PanelName.ABOUT:
                        await self._expand_about_description(page)
                    opened_panels.append(panel)
            run.opened_panels = opened_panels

            bundle = ExtractionBundle(captures=session.captures)
            if property_name and run.property_id:
                parsed = parse_property_bundle(run.property_id, session.captures, opened_panels=opened_panels)
                if parsed.property_record is not None:
                    dom_record = await self._extract_property_dom(page, run.property_id)
                    self._merge_dom_record(parsed.property_record, dom_record)
                bundle.property_record = parsed.property_record
                bundle.offers = parsed.offers
                bundle.listings = parsed.listings
            else:
                listings = parse_search_captures(session.captures, self.query_key(query))
                dom_listings = await self._extract_search_listing_dom(page, self.query_key(query))
                bundle.listings = self._merge_search_listings(listings, dom_listings)
            return run, bundle
        finally:
            await self._close_session(session)

    async def _open_session(self, run: ScrapeRun, lean: bool) -> CapturedPageSession:
        if self._browser is None:
            raise RuntimeError("Scraper browser is not started.")
        context = await self._browser.new_context(locale=self.config.locale)
        page = await context.new_page()
        await page.route("**/*", self._route_handler(lean))
        captured_session = CapturedPageSession(run=run, page_url=page.url, context=context, page=page, captures=[])
        page.on("response", lambda response: asyncio.create_task(self._record_response(captured_session, response)))
        return captured_session

    async def _close_session(self, session: "CapturedPageSession") -> None:
        if session.pending_tasks:
            await asyncio.gather(*session.pending_tasks, return_exceptions=True)
        if session.context is not None:
            await session.context.close()

    def _route_handler(self, lean: bool):
        async def handler(route):
            request = route.request
            if lean and request.resource_type in self.config.blocked_resource_types:
                await route.abort()
                return
            await route.continue_()

        return handler

    async def _record_response(self, session: "CapturedPageSession", response) -> None:
        request = response.request
        if self.config.capture_url_filters and not any(fragment in response.url for fragment in self.config.capture_url_filters):
            return
        task = asyncio.current_task()
        if task is not None:
            session.pending_tasks.add(task)
        try:
            body = await response.text()
        except Exception:
            body = None
        finally:
            if task is not None:
                session.pending_tasks.discard(task)
        capture = NetworkCapture(
            capture_id=uuid.uuid4().hex,
            stage=session.run.stage,
            action=session.last_action,
            page_url=session.page.url,
            request_url=request.url,
            request_method=request.method,
            request_headers=dict(request.headers),
            request_body=request.post_data,
            response_status=response.status,
            response_headers=dict(response.headers),
            response_body=body,
            rpcids=self._extract_rpcids(response.url, request.post_data),
        )
        session.captures.append(capture)

    async def _goto_search(self, page: Page, query: HotelQuery) -> None:
        url = self.build_search_url(query)
        await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
        await self._submit_search(page, query)
        await self._validate_search_state(page, query)

    async def _settle(self, page: Page, *, delay_ms: int = 250, networkidle_timeout_ms: int | None = 2_000) -> None:
        if delay_ms > 0:
            await page.wait_for_timeout(delay_ms)
        if networkidle_timeout_ms is None:
            return
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=networkidle_timeout_ms)

    async def _submit_search(self, page: Page, query: HotelQuery) -> None:
        destination = page.get_by_role("combobox", name="Search for places, hotels and more").first
        await destination.wait_for(state="visible", timeout=self.config.timeout_ms)
        await destination.click()
        await destination.fill(query.destination)
        await destination.press("Enter")
        await self._wait_for_destination_value(page, query.destination)
        await self._set_date_range(page, query.check_in, query.check_out)
        if query.adults != 2 or query.children != 0:
            await self._set_travelers(page, query.adults, query.children)

    async def _set_date_range(self, page: Page, check_in: date, check_out: date) -> None:
        check_in_box = page.get_by_role("textbox", name="Check-in").first
        await check_in_box.wait_for(state="visible", timeout=self.config.timeout_ms)
        await check_in_box.click()
        dialog = page.locator('[role="dialog"]').filter(has_text="Enter a date or use the arrow keys").first
        await dialog.wait_for(state="visible", timeout=self.config.timeout_ms)

        reset_button = dialog.get_by_text("Reset", exact=True).first
        if await reset_button.count():
            await reset_button.click()

        await self._click_calendar_day(dialog, check_in)
        await self._click_calendar_day(dialog, check_out)
        await dialog.get_by_text("Done", exact=True).last.click()
        await dialog.wait_for(state="hidden", timeout=self.config.timeout_ms)
        await self._wait_for_date_values(page, check_in, check_out)

    async def _click_calendar_day(self, dialog: Locator, target_date: date) -> None:
        month_label = self._calendar_month_label(target_date)
        day_value = str(target_date.day)
        month_group = dialog.locator('[role="rowgroup"]').filter(has_text=month_label).first
        await month_group.wait_for(state="visible", timeout=self.config.timeout_ms)
        last_error: Exception | None = None
        for _ in range(3):
            day_locator = month_group.get_by_text(day_value, exact=True).first
            if not await day_locator.count():
                raise RuntimeError(f"Could not find calendar day {target_date.isoformat()}.")
            try:
                await day_locator.click()
                return
            except Exception as exc:
                last_error = exc
                await dialog.page.wait_for_timeout(100)
        if last_error is not None:
            raise last_error

    async def _set_travelers(self, page: Page, adults: int, children: int) -> None:
        button = page.get_by_role("button", name="Number of travelers. Current number of travelers").first
        await button.click()
        dialog = page.locator('[role="dialog"]').filter(has_text="AdultsRemove adult").first
        await dialog.wait_for(state="visible", timeout=self.config.timeout_ms)
        await self._adjust_counter(dialog, "adult", adults)
        await self._adjust_counter(dialog, "child", children)
        await dialog.get_by_text("Done", exact=True).last.click()
        await dialog.wait_for(state="hidden", timeout=self.config.timeout_ms)

    async def _adjust_counter(self, dialog: Locator, counter_name: str, target: int) -> None:
        current = await self._read_counter(dialog, counter_name)
        while current != target:
            direction = "Add" if current < target else "Remove"
            action = f"{direction} {counter_name}"
            await dialog.get_by_role("button", name=action).first.click()
            current = await self._read_counter(dialog, counter_name)

    async def _read_counter(self, dialog: Locator, counter_name: str) -> int:
        value = await dialog.evaluate(
            """(node, counterName) => {
                const label = Array.from(node.querySelectorAll('[aria-label]')).find((item) => {
                    return item.getAttribute('aria-label')?.toLowerCase() === `${counterName}s`;
                });
                if (!label) {
                    return null;
                }
                const match = label.textContent?.match(/\\b(\\d+)\\b/);
                return match ? Number(match[1]) : null;
            }""",
            counter_name,
        )
        if value is None:
            raise RuntimeError(f"Could not read {counter_name} counter.")
        return int(value)

    async def _validate_search_state(self, page: Page, query: HotelQuery) -> None:
        destination_value = (await page.get_by_role("combobox", name="Search for places, hotels and more").first.input_value()).strip()
        if destination_value.lower() != query.destination.strip().lower():
            raise RuntimeError(
                f"Search destination mismatch. Expected '{query.destination}', got '{destination_value}'."
            )

        check_in_value = (await page.get_by_role("textbox", name="Check-in").first.input_value()).strip()
        check_out_value = (await page.get_by_role("textbox", name="Check-out").first.input_value()).strip()
        expected_check_in = self._visible_date_value(query.check_in)
        expected_check_out = self._visible_date_value(query.check_out)
        if check_in_value != expected_check_in or check_out_value != expected_check_out:
            raise RuntimeError(
                "Search date mismatch. "
                f"Expected '{expected_check_in}' -> '{expected_check_out}', "
                f"got '{check_in_value}' -> '{check_out_value}'."
            )

    async def _wait_for_destination_value(self, page: Page, expected_destination: str) -> None:
        await page.wait_for_function(
            """([role, expected]) => {
                const element = document.querySelector(role);
                if (!element) {
                    return false;
                }
                const value = (element.value || element.getAttribute('value') || '').trim().toLowerCase();
                return value === expected.trim().toLowerCase();
            }""",
            arg=['input[role="combobox"]', expected_destination],
            timeout=self.config.timeout_ms,
        )

    async def _wait_for_date_values(self, page: Page, check_in: date, check_out: date) -> None:
        expected_check_in = self._visible_date_value(check_in)
        expected_check_out = self._visible_date_value(check_out)
        await page.wait_for_function(
            """([checkInSelector, checkOutSelector, expectedCheckIn, expectedCheckOut]) => {
                const checkIn = document.querySelector(checkInSelector);
                const checkOut = document.querySelector(checkOutSelector);
                if (!checkIn || !checkOut) {
                    return false;
                }
                const checkInValue = (checkIn.value || checkIn.getAttribute('value') || '').trim();
                const checkOutValue = (checkOut.value || checkOut.getAttribute('value') || '').trim();
                return checkInValue === expectedCheckIn && checkOutValue === expectedCheckOut;
            }""",
            arg=['input[aria-label="Check-in"]', 'input[aria-label="Check-out"]', expected_check_in, expected_check_out],
            timeout=self.config.timeout_ms,
        )

    async def _wait_for_search_results(self, page: Page) -> None:
        results = page.locator('div[jsname="mutHjb"]')
        with suppress(Exception):
            await results.first.wait_for(state="visible", timeout=8_000)
        with suppress(Exception):
            await results.nth(9).wait_for(state="visible", timeout=4_000)
        await self._settle(page, delay_ms=500, networkidle_timeout_ms=2_500)

    async def _open_panel(self, page: Page, session: "CapturedPageSession", panel: PanelName) -> bool:
        locators: list[Locator] = {
            PanelName.PHOTOS: [
                page.get_by_role("tab", name="Photos").first,
                page.get_by_text("View photos", exact=True).first,
            ],
            PanelName.REVIEWS: [
                page.get_by_role("tab", name="Reviews").first,
            ],
            PanelName.AMENITIES: [
                page.get_by_text("Amenities", exact=True).first,
                page.get_by_text("What this place offers", exact=True).first,
            ],
            PanelName.ABOUT: [
                page.get_by_role("tab", name="About").first,
                page.get_by_text("Description", exact=True).first,
            ],
            PanelName.POLICIES: [
                page.get_by_text("Policies", exact=True).first,
                page.get_by_text("Check-in", exact=True).first,
                page.get_by_text("Check-out", exact=True).first,
            ],
            PanelName.CONTACT: [
                page.get_by_text("Website", exact=True).first,
                page.get_by_text("Phone", exact=True).first,
            ],
            PanelName.OFFERS: [
                page.get_by_role("tab", name="Prices").first,
                page.get_by_text("Booking options", exact=True).first,
                page.get_by_role("button", name="View prices").first,
                page.get_by_text("Check availability", exact=True).first,
            ],
            PanelName.OVERVIEW: [
                page.get_by_role("tab", name="Overview").first,
            ],
        }[panel]
        for locator in locators:
            if await locator.count():
                await self._mark_action(session, f"panel:{panel.value}")
                with suppress(Exception):
                    await locator.click(timeout=5_000)
                    return True
        return False

    async def _extract_search_listing_dom(self, page: Page, query_key: str) -> list["SearchListing"]:
        cards = await page.locator('div[jsname="mutHjb"]').evaluate_all(
            """(elements) => {
                const clean = (value) => (value || "").replace(/\\s+/g, " ").trim();
                return elements.map((card) => {
                    const name = clean(card.querySelector('h2')?.textContent);
                    if (!name) {
                        return null;
                    }
                    const detailAnchor =
                        Array.from(card.querySelectorAll('a[data-href^="/entity/"]')).find((anchor) => {
                            return clean(anchor.getAttribute('aria-label')) === name;
                        }) || null;
                    const photo = card.querySelector('img[src], img[data-src]');
                    return {
                        name,
                        detail_url: detailAnchor?.href || null,
                        entity_path: detailAnchor?.getAttribute('data-href') || null,
                        thumbnail_url: photo?.getAttribute('src') || photo?.getAttribute('data-src') || null,
                    };
                }).filter(Boolean);
            }"""
        )
        listings = []
        for rank, card in enumerate(cards, start=1):
            name = card.get("name")
            entity_path = card.get("entity_path")
            token = self._extract_entity_token(entity_path)
            if not name or not token:
                continue
            listings.append(
                SearchListing(
                    listing_id=stable_id(token),
                    query_key=query_key,
                    rank=rank,
                    name=name,
                    thumbnail_url=self._normalize_dom_url(card.get("thumbnail_url")),
                    detail_url=card.get("detail_url"),
                )
            )
        return listings

    @staticmethod
    def _merge_search_listings(
        listings: list["SearchListing"],
        dom_listings: list["SearchListing"],
    ) -> list["SearchListing"]:
        if not dom_listings:
            return listings
        merged: dict[str, SearchListing] = {listing.listing_id: listing for listing in listings}
        name_index = {listing.name: listing for listing in listings if listing.name}
        ordered = list(listings)
        for dom_listing in dom_listings:
            target = merged.get(dom_listing.listing_id)
            if target is None and dom_listing.name:
                target = name_index.get(dom_listing.name)
            if target is None:
                ordered.append(dom_listing)
                merged[dom_listing.listing_id] = dom_listing
                if dom_listing.name:
                    name_index[dom_listing.name] = dom_listing
                continue
            target.rank = min(target.rank, dom_listing.rank)
            target.name = target.name or dom_listing.name
            target.thumbnail_url = dom_listing.thumbnail_url or target.thumbnail_url
            target.detail_url = dom_listing.detail_url or target.detail_url
        ordered.sort(key=lambda listing: (listing.rank, listing.name or ""))
        return ordered

    async def _open_property_from_results(self, page: Page, session: "CapturedPageSession", property_name: str) -> None:
        anchor = page.locator(f'a[aria-label="{property_name}"]').first
        if await anchor.count():
            await self._mark_action(session, f"open_property:{property_name}")
            await anchor.evaluate("node => node.click()")
            return
        heading = page.get_by_role("heading", name=property_name).first
        if await heading.count():
            await self._mark_action(session, f"open_property:{property_name}")
            await heading.evaluate("node => node.click()")
            return
        raise RuntimeError(f"Could not find result card for property '{property_name}'.")

    async def _mark_action(self, session: "CapturedPageSession", action: str) -> None:
        session.last_action = action

    async def _expand_about_description(self, page: Page) -> None:
        read_more = page.get_by_role("button", name="Read more").first
        if await read_more.count():
            await read_more.click()
            await self._settle(page)

    async def _extract_property_dom(self, page: Page, property_id: str) -> PropertyRecord:
        panel = page.get_by_role("tabpanel").filter(has=page.get_by_role("heading", name="About this hotel")).first
        if not await panel.count():
            return PropertyRecord(property_id=property_id)

        payload = await panel.evaluate(
            """(panel) => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const cleanItem = (value) => normalize(value).replace(/^[-•·]\\s*/, "");
                const formatItem = (item) => {
                    const parts = Array.from(item.children)
                        .map((child) => normalize(child.innerText || child.textContent))
                        .filter(Boolean);
                    if (!parts.length) {
                        return cleanItem(item.innerText || item.textContent);
                    }
                    if (parts.length === 1) {
                        return parts[0];
                    }
                    return `${parts[0]} (${parts.slice(1).join(', ')})`;
                };

                const byHeading = (tag, text) => Array.from(panel.querySelectorAll(tag)).find((node) => {
                    return normalize(node.textContent) === text;
                });

                const description = (() => {
                    const paragraphs = Array.from(panel.querySelectorAll('p'));
                    const candidate = paragraphs.find((node) => normalize(node.textContent).length > 40);
                    if (!candidate) {
                        return null;
                    }
                    return normalize(candidate.textContent)
                        .replace(/\\s*Read more$/i, "")
                        .replace(/\\s*(?:\\.\\.\\.|…)?\\s*More$/i, "");
                })();

                const times = {};
                for (const node of panel.querySelectorAll('*')) {
                    const text = normalize(node.textContent);
                    if (!times.checkIn && text.startsWith('Check-in time:')) {
                        times.checkIn = normalize(text.split(':').slice(1).join(':'));
                    }
                    if (!times.checkOut && text.startsWith('Check-out time:')) {
                        times.checkOut = normalize(text.split(':').slice(1).join(':'));
                    }
                }

                const addressNode = panel.querySelector('[aria-label*="hotel address is"]');
                const phoneNode = panel.querySelector('[aria-label*="call this hotel"]');
                const websiteLink = Array.from(panel.querySelectorAll('a')).find((node) => normalize(node.textContent) === 'Website');

                const amenityRoot = (() => {
                    const heading = Array.from(panel.querySelectorAll('h2')).find((node) => {
                        return normalize(node.textContent).startsWith('Amenities');
                    });
                    return heading ? heading.parentElement?.parentElement : null;
                })();

                const amenityGroups = [];
                const amenities = [];
                if (amenityRoot) {
                    const groupHeadings = Array.from(amenityRoot.querySelectorAll('h3, h4'));
                    const amenityItems = Array.from(amenityRoot.querySelectorAll('li'));
                    for (const heading of groupHeadings) {
                        const title = normalize(heading.textContent);
                        if (!title || title === 'Energy efficiency') {
                            continue;
                        }
                        const nextHeading = groupHeadings[groupHeadings.indexOf(heading) + 1] || null;
                        const items = amenityItems
                            .filter((item) => {
                                const followsHeading =
                                    Boolean(heading.compareDocumentPosition(item) & Node.DOCUMENT_POSITION_FOLLOWING);
                                const beforeNextHeading =
                                    !nextHeading ||
                                    Boolean(item.compareDocumentPosition(nextHeading) & Node.DOCUMENT_POSITION_FOLLOWING);
                                return followsHeading && beforeNextHeading;
                            })
                            .map((item) => formatItem(item))
                            .filter(Boolean);
                        if (!items.length) {
                            continue;
                        }
                        amenityGroups.push({ title, items });
                        for (const item of items) {
                            amenities.push(title === 'Popular amenities' ? item : `${title}: ${item}`);
                        }
                    }
                }

                return {
                    description,
                    address: addressNode ? normalize(addressNode.textContent) : null,
                    phone: phoneNode ? normalize(phoneNode.textContent) : null,
                    website: websiteLink ? websiteLink.href : null,
                    check_in_time: times.checkIn || null,
                    check_out_time: times.checkOut || null,
                    amenities,
                    amenity_groups: amenityGroups,
                };
            }"""
        )
        record = PropertyRecord(property_id=property_id)
        if not payload:
            return record
        record.description = self._clean_description(payload.get("description"))
        record.address = payload.get("address")
        record.phone = payload.get("phone")
        record.website = payload.get("website")
        record.check_in_time = payload.get("check_in_time")
        record.check_out_time = payload.get("check_out_time")
        record.amenities = [item for item in payload.get("amenities", []) if item]
        record.amenity_groups = [
            AmenityGroup(title=group["title"], items=[item for item in group.get("items", []) if item])
            for group in payload.get("amenity_groups", [])
            if group.get("title")
        ]
        return record

    @staticmethod
    def _merge_dom_record(record: PropertyRecord, dom_record: PropertyRecord) -> None:
        if dom_record.description:
            record.description = dom_record.description
        if dom_record.address:
            record.address = record.address or dom_record.address
        if dom_record.phone:
            record.phone = record.phone or dom_record.phone
        if dom_record.website:
            record.website = record.website or dom_record.website
        if dom_record.check_in_time:
            record.check_in_time = record.check_in_time or dom_record.check_in_time
        if dom_record.check_out_time:
            record.check_out_time = record.check_out_time or dom_record.check_out_time
        if dom_record.amenity_groups:
            record.amenity_groups = dom_record.amenity_groups
        if dom_record.amenities:
            record.amenities = list(dict.fromkeys(dom_record.amenities))

    @staticmethod
    def _clean_description(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.split()).strip()
        cleaned = cleaned.removesuffix("Read more").strip()
        for suffix in ("... More", "… More", "More"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].rstrip(" .…")
                break
        return cleaned or None

    @staticmethod
    def _extract_rpcids(url: str, request_body: str | None) -> list[str]:
        rpcids = parse_qs(urlparse(url).query).get("rpcids", [])
        if rpcids:
            return [item for value in rpcids for item in value.split(",") if item]
        if request_body and "rpcids=" in request_body:
            parsed = parse_qs(request_body)
            return [item for value in parsed.get("rpcids", []) for item in value.split(",") if item]
        return []

    @staticmethod
    def _extract_property_id_from_url(url: str) -> str | None:
        query = parse_qs(urlparse(url).query)
        raw = query.get("qs", [None])[0]
        if raw:
            return raw
        return None

    @staticmethod
    def _extract_entity_token(entity_path: str | None) -> str | None:
        if not entity_path:
            return None
        parts = [part for part in entity_path.split("/") if part]
        if len(parts) < 2 or parts[0] != "entity":
            return None
        return parts[1] or None

    @staticmethod
    def _normalize_dom_url(url: str | None) -> str | None:
        if not url:
            return None
        return unescape(url)

    @staticmethod
    def query_key(query: HotelQuery) -> str:
        return stable_id(
            query.destination,
            query.check_in.isoformat(),
            query.check_out.isoformat(),
            str(query.adults),
            str(query.children),
            str(query.rooms),
        )

    @staticmethod
    def build_search_url(query: HotelQuery) -> str:
        locale = query.locale or "en-US"
        return f"https://www.google.com/travel/hotels?hl={locale}"

    @staticmethod
    def _calendar_month_label(target_date: date) -> str:
        if target_date.year == date.today().year:
            return target_date.strftime("%B")
        return target_date.strftime("%B %Y")

    @staticmethod
    def _visible_date_value(target_date: date) -> str:
        base = f"{target_date.strftime('%a')}, {target_date.strftime('%b')} {target_date.day}"
        if target_date.year != date.today().year:
            return f"{base}, {target_date.year}"
        return base


@dataclass(slots=True)
class CapturedPageSession(CapturedSession):
    context: BrowserContext | None = None
    page: Page | Any = None
    last_action: str = "initial_load"
    pending_tasks: set[asyncio.Task] = field(default_factory=set)
