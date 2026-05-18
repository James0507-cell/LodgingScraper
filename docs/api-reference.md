# API Reference

This document explains the HTTP API exposed by the scraper server.

The API is designed for application use, especially from a mobile app backend or trip-planning service. It exposes the same scraper flows that already exist in the CLI:

- live search
- live detail scraping
- live probe scraping
- offline replay
- live replay
- access to stored runs
- access to stored properties
- async job submission and polling

## Base Server

Start the server from the project root:

```bash
python main.py serve --host 127.0.0.1 --port 8000
```

Base URL during local development:

```text
http://127.0.0.1:8000
```

## General Notes

- All request bodies must be JSON objects.
- All responses are JSON.
- Dates must use `YYYY-MM-DD`.
- Live scraper endpoints can take time because they may open a real browser session or replay live requests.
- Output quality depends on the underlying scraper mode:
  - `search` is best for discovery
  - `detail` is weaker for full property extraction
  - `replay` with `live=true` is currently the strongest mode for complete property data

## Common Fields

These fields appear in many requests:

- `destination`
  - Type: `string`
  - Example: `"Manila"`
  - Meaning: destination to search in Google Hotels

- `check_in`
  - Type: `string`
  - Format: `YYYY-MM-DD`
  - Example: `"2026-06-10"`

- `check_out`
  - Type: `string`
  - Format: `YYYY-MM-DD`
  - Example: `"2026-06-11"`

- `adults`
  - Type: `integer`
  - Default: `2`

- `children`
  - Type: `integer`
  - Default: `0`

- `rooms`
  - Type: `integer`
  - Default: `1`

- `currency`
  - Type: `string | null`
  - Example: `"PHP"`
  - Optional

- `locale`
  - Type: `string | null`
  - Example: `"en-US"`
  - Optional

- `headful`
  - Type: `boolean`
  - Default: `false`
  - Meaning: if `true`, the browser is visible during live browser-based scraping

## Shared Response Structure

Most scraper endpoints return this top-level structure:

```json
{
  "command": "replay",
  "run": {
    "run_id": "dcf6752254384d36ae068160b8a3c1c7",
    "stage": "replay",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "opened_panels": ["offers", "reviews", "photos", "about"],
    "captures": 26,
    "rpcids": {
      "AtySUc": 6,
      "ocp93e": 4,
      "pSDzMb": 2
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/dcf6752254384d36ae068160b8a3c1c7/bundle.json",
    "run_json": "artifacts/dcf6752254384d36ae068160b8a3c1c7/run.json"
  }
}
```

Possible response payloads after that:

- `places`
  - used by search
  - list of listing-level results

- `place`
  - used by detail, probe, replay, and stored property lookup
  - one fully structured place record

- `booking_options`
  - used when offers exist but no `place` is present

## Error Response Format

If the request fails, the server returns:

```json
{
  "error": "A message explaining the problem."
}
```

Typical failure status codes:

- `400`
  - invalid or missing arguments
- `404`
  - requested stored run or property was not found
- `500`
  - scraper execution error or server-side failure

## 1. Health Check

### Endpoint

```http
GET /health
```

### Purpose

Checks whether the API server is running.

### Request Arguments

None.

### Example Request

```bash
curl http://127.0.0.1:8000/health
```

### Example Response

```json
{
  "status": "ok"
}
```

## 2. List Recent Runs

### Endpoint

```http
GET /api/runs
```

### Purpose

Returns recently stored scraper runs from SQLite.

### Query Arguments

- `limit`
  - Type: `integer`
  - Default: `20`
  - Meaning: maximum number of recent runs to return

### Example Request

```bash
curl "http://127.0.0.1:8000/api/runs?limit=5"
```

### Example Response

