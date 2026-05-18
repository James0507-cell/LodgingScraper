# Google Hotels Scraper Project Guide

This document explains the procedure used to build the Google Flights scraper so the same approach can be reused for a new Google Hotels scraper project.

The goal is not to copy the Flights code blindly. The goal is to reuse the architecture, the development order, and the important system boundaries.

## Core Approach

The Flights scraper was built as a network-first scraper, not a DOM-first scraper.

That means the project was designed around this idea:

1. Use Playwright to drive the live site.
2. Find the real backend request that returns the useful data.
3. Capture the request and response.
4. Parse the response into your own normalized models.
5. Archive both raw and parsed data.
6. Add a replay path so repeated queries can skip most of the UI work.

For Google Hotels, the same process is the right starting point.

## Recommended Build Procedure

Build the Hotels project in this order.

### 1. Start With One Live Browser Query

Do not begin with parsers, databases, or batch systems.

First prove that you can:

- open Google Hotels
- submit one search
- identify the backend request that contains hotel results
- capture the raw response

This is the most important first milestone.

If this step is weak, everything built on top of it will be weak.

### 2. Save Raw Request And Response Samples

As soon as one live query works, archive:

- request URL
- request body
- request headers if relevant
- raw response body
- timestamp
- query inputs

Do this before writing a serious parser.

Reason:

- real samples drive parser development
- real samples make replay possible later
- real samples give you regression fixtures for tests

### 3. Build A Parser Around Real Samples

Only after you have real response samples should you build the parser.

For Hotels, normalize data into your own schema, for example:

- hotel name
- property id
- check-in date
- check-out date
- nightly price
- total price
- taxes and fees if available
- currency
- review score
- review count
- address
- neighborhood
- amenities
- room type
- cancellation policy
- booking link or token

The important rule is:

- parse into your own stable model
- do not let the rest of the code depend on Google’s raw internal payload shape

### 4. Add Storage Early

Once live capture and parsing work, add storage immediately.

Store:

- raw captures
- parsed results
- run metadata

This makes debugging much easier and prevents the scraper from becoming a black box.

### 5. Add Replay Only After Browser Mode Works

Replay was not the first thing built in the Flights scraper.

First the browser path was made to work. After that, replay was added as a speed optimization.

Use the same rule for Hotels:

- browser mode first
- replay second

Replay depends on understanding the live request shape. You only get that after the browser path is working and archived.

### 6. Add Batch And Benchmarking After Single-Query Success

Do not start with concurrency.

First prove:

- one query works
- one query parses correctly
- one query archives correctly

Then add:

- batch mode
- replay reuse
- benchmarking
- persistence queries

### 7. Add Reports After Persistence Exists

Reports should come after the data model and storage are stable enough.

Typical reports for Hotels might be:

- cheapest hotels for a city/date range
- price changes over time
- median nightly price by market
- replay vs browser timing summary
- capture success/failure rates

## Project Structure To Reuse

The Flights project ended up with a structure that is worth copying.

Use a similar package layout for Hotels.

### Root Files

- [main.py](C:/Users/Admin/PycharmProjects/FlightScraperV2/main.py)
  - Thin entrypoint.
  - Keeps startup simple.
  - Delegates immediately into the package CLI.

### Main Package

Current Flights package:

- `flightscraperv2/`

For Hotels, use something like:

- `googlehotels/`
  - or
- `hotelsscraper/`

Inside that package, keep the same responsibilities.

## Purpose Of Each Important Module

### `cli.py`

Purpose:

- command-line entrypoint
- argument parsing
- single-query mode
- batch mode
- benchmark mode
- report mode

Why it matters:

- this becomes the control surface for everything else
- keep it focused on orchestration, not scraping details

For Hotels, this should probably be one of the first files created.

### `models.py`

Purpose:

- define normalized query and result models
- define network capture model
- define full run metadata model

Why it matters:

- this keeps the scraper internally consistent
- this prevents parser and storage code from inventing their own shapes

This is one of the most important files in the project.

For Hotels, expect models like:

- `HotelQuery`
- `HotelOffer`
- `RoomOffer`
- `NetworkCapture`
- `ScrapeRun`

### `google_flights.py`

Purpose:

- Playwright browser automation
- live query submission
- network-response capture

Why it matters:

- this is where the site-specific browser behavior lives
- this is where the first real proof of scraping success happens

For Hotels, this would become something like:

- `google_hotels.py`

This will be one of the most important files in the new project.

### `parser.py`

Purpose:

- parse Google’s internal response
- normalize raw results into your own models

Why it matters:

- this is where raw Google payloads become usable application data
- this is the main defense against upstream payload complexity

This is another critical file.

For Hotels, the parser will likely need more variation handling than Flights because hotel results often carry more optional fields.

### `storage.py`

Purpose:

- create artifact folders
- write raw request and response files
- write parsed JSON output
- hand off to database persistence

Why it matters:

- gives you reproducibility
- helps investigate parser breakage
- makes replay and regression testing easier

This file is operationally important even if it looks simple.

