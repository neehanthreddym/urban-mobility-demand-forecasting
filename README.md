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
data/raw/yellow_tripdata_2025-05.parquet
data/raw/yellow_tripdata_2025-06.parquet
data/reference/taxi_zone_lookup.csv
```

The [data manifest](data/manifest.json) records source URLs, measured sizes, SHA-256 checksums, and provenance limitations. April and the lookup have user-reported November 3 download dates. May/June browser-origin URLs are verified, while their exact download dates remain unconfirmed. Raw/reference datasets and the local environment are excluded from Git; the manifest and lockfile should be versioned.

April screening, exclusion inspection, zone-hour preparation, and initial EDA are complete. May and June are downloaded; monthly quality screening is the next step.

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

The user's completed [April build](reports/data_preparation/april_2025/20261106T041153628221Z/report.json) validated 262 zones, 720 hours per zone, 188,640 unique zone-hours, and 3,961,082 total pickups. Each build creates a new ignored Parquet snapshot under `data/processed/april_2025/` and a versionable provenance/validation JSON under `reports/data_preparation/april_2025/`. Original files and historical reports are preserved.

## Monthly quality screening

The monthly checker supports the approved April–June 2025 scope. It keeps the original quality rules and derives calendar bounds and expected hours from `--month`. Field names use `month` rather than `april` (for example, `out_of_month_timestamp`). The April commands retain their historical report formats.

First run the synthetic tests and compare the new checker with the preserved April report:

```sh
uv run --locked python -m pytest -q
uv run --locked python scripts/assess_month_quality.py --month 2025-04 --compare-april-report reports/data_quality/april_2025/20261104T053754311799Z/report.json
```

Proceed only after `Legacy April comparison: PASS` and a preliminary quality pass. Then screen the new files separately:

```sh
uv run --locked python scripts/assess_month_quality.py --month 2025-05
uv run --locked python scripts/assess_month_quality.py --month 2025-06
```

Expected calendar hours are 720, 744, and 720 for April, May, and June respectively. Record counts and quality percentages must come from actual runs. Results are written to unique `reports/data_quality/monthly/YYYY-MM/<run_id>/` folders. Exit 0 means a preliminary pass, 2 requires review, and 1 means failure; do not suppress review flags or change rules to obtain a pass.

## Monthly exclusion inspection

All three monthly screens passed preliminary checks, and April matched its historical report. Reconcile May and June against the exact screening runs:

```sh
uv run --locked python scripts/inspect_month_exclusions.py --month 2025-05 --baseline-report reports/data_quality/monthly/2025-05/20261108T033428313057Z/report.json
uv run --locked python scripts/inspect_month_exclusions.py --month 2025-06 --baseline-report reports/data_quality/monthly/2025-06/20261108T033438379619Z/report.json
```

Read the date and geographic breakdowns under `reports/data_quality/monthly_exclusions/`. Individual date excerpts stay under ignored `data/interim/monthly_exclusions/`. Review unresolved lookup labels or count mismatches before building zone-hour tables.

## May zone-hour preparation

Run the builder with the exact reports used to validate May.

```sh
uv run --locked python scripts/build_april_zone_hour.py --month 2025-05 \
  --quality-report reports/data_quality/monthly/2025-05/20261108T033428313057Z/report.json \
  --exclusions-report reports/data_quality/monthly_exclusions/2025-05/20261108T040104782376Z/report.json
```

The [May validation report](reports/data_preparation/monthly/2025-05/20261108T052612838884Z/report.json) records 262 zones, 744 hours per zone, 194,928 zone-hour rows and 4,581,602 accepted pickups.

## Combine April through June

Run `uv run --locked python scripts/combine_zone_hours.py` from the project root with the three pinned monthly snapshots available locally. The [combined validation report](reports/data_preparation/april_june_2025/20261108T062052975430Z/report.json) records the input and output fingerprints and confirms 2,184 consecutive hours for each of 262 zones.

## Prepare forecast features and splits

Run `uv run --locked python scripts/prepare_forecast_features.py` from the project root. The [feature report](reports/data_preparation/forecast_features/20261108T064005732515Z/report.json) identifies the input and output snapshots and lists the predictor columns. Treat pickup zone as categorical when loading the table. Use `pickup_count` as the target and `split` to select initial fitting, validation, and final-test rows. For the June 15 refit, `refit_eligible` includes the May 31 embargo hour because its count is available by June 15. Warm-up rows supply history.

Each lag uses the same zone's observations. Each trailing mean ends two hours before the forecast origin. The one-hour delay after a bucket closes is the charter's simulated reporting delay.

## Validation baselines

Run `uv run --locked python scripts/score_validation_baselines.py` after preparing forecast features. The script reads the pinned feature snapshot, freezes the top 20 zones by initial training volume, and evaluates all three lag baselines on the same validation cells. Each run saves weekly and pooled scores, error breakdowns and provenance under `reports/baselines/` and adds an entry to `reports/experiments.csv`. The [validation metrics](reports/baselines/20261108T233614690012Z/validation_metrics.csv) select the weekly seasonal baseline as the reference for the candidate model.