```json
{
  "runs": [
    {
      "run_id": "dcf6752254384d36ae068160b8a3c1c7",
      "stage": "replay",
      "started_at": "2026-05-18T13:21:05.123456+00:00",
      "finished_at": "2026-05-18T13:21:07.654321+00:00",
      "status": "success",
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "listing_id": null,
      "error": null
    }
  ]
}
```

## 3. Get One Stored Run

### Endpoint

```http
GET /api/runs/<run_id>
```

### Purpose

Returns metadata for one stored run and, if available, the saved parsed bundle from disk.

### Path Arguments

- `run_id`
  - Type: `string`
  - Meaning: scraper run identifier

### Example Request

```bash
curl http://127.0.0.1:8000/api/runs/dcf6752254384d36ae068160b8a3c1c7
```

### Example Response

```json
{
  "run": {
    "run_id": "dcf6752254384d36ae068160b8a3c1c7",
    "stage": "replay",
    "started_at": "2026-05-18T13:21:05.123456+00:00",
    "finished_at": "2026-05-18T13:21:07.654321+00:00",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "listing_id": null,
    "error": null
  },
  "artifacts": {
    "bundle_json": "artifacts/dcf6752254384d36ae068160b8a3c1c7/bundle.json",
    "run_json": "artifacts/dcf6752254384d36ae068160b8a3c1c7/run.json"
  },
  "bundle": {
    "property_record": {
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "name": "Airo Hotel Manila"
    }
  }
}
```

## 4. Get One Stored Property

### Endpoint

```http
GET /api/properties/<property_id>
```

### Purpose

Returns one stored property record from SQLite, plus the saved booking options currently associated with it.

### Path Arguments

- `property_id`
  - Type: `string`
  - Meaning: canonical scraper property identifier

### Optional Query Arguments

- `check_in`
  - Type: `string`
  - Format: `YYYY-MM-DD`
  - Meaning: filter offers to one stay date

- `check_out`
  - Type: `string`
  - Format: `YYYY-MM-DD`
  - Meaning: filter offers to one stay date

### Example Request

```bash
curl "http://127.0.0.1:8000/api/properties/CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA?check_in=2026-06-10&check_out=2026-06-11"
```

### Example Response

```json
{
  "place": {
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "name": "Airo Hotel Manila",
    "rating": 4.0,
    "review_count": 249,
    "address": "427 Antonio Flores, corner L Guerrero St, Ermita, Manila, 1000 Metro Manila",
    "coordinates": {
      "latitude": 14.5787274,
      "longitude": 120.9790879
    },
    "images": [
      "https://lh3.googleusercontent.com/p/AF1QipO_example_1",
      "https://lh3.googleusercontent.com/p/AF1QipO_example_2"
    ],
    "cheapest_price": "₱1,053",
    "cheapest_price_amount": 1053.0,
    "cheapest_price_currency": "PHP",
    "cheapest_price_provider": "Priceline",
    "booking_options": [
      {
        "offer_id": "offer-1",
        "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
        "provider_name": "Priceline",
        "provider_url": "https://www.google.com/aclk?...",
        "provider_image_url": "https://www.gstatic.com/travel-hotels/branding/priceline.png",
        "price": "₱1,053",
        "price_amount": 1053.0,
        "currency": "PHP",
        "room_type": null,
        "cancellation_policy": null,
        "scraped_at": "2026-05-18T13:21:07.100000+00:00",
        "raw_capture_id": "capture-1"
      }
    ],
    "contact": {
      "phone": "0945 259 6433",
      "website": "https://www.airohotelmanila.com/"
    },
    "check_in_time": "3:00 PM",
    "check_out_time": "12:00 PM",
    "description": "Airo Hotel Manila in Manila provides adults-only accommodation with air-conditioned rooms and a central city location.",
    "amenities": [
      "Free Wi-Fi",
      "Air conditioning"
    ],
    "amenity_groups": [
      {
        "title": "Popular amenities",
        "items": ["Free Wi-Fi", "Air conditioning"]
      }
    ],
    "canonical_url": "https://www.google.com/travel/search?...",
    "google_entity_id": "gcid:example"
  }
}
```

