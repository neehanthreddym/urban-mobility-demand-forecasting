# April 2025 Preliminary Data-Quality Report

Status: **PASS_PRELIMINARY**

Run (UTC): 2026-11-04T05:37:54.309488+00:00

## Counts

| Check | Rows |
|---|---:|
| total_rows | 3,970,553 |
| missing_pickup_timestamp | 0 |
| unparseable_pickup_timestamp | 0 |
| missing_pickup_zone | 0 |
| unmapped_pickup_zone | 0 |
| combined_key_quality_failures | 0 |
| out_of_april_timestamp | 7 |
| in_april_mapped_non_nyc_scope_exclusions | 9,464 |
| accepted_for_april_nyc_screening | 3,961,082 |

Diagnostic counts can overlap. Exclusive dispositions are in report.json.

## Thresholds

- combined_key_quality_failures: 0.000000% (review when greater than 1%).
- out_of_april_timestamp: 0.000176% (review when greater than 1%).

## Review reasons

No automatic review flags. This is not proof of source completeness.

## Limitations

- Nonzero counts cannot prove complete vendor submissions or absence of outages.
- Hourly zero values describe observed accepted records, not imputed model targets.
- Low-count flags use full-month data for quality diagnostics only; not forecasting features.
- No raw rows are removed, corrected, deduplicated, or saved by this script.
- Full-row duplicates and unrelated fare/distance/duration anomalies are not assessed.
- No zone-hour modeling table is produced; this is not final three-month data acceptance.
- Naive timestamp timezone semantics still require source evidence before modeling.

See hourly_counts.csv for every April hour and its review flags;
daily_counts.csv for day totals; report.json for schema, provenance, and exact counts.
