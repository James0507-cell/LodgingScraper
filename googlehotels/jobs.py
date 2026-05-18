from __future__ import annotations

from dataclasses import dataclass

from .models import HotelQuery, PanelName


@dataclass(slots=True)
class SearchJob:
    query: HotelQuery


@dataclass(slots=True)
class PropertyJob:
    query: HotelQuery
    detail_url: str
    property_id: str | None = None


@dataclass(slots=True)
class PanelJob:
    query: HotelQuery
    detail_url: str
    property_id: str
    panels: list[PanelName]