## 5. Get One Async Job

### Endpoint

```http
GET /api/jobs/<job_id>
```

### Purpose

Returns the current status of one async job created through `/api/jobs/...`.

### Path Arguments

- `job_id`
  - Type: `string`
  - Meaning: async scraper job identifier

### Example Request

```bash
curl http://127.0.0.1:8000/api/jobs/6c23d38892fb4379b95fe1a4bbf35247
```

### Example Response While Running

```json
{
  "job_id": "6c23d38892fb4379b95fe1a4bbf35247",
  "kind": "replay",
  "status": "running",
  "cache_key": "a8cbb8e5656d4d38a4b909f1a0f7f0f12be5a4ed4b1f30b65f8edc915cbefb39",
  "created_at": "2026-05-18T13:40:00.100000+00:00",
  "updated_at": "2026-05-18T13:40:00.300000+00:00",
  "error": null
}
```

### Example Response When Complete

```json
{
  "job_id": "6c23d38892fb4379b95fe1a4bbf35247",
  "kind": "replay",
  "status": "success",
  "cache_key": "a8cbb8e5656d4d38a4b909f1a0f7f0f12be5a4ed4b1f30b65f8edc915cbefb39",
  "created_at": "2026-05-18T13:40:00.100000+00:00",
  "updated_at": "2026-05-18T13:40:02.100000+00:00",
  "error": null,
  "result": {
    "command": "replay",
    "run": {
      "run_id": "live-replay-run-id",
      "stage": "replay",
      "status": "success",
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "opened_panels": ["offers", "reviews", "photos", "about"],
      "captures": 10,
      "rpcids": {
        "AtySUc": 4
      }
    },
    "artifact_paths": {
      "bundle_json": "artifacts/live-replay-run-id/bundle.json",
      "run_json": "artifacts/live-replay-run-id/run.json"
    },
    "place": {
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "name": "Airo Hotel Manila"
    }
  }
}
```

## 6. Live Search

### Endpoint

```http
POST /api/search
```

### Purpose

Runs a live Google Hotels search and returns listing-level results.

This is the best endpoint for:

- destination discovery
- collecting `detail_url`
- collecting candidate `property_id` values if present downstream

This is not the best endpoint for a complete property record.

### Request Body

Required:

- `destination`
- `check_in`
- `check_out`

Optional:

- `adults`
- `children`
- `rooms`
- `currency`
- `locale`
- `headful`

### Example Request

```json
{
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11",
  "adults": 2,
  "children": 0,
  "rooms": 1,
  "headful": false
}
```

### Example cURL

```bash
curl -X POST http://127.0.0.1:8000/api/search ^
  -H "Content-Type: application/json" ^
  -d "{\"destination\":\"Manila\",\"check_in\":\"2026-06-10\",\"check_out\":\"2026-06-11\",\"adults\":2,\"children\":0,\"rooms\":1}"
```

### Example Response

```json
{
  "command": "search",
  "run": {
    "run_id": "search-run-id",
    "stage": "search",
    "status": "success",
    "property_id": null,
    "opened_panels": [],
    "captures": 22,
    "rpcids": {
      "AtySUc": 5
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/search-run-id/bundle.json",
    "run_json": "artifacts/search-run-id/run.json"
  },
  "places": [
    {
      "listing_id": "listing-1",
      "name": "Airo Hotel Manila",
      "rating": 4.0,
      "review_count": 249,
      "visible_price": "₱1,053",
      "thumbnail_url": "https://lh3.googleusercontent.com/p/example-thumb",
      "detail_url": "https://www.google.com/travel/search?q=Manila&qs=CAEgACgAMihDaG9J..."
    },
    {
      "listing_id": "listing-2",
      "name": "Another Hotel",
      "rating": null,
      "review_count": null,
      "visible_price": null,
      "thumbnail_url": null,
      "detail_url": "https://www.google.com/travel/search?q=Manila&qs=AnotherToken..."
    }
  ]
}
```

