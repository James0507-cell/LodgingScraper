from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectionSelector:
    name: str
    label_patterns: tuple[str, ...]


SEARCH_RESULTS = SectionSelector(
    name="search_results",
    label_patterns=("Hotels", "Places to stay", "Results"),
)

PROPERTY_HEADER = SectionSelector(
    name="property_header",
    label_patterns=("Overview", "About", "Photos"),
)

PANELS: tuple[SectionSelector, ...] = (
    SectionSelector("photos", ("Photos", "View photos")),
    SectionSelector("amenities", ("Amenities", "What this place offers")),
    SectionSelector("about", ("About", "Description")),
    SectionSelector("policies", ("Policies", "Property policies")),
    SectionSelector("contact", ("Website", "Phone")),
    SectionSelector("offers", ("Prices", "Booking options", "View prices")),
)
