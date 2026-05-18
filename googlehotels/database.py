from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import AmenityGroup, OfferRecord, PropertyRecord, ScrapeRun


class Database:
    def __init__(self, path: str | Path = "googlehotels.sqlite3") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def session(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    property_id TEXT,
                    listing_id TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS properties (
                    property_id TEXT PRIMARY KEY,
                    canonical_url TEXT,
                    google_entity_id TEXT,
                    name TEXT,
                    address TEXT,
                    latitude REAL,
                    longitude REAL,
                    rating REAL,
                    review_count INTEGER,
                    description TEXT,
                    cheapest_price TEXT,
                    cheapest_price_amount REAL,
                    cheapest_price_currency TEXT,
                    cheapest_price_provider TEXT,
                    phone TEXT,
                    website TEXT,
                    check_in_time TEXT,
                    check_out_time TEXT,
                    property_type TEXT,
                    images_json TEXT NOT NULL,
                    amenities_json TEXT NOT NULL,
                    amenity_groups_json TEXT NOT NULL DEFAULT '[]',
                    raw_capture_ids_json TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS offers (
                    offer_id TEXT PRIMARY KEY,
                    property_id TEXT NOT NULL,
                    check_in TEXT NOT NULL,
                    check_out TEXT NOT NULL,
                    provider_name TEXT,
                    provider_url TEXT,
                    provider_image_url TEXT,
                    price TEXT,
                    price_amount REAL,
                    currency TEXT,
                    room_type TEXT,
                    cancellation_policy TEXT,
                    scraped_at TEXT NOT NULL,
                    raw_capture_id TEXT,
                    FOREIGN KEY (property_id) REFERENCES properties (property_id)
                );

                CREATE TABLE IF NOT EXISTS api_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cache_key TEXT,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    run_id TEXT,
                    property_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """
            )
            self._ensure_property_column(connection, "amenity_groups_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_property_column(connection, "cheapest_price", "TEXT")
            self._ensure_property_column(connection, "cheapest_price_amount", "REAL")
            self._ensure_property_column(connection, "cheapest_price_currency", "TEXT")
            self._ensure_property_column(connection, "cheapest_price_provider", "TEXT")
            self._ensure_offer_column(connection, "price_amount", "REAL")

    @staticmethod
    def _ensure_property_column(connection: sqlite3.Connection, column_name: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(properties)")
        }
        if column_name not in existing:
            connection.execute(f"ALTER TABLE properties ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _ensure_offer_column(connection: sqlite3.Connection, column_name: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(offers)")
        }
        if column_name not in existing:
            connection.execute(f"ALTER TABLE offers ADD COLUMN {column_name} {definition}")

    def save_run(self, run: ScrapeRun) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO scrape_runs (
                    run_id, stage, started_at, finished_at, status, property_id, listing_id, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    property_id = excluded.property_id,
                    listing_id = excluded.listing_id,
                    error = excluded.error
                """,
                (
                    run.run_id,
                    run.stage.value,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status.value,
                    run.property_id,
                    run.listing_id,
                    run.error,
                ),
            )

    def save_property(self, record: PropertyRecord) -> None:
        import json

        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO properties (
                    property_id, canonical_url, google_entity_id, name, address, latitude, longitude,
                    rating, review_count, description, cheapest_price, cheapest_price_amount,
                    cheapest_price_currency, cheapest_price_provider, phone, website, check_in_time, check_out_time,
                    property_type, images_json, amenities_json, amenity_groups_json, raw_capture_ids_json, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(property_id) DO UPDATE SET
                    canonical_url = excluded.canonical_url,
                    google_entity_id = excluded.google_entity_id,
                    name = excluded.name,
                    address = excluded.address,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    rating = excluded.rating,
                    review_count = excluded.review_count,
                    description = excluded.description,
                    cheapest_price = excluded.cheapest_price,
                    cheapest_price_amount = excluded.cheapest_price_amount,
                    cheapest_price_currency = excluded.cheapest_price_currency,
                    cheapest_price_provider = excluded.cheapest_price_provider,
                    phone = excluded.phone,
                    website = excluded.website,
                    check_in_time = excluded.check_in_time,
                    check_out_time = excluded.check_out_time,
                    property_type = excluded.property_type,
                    images_json = excluded.images_json,
                    amenities_json = excluded.amenities_json,
                    amenity_groups_json = excluded.amenity_groups_json,
                    raw_capture_ids_json = excluded.raw_capture_ids_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    record.property_id,
                    record.canonical_url,
                    record.google_entity_id,
                    record.name,
                    record.address,
                    record.latitude,
                    record.longitude,
                    record.rating,
                    record.review_count,
                    record.description,
                    record.cheapest_price,
                    record.cheapest_price_amount,
                    record.cheapest_price_currency,
                    record.cheapest_price_provider,
                    record.phone,
                    record.website,
                    record.check_in_time,
                    record.check_out_time,
                    record.property_type,
                    json.dumps(record.images),
                    json.dumps(record.amenities),
                    json.dumps([{"title": group.title, "items": group.items} for group in record.amenity_groups]),
                    json.dumps(record.raw_capture_ids),
                    record.last_seen_at.isoformat(),
                ),
            )

    def save_offers(self, offers: list[OfferRecord]) -> None:
        with self.session() as connection:
            connection.executemany(
                """
                INSERT INTO offers (
                    offer_id, property_id, check_in, check_out, provider_name, provider_url,
                    provider_image_url, price, price_amount, currency, room_type, cancellation_policy,
                    scraped_at, raw_capture_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(offer_id) DO UPDATE SET
                    provider_name = excluded.provider_name,
                    provider_url = excluded.provider_url,
                    provider_image_url = excluded.provider_image_url,
                    price = excluded.price,
                    price_amount = excluded.price_amount,
                    currency = excluded.currency,
                    room_type = excluded.room_type,
                    cancellation_policy = excluded.cancellation_policy,
                    scraped_at = excluded.scraped_at,
                    raw_capture_id = excluded.raw_capture_id
                """,
                [
                    (
                        offer.offer_id,
                        offer.property_id,
                        offer.check_in.isoformat(),
                        offer.check_out.isoformat(),
                        offer.provider_name,
                        offer.provider_url,
                        offer.provider_image_url,
                        offer.price,
                        offer.price_amount,
                        offer.currency,
                        offer.room_type,
                        offer.cancellation_policy,
                        offer.scraped_at.isoformat(),
                        offer.raw_capture_id,
                    )
                    for offer in offers
                ],
            )

    def get_run(self, run_id: str) -> dict | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT run_id, stage, started_at, finished_at, status, property_id, listing_id, error
                FROM scrape_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "stage": row["stage"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "property_id": row["property_id"],
            "listing_id": row["listing_id"],
            "error": row["error"],
        }

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT run_id, stage, started_at, finished_at, status, property_id, listing_id, error
                FROM scrape_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "stage": row["stage"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "property_id": row["property_id"],
                "listing_id": row["listing_id"],
                "error": row["error"],
            }
            for row in rows
        ]

    def get_property(self, property_id: str) -> PropertyRecord | None:
        import json

        with self.session() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM properties
                WHERE property_id = ?
                """,
                (property_id,),
            ).fetchone()
        if row is None:
            return None
        amenity_groups = [
            AmenityGroup(
                title=str(group.get("title", "")).strip(),
                items=[item for item in group.get("items", []) if isinstance(item, str)],
            )
            for group in json.loads(row["amenity_groups_json"] or "[]")
            if isinstance(group, dict) and str(group.get("title", "")).strip()
        ]
        return PropertyRecord(
            property_id=row["property_id"],
            canonical_url=row["canonical_url"],
            google_entity_id=row["google_entity_id"],
            name=row["name"],
            address=row["address"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            rating=row["rating"],
            review_count=row["review_count"],
            description=row["description"],
            images=json.loads(row["images_json"] or "[]"),
            cheapest_price=row["cheapest_price"],
            cheapest_price_amount=row["cheapest_price_amount"],
            cheapest_price_currency=row["cheapest_price_currency"],
            cheapest_price_provider=row["cheapest_price_provider"],
            amenities=json.loads(row["amenities_json"] or "[]"),
            amenity_groups=amenity_groups,
            phone=row["phone"],
            website=row["website"],
            check_in_time=row["check_in_time"],
            check_out_time=row["check_out_time"],
            property_type=row["property_type"],
            raw_capture_ids=json.loads(row["raw_capture_ids_json"] or "[]"),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )

    def get_offers(
        self,
        property_id: str,
        *,
        check_in: date | None = None,
        check_out: date | None = None,
    ) -> list[OfferRecord]:
        query = """
            SELECT *
            FROM offers
            WHERE property_id = ?
        """
        params: list[object] = [property_id]
        if check_in is not None:
            query += " AND check_in = ?"
            params.append(check_in.isoformat())
        if check_out is not None:
            query += " AND check_out = ?"
            params.append(check_out.isoformat())
        query += " ORDER BY price_amount ASC, scraped_at DESC"
        with self.session() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [
            OfferRecord(
                offer_id=row["offer_id"],
                property_id=row["property_id"],
                check_in=date.fromisoformat(row["check_in"]),
                check_out=date.fromisoformat(row["check_out"]),
                provider_name=row["provider_name"],
                provider_url=row["provider_url"],
                provider_image_url=row["provider_image_url"],
                price=row["price"],
                price_amount=row["price_amount"],
                currency=row["currency"],
                room_type=row["room_type"],
                cancellation_policy=row["cancellation_policy"],
                scraped_at=datetime.fromisoformat(row["scraped_at"]),
                raw_capture_id=row["raw_capture_id"],
            )
            for row in rows
        ]

    def create_job(self, job_id: str, kind: str, status: str, request_json: str, cache_key: str | None, created_at: str) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO api_jobs (job_id, kind, status, cache_key, request_json, result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (job_id, kind, status, cache_key, request_json, created_at, created_at),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result_json: str | None = None,
        error: str | None = None,
        updated_at: str,
    ) -> None:
        with self.session() as connection:
            connection.execute(
                """
                UPDATE api_jobs
                SET status = ?, result_json = COALESCE(?, result_json), error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, result_json, error, updated_at, job_id),
            )

    def get_job(self, job_id: str) -> dict | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT job_id, kind, status, cache_key, request_json, result_json, error, created_at, updated_at
                FROM api_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "kind": row["kind"],
            "status": row["status"],
            "cache_key": row["cache_key"],
            "request": row["request_json"],
            "result": row["result_json"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_cache(
        self,
        *,
        cache_key: str,
        endpoint: str,
        payload_json: str,
        run_id: str | None,
        property_id: str | None,
        created_at: str,
        expires_at: str,
    ) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO api_cache (cache_key, endpoint, payload_json, run_id, property_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    payload_json = excluded.payload_json,
                    run_id = excluded.run_id,
                    property_id = excluded.property_id,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (cache_key, endpoint, payload_json, run_id, property_id, created_at, expires_at),
            )

    def get_cache(self, cache_key: str, now_iso: str) -> dict | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT cache_key, endpoint, payload_json, run_id, property_id, created_at, expires_at
                FROM api_cache
                WHERE cache_key = ? AND expires_at >= ?
                """,
                (cache_key, now_iso),
            ).fetchone()
        if row is None:
            return None
        return {
            "cache_key": row["cache_key"],
            "endpoint": row["endpoint"],
            "payload_json": row["payload_json"],
            "run_id": row["run_id"],
            "property_id": row["property_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