### Important Notes

- Some results may still have `null` values for:
  - `rating`
  - `review_count`
  - `visible_price`
  - `thumbnail_url`
- `detail_url` is the most important output from this endpoint.

## 7. Live Detail Scraping

### Endpoint

```http
POST /api/detail
```

### Purpose

Opens one known Google Hotels result URL and attempts to extract detailed property information.

### Request Body

Required:

- `destination`
- `check_in`
- `check_out`
- `detail_url`

Optional:

- `property_id`
- `adults`
- `children`
- `rooms`
- `currency`
- `locale`
- `headful`

### Request Body Example

```json
{
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11",
  "detail_url": "https://www.google.com/travel/search?q=Manila&qs=CAEgACgAMihDaG9J...",
  "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
  "headful": false
}
```

### Example Response

```json
{
  "command": "detail",
  "run": {
    "run_id": "detail-run-id",
    "stage": "detail",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "opened_panels": [],
    "captures": 18,
    "rpcids": {
      "AtySUc": 4,
      "bdmBfe": 2
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/detail-run-id/bundle.json",
    "run_json": "artifacts/detail-run-id/run.json"
  },
  "place": {
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "name": null,
    "rating": null,
    "review_count": null,
    "address": null,
    "coordinates": {
      "latitude": null,
      "longitude": null
    },
    "images": [
      "https://lh3.googleusercontent.com/p/example-1"
    ],
    "cheapest_price": "₱1,053",
    "cheapest_price_amount": 1053.0,
    "cheapest_price_currency": "PHP",
    "cheapest_price_provider": "Priceline",
    "booking_options": [
      {
        "offer_id": "offer-1",
        "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
        "provider_name": "Priceline",
        "provider_url": "https://www.google.com/aclk?...",
        "provider_image_url": "https://www.gstatic.com/travel-hotels/branding/priceline.png",
        "price": "₱1,053",
        "price_amount": 1053.0,
        "currency": "PHP",
        "room_type": null,
        "cancellation_policy": null,
        "scraped_at": "2026-05-18T13:21:07.100000+00:00",
        "raw_capture_id": "capture-1"
      }
    ],
    "contact": {
      "phone": null,
      "website": null
    },
    "check_in_time": null,
    "check_out_time": null,
    "description": null,
    "amenities": [],
    "amenity_groups": [],
    "canonical_url": null,
    "google_entity_id": null
  }
}
```

### Important Notes

- This endpoint is currently not the strongest full-property endpoint.
- It often returns offers and some images correctly, but some core fields may remain `null`.

## 8. Live Probe Scraping

### Endpoint

```http
POST /api/probe
```

### Purpose

Runs a live search, opens one property by name, and traverses specific panels.

This is mainly useful for:

- debugging scraper behavior
- collecting fresh artifacts
- deeper browser-driven scraping

### Request Body

Required:

- `destination`
- `check_in`
- `check_out`

Optional:

- `property_name`
- `panels`
- `adults`
- `children`
- `rooms`
- `currency`
- `locale`
- `headful`

### `panels` Argument

Type: `string`

Comma-separated panel names. Supported values:

- `prices`
- `offers`
- `reviews`
- `photos`
- `about`
- `amenities`
- `contact`
- `policies`
- `overview`

Recommended default:

```text
prices,reviews,photos,about
```

### Request Body Example

```json
{
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11",
  "property_name": "Airo Hotel Manila",
  "panels": "prices,reviews,photos,about",
  "headful": false
}
```

### Example Response

