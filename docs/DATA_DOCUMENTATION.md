# Data Documentation

Current status reviewed November 17, 2026. April–September 2025 source files and six complete monthly zone-hour tables are validated. The April–June forecasting benchmark has been evaluated. Expanded forecasting experiments remain pending. The [snapshot inventory](../configs/data_snapshot_v1.json) identifies the 13 DVC-tracked data files.

## Timestamp decision — D05

Evidence reviewed November 4, 2026 using April. The same processing assumption applies to the validated April–September 2025 snapshots.

**Decision:** Retain the approved `America/New_York` interpretation as an explicit processing assumption. Preserve recorded clock values when assigning local dates and hours. The processing policy is settled for the MVP; the source's precise daylight-saving convention is not verified.

### Evidence and its limits

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Saved April quality report: `tpep_pickup_datetime` has Arrow type `timestamp[us]`; `source_timestamp_timezone` is null. | The inspected Parquet field has no embedded timezone identifier. | Whether the values represent UTC, fixed standard time, or daylight-adjusted local time. |
| [TLC yellow-taxi dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf), dated March 18, 2025. | Pickup time represents meter engagement; drop-off time represents meter disengagement. | The document does not explicitly specify a timezone or daylight-saving convention. |
| [Official 2025 NYC Open Data listing](https://data.cityofnewyork.us/Transportation/2025-Yellow-Taxi-Trip-Data/irx2-vgm4). | The portal lists pickup/drop-off fields as Floating Timestamp. This corroborates timezone-free publication metadata. | It does not prove byte-for-byte equivalence to the downloaded Parquet file or identify an offset. |
| [Socrata Floating Timestamp documentation](https://dev.socrata.com/docs/datatypes/floating_timestamp.html). | This datatype has no inherent timezone; publisher-local interpretation is a convention when not specified. | The general convention is not dataset-specific proof of `America/New_York` or daylight-saving handling. |
| [NYC City Record, May 17, 2018, printed page 2736, section 66-24(f)(3)](https://www.nyc.gov/assets/dcas/downloads/pdf/cityrecord/2018/cityrecord-05-17-18.pdf#page=32). | A historical TLC technical rule specifies Eastern Standard Time for collected trip times. | It does not establish how the 2025 public files were transformed or whether the wording denotes a fixed offset throughout summer. It is a reason to retain uncertainty, not silently equate standard time with daylight time. |

Evidence reviewed does not justify claiming that the source timezone has been conclusively verified. The project must not convert an assumption into a source fact.

### Processing contract

1. Keep the original Parquet data unchanged and identify the input snapshot through its manifest hash.
2. Interpret naive pickup values as NYC local wall time under D05. Do not first label them UTC and convert them to New York; that would shift recorded dates and hours without evidence.
3. For a timezone-aware derived key, attach `America/New_York` while retaining the wall-clock value. Label the interpretation as assumed in dataset documentation. Any UTC value derived from that key inherits the same assumption.
4. Define each file's month membership using its recorded local month start and next-month start under this assumption. Define hourly membership using half-open intervals `[hour, hour + 1 hour)`.
5. The approved April–September window contains no daylight-saving clock transition under `America/New_York`. Source clock semantics remain an open factual question.
6. Before including a clock-change period, specify and test ambiguous/nonexistent-hour behavior. Do not silently infer which repeated hour a timezone-free record belongs to.
7. Before joining weather/events, interpreting UTC instants, or claiming actual operational clock alignment, obtain dataset-specific clarification or run and document an appropriate sensitivity analysis. Do not treat UTC alignment as verified solely because localization succeeds.

### Remaining uncertainty and resolution condition

**Open factual question:** Do the published 2025 yellow-taxi clock values follow daylight-adjusted New York time or fixed Eastern Standard Time?

Resolution requires an explicit statement applicable to the published dataset from TLC or the relevant provider, or independent timestamp evidence tied to the same records. A successful parse, a plausible hourly pattern, and a nonzero count in every April hour are insufficient proof.

No external contact was made, no raw timestamps were modified, and no additional analysis was run for this decision. Continue the offline MVP under the already approved assumption, while keeping this limitation visible in outputs and the final case study. Revisit the decision if stronger evidence contradicts it; do not overwrite existing reports retrospectively.

## Existing April screening evidence

The preserved [quality report](../reports/data_quality/april_2025/20261104T053754311799Z/report.md) and [detailed JSON](../reports/data_quality/april_2025/20261104T053754311799Z/report.json) describe the user's completed preliminary run. The report's timestamp assumption remains accurate; this document adds source evidence and a processing contract without changing that historical artifact.

## April exclusion inspection

Reviewed November 5, 2026 against the user's [reconciled inspection report](../reports/data_quality/april_2025_exclusions/20261105T074607348105Z/report.md) and [per-zone breakdown](../reports/data_quality/april_2025_exclusions/20261105T074607348105Z/geographic_exclusions.csv).

The seven local-only date excerpts were inspected directly: four pickup timestamps fall on March 31, 2025 and three on May 1, 2025. All seven match their exclusion reason. Preserve the raw values and exclude them from the April target; their proximity to the boundary does not prove a timezone error or justify correcting them. Row-level excerpts remain under ignored `data/interim/`.

| Exclusion | Records | Interpretation |
|---|---:|---|
| Before April | 4 | Outside the half-open April pickup interval |
| On or after May 1 | 3 | Outside the half-open April pickup interval |
| ID 1: EWR / Newark Airport | 473 | Known outside-NYC location according to lookup labels |
| ID 264: Unknown / N/A | 7,356 | Unknown, unusable NYC zone assignment |
| ID 265: N/A / Outside of NYC | 1,635 | Preserve the explicit outside-NYC label; no specific NYC zone is available. The inspection groups it under unknown_or_unspecified reference geography, not under a named outside location. |

The 8,991 records in the inspection's unknown_or_unspecified group must not all be described as confirmed outside-NYC trips; preserve the individual lookup labels. No unresolved reference categories remain. This classification interprets reference metadata, not independent pickup coordinates.

The exclusive accounting is **3,970,553 = 7 + 9,464 + 3,961,082**. Retain the approved date/geographic filters without modifying raw records. The user-run inspection reproduces the screening counts; it does not prove complete vendor reporting.

## April zone-hour preparation contract

The prepared target is one row per in-scope zone and assumed-NYC-local hour, with these project-defined fields:

| Field | Definition |
|---|---|
| pickup_zone_id | Integer TLC lookup ID in one of NYC's five boroughs |
| hour_start | Timezone-aware hour start, localized under assumption D05 |
| pickup_count | Nonnegative integer number of accepted records in the half-open hourly bucket |

Retain all 262 in-scope lookup zones and all 720 April hours, including inactive zones: **188,640 expected rows** and **3,961,082 expected total pickups** for the inspected snapshot. Fill unobserved zone-hours with zero only after verifying the successful screening, reconciled exclusions, coverage checks, and exact input identities. These are observed-count zeros; source completeness and unserved demand remain unobserved.

`scripts/build_april_zone_hour.py` implements batching, explicit timestamp localization, count reconciliation, and Parquet round-trip validation. The completed [April build](../reports/data_preparation/april_2025/20261106T041153628221Z/report.json) confirms 188,640 rows and 3,961,082 accepted pickups. The six original synthetic transformation tests covered month boundaries, missing/unmapped identifiers, geographic exclusions, clock preservation, inactive zones, and invalid aggregate values. The later targeted monthly pipeline check passed 28 tests.

Prepared April Parquet snapshots are saved under `data/processed/april_2025/<run_id>/`. Git tracks the selected snapshot's adjacent DVC reference and the aggregate validation report under `reports/data_preparation/april_2025/<run_id>/`. The builder produces the hourly target table. Feature creation and split assignment occur in the subsequent forecasting pipeline.

## Monthly quality-screening extension

### Approved July–September expansion

#### Recoverable Google Drive snapshot

As of November 17, 2026, the six April–September raw Parquet files, zone lookup and six validated monthly tables are registered with DVC and synchronized to `gdrive://11Hs3fVH50aKECPCNhMVIxN4L8ZxL7tun`. The 13 data files total 421,263,309 bytes. The user reported one lookup upload, then 12 further file uploads, followed by an in-sync remote status.

The [storage record](../configs/google_drive_storage.json) identifies the DVC remote, inventory and available verification evidence. The authoritative [snapshot inventory](../configs/data_snapshot_v1.json) defines the selected file paths, sizes, SHA-256 hashes and monthly validation reports. The other inventories point to this record for current status. Adjacent `.dvc` files identify the cached contents used for each local path.

DVC initialization, Desktop OAuth configuration, authorization and pointer creation have succeeded. The lookup was pulled into a separate no-SCM project with an empty cache. Its SHA-256 matched the original. The [restoration report](../reports/data_versioning/google_drive_restore_v1.json) records this lookup-only test from user-provided terminal output. A complete 13-file DVC restoration and hash comparison remains pending.

Earlier documentation described a connector-based upload and 13-file restoration in a different Drive folder. Its per-file storage record is absent. The original claim is retained as a historical record with evidence marked `Requires validation` inside the restoration report. The current recovery evidence is the DVC lookup test.

DVC with Google Drive support is locked through the `data-versioning` extra. Use `uv sync --locked --extra modeling --extra data-versioning` for the complete current environment. Public remote configuration is in `.dvc/config`. Private OAuth configuration is in Git-ignored `.dvc/config.local`. Cloud-placeholder files previously stalled Python, uv, pytest and Git reads. Keep required project files available locally during reproduction.

On November 15, 2026 the user reported that the additional files were downloaded. All three local byte sizes match the official HTTP header checks. Their SHA-256 fingerprints and official catalog URLs are recorded in the manifest. Exact download dates and browser download origins remain unconfirmed.

| Month | Local bytes | Intended use |
|---|---:|---|
| July 2025 | 66,943,728 | Rolling model comparison |
| August 2025 | 62,293,743 | Interval calibration |
| September 2025 | 72,432,945 | Final holdout |

The monthly entry points now accept April–September. Apply the existing timestamp, geographic, coverage and reconciliation rules. September diagnostics support predefined integrity checks. Model choices and thresholds follow the approved experiment protocol. Registration establishes snapshot identity. Quality screening and exclusion reconciliation are separate steps.

#### July–September date-exception review

All 31 excerpted timestamps were independently compared with their source month boundaries. Each exclusion label matched, and direction counts matched the pinned inspection reports. Recorded and interpreted clock values matched in every excerpt. CSV byte fingerprints were retained in the [date-review record](../reports/data_quality/exclusion_date_review/20261116T045758712230Z/report.json).

| Source month | Excluded dates and counts | Before month | At or after next month |
|---|---|---:|---:|
| July 2025 | January 1, 2009 (1), June 30, 2025 (6) | 7 | 0 |
| August 2025 | January 1, 2009 (1), July 31, 2025 (15), September 1, 2025 (1) | 16 | 1 |
| September 2025 | August 31, 2025 (6), October 1, 2025 (1) | 6 | 1 |

Twenty-nine timestamps fall on a day immediately adjacent to the source month. The cause of the two January 2009 timestamps is unknown. Their values remain preserved, and the established monthly exclusions apply. This review does not establish corrected dates or cross-file duplication. Source timezone semantics remain an assumption.

#### July–September hourly preparation

Each monthly build verified the pinned screening and exclusion reports, manifest input sizes and hashes, all 262 NYC lookup zones, unique hourly keys, nonnegative integer counts, accepted-count reconciliation and the Parquet round-trip. All zone-hour combinations are retained, including zero observed-count cells.

| Month | Hours per zone | Rows | Accepted pickups | Validation report |
|---|---:|---:|---:|---|
| July 2025 | 744 | 194,928 | 3,890,093 | [Validated](../reports/data_preparation/monthly/2025-07/20261116T045854716532Z/report.json) |
| August 2025 | 744 | 194,928 | 3,565,907 | [Validated](../reports/data_preparation/monthly/2025-08/20261116T045915792847Z/report.json) |
| September 2025 | 720 | 188,640 | 4,242,242 | [Validated](../reports/data_preparation/monthly/2025-09/20261116T045946621544Z/report.json) |

Prepared files reside under ignored `data/processed/monthly/<month>/<run_id>/zone_hour_demand.parquet`. Their exact paths and SHA-256 hashes are in the validation reports. Zero observed counts describe accepted recorded pickups. Source completeness and unserved requests remain unobserved. September preparation uses the predefined integrity checks for the approved holdout.

### April–June screening history

November 7, 2026: May and June yellow-taxi source files are present and registered in the manifest with measured byte sizes, SHA-256 fingerprints, and browser-origin source URLs. Registration is not data-quality acceptance; exact download dates remain unconfirmed.

`scripts/assess_month_quality.py --month YYYY-MM` generalizes the screening step for the approved April–June scope. The April entry point retains its historical report format. The new script verifies the manifest's `study_month`, derives half-open month bounds, preserves the existing rules, and writes unique report folders under `reports/data_quality/monthly/`. Months spanning clock changes are rejected pending a separate policy.

April's optional legacy comparison checks source fingerprints, diagnostic and exclusive counts, coverage, lookup results, source schema/timezone, timestamp extrema, and screening status against the original report. The manifest-level hash may change when new source entries are appended; exact input-file identities must still match. Synthetic tests additionally compare complete hourly and daily outputs to the legacy implementation. The saved monthly reports confirm April parity and preliminary passes for May and June.

Monthly exclusion inspection uses each file’s own half-open calendar bounds and its pinned quality report. Its counts describe records in that file. A timestamp in a neighboring month does not establish that the other file contains the same trip. The May and June builds and the combined April–June zone-hour checks are complete. June 15–30 remains reserved from model-selection EDA; routine integrity and coverage checks do not authorize tuning thresholds or features against the final-test period.

### May and June date-exception review

All 44 excerpted pickup timestamps matched their exclusion labels under the D05 local-clock assumption. The direction counts also matched the saved inspection reports.

| Source file | Dates of excluded pickups (count) | Earliest recorded timestamp | Latest recorded timestamp |
|---|---|---|---|
| [May inspection](../reports/data_quality/monthly_exclusions/2025-05/20261108T040104782376Z/report.md) | Jan 1, 2009 (1), Apr 30, 2025 (20), Jun 1, 2025 (3) | 2009-01-01 00:20:39 | 2025-06-01 00:04:31 |
| [June inspection](../reports/data_quality/monthly_exclusions/2025-06/20261108T040115260148Z/report.md) | May 31, 2025 (20) | 2025-05-31 22:34:26 | 2025-05-31 23:59:57 |

Of the 44 timestamps, 43 fall on a calendar day immediately adjacent to the file month. The cause of the January 2009 timestamp in the May file is unknown. Retain the original values and exclude all 44 from their respective monthly counts. The review did not establish cross-file duplicates or a corrected pickup date.
