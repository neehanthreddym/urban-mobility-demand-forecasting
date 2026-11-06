# Project Charter: Urban Mobility Demand Forecasting and Capacity Planning

**Decision package D01–D20 approved by the user on November 3, 2026.**

This charter is the authoritative project reference. The user approved D01–D20 as written, including responsibilities and the effort estimate. These decisions establish the project protocol; empirical checks remain mandatory and no experimental findings are implied. Remaining uses of “proposed” describe the approved plan, not a pending user decision. As of November 5, 2026, April data screening and exclusion inspection are complete; aggregation code is prepared, and no forecasting models have been trained.

## 1. Project Overview

| Item | Definition |
|---|---|
| Project name | Urban Mobility Demand Forecasting and Capacity Planning |
| Description | Forecast hourly recorded yellow-taxi pickups by NYC TLC taxi zone and produce interpretable indicators for short-term capacity review. |
| Project type | Reproducible data-science portfolio project owned by the user, with Codex assistance |
| Lifecycle stage | CRISP-DM Data Understanding, with initial Data Preparation implementation |
| Framework | CRISP-DM |
| Status | In progress — April screening/exclusions reviewed; zone-hour aggregation script and tests prepared; full build pending |
| Proposed delivery plan | Original six-week estimate was based on two contributors. Re-estimate after the first data/pipeline milestone; no fixed solo deadline is committed |

### Approved decision register

Every row has status **Approved by user — November 3, 2026**. References to decision IDs elsewhere inherit that status. The user subsequently confirmed sole ownership; no collaborator acknowledgment is required. Empirical validation remains mandatory.

