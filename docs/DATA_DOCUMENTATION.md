# Data Documentation

## Timestamp decision — D05

Reviewed November 4, 2026. Applies to the approved April–June 2025 yellow-taxi MVP; only April has been inspected locally.

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
4. Define April membership using the recorded local interval `[2025-04-01 00:00, 2025-05-01 00:00)` under this assumption, and hourly membership using half-open intervals `[hour, hour + 1 hour)`.
5. The approved April–June window contains no daylight-saving clock transition under `America/New_York`. This avoids repeated/nonexistent local hours within the MVP; it does not prove which clock convention the source used.
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

`scripts/build_april_zone_hour.py` implements batching, explicit timestamp localization, count reconciliation, and Parquet round-trip validation. Six synthetic tests pass, covering month boundaries, missing/unmapped identifiers, geographic exclusions, clock preservation, inactive zones, and invalid aggregate values. The full data build has not been executed by Codex; its expected dimensions and totals above are acceptance checks, not newly generated results.

Prepared Parquet snapshots will be saved under ignored `data/processed/april_2025/<run_id>/`; aggregate validation/provenance reports will be saved under versionable `reports/data_preparation/april_2025/<run_id>/`. No forecast features or train/test splits are created in this step.
