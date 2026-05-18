from __future__ import annotations

import http.client
import json
import threading
import unittest
from pathlib import Path

from googlehotels.api import create_server
from googlehotels.service import ScraperService, ServiceConfig


ARTIFACT_RUN = "d6dd05565b3740bfa72d92fd1128d487"
PROPERTY_ID = "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA"


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = Path("tests/.api-test.sqlite3")
        cls.artifacts_root = Path("tests/.api-artifacts")
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls.artifacts_root.mkdir(exist_ok=True)
        service = ScraperService(
            ServiceConfig(
                artifacts_root=cls.artifacts_root,
                database_path=cls.db_path,
                replay_artifacts_root="artifacts",
            )
        )
        cls.server = create_server("127.0.0.1", 0, service)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.server.server_address

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls.db_path.exists():
            cls.db_path.unlink()
        if cls.artifacts_root.exists():
            for path in sorted(cls.artifacts_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            cls.artifacts_root.rmdir()

    def request_json(self, method: str, path: str, payload: dict | None = None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw)

    def test_health_endpoint(self) -> None:
        status, payload = self.request_json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_replay_endpoint_returns_place_payload(self) -> None:
        status, payload = self.request_json(
            "POST",
            "/api/replay",
            {
                "artifact_run": ARTIFACT_RUN,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["command"], "replay")
        self.assertEqual(payload["place"]["name"], "Airo Hotel Manila")
        self.assertTrue(payload["place"]["booking_options"])
        self.assertTrue(payload["place"]["amenity_groups"])

    def test_property_endpoint_returns_persisted_property(self) -> None:
        replay_status, replay_payload = self.request_json(
            "POST",
            "/api/replay",
            {
                "artifact_run": ARTIFACT_RUN,
            },
        )
        self.assertEqual(replay_status, 200)
        self.assertEqual(replay_payload["place"]["property_id"], PROPERTY_ID)

        status, payload = self.request_json("GET", f"/api/properties/{PROPERTY_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["place"]["name"], "Airo Hotel Manila")
        self.assertEqual(payload["place"]["cheapest_price_provider"], "Priceline")


if __name__ == "__main__":
    unittest.main()