```json
{
  "command": "probe",
  "run": {
    "run_id": "probe-run-id",
    "stage": "probe",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "opened_panels": ["offers", "reviews", "photos", "about"],
    "captures": 26,
    "rpcids": {
      "AtySUc": 6,
      "ocp93e": 4,
      "pSDzMb": 2,
      "bdmBfe": 2
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/probe-run-id/bundle.json",
    "run_json": "artifacts/probe-run-id/run.json"
  },
  "place": {
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "name": "Airo Hotel Manila",
    "rating": 4.0,
    "review_count": 249,
    "address": "427 Antonio Flores, corner L Guerrero St, Ermita, Manila, 1000 Metro Manila",
    "coordinates": {
      "latitude": 14.5787274,
      "longitude": 120.9790879
    },
    "images": [
      "https://lh3.googleusercontent.com/p/example-1",
      "https://lh3.googleusercontent.com/p/example-2"
    ],
    "cheapest_price": "₱1,053",
    "cheapest_price_amount": 1053.0,
    "cheapest_price_currency": "PHP",
    "cheapest_price_provider": "Priceline",
    "booking_options": [
      {
        "offer_id": "offer-1",
        "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
        "provider_name": "Priceline",
        "provider_url": "https://www.google.com/aclk?...",
        "provider_image_url": "https://www.gstatic.com/travel-hotels/branding/priceline.png",
        "price": "₱1,053",
        "price_amount": 1053.0,
        "currency": "PHP",
        "room_type": null,
        "cancellation_policy": null,
        "scraped_at": "2026-05-18T13:21:07.100000+00:00",
        "raw_capture_id": "capture-1"
      }
    ],
    "contact": {
      "phone": "0945 259 6433",
      "website": "https://www.airohotelmanila.com/"
    },
    "check_in_time": "3:00 PM",
    "check_out_time": "12:00 PM",
    "description": "Airo Hotel Manila in Manila provides adults-only accommodation with air-conditioned rooms and a central city location.",
    "amenities": [
      "Free Wi-Fi",
      "Air conditioning"
    ],
    "amenity_groups": [
      {
        "title": "Popular amenities",
        "items": ["Free Wi-Fi", "Air conditioning"]
      }
    ],
    "canonical_url": "https://www.google.com/travel/search?...",
    "google_entity_id": "gcid:example"
  }
}
```

### Important Notes

- This endpoint is one of the best sources for collecting fresh artifacts.
- It depends on browser automation and can be slower than replay.

## 9. Replay Scraping

### Endpoint

```http
POST /api/replay
```

### Purpose

Rebuilds data from a saved artifact run.

It supports two modes:

- offline replay
- live replay

## 8a. Offline Replay

### Request Body

Required:

- `artifact_run`

Optional:

- `property_id`
- `panels`

### Example Request

```json
{
  "artifact_run": "d6dd05565b3740bfa72d92fd1128d487"
}
```

### Example Response

```json
{
  "command": "replay",
  "run": {
    "run_id": "offline-replay-run-id",
    "stage": "replay",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "opened_panels": ["offers", "reviews", "photos", "about"],
    "captures": 26,
    "rpcids": {
      "AtySUc": 6,
      "ocp93e": 4
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/offline-replay-run-id/bundle.json",
    "run_json": "artifacts/offline-replay-run-id/run.json"
  },
  "place": {
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "name": "Airo Hotel Manila",
    "rating": 4.0,
    "review_count": 249,
    "address": "427 Antonio Flores, corner L Guerrero St, Ermita, Manila, 1000 Metro Manila",
    "coordinates": {
      "latitude": 14.5787274,
      "longitude": 120.9790879
    },
    "images": [
      "https://lh3.googleusercontent.com/p/example-1"
    ],
    "cheapest_price": "₱1,053",
    "cheapest_price_amount": 1053.0,
    "cheapest_price_currency": "PHP",
    "cheapest_price_provider": "Priceline",
    "booking_options": [],
    "contact": {
      "phone": "0945 259 6433",
      "website": "https://www.airohotelmanila.com/"
    },
    "check_in_time": "3:00 PM",
    "check_out_time": "12:00 PM",
    "description": "Airo Hotel Manila in Manila provides adults-only accommodation with air-conditioned rooms and a central city location.",
    "amenities": [
      "Free Wi-Fi",
      "Air conditioning"
    ],
    "amenity_groups": [
      {
        "title": "Popular amenities",
        "items": ["Free Wi-Fi", "Air conditioning"]
      }
    ],
    "canonical_url": "https://www.google.com/travel/search?...",
    "google_entity_id": "gcid:example"
  }
}
```

