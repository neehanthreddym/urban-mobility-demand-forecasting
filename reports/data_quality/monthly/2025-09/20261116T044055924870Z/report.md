# 2025-09 Preliminary Data-Quality Report

Status: **PASS_PRELIMINARY**

Run (UTC): 2026-11-16T04:40:55.922246+00:00

## Counts

| Check | Rows |
|---|---:|
| total_rows | 4,251,015 |
| missing_pickup_timestamp | 0 |
| unparseable_pickup_timestamp | 0 |
| missing_pickup_zone | 0 |
| unmapped_pickup_zone | 0 |
| combined_key_quality_failures | 0 |
| out_of_month_timestamp | 7 |
| in_month_mapped_non_nyc_scope_exclusions | 8,766 |
| accepted_for_month_nyc_screening | 4,242,242 |

Diagnostic counts can overlap; exclusive dispositions are in report.json.

## Review thresholds

- combined_key_quality_failures: 0.000000% (review if greater than 1%).
- out_of_month_timestamp: 0.000165% (review if greater than 1%).

## Coverage

- Expected hours: 720
- Zero-observed hours: 0
- Unusually-low hours: 0

## Review reasons

No automatic review flags; source completeness is not proven.

## Limitations

- Nonzero counts cannot prove complete vendor submissions or absence of outages.
- Hourly zero values describe observed accepted records, not imputed model targets.
- Low-count flags use full-month data for quality diagnostics only; not forecasting features.
- No raw rows are removed, corrected, deduplicated, or saved by this script.
- Full-row duplicates and unrelated fare/distance/duration anomalies are not assessed.
- No zone-hour modeling table is produced; this is not final three-month data acceptance.
- Naive timestamp timezone semantics still require source evidence before modeling.

Coverage flags are quality diagnostics, not causal findings or modeling features.
For a designated final holdout, use these diagnostics only for predefined integrity checks.
Do not silently amend exclusion rules in response to these diagnostics.
