# Scraper Commands

This project currently supports live browser-based scraping through the CLI in `main.py`.

## Initialize the database

```bash
python main.py init-db
```

Use a custom SQLite path if needed:

```bash
python main.py init-db --db googlehotels.sqlite3
```

## Run a search

Runs a live Google Hotels search and prints JSON output to the terminal.

```bash
python main.py search --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11
```

Headful browser mode:

```bash
python main.py search --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --headful
```

With explicit occupancy:

```bash
python main.py search --destination "Davao" --check-in 2026-06-10 --check-out 2026-06-11 --adults 2 --children 0 --rooms 1
```

## Run property detail scraping

Opens one known Google Hotels property detail URL and extracts place data.

```bash
python main.py detail --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --detail-url "https://www.google.com/travel/search?qs=ChoIoKz0-qyipbXjARoNL2cvMTFoX2swNTBsehAB"
```

Headful browser mode:

```bash
python main.py detail --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --detail-url "https://www.google.com/travel/search?qs=ChoIoKz0-qyipbXjARoNL2cvMTFoX2swNTBsehAB" --headful
```

## Run full probe mode

`probe` is the most complete development/testing mode. It:
- runs a search
- optionally opens a property by visible name
- traverses selected panels
- prints parsed JSON to stdout
- saves artifacts under `artifacts/<run_id>/`

Example:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about
```

Headful browser mode:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about --headful
```

Probe with additional panels:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about,amenities,contact,policies
```

## Supported panel names

Use these values in `--panels`:

- `prices`
- `offers`
- `reviews`
- `photos`
- `about`
- `amenities`
- `contact`
- `policies`
- `overview`

## Output

All live scrape commands print JSON to stdout and also save artifacts:

- `artifacts/<run_id>/bundle.json`
- `artifacts/<run_id>/run.json`

## Run replay mode

Replays one saved artifact run and prints parsed JSON to stdout.

Offline replay from saved captures:

By run id:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487
```

By artifact directory path:

```bash
python main.py replay --artifact-run "artifacts/d6dd05565b3740bfa72d92fd1128d487"
```

Override the property id if needed:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487 --property-id "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA"
```

Override the panels associated with the replay parse:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487 --panels prices,reviews,photos,about
```

Live HTTP replay using the saved request templates:

```bash
python main.py replay --live --artifact-run d6dd05565b3740bfa72d92fd1128d487
```

Live HTTP replay with explicit dates and destination:

```bash
python main.py replay --live --artifact-run d6dd05565b3740bfa72d92fd1128d487 --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11
```

The JSON output includes, when available:

- place name
- rating
- review count
- address
- coordinates
- images
- cheapest price
- cheapest price provider
- booking options
- contact details
- check-in / check-out times
- description
- amenities
- amenity groups

## Current limitation

Live replay is HTTP-based and reuses saved batchexecute templates from an earlier browser run. It is fresh data, but it is still template-driven:

- it depends on the saved artifact having the right request shapes
- property replay is scoped to the saved property flow
- some DOM-only fields still fall back to the saved `bundle.json` when they are not present in the live RPC responses