### Notes

- No live data is fetched in offline replay.
- The result is only as fresh as the original artifact.

## 8b. Live Replay

### Request Body

Required:

- `artifact_run`
- `live`
- `destination`
- `check_in`
- `check_out`

Optional:

- `property_id`
- `panels`
- `adults`
- `children`
- `rooms`
- `currency`
- `locale`

### Example Request

```json
{
  "artifact_run": "d6dd05565b3740bfa72d92fd1128d487",
  "live": true,
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11",
  "adults": 2,
  "children": 0,
  "rooms": 1
}
```

### Example Response

```json
{
  "command": "replay",
  "run": {
    "run_id": "live-replay-run-id",
    "stage": "replay",
    "status": "success",
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "opened_panels": ["offers", "reviews", "photos", "about"],
    "captures": 10,
    "rpcids": {
      "AtySUc": 4,
      "ocp93e": 2,
      "bdmBfe": 1
    }
  },
  "artifact_paths": {
    "bundle_json": "artifacts/live-replay-run-id/bundle.json",
    "run_json": "artifacts/live-replay-run-id/run.json"
  },
  "place": {
    "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
    "name": "Airo Hotel Manila",
    "rating": 4.0,
    "review_count": 249,
    "address": "427 Antonio Flores, corner L Guerrero St, Ermita, Manila, 1000 Metro Manila",
    "coordinates": {
      "latitude": 14.5787274,
      "longitude": 120.9790879
    },
    "images": [
      "https://lh3.googleusercontent.com/p/example-1",
      "https://lh3.googleusercontent.com/p/example-2"
    ],
    "cheapest_price": "₱1,053",
    "cheapest_price_amount": 1053.0,
    "cheapest_price_currency": "PHP",
    "cheapest_price_provider": "Priceline",
    "booking_options": [
      {
        "offer_id": "offer-1",
        "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
        "provider_name": "Priceline",
        "provider_url": "https://www.google.com/aclk?...",
        "provider_image_url": "https://www.gstatic.com/travel-hotels/branding/priceline.png",
        "price": "₱1,053",
        "price_amount": 1053.0,
        "currency": "PHP",
        "room_type": null,
        "cancellation_policy": null,
        "scraped_at": "2026-05-18T13:21:07.100000+00:00",
        "raw_capture_id": "capture-1"
      }
    ],
    "contact": {
      "phone": "0945 259 6433",
      "website": "https://www.airohotelmanila.com/"
    },
    "check_in_time": "3:00 PM",
    "check_out_time": "12:00 PM",
    "description": "Airo Hotel Manila in Manila provides adults-only accommodation with air-conditioned rooms and a central city location.",
    "amenities": [
      "Free Wi-Fi",
      "Air conditioning"
    ],
    "amenity_groups": [
      {
        "title": "Popular amenities",
        "items": ["Free Wi-Fi", "Air conditioning"]
      }
    ],
    "canonical_url": "https://www.google.com/travel/search?...",
    "google_entity_id": "gcid:example"
  }
}
```

### Important Notes

- This is currently the strongest endpoint for complete property data.
- It still depends on the original artifact template matching the property/search flow you want to replay.

## 10. Async Job Endpoints

These endpoints are the production-shaped version of the scraper API. They queue work immediately and let the client poll later.

Available async submit routes:

