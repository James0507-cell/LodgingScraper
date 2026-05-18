from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from googlehotels.models import PanelName, Stage
from googlehotels.replay_client import ReplayClient


ARTIFACT_DIR = Path("artifacts/d6dd05565b3740bfa72d92fd1128d487")


class ReplayModeTests(unittest.TestCase):
    def test_replay_client_rebuilds_property_bundle_from_artifacts(self) -> None:
        client = ReplayClient("artifacts")
        result = asyncio.run(client.replay_artifact(ARTIFACT_DIR.name))

        self.assertEqual(result.run.stage, Stage.REPLAY)
        self.assertEqual(result.source_run_id, ARTIFACT_DIR.name)
        self.assertIsNotNone(result.bundle.property_record)
        assert result.bundle.property_record is not None
        self.assertEqual(result.bundle.property_record.name, "Airo Hotel Manila")
        self.assertEqual(result.bundle.property_record.cheapest_price_provider, "Priceline")
        self.assertIn(PanelName.ABOUT, result.run.opened_panels)
        self.assertTrue(result.bundle.property_record.amenity_groups)
        self.assertTrue(result.bundle.offers)
        self.assertTrue(result.bundle.captures)


if __name__ == "__main__":
    unittest.main()