### `database.py`

Purpose:

- persist runs, results, and child records into SQLite
- provide reporting queries

Why it matters:

- it converts ad hoc scraping output into queryable historical data
- it makes the scraper useful beyond one-off runs

For Hotels, you may eventually outgrow SQLite faster if you track many room-level variants, but SQLite is still the right first step.

### `replay.py`

Purpose:

- decode archived real requests
- treat them as templates
- rebuild request bodies for new queries

Why it matters:

- this is the foundation for the high-speed path
- it isolates replay logic away from browser logic

This is important, but only after browser mode already works.

### `replay_client.py`

Purpose:

- bootstrap a live browser session
- reuse a real request template
- replay requests through the active session context
- fall back to browser mode when replay fails

Why it matters:

- this is where the speed win comes from
- it also protects the system by keeping a fallback path

For Hotels, this should be added only after you understand the live request shape.

### `tests/`

Purpose:

- parser regression tests
- replay template tests
- storage and database tests
- CLI/report tests

Why it matters:

- scraper code breaks silently if you do not lock in behavior with archived samples

For Hotels, build tests from captured artifacts as early as possible.

### `docs/`

Purpose:

- explain how the scraper works
- provide command references
- provide testing steps
- preserve benchmark findings and design decisions

Why it matters:

- scraper projects get brittle fast
- documented procedures save time when the site changes

## Which Files Matter Most

If you are prioritizing engineering time, these are the most important files:

1. `google_hotels.py`
2. `parser.py`
3. `models.py`
4. `replay.py`
5. `replay_client.py`
6. `storage.py`
7. `database.py`
8. `cli.py`

Why this order:

- without the live scraper file, nothing is captured
- without the parser, nothing becomes usable
- without models, the system shape drifts
- without replay, you lose the main speed optimization
- without storage and persistence, debugging and analytics are much weaker

## Development Stages Used In The Flights Project

The Flights scraper was built in roughly this progression:

1. Decide on Playwright as the primary scraper tool.
2. Validate that the site returns useful backend data.
3. Capture a real live network response.
4. Build a parser for normalized offers.
5. Archive raw and parsed results.
6. Stabilize browser submission with retries.
7. Add batch support.
8. Reverse-map the request body into a replay template.
9. Add replay execution.
10. Add replay fallback behavior.
11. Benchmark browser vs replay.
12. Persist runs into SQLite.
13. Add SQLite reporting commands.
14. Add docs for testing, commands, and architecture.

Use almost the same sequence for Hotels.

## What To Reuse For A Google Hotels Scraper

You should reuse these ideas directly:

- thin `main.py`
- package-based scraper layout
- clear `models.py`
- Playwright browser path first
- network capture archive flow
- parser driven by archived samples
- replay template layer
- replay client with fallback
- SQLite persistence
- CLI reports
- benchmark mode

You should not assume these parts can be reused unchanged:

- selectors
- request payload structure
- parser logic
- normalized fields
- replay template structure

Those will be Hotels-specific.

## Suggested Hotels Project Skeleton

Use something like this:

```text
googlehotels/
  __init__.py
  cli.py
  models.py
  google_hotels.py
  parser.py
  replay.py
  replay_client.py
  storage.py
  database.py
tests/
  test_parser.py
  test_replay.py
  test_database.py
  test_reports.py
docs/
  testing.md
  commands.md
  how-scraping-works.md
main.py
```

## Suggested First Milestones For Hotels

Use this milestone order:

### Milestone 1

- one live Google Hotels query works in Playwright
- one useful backend results response is captured

### Milestone 2

- raw artifacts are archived
- one parser extracts basic hotel offers

### Milestone 3

- one successful run is persisted into SQLite
- one report can list recent runs

### Milestone 4

- replay template generation works from archived requests
- replay mode works for repeated queries

### Milestone 5

- batch runs work
- benchmark mode compares browser vs replay

## Practical Lessons From The Flights Project

The most important practical lessons were:

- Use browser mode first, not replay first.
- Treat raw network captures as first-class artifacts.
- Keep parsing isolated from browser automation.
- Normalize into your own schema early.
- Add fallback behavior because replay is inherently more brittle.
- Benchmark real runs instead of assuming replay is faster.
- Add storage and reporting early enough that you can inspect historical behavior.

## Risks To Expect In Google Hotels

Expect the same general risks:

- changing selectors
- changing internal request formats
- nested undocumented response payloads
- intermittent live failures
- session-sensitive replay behavior

Hotels may also add complexity around:

- room variants
- promotions
- taxes and fees
- occupancy-specific pricing
- localization and currency formatting

That means the Hotels parser and data model will likely be more complex than the Flights version.

## Final Recommendation

For the new Google Hotels project, do not start by cloning the whole Flights scraper and renaming files.

Do this instead:

1. Copy the architecture.
2. Keep the module boundaries.
3. Rebuild the site-specific browser logic.
4. Rebuild the parser from real Hotels captures.
5. Add replay only after the browser path is stable.

That is the part of the Flights project that is most worth reusing.