- `POST /api/jobs/search`
- `POST /api/jobs/detail`
- `POST /api/jobs/probe`
- `POST /api/jobs/replay`

Each one accepts the same request body as its non-job equivalent.

### Why Use Job Endpoints

Use them when:

- your mobile app should not wait on a long live scrape request
- you want polling instead of a long blocking HTTP request
- you want cache reuse for repeated identical requests

### Shared Async Submit Response

Example first submission:

```json
{
  "job_id": "6c23d38892fb4379b95fe1a4bbf35247",
  "kind": "replay",
  "status": "pending",
  "cache_key": "a8cbb8e5656d4d38a4b909f1a0f7f0f12be5a4ed4b1f30b65f8edc915cbefb39",
  "created_at": "2026-05-18T13:40:00.100000+00:00",
  "updated_at": "2026-05-18T13:40:00.100000+00:00",
  "error": null
}
```

Example repeated submission served from cache:

```json
{
  "job_id": "f515b3bc04dd406e8a7dbf53ca0ab8bb",
  "kind": "replay",
  "status": "success",
  "cache_key": "a8cbb8e5656d4d38a4b909f1a0f7f0f12be5a4ed4b1f30b65f8edc915cbefb39",
  "created_at": "2026-05-18T13:45:10.200000+00:00",
  "updated_at": "2026-05-18T13:45:10.200000+00:00",
  "error": null,
  "cached": true,
  "result": {
    "command": "replay",
    "run": {
      "run_id": "live-replay-run-id",
      "stage": "replay",
      "status": "success",
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "opened_panels": ["offers", "reviews", "photos", "about"],
      "captures": 10,
      "rpcids": {
        "AtySUc": 4
      }
    },
    "artifact_paths": {
      "bundle_json": "artifacts/live-replay-run-id/bundle.json",
      "run_json": "artifacts/live-replay-run-id/run.json"
    },
    "place": {
      "property_id": "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA",
      "name": "Airo Hotel Manila"
    }
  }
}
```

### `force_refresh`

All async job routes support:

- `force_refresh`
  - Type: `boolean`
  - Default: `false`
  - Meaning: if `true`, skip a valid cache hit and enqueue fresh work anyway

### Async Search Job

```http
POST /api/jobs/search
```

Request body: same as `POST /api/search`, plus optional `force_refresh`.

### Async Detail Job

```http
POST /api/jobs/detail
```

Request body: same as `POST /api/detail`, plus optional `force_refresh`.

### Async Probe Job

```http
POST /api/jobs/probe
```

Request body: same as `POST /api/probe`, plus optional `force_refresh`.

### Async Replay Job

```http
POST /api/jobs/replay
```

Request body: same as `POST /api/replay`, plus optional `force_refresh`.

### Example Mobile-Friendly Flow

1. Submit:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/replay ^
  -H "Content-Type: application/json" ^
  -d "{\"artifact_run\":\"d6dd05565b3740bfa72d92fd1128d487\",\"live\":true,\"destination\":\"Manila\",\"check_in\":\"2026-06-10\",\"check_out\":\"2026-06-11\"}"
```

2. Read `job_id` from the response.

3. Poll:

```bash
curl http://127.0.0.1:8000/api/jobs/<job_id>
```

4. When `status` becomes `success`, read `result.place`.

## Recommendation by Use Case

If your mobile app needs:

- a list of candidate places:
  - use `POST /api/search`

- a complete property payload with pricing:
  - use `POST /api/jobs/replay` with `live=true`

- a property that was already scraped and stored:
  - use `GET /api/properties/<property_id>`

- debugging, artifact collection, or parser validation:
  - use `POST /api/probe`

## Current Known Limitations

- `search` still returns some `null` listing fields.
- `detail` still leaves many property fields `null` in some runs.
- `probe` and live browser endpoints depend on Playwright running correctly in the host environment.
- `replay` with `live=true` is the strongest path right now, but it is still template-driven.
