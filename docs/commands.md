# Scraper Commands

This document explains the current CLI commands in `main.py`, what each command is for, how to run it, and what kind of output quality to expect.

All commands are run from the project root:

```bash
python main.py <command> ...
```

## Quick Summary

- `init-db`
  - Creates the SQLite database used to store runs, properties, and offers.
- `search`
  - Runs a live Google Hotels search and returns listing-level results.
  - Best for discovery.
  - Not a full property scraper.
- `detail`
  - Opens one known property result URL and tries to extract property data.
  - Currently weaker than `replay --live` for complete property extraction.
- `probe`
  - Development/debug mode that runs a search, opens one property, and traverses selected panels.
  - Best for collecting raw artifacts and testing browser behavior.
- `replay`
  - Replays a previous artifact run.
  - With `--live`, this is currently the strongest mode for complete property data.

## Common Query Arguments

These are used by `search`, `detail`, and `probe`:

- `--destination`
  - Search destination such as `"Manila"`.
- `--check-in`
  - Check-in date in `YYYY-MM-DD`.
- `--check-out`
  - Check-out date in `YYYY-MM-DD`.
- `--adults`
  - Number of adults. Default: `2`.
- `--children`
  - Number of children. Default: `0`.
- `--rooms`
  - Number of rooms. Default: `1`.
- `--currency`
  - Optional currency code if supported by the flow.
- `--locale`
  - Optional locale such as `en-US`.

## Output Behavior

Every scraping command prints JSON to stdout and also writes artifacts under:

- `artifacts/<run_id>/bundle.json`
- `artifacts/<run_id>/run.json`

The JSON shape depends on the command:

- `search`
  - prints `places`
  - each item is a listing-level record
- `detail`, `probe`, `replay`
  - print `place`
  - includes property-level fields and booking options when available

## 1. Initialize the Database

Command:

```bash
python main.py init-db
```

Use a custom database path:

```bash
python main.py init-db --db googlehotels.sqlite3
```

What it does:

- Creates the SQLite database file if it does not exist.
- Initializes the tables used by the scraper.

When to use it:

- Run once before using the scraper.
- Run again if you want to recreate the schema in a different file.

## 2. Run a Live Search

Command:

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

What it does:

- Opens Google Hotels in a live browser session.
- Submits the destination and date range through the UI.
- Collects the visible search result cards.
- Merges browser DOM and network payload data into listing results.

What it returns:

- `listing_id`
- `name`
- `rating`
- `review_count`
- `visible_price`
- `thumbnail_url`
- `detail_url`

What it is good for:

- Discovering places to scrape further.
- Getting result-card links that can be passed to `detail`.

Current limitation:

- `search` is not a full property scraper.
- Some listings still come back with null `rating`, `review_count`, `visible_price`, or `thumbnail_url`.
- `detail_url` is the most reliable field in this mode and is the main output you should reuse.

Recommended use:

1. Run `search`.
2. Pick a `detail_url` from the output.
3. Use that `detail_url` with `detail`, or use `replay --live` if you want the most complete property data.

## 3. Run Property Detail Scraping

Command:

```bash
python main.py detail --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --detail-url "https://www.google.com/travel/search?q=Manila&qs=CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA&hl=en-US&ved=0CKcBEMr3BGoYChMI8MS8geLClAMVAAAAAB0AAAAAELsB&ts=CAESCgoCCAMKAggDEAAaXAo-EjoKCS9tLzAxOTVwZDIlMHgzMzk3Y2EwMzU3MWVjMzhiOjB4NjlkMWQ1NzUxMDY5YzExZjoGTWFuaWxhGgASGhIUCgcI6g8QBhgKEgcI6g8QBhgLGAEyAggBKgkKBToDUEhQGgA&ap=MAE"
```

Headful browser mode:

```bash
python main.py detail --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --detail-url "https://www.google.com/travel/search?q=Manila&qs=CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA&hl=en-US&ved=0CKcBEMr3BGoYChMI8MS8geLClAMVAAAAAB0AAAAAELsB&ts=CAESCgoCCAMKAggDEAAaXAo-EjoKCS9tLzAxOTVwZDIlMHgzMzk3Y2EwMzU3MWVjMzhiOjB4NjlkMWQ1NzUxMDY5YzExZjoGTWFuaWxhGgASGhIUCgcI6g8QBhgKEgcI6g8QBhgLGAEyAggBKgkKBToDUEhQGgA&ap=MAE" --headful
```

What it does:

- Opens a known Google Hotels property result URL.
- Attempts to traverse the property page and selected sections automatically.
- Extracts property fields and booking options.

What it returns:

- property-level JSON in `place`
- booking providers and prices
- some images

What it is good for:

- Testing a specific property page directly.
- Scraping one known listing without running `probe`.

