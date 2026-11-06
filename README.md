![Minimal illustration of NYC taxis moving through an urban street grid](public/assets/images/urban-mobility-banner.png)

# Urban Mobility Demand Forecasting and Capacity Planning

Forecast hourly recorded NYC taxi pickups by TLC zone using the CRISP-DM framework. See the [project charter](docs/PROJECT_CHARTER.md) for the approved scope and evaluation protocol.

## Environment setup

Use uv from the project root. Python 3.12.13 is pinned in `.python-version`; `uv.lock` records exact dependency versions.

```sh
uv sync --locked
uv run --locked python --version
```

The default environment includes data-inspection and plotting tools plus pytest. Modeling dependencies are optional; install them when the modeling phase begins with `uv sync --locked --extra modeling`. No forecasting package or command-line pipeline has been implemented yet.

## Local data

Keep the original files at these paths:

```text
data/raw/yellow_tripdata_2025-04.parquet
data/reference/taxi_zone_lookup.csv
```

The [data manifest](data/manifest.json) records expected official URLs, measured byte sizes, SHA-256 checksums, and provenance limitations. The user reported November 3, 2026 as the download date for both files. Raw/reference datasets and the local environment are excluded from Git; the manifest and lockfile should be versioned.

April screening and exclusion inspection are complete. Next: build and validate April's zone-hour counts before acquiring more months.

## April data-quality screening

From the project root:

```sh
uv sync --locked
uv run --locked python scripts/assess_april_quality.py
```

The script verifies both inputs against the manifest, checks the lookup and required types, and scans pickup timestamps/zones in batches. Original data are unchanged. Each run creates a unique folder under `reports/data_quality/april_2025/` containing `report.md`, `report.json`, `hourly_counts.csv`, and `daily_counts.csv`.

Exit code 0 means `PASS_PRELIMINARY`; 2 means `REVIEW_REQUIRED`; 1 means the run failed or an input was invalid. Review is triggered by more than 1% combined key-quality failures, more than 1% out-of-April timestamps, zero-observed April hours, or unusually low hourly counts. The low-count flag (less than 10% of the monthly median for that clock hour) is a diagnostic heuristic, not an approved acceptance threshold or a confirmed outage.

Diagnostic counts can overlap; exclusive row dispositions and count reconciliation are recorded separately. Mapped non-NYC locations are scope exclusions. Zero-observed hours are not automatically imputed into model targets. Naive timestamps are screened under the NYC-local-time assumption, whose source semantics still require validation. Full-row duplicates and fare/distance/duration anomalies are outside this initial script.

The user's completed April run returned `PASS_PRELIMINARY`; see the [saved quality report](reports/data_quality/april_2025/20261104T053754311799Z/report.md). This does not establish source completeness or timezone semantics.

The [timestamp evidence and processing contract](docs/DATA_DOCUMENTATION.md#timestamp-decision--d05) retains the approved `America/New_York` assumption while preserving recorded clock values. Source daylight-saving semantics remain unverified; no raw timestamps were changed.

## April zone-hour preparation

The [exclusion inspection](reports/data_quality/april_2025_exclusions/20261105T074607348105Z/report.md) reconciles seven out-of-April records, 9,464 geographic exclusions, and 3,961,082 accepted pickups. The seven local date excerpts were reviewed; exclusion rules remain unchanged. See the [data documentation](docs/DATA_DOCUMENTATION.md) for exact reference labels and limitations.

Run synthetic transformation tests, then the data build:

```sh
uv run --locked python -m pytest -q
uv run --locked python scripts/build_april_zone_hour.py
```

Expected checks for the inspected snapshot: 262 zones, 720 hours per zone, 188,640 unique zone-hours, and 3,961,082 total pickups. These expectations are not a claim that the full build has already run. Each build creates a new ignored Parquet snapshot under `data/processed/april_2025/` and a versionable provenance/validation JSON under `reports/data_preparation/april_2025/`. Original files and historical reports are preserved.