| ID | Decision | Recommendation and reason |
|---|---|---|
| D01 | Service and period | Yellow taxis, April 1–June 30, 2025. Three contiguous published months keep the first iteration bounded; this window avoids a daylight-saving clock transition and does not support annual-seasonality claims. |
| D02 | Geographic unit | Official TLC pickup taxi zone, restricted to lookup entries in NYC's five boroughs. Include all such zones, including sparse zones; exclude unknown/unmapped IDs and locations outside NYC. Freeze the lookup snapshot before preparation. |
| D03 | Target | Count accepted trip records by `PULocationID` and hourly `tpep_pickup_datetime`; one trip is one count, not passenger count. Call this recorded pickup demand, a proxy for served demand. |
| D04 | Forecast schedule | At each hourly origin `t`, predict pickups during `[t, t+1 hour)`. Assume a one-hour reporting lag after an hourly bucket closes; only buckets ending at or before `t-1 hour` are available. This is retrospective replay, not a live feed. |
| D05 | Time handling | Retain `America/New_York` as the approved, explicitly labeled processing assumption. The November 4 evidence review confirms timezone-free storage/publication metadata but does not verify source daylight-saving semantics. Preserve wall-clock values when localizing derived hour keys; do not assume UTC first. Use half-open intervals. See [timestamp evidence and processing contract](DATA_DOCUMENTATION.md#timestamp-decision--d05). |
| D06 | Evaluation | Fixed chronological training, validation, and final-test intervals with one-hour pre-fit embargoes, as specified in Section 8. No random row splitting or test-driven tuning. |
| D07 | Mandatory baselines | Last available hour, same hour previous day, and same hour previous week. Select the strongest on validation only. |
| D08 | Candidate approach | One pooled LightGBM count-regression model with a Poisson objective, zone treated categorically, and a bounded six-configuration search. It is a candidate, not a preselected winner. |
| D09 | Selection and metrics | Pooled WMAPE controls selection; report MAE and zone/time breakdowns. Require at least 5% relative validation WMAPE improvement plus the zone guardrail in Section 8 to prefer ML. Otherwise recommend the baseline. |
| D10 | Features | Known calendar attributes, zone identity, and strictly lagged own-zone counts/statistics. Defer weather, events, cross-zone demand features, and target encodings. |
| D11 | Capacity interpretation | Rank forecast demand and flag unusually high demand against a frozen historical reference. Optional explicitly hypothetical capacity scenarios may show forecast-minus-capacity; no measured shortage or underserved-zone claim. |
| D12 | Data quality | Adopt the inclusion, exclusion, missingness, duplication, and completeness rules in Section 7, with proposed review thresholds rather than invented observed quality. |
| D13 | Environment | Local CPU workflow using Python 3.12, uv and a committed lockfile; DuckDB/Parquet for preparation; pandas/NumPy, LightGBM, scikit-learn, Matplotlib, PyYAML, and pytest as needed. Verify installation compatibility during setup. |
| D14 | Resource budget | At most four CPU threads, one run at a time, 6 GiB working memory target, 5 GiB persistent project growth and 1 GiB temporary space; preserve at least 10 GiB free disk. Stop for review if these limits cannot be met. |
| D15 | Reproducibility | Immutable raw snapshots, SHA-256 manifest, configuration-driven commands, seed 42, Git revision and environment capture, per-run artifacts, and tested and reviewed critical transformations. |
| D16 | Ownership | The user owns all work and approvals; Codex assists as described in Section 11. |
| D17 | Collaboration | Repository-based records, small reviewable changes, Codex-assisted review, clean reproduction, and a weekly 30-minute progress review. |
| D18 | Delivery | Static forecast files, plots, report, and reproduction instructions complete the MVP. Defer API, dashboard, intervals, and monitoring until analytical validation. |
| D19 | Expansion gate | Expand one dimension at a time only after quality gates, critical tests, full reproduction, resource fit, documented error evidence, and user approval. |
| D20 | Timeline | Keep the milestone sequence: framing/setup; acquisition/quality; EDA/preparation; baselines/ML; evaluation; report/reproduction. Re-estimate duration after the first data/pipeline milestone because the original six-week plan assumed two contributors. |

## 2. Business Problem

Hourly geographic variation can make a single overall demand average a weak guide to where and when capacity deserves attention. The project supports a planner's short-term review of the next hour's expected recorded pickups across TLC zones.

**Assumption — Requires validation:** A plausible current approach uses recent activity, historical averages, seasonal summaries, and planner judgment. No actual operator or planning process is confirmed. Reactive planning responds after activity is observed, while broad averages can hide local peaks and quiet periods.

The forecast target is recorded trips that occurred, not all requests or unserved passengers. The selected data do not establish available vehicle-hours or unmet demand. D11 therefore defines planning priorities and optional hypothetical scenarios, rather than inferred real shortages. Lower waits, fewer shortages, and lower costs are potential benefits requiring an intervention study or equivalent operational validation.

## 3. Intended Users

These are plausible roles, not confirmed stakeholders or organizations.

| User | Decision supported | Information required |
|---|---|---|
| Transportation operations planner | Which zones merit attention in the next hour? | Zone-hour forecasts, demand ranks, historical reference flags, horizon, and limitations |
| Fleet or capacity manager | Where might an explicitly supplied capacity scenario fall below forecast activity? | Forecasts, assumed capacity in the same units, scenario gap, and clear hypothetical labeling |
| Data analyst or data scientist | Can the result be reproduced and its weaknesses explained? | Data lineage, quality rules, splits, features, configurations, metrics, and error slices |
| Portfolio or technical reviewer | Is the work rigorous and credible? | Business framing, baseline comparisons, tests, traceable results, limitations, and reproduction instructions |

## 4. Project Goals

| Category | Verifiable goal |
|---|---|
| Primary | Compare hourly zone forecasts with all D07 baselines using the same locked protocol, and apply the D09 selection rule. |
| Secondary | Produce demand ranks and historical-reference flags; identify the largest zone/time errors and report sparse-zone behavior. |
| Learning | Demonstrate chronological validation, feature-availability checks, grouped aggregation, and a baseline-to-ML comparison. |
| Portfolio | Deliver all required artifacts, documented review, and a clean reproduction of principal results from pinned inputs and configuration. |

A baseline-winning or inconclusive result can complete the project if transparently evaluated and documented. Model superiority is a separate outcome, not a condition for honest portfolio completion.

## 5. Analytical Questions

1. How accurately can next-hour recorded pickups be forecast across the defined NYC TLC zones?
2. Does the candidate improve on persistence, daily-seasonal, and weekly-seasonal baselines?
3. How much do own-zone lagged demand and known calendar information contribute, assessed through one calendar-and-zone-only ablation?
4. Which zones, hours, days of week, and validation/test periods produce the largest errors?
5. How useful and interpretable are forecast ranks, high-demand flags, and hypothetical capacity gaps?
6. **Deferred:** Would publicly available weather or event information add reproducible value? Their coverage and availability at prediction time must be validated before expansion.

## 6. Project Scope

### MVP scope

D01–D18 define the proposed MVP: one taxi type, three months, all in-scope TLC pickup zones, hourly counts, quality checks, EDA, three baselines, one ML family, chronological validation, reproducible training/evaluation, static forecast outputs, and plots.

Use calendar hour, day of week, weekend indicator, categorical pickup zone, counts at lags 2, 3, 24, 48, and 168 hours, and trailing means over 3, 24, and 168 buckets ending at lag 2. For target bucket `t`, no count newer than `y[t-2]` is permitted. No fare, tip, duration, drop-off, or other target-trip outcome is a predictor.

### Potential expansion

Additional months/years or service types, weather/events, prediction intervals, an interactive dashboard, a FastAPI service, and performance/drift monitoring remain optional. A longer-horizon forecast is also an expansion. Each requires D19 approval and an updated protocol before work begins.

### Non-goals

Real-time dispatch optimization; individual driver routing; autonomous fleet control; causal claims about wait-time reductions; production operation for a transportation organization; citywide traffic simulation; and unverified live-data integration.

## 7. Proposed Data Source

### Verified external evidence

Official TLC documentation lists monthly Parquet trip files, including yellow-taxi files for April–June 2025, and zone reference resources. It warns that data accuracy is not guaranteed and describes publication with a typical two-month delay. This supports an offline study, not an operational live feed. [TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).

The dictionary defines `tpep_pickup_datetime` as meter-engagement time and `PULocationID` as its TLC taxi zone; these support D02–D03. [Yellow Taxi Data Dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf).

### Acquisition and versioning proposal

After approval, obtain `yellow_tripdata_2025-04.parquet`, `yellow_tripdata_2025-05.parquet`, and `yellow_tripdata_2025-06.parquet` through the corresponding official TLC download links, plus the linked taxi-zone lookup CSV. No trip or lookup data have been downloaded for this decision package. Maps can use lookup labels initially; obtain the official zone geometry only if a map is needed.

Use sequential HTTPS downloads, check response status and Parquet readability, and record resolved URL, retrieval time, byte size, SHA-256, schema, source terms, and applicable reference-file hash. These immutable snapshots define the data version; the live source URL alone is insufficient.

The AWS public-data registry links the dataset's license entry to NYC terms and points users to anonymous downloads on TLC's documentation page. Record and attribute the actual source terms; do not label the data CC0 or MIT. Do not redistribute raw trip files in Git. [AWS dataset registry](https://registry.opendata.aws/nyc-tlc-trip-records-pds/), [NYC terms of use](https://www.nyc.gov/main/terms-of-use).

### Units, quality rules, and acceptance proposal

Raw unit: one published trip record. Aggregated unit: one in-scope zone and one timezone-aware hourly interval, with an integer recorded-pickup count.

| Rule | Proposed treatment |
|---|---|
| Missing/unparseable pickup timestamp | Quarantine and count; do not impute a target hour. |
| Missing/unmapped pickup identifier | Quarantine and count; resolve through the frozen lookup, not guessed geography. |
| Outside the study window | Exclude based on pickup time; report separately from in-window quality failures. |
| Outside NYC geography | Exclude as a scope rule, including unknown/non-borough entries; retain exclusion counts. |
| Sparse or zero-demand zone | Retain every in-scope lookup zone. Fill a missing zone-hour with zero only after source-file and time-coverage checks pass. |
| Missing/corrupt source file or suspicious missing time block | Fail the pipeline; preserve missingness rather than convert a suspected outage to zero. Inspect daily/hourly count continuity; unexplained citywide zero hours require review. |
| Apparent duplicate records | Flag exact full-row duplicates. Preserve them in the primary target absent evidence that they are erroneous; do not deduplicate on pickup time and zone, which can describe different trips. |
| Fare, passenger count, distance, or duration anomalies | Profile where available; do not exclude from pickup demand merely for unrelated anomalous values. Document any evidence-based rule change before modeling. |
| Quality acceptance threshold | Combined missing/unparseable pickup or missing/unmapped location must be at most 1% of file rows for automatic acceptance. More than 1% out-of-window rows also triggers review. These are proposed review gates, not observed rates. |
| Coverage acceptance | All three files load; reference joins are validated; accepted counts reconcile exactly to aggregation; final zone-hour keys are unique and complete. |

Threshold breaches require a documented correction or explicit scope/protocol amendment; do not silently replace the study period or hide exclusions. Source completeness cannot be proven solely from nonzero counts.

### Privacy and external data

Publish aggregate forecasts and summaries; do not identify passengers/drivers, infer individual movements, or claim geographic differences demonstrate discrimination or unmet need. Keep raw data local and reproducible through official acquisition instructions. Retain one raw snapshot for reproduction within D14; review retained data at final delivery. No special retention obligation is asserted without source evidence.

Weather and event datasets are deferred, not needed for the MVP. Later use requires a public source, compatible terms, geographic/time coverage, historical availability as of forecast origin, and validation improvement.

## 8. Success Criteria

All thresholds in this section were **approved by the user on November 3, 2026**; they are protocol requirements, not measured performance.

### Data success

Acquisition/loading, source hashes, quality rules/exclusions, and hourly aggregation are reproducible. D12's gates pass or an approved amendment explains the limitation. No accepted trip is lost or counted twice in aggregation.

### Modeling success and fixed protocol

Let `y[z,t]` be recorded pickups in zone `z` during `[t,t+1 hour)`. At origin `t`, the latest usable count is `y[z,t-2 hours]`; the one-hour reporting lag is a simulation assumption requiring operational validation.

All boundaries below are local `America/New_York` times and intervals are half-open.

| Role | Proposed interval and use |
|---|---|
| Raw study period | `[2025-04-01 00:00, 2025-07-01 00:00)` |
| History warm-up | First 169 hours; model targets begin `2025-04-08 01:00` so the longest shifted rolling window exists. |
| Initial fitting targets | `[2025-04-08 01:00, 2025-05-31 23:00)` |
| Validation targets | `[2025-06-01 00:00, 2025-06-14 23:00)`; report each validation week separately as well as the pooled score. |
| Availability embargoes | `[2025-05-31 23:00, 2025-06-01 00:00)` and `[2025-06-14 23:00, 2025-06-15 00:00)` are not scored or used as fitting labels at the following midnight. Counts can enter later lagged history only after their availability time. |
| Final refit | Freeze selection using validation, then refit the chosen ML configuration on eligible targets before `2025-06-14 23:00`, including validation targets. Refit occurs at simulated `2025-06-15 00:00`. |
| Final test | `[2025-06-15 00:00, 2025-07-01 00:00)`; score once after freezing code, features, metrics, configuration, and selection rule. No test tuning or retraining during this interval. |

Replay forecast origins chronologically. Earlier validation/test observations can update lagged history when they become available, as in the stated forecast schedule; they cannot update fitted model parameters or feature-selection decisions during a scored interval. Unknown actual source reporting latency remains a limitation of this offline replay.

**Baselines:** persistence `y[z,t-2]`, daily seasonal `y[z,t-24]`, and weekly seasonal `y[z,t-168]`. Use the same target cells and availability rules for every method; do not drop difficult cells for one method.

**ML candidate:** one global LightGBM Poisson model, categorical zone, learning rate 0.05, at most 500 boosting rounds, 50-round early stopping on validation MAE, and six combinations of `num_leaves ∈ {15,31}` and `min_child_samples ∈ {20,50,100}`. Record all parameters and selected iteration count before refit. Run one additional calendar-and-zone-only ablation using the selected configuration, for diagnostic interpretation only; it cannot become a new contender after test inspection.

LightGBM documents the Poisson objective, categorical support, and CPU determinism settings. Use seed 42, four threads, `deterministic=true`, and `force_col_wise=true`; pin versions and record platform because cross-platform bitwise equality is not guaranteed. [Parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html), [categorical features](https://lightgbm.readthedocs.io/en/stable/Advanced-Topics.html#categorical-feature-support).

**Metrics and selection:**

- Primary: pooled `WMAPE = 100 × sum(abs(y - forecast)) / sum(y)` over the full fixed set of zone-hours. Secondary: MAE in trips per zone-hour. On identical cells these metrics give the same ordering; WMAPE is chosen for its relative scale.
- Keep predictions nonnegative and unrounded for scoring. Report rounding only in any presentation/scenario layer.
- A zero-target cell contributes its absolute error to the numerator. A zone/period with zero total actual pickups receives WMAPE `N/A`, with its MAE, forecast total, and actual total still reported. If the entire scored set totals zero, stop evaluation as unsuitable.
- Report per-zone MAE/WMAPE, median zone WMAPE over positive-volume zones, zone volume and zero-demand frequency, hour/day-of-week errors, daily errors, and the 20 zones with highest initial-training volume. Break volume ties by zone ID and freeze this list before validation.
- Select the lowest-validation-WMAPE baseline; ties favor weekly seasonal, then daily seasonal, then persistence.
- Prefer the lowest-validation-WMAPE ML configuration only if its relative WMAPE gain over that baseline is at least 5% and no frozen top-20 zone has more than 10% MAE degradation relative to that baseline. For a zone where baseline MAE is zero, candidate MAE must also be zero. If the baseline's pooled WMAPE is zero, retain it.
- If ML configurations tie to six decimal places in validation WMAPE, prefer fewer leaves, then larger minimum leaf size, then fewer iterations.
- Final testing assesses the frozen selection and all required comparators. If the selected ML fails the same improvement/zone guardrails on test, report that it did not generalize; retain the validation-selected baseline as the predeclared recommendation. Do not search for a different winner on test.
- Treat 5% and 10% as practical proposal thresholds, not business-derived values or guarantees. Honest negative results still satisfy analytical completion.
- RMSE and interval coverage are deferred; intervals are outside the MVP. No identified leakage is permitted.

### Operational success

Produce zone/hour forecasts, demand rankings, and a high-demand indicator defined as forecast exceeding the zone's initial-training 90th-percentile observed hourly count. Freeze the reference before validation; this is an unusual-activity flag, not a calibrated shortage probability.

If a capacity scenario is included, express capacity as hypothetical pickups supportable per zone-hour and show `max(0, forecast - scenario capacity)`. Scenarios are user-supplied or explicitly illustrative, not estimated available taxis. Do not convert pickups to vehicle counts without a separately validated utilization/service-time model.

### Engineering success

A pinned environment, documented pipeline, configuration-driven experiments, and automated tests cover timestamp boundaries, zone joins, count reconciliation, zero-versus-missing handling, lag availability, split isolation, and metric edge cases. The user can reproduce the principal result from one documented command sequence and stored configuration.

## 9. Deliverables

Required: charter; source manifest, data documentation and dictionary; ingestion/preparation pipeline; EDA; three baselines; candidate model and ablation; evaluation/error analysis; experiment log; forecast tables/plots; final report or case study; tests; and reproduction instructions.

Proposed forecast columns are project output fields, not asserted source columns: forecast origin, target-hour start, zone ID, predicted pickups, model/experiment ID, historical-reference flag, and optional hypothetical scenario gap.

The README will become the project entry point during implementation. API/dashboard, prediction intervals, and monitoring are post-validation options, not completion requirements.

## 10. CRISP-DM Phases

| Phase | Objective | Principal activities | Required output | Completion evidence | Current status |
|---|---|---|---|---|---|
| Business Understanding | Agree on decision and target | Review D01–D20, assumptions, roles, and success criteria | Approved charter | User approval and sole ownership recorded | Completed |
| Data Understanding | Verify source suitability | Acquire approved snapshots, inspect schema/coverage, validate quality, perform EDA | Manifest, dictionary, quality report, EDA | April screening/exclusions reviewed; EDA and later months remain | In progress |
| Data Preparation | Build the modeling table | Apply approved rules, aggregate, create lag features, enforce splits | Reproducible zone-hour dataset | April aggregation code prepared; full build, features, and splits pending | In progress |
| Modeling | Compare simple and ML forecasts | Run baselines, bounded tuning, ablation, and final refit | Traceable configurations and forecast artifacts | Runs reproduce and selection follows the fixed rule | Not started |
| Evaluation | Assess generalization and limits | Score frozen test, analyze zone/time errors, review planning interpretation | Evaluation report and recommendation | Test scored only after protocol freeze; limitations explicit | Not started |
| Deployment | Deliver portfolio demonstration | Package static outputs, case study, and reproduction commands | Reviewable reproducible project | Principal results reproduced from a clean environment | Not started |

## 11. Collaboration and Responsibilities

The user is the sole project owner and decision-maker. Codex assists with implementation, analysis, documentation, and review. No second collaborator acknowledgment is required.

| Work area | Accountable owner | Assistance and verification |
|---|---|---|
| Business framing and scope | User | Codex drafts recommendations; user approves material changes |
| Acquisition and data validation | User | Codex builds the reproducible workflow and reports quality checks |
| EDA and feature engineering | User | Codex assists with analysis and leakage checks |
| Baselines and candidate modeling | User | Codex runs the approved protocol and records experiments when authorized |
| Evaluation and testing | User | Codex assists with tests, error analysis, and a separate review pass |
| Documentation and demonstration | User | Codex prepares artifacts and verifies reproduction instructions |

Track tasks in `docs/TASKS.md`, decisions in `docs/DECISIONS.md`, and experiments in `reports/experiments.csv` during implementation. These remain planned artifacts. Each experiment records its ID, source hashes, Git revision, configuration, split boundaries, seeds, metrics, runtime, and artifact path.

Use small, reviewable Git changes. Check analytical assumptions and code, run critical tests, and reproduce principal results from a clean environment. A Codex review is assistance, not independent human peer review. Use a weekly 30-minute progress review to adjust workload and record decisions.

Keep large data and environments outside Git; preserve official input snapshots and hashes. Reproduction records include commands, configuration, manifest, revision, run ID, limitations, and the next task. A changed remote source requires an explicitly recorded new data version.

The user approves material changes to targets, sources, quality rules, splits, metrics, resource budgets, external data, expansion, final model recommendations, and public claims. Record methodological concerns with evidence and options; retain the approved protocol until the user approves a change.

## 12. Constraints

- Public data only; no private operator data or assumed live API.
- Local CPU execution and D14 resource limits; no paid infrastructure, GPU, or distributed framework in the MVP.
- Observed host resources on November 3, 2026: 18 GiB RAM, 11 logical CPUs, and approximately 17 GiB available disk. These are a point-in-time observation, not a reservation..
- D14's 5 GiB persistent budget includes environment, source snapshots, prepared data, and retained outputs. Check expected download size where available and recheck free space before each file; stop before violating the budget or 10 GiB free-space floor. Process one month at a time and avoid full raw CSV copies.
- Use the inspected machine as the reference execution host. A smaller machine may use a matched configuration within its own limits; resource changes require documentation, not fabricated compatibility claims.
- Reproducibility requires pinned dependencies, immutable input hashes, stored configurations, and traceable results.
- Generalization is to future hours in known zones. Unseen-zone evaluation is outside the MVP. Prohibit future cross-zone targets and globally fitted target encodings; repeated zones across chronological splits are intentional.
- Six working weeks is a proposed effort plan. The original estimate needs reassessment for solo ownership; no fixed calendar deadline is confirmed.
- Keep the first iteration bounded; stop and review quality or feasibility failures before silently broadening scope.

## 13. Assumptions and Validation Obligations

These are empirical limitations; approval cannot turn them into established facts.

| Assumption / unknown | Validation obligation and owner |
|---|---|
| Published source files match the dictionary and planned fields. | User (with Codex assistance) validates schema, types, source revision, and hashes after approved acquisition. |
| Source timestamps can be interpreted as NYC local time. | Evidence reviewed November 4, 2026; D05 remains the approved processing assumption, not a verified source-timezone claim. See [data documentation](DATA_DOCUMENTATION.md). Dataset-specific daylight-saving clarification is still needed before verified external/UTC alignment. |
| A zone-hour with no accepted records represents zero activity rather than incomplete reporting. | User (with Codex assistance) checks file integrity and continuity; unresolved outages remain missing and trigger review. |
| Three months provide useful daily/weekly forecasting evidence. | User (with Codex assistance) evaluates validation stability; no claim about annual seasonality or later regimes. |
| The one-hour lag represents a useful planning scenario. | User (with Codex assistance) states it as hypothetical; actual pickup reporting delay and operational feasibility remain unverified. |
| Recorded pickups are an adequate proxy for the planning illustration. | The user acknowledges that unserved requests, real capacity, and intervention impact are unobserved. |
| Historical calendar/lag features have predictive value. | User (with Codex assistance) tests against baselines and the planned ablation; negative results are acceptable. |
| Source completeness, duplicates, and anomalies are manageable under D12. | User (with Codex assistance) measures and reports them; do not claim verified completeness or unique physical trips. |
| The scoped workflow fits D14. | User (with Codex assistance) checks file sizes, pipeline memory, runtime, and disk growth before expansion. |
| The original schedule fits solo ownership. | User and Codex reassess after the first data/pipeline milestone; the prior two-person effort estimate is not a solo commitment. |
| Thresholds and historical flags are operationally meaningful. | Treat them as portfolio conventions until an operator validates them; do not claim business-derived thresholds. |
| Weather/events or additional complexity could help. | Deferred hypothesis, not an MVP dependency or established benefit. |

Unknown data counts, file sizes, hashes, measured quality rates, model scores, training times, exact installable package versions, and actual operator impact will be measured at the appropriate phase. They are not decisions to fabricate in Business Understanding.

## 14. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Large volume and limited free disk | D14 budgets, sequential Parquet processing, column selection, one raw snapshot, and a pre-download capacity check |
| Invalid/missing timestamps or locations | D12 quarantine, measured exclusions, explicit timezone handling, and reconciliation tests |
| Distribution shifts | Separate validation weeks and final period; document the short window; require longer-period evaluation before broader claims |
| Target leakage | D04 availability rule, shifted features, embargoed fitting labels, and automated checks |
| Random splitting | D06 fixed chronological boundaries; disallow random reported forecasting splits |
| Sparse zones | Retain zeros where justified, report volume and MAE, mark zero-denominator WMAPE unavailable, and expose zone-level weaknesses |
| Unavailable external features | Defer weather/events and complete the MVP with approved TLC-derived/calendar features |
| Excessive complexity or tuning | One ML family, six configurations, one diagnostic ablation, resource caps, and a baseline-first selection rule |
| Scope expansion | D19 evidence gate and joint agreement before adding a dimension |
| Solo workload exceeds available time | Keep the MVP bounded, review progress weekly, and re-estimate after the first pipeline milestone |
| Accuracy confused with impact | Forecast recorded activity; label capacity scenarios hypothetical; prohibit unvalidated service/cost claims |
| Reporting latency differs from simulation | Explicit offline-replay assumption; require a real timely feed and a new evaluation before live use |
| Failed or negative ML result | Publish the comparison and limitations; recommend the baseline rather than chase a favorable test result |

## 15. Decision Approval and Remaining Checks

All previously open design questions now have a proposed resolution, an accountable role, and an approval status.

| Previously open question | Proposed resolution | Status | Accountable owner after approval |
|---|---|---|---|
| Taxi type and months | D01: yellow, April–June 2025 | Approved by user | User (with Codex assistance) |
| Geography and timestamp | D02–D03: NYC TLC pickup zones, pickup meter-engagement time | Approved by user | User (with Codex assistance) |
| Horizon, origin, latency | D04–D05: next hour, hourly origins, one-hour reporting lag, NYC local time subject to source validation | Approved by user | User (with Codex assistance) |
| Baselines and candidate | D07–D08: persistence/daily/weekly and pooled LightGBM Poisson | Approved by user | User (with Codex assistance) |
| Splits, metrics, zero handling | D06/D09 and Section 8 | Approved by user | User (with Codex assistance) |
| External data | D10: defer weather/events | Approved by user | User (with Codex assistance) |
| Capacity measure | D11: demand ranks/reference flags; optional hypothetical pickups-per-hour scenario | Approved by user | User (with Codex assistance) |
| Quality thresholds and exclusions | D12 and Section 7 | Approved by user | User (with Codex assistance) |
| Environment and compute/storage | D13–D15 and Section 12 | Approved by user | User (with Codex assistance) |
| Responsibilities and handoff | D16–D17 and Section 11 | Approved by user; sole ownership confirmed | User |
| Delivery and expansion | D18–D19 | Approved by user | User |
| Timeline | D20: milestone sequence retained; duration re-estimated after the first data/pipeline milestone | Updated for confirmed solo ownership | User |

**Approval record:** The user approved D01–D20 as written on November 3, 2026, replying “Yes I approve” to the full decision package, including proposed responsibilities and effort estimate. The user subsequently clarified that they are the sole collaborator; this clarification supersedes the two-person assignments and removes the acknowledgment requirement. The original timeline is an estimate requiring reassessment for solo execution. April acquisition, preliminary quality screening, and exclusion inspection are complete; the aggregation script is prepared and six synthetic tests pass. The full zone-hour build remains pending. Source-timezone semantics, later-month quality, resource use, and model performance remain validation obligations.

## 16. Definition of Done

The MVP is complete only when:

- The approved business question, target, geography, timestamp semantics, horizon, and reporting-lag assumption are explicit.
- Source files, dictionary, lookup snapshot, retrieval details, hashes, and applicable terms are documented.
- Raw-to-model transformations and exclusions are reproducible and counts reconcile.
- Chronological splits, embargoes, features, metric rules, and selection thresholds are frozen before final test evaluation.
- Baselines and candidates use the same target cells, availability assumptions, and protocol.
- Every principal result links to data hashes, configuration, scripts/Git revision, environment, and experiment ID.
- The bounded comparison, zone/time error analysis, and limitations are documented, including a negative result if applicable.
- Critical tests pass and a clean reproduction verifies exact row counts, split membership, and source hashes; on the same locked environment, predictions and aggregate metrics match within absolute tolerance 0.000001. Cross-platform deviations are reported and investigated rather than silently treated as identical.
- Forecast tables, static plots, case study, and complete reproduction instructions are available.
- No unverified business-impact, real-shortage, live-readiness, or causal claim is presented as a result.

## 17. Immediate Next Step

**Recommended action:** Run the synthetic transformation tests and April zone-hour build, then review the validation report before expanding data acquisition.
