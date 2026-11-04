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

Next: validate April's timestamps, pickup-zone coverage, missingness, and hourly continuity before acquiring more months.

## April data-quality screening

From the project root:

```sh
uv sync --locked
uv run --locked python scripts/assess_april_quality.py
```

The script verifies both inputs against the manifest, checks the lookup and required types, and scans pickup timestamps/zones in batches. Original data are unchanged. Each run creates a unique folder under `reports/data_quality/april_2025/` containing `report.md`, `report.json`, `hourly_counts.csv`, and `daily_counts.csv`.

Exit code 0 means `PASS_PRELIMINARY`; 2 means `REVIEW_REQUIRED`; 1 means the run failed or an input was invalid. Review is triggered by more than 1% combined key-quality failures, more than 1% out-of-April timestamps, zero-observed April hours, or unusually low hourly counts. The low-count flag (less than 10% of the monthly median for that clock hour) is a diagnostic heuristic, not an approved acceptance threshold or a confirmed outage.

Diagnostic counts can overlap; exclusive row dispositions and count reconciliation are recorded separately. Mapped non-NYC locations are scope exclusions. Zero-observed hours are not automatically imputed into model targets. Naive timestamps are screened under the NYC-local-time assumption, whose source semantics still require validation. Full-row duplicates and fare/distance/duration anomalies are outside this initial script.

The script was created without execution at the user's request; no quality results are yet available.
