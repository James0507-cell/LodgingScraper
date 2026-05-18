from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from googlehotels.models import NetworkCapture, PanelName, Stage
from googlehotels.parser import parse_property_bundle


ARTIFACT_DIR = Path("artifacts/d6dd05565b3740bfa72d92fd1128d487")
CAPTURES_DIR = ARTIFACT_DIR / "captures"
PROPERTY_ID = "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA"


def _load_captures() -> list[NetworkCapture]:
    captures: list[NetworkCapture] = []
    for path in sorted(CAPTURES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        captures.append(
            NetworkCapture(
                capture_id=payload["capture_id"],
                stage=Stage(payload["stage"]),
                action=payload["action"],
                page_url=payload["page_url"],
                request_url=payload["request_url"],
                request_method=payload["request_method"],
                request_headers=payload.get("request_headers", {}),
                request_body=payload.get("request_body"),
                response_status=payload.get("response_status"),
                response_headers=payload.get("response_headers", {}),
                response_body=payload.get("response_body"),
                captured_at=datetime.fromisoformat(payload["captured_at"]),
                parser_version=payload.get("parser_version", "0"),
                rpcids=payload.get("rpcids", []),
            )
        )
    return captures


class ParserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.captures = _load_captures()
        cls.raw_image_urls = [
            image
            for capture in cls.captures
            for image in ((capture.response_body or "").split("https://"))
            if "googleusercontent.com" in image
        ]
        cls.bundle = parse_property_bundle(
            PROPERTY_ID,
            cls.captures,
            opened_panels=[PanelName.OFFERS, PanelName.REVIEWS, PanelName.PHOTOS, PanelName.ABOUT],
        )
        cls.record = cls.bundle.property_record

    def test_property_core_fields_are_present(self) -> None:
        self.assertIsNotNone(self.record)
        assert self.record is not None
        self.assertEqual(self.record.name, "Airo Hotel Manila")
        self.assertTrue(self.record.description)
        self.assertIn("Airo Hotel Manila in Manila", self.record.description or "")
        self.assertIn("air-conditioned rooms", self.record.description or "")
        self.assertEqual(self.record.phone, "0945 259 6433")
        self.assertEqual(self.record.website, "https://www.airohotelmanila.com/")
        self.assertEqual(self.record.check_in_time, "3:00\u202fPM")
        self.assertEqual(self.record.check_out_time, "12:00\u202fPM")
        self.assertEqual(self.record.cheapest_price, "₱1,053")
        self.assertEqual(self.record.cheapest_price_amount, 1053.0)
        self.assertEqual(self.record.cheapest_price_currency, "PHP")
        self.assertEqual(self.record.cheapest_price_provider, "Priceline")

    def test_offers_are_parsed_for_multiple_providers(self) -> None:
        assert self.record is not None
        providers = {offer.provider_name for offer in self.bundle.offers}
        self.assertIn("Agoda", providers)
        self.assertIn("Booking.com", providers)
        self.assertIn("Skyscanner", providers)
        self.assertTrue({"Tripadvisor", "KAYAK.com.ph"} & providers)
        self.assertNotIn("Bluepillow", providers)
        self.assertNotIn("Muv AI", providers)
        self.assertNotIn("Tripening Hotels", providers)
        self.assertTrue(any(offer.price for offer in self.bundle.offers))
        self.assertTrue(all(offer.price_amount is not None for offer in self.bundle.offers))

    def test_images_are_filtered_to_property_assets(self) -> None:
        assert self.record is not None
        self.assertTrue(self.record.images)
        self.assertGreaterEqual(len(self.record.images), 10)
        self.assertLessEqual(len(self.record.images), 20)
        self.assertLess(len(self.record.images), len(self.raw_image_urls))
        self.assertTrue(any("/p/" in image for image in self.record.images))
        self.assertFalse(any("/a-/" in image or "/a/" in image for image in self.record.images))
        self.assertFalse(any("/gcs/" in image for image in self.record.images))
        unique_keys = {image.split("\\u003d", 1)[0].split("=", 1)[0] for image in self.record.images}
        self.assertEqual(len(unique_keys), len(self.record.images))


if __name__ == "__main__":
    unittest.main()
