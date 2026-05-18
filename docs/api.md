# API Server

This server wraps the existing scraper so a mobile app can call it over HTTP.

Start it from the project root:

```bash
python main.py serve --host 127.0.0.1 --port 8000
```

## Routes

### `GET /health`

Returns:

```json
{
  "status": "ok"
}
```

### `GET /api/runs`

Returns recent stored runs from SQLite.

Optional query parameters:

- `limit`

Example:

```bash
curl "http://127.0.0.1:8000/api/runs?limit=10"
```

### `GET /api/runs/<run_id>`

Returns one stored run plus the saved `bundle.json` if present.

### `GET /api/properties/<property_id>`

Returns one stored property from SQLite.

Optional query parameters:

- `check_in`
- `check_out`

If dates are provided, stored offers are filtered to that stay window.

### `POST /api/search`

Runs live browser search.

Request body:

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

### `POST /api/detail`

Runs live browser detail scraping for a known `detail_url`.

Request body:

```json
{
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11",
  "detail_url": "https://www.google.com/travel/search?...",
  "property_id": "optional",
  "headful": false
}
```

### `POST /api/probe`

Runs live browser probe mode.

Request body:

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

### `POST /api/replay`

Runs offline or live replay.

Offline replay request:

```json
{
  "artifact_run": "d6dd05565b3740bfa72d92fd1128d487"
}
```

Live replay request:

```json
{
  "artifact_run": "d6dd05565b3740bfa72d92fd1128d487",
  "live": true,
  "destination": "Manila",
  "check_in": "2026-06-10",
  "check_out": "2026-06-11"
}
```

## Response Shape

The API intentionally mirrors the CLI JSON shape.

Search returns:

- `command`
- `run`
- `artifact_paths`
- `places`

Detail, probe, and replay return:

- `command`
- `run`
- `artifact_paths`
- `place`

`place` includes:

- `property_id`
- `name`
- `rating`
- `review_count`
- `address`
- `coordinates`
- `images`
- `cheapest_price`
- `cheapest_price_amount`
- `cheapest_price_currency`
- `cheapest_price_provider`
- `booking_options`
- `contact`
- `check_in_time`
- `check_out_time`
- `description`
- `amenities`
- `amenity_groups`
- `canonical_url`
- `google_entity_id`

## Recommended Mobile-App Flow

1. Use `POST /api/search` for discovery.
2. If you need the strongest current full-property result, call `POST /api/replay` with `"live": true`.
3. Cache `property_id` and later fetch `GET /api/properties/<property_id>` for stored data.

## Current Quality Notes

- `search` is still partial and mainly useful for discovery.
- `detail` still leaves some core property fields null on some runs.
- `replay` with `"live": true` is currently the strongest endpoint for complete property data.
