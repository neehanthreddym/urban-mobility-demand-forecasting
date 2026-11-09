# 2025-05 Exclusion Inspection

Status: **RECONCILED**

Input identities, diagnostic counts, and exclusive dispositions match the original report.

## Date exclusions

- before_month: 21
- on_or_after_next_month: 3

## Geographic classifications

- known_outside_nyc: 532
- unknown_or_unspecified: 9,687
- unresolved_reference: 0

See geographic_exclusions.csv for per-ID labels and counts.
Unknown geography is not evidence that a pickup happened outside NYC.

## Exclusive row dispositions

- bad_timestamp: 0
- bad_zone_after_timestamp_check: 0
- out_of_month_after_key_checks: 24
- mapped_non_nyc_in_month: 10,219
- accepted: 4,581,602

## Treatment

Retain exclusion rules for the monthly NYC target; preserve original files and historical screening report

If unresolved_reference is nonzero, inspect those labels before finalizing the classification.

Row-level date excerpts are saved separately under ignored data/interim/.
Do not publish those excerpts as part of the aggregate report.

## Limitations

- Geographic classification interprets lookup labels, not independently verified trip coordinates.
- Unknown/unspecified categories do not establish that pickups occurred outside NYC.
- Date and geography are disjoint in the exclusive dispositions; diagnostic key failures can overlap.
- Derived source_row_number is physical scan position, not an official unique trip identifier.
- No date correction, timezone shift, deduplication, or modeling table is performed.
- RECONCILED establishes accounting/classification only, not overall source completeness.
