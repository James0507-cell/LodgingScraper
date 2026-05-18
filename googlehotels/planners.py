from __future__ import annotations

from .models import PanelName, PropertyRecord


def plan_missing_panels(record: PropertyRecord) -> list[PanelName]:
    panels: list[PanelName] = []
    if len(record.images) < 5:
        panels.append(PanelName.PHOTOS)
    if not record.amenities:
        panels.append(PanelName.AMENITIES)
    if not record.description:
        panels.append(PanelName.ABOUT)
    if not record.phone or not record.website:
        panels.append(PanelName.CONTACT)
    if not record.check_in_time or not record.check_out_time:
        panels.append(PanelName.POLICIES)
    return panels


def include_offer_panel(always: bool = True) -> list[PanelName]:
    return [PanelName.OFFERS] if always else []
