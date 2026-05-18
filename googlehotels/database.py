from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import OfferRecord, PropertyRecord, ScrapeRun


class Database:
    def __init__(self, path: str | Path = "googlehotels.sqlite3") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
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
        with self.connect() as connection:
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

        with self.connect() as connection:
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
        with self.connect() as connection:
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
