from __future__ import annotations

import json
from pathlib import Path

from .models import ExtractionBundle, NetworkCapture, ScrapeRun, to_jsonable


class ArtifactStore:
    def __init__(self, root: str | Path = "artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_run(self, run: ScrapeRun) -> Path:
        run_dir = self.run_dir(run.run_id)
        path = run_dir / "run.json"
        path.write_text(json.dumps(to_jsonable(run), indent=2), encoding="utf-8")
        return path

    def write_capture(self, run_id: str, capture: NetworkCapture) -> Path:
        run_dir = self.run_dir(run_id) / "captures"
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{capture.capture_id}.json"
        path.write_text(json.dumps(to_jsonable(capture), indent=2), encoding="utf-8")
        return path

    def write_bundle(self, run_id: str, bundle: ExtractionBundle) -> Path:
        run_dir = self.run_dir(run_id)
        path = run_dir / "bundle.json"
        path.write_text(json.dumps(to_jsonable(bundle), indent=2), encoding="utf-8")
        return path
