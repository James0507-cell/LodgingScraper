from __future__ import annotations

from dataclasses import dataclass

from .models import NetworkCapture
from .replay import ReplayTemplate


@dataclass(slots=True)
class ReplayResult:
    capture: NetworkCapture | None
    used_fallback: bool = False


class ReplayClient:
    def __init__(self) -> None:
        self._templates: list[ReplayTemplate] = []

    def add_template(self, template: ReplayTemplate) -> None:
        self._templates.append(template)

    async def execute(self, template: ReplayTemplate) -> ReplayResult:
        # Placeholder for active-session replay once live traffic is understood.
        _ = template
        return ReplayResult(capture=None, used_fallback=True)