Current limitation:

- This mode is still inconsistent for some core property fields.
- In current testing, it often fills offers and images but leaves some core fields null, such as:
  - `name`
  - `address`
  - `coordinates`
  - `phone`
  - `check_in_time`
  - `check_out_time`
  - `google_entity_id`
  - `canonical_url`

Recommendation:

- Use `detail` if you want a direct browser test against a known result URL.
- For the most complete current output, prefer `replay --live`.

## 4. Run Full Probe Mode

Command:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about
```

Headful browser mode:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about --headful
```

With more panels:

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about,amenities,contact,policies
```

What it does:

- Runs a live search.
- Opens one property by visible result name.
- Clicks specific panels/tabs.
- Captures network traffic and parsed output.
- Saves everything as artifacts for later replay and parser work.

What it is good for:

- Debugging.
- Reverse engineering.
- Collecting fresh artifact runs for `replay`.
- Testing whether panel traversal still works after Google UI changes.

Recommended panel list:

```text
prices,reviews,photos,about
```

Supported panel names:

- `prices`
- `offers`
- `reviews`
- `photos`
- `about`
- `amenities`
- `contact`
- `policies`
- `overview`

Current note:

- `probe` is the most useful browser-debug command.
- If Playwright process startup fails in your environment, `probe` will fail before scraper logic runs. That is an environment/process issue, not a parsing issue.

## 5. Run Replay Mode

Replay has 2 forms:

- offline replay
- live replay

### 5a. Offline Replay

By run id:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487
```

By artifact directory path:

```bash
python main.py replay --artifact-run "artifacts/d6dd05565b3740bfa72d92fd1128d487"
```

Override property id:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487 --property-id "CAEgACgAMihDaG9Jb0t6MC1xeWlwYlhqQVJvTkwyY3ZNVEZvWDJzd05UQnNlaEFCOA1IAA"
```

Override replay panels:

```bash
python main.py replay --artifact-run d6dd05565b3740bfa72d92fd1128d487 --panels prices,reviews,photos,about
```

What it does:

- Loads a previously saved artifact run.
- Rebuilds the parsed result from saved captures.
- Does not fetch fresh live data unless `--live` is added.

What it is good for:

- Parser testing.
- Reproducing earlier runs.
- Comparing parser changes against a known artifact.

### 5b. Live Replay

Command:

```bash
python main.py replay --live --artifact-run d6dd05565b3740bfa72d92fd1128d487
```

With explicit query overrides:

```bash
python main.py replay --live --artifact-run d6dd05565b3740bfa72d92fd1128d487 --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11
```

What it does:

- Starts from a previously captured artifact run.
- Reuses the saved request templates.
- Fetches fresh live data over HTTP.
- Reparses the fresh responses into the normal property output shape.

What it returns:

- property name
- rating
- review count
- address
- coordinates
- images
- cheapest price
- booking options
- contact details
- check-in and check-out times
- description
- amenities
- amenity groups

Why this mode matters:

- In current testing, `replay --live` is the most complete mode.
- It is currently stronger than `detail` for full property extraction.

Current limitation:

- It is still template-driven.
- It depends on the saved artifact having the right request structure for the same property flow.

## Recommended Workflows

## Discover listings only

```bash
python main.py search --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11
```

Use this when:

- you want a list of places
- you want `detail_url` values for follow-up scraping

## Test one property in the browser

```bash
python main.py detail --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --detail-url "<detail_url from search>"
```

Use this when:

- you want a direct browser scrape for one property
- you want to inspect how strong the current `detail` extraction is

## Collect a fresh debugging artifact

```bash
python main.py probe --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11 --property-name "Airo Hotel Manila" --panels prices,reviews,photos,about
```

Use this when:

- you want fresh raw captures
- you are debugging selectors, panels, or parser behavior

## Get the most complete current property output

```bash
python main.py replay --live --artifact-run d6dd05565b3740bfa72d92fd1128d487 --destination "Manila" --check-in 2026-06-10 --check-out 2026-06-11
```

Use this when:

- you want the strongest current extraction quality
- you want a fuller place record with fewer null fields

## Current Quality Status

Based on recent live runs:

- `search`
  - good for listing discovery
  - `detail_url` is reliable
  - many `thumbnail_url` values are still null
  - some listing-level rating and price fields are also null
- `detail`
  - works for offers and some images
  - still leaves many core property attributes null
- `replay --live`
  - currently the best command for complete property data
  - most important place fields are populated consistently for the tested property

## Artifact Notes

The newest successful runs can always be inspected under `artifacts/<run_id>/`.

Useful files:

- `run.json`
  - run metadata
  - command stage
  - capture counts
  - rpc ids seen
- `bundle.json`
  - parsed scraper output
  - this is the main file to inspect when checking extraction quality
