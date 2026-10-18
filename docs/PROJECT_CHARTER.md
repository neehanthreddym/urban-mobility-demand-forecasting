# Project Charter: Urban Mobility Demand Forecasting and Capacity Planning

## 1. Project Overview

| Item | Definition |
|---|---|
| Project name | Urban Mobility Demand Forecasting and Capacity Planning |
| One-sentence description | Build a small, reproducible system for forecasting hourly taxi demand by a confirmed geographic service unit and translating forecasts into interpretable capacity-planning indicators. |
| Project type | Data-science portfolio project; spatiotemporal demand forecasting and capacity-planning analysis |
| Current lifecycle stage | CRISP-DM Business Understanding |
| Framework | CRISP-DM |
| Current project status | In progress — charter initialization; target, data subset, evaluation protocol, and collaborator assignments remain unresolved |

This charter is the authoritative source for the project's purpose, scope, expected deliverables, responsibilities, constraints, and definition of success. Items labeled **Proposed**, **Assumption**, **Requires validation**, or **TBD** are not confirmed facts.

## 2. Business Problem

Taxi demand varies across hours and geographic areas. A capacity decision made from an overall average can therefore overlook localized peaks, quiet periods, and changes in the timing or location of demand. The project will estimate demand for each zone-hour at a forecast horizon that is **TBD** so a planner can compare expected demand across locations and time periods and identify where available vehicle capacity may warrant attention.

The supported decision is how to prioritize or plan vehicle capacity across geographic units and hourly intervals. The project will not optimize dispatch or prescribe individual vehicle movements. The precise capacity measure, decision horizon, and action threshold are **TBD** and require operational framing before the forecast can be interpreted as a demand–capacity imbalance.

**Assumption — Requires validation:** In the absence of a forecasting system, plausible planning practices include recent observations, historical averages, seasonal summaries, and planner judgment. These practices have not been verified for a particular operator. Reactive planning responds after demand is observed, while simple historical averages may mask hour-specific, day-specific, seasonal, and geographic variation. Forecasts could potentially support earlier or more targeted planning, but any effect on wait times, shortages, service levels, or operating costs would require operational validation or an intervention study.

## 3. Intended Users

These are plausible user roles, not confirmed stakeholders or organizations.

| Plausible user | Decision supported | Information required |
|---|---|---|
| Transportation operations planner | Prioritize time periods and geographic units for capacity review | Hourly forecasts, forecast horizon, expected peaks, uncertainty where available, and clear geographic definitions |
| Fleet or capacity manager | Compare forecast demand with a defined capacity measure and identify possible imbalances | Zone-hour forecasts, capacity assumptions, interpretable flags or rankings, and limitations |
| Data analyst or data scientist | Reproduce, diagnose, compare, and extend the analysis | Data lineage, quality rules, feature definitions, validation splits, metrics, configurations, seeds, experiment records, and error breakdowns |
| Portfolio or technical reviewer | Assess the quality, rigor, and reproducibility of the work | Business framing, scoped decisions, repository structure, methods, baseline comparisons, tests, results, limitations, and reproduction instructions |

## 4. Project Goals

### Primary goal

Produce reproducible hourly demand forecasts at a confirmed geographic level and present zone- and time-level evidence showing whether candidate methods improve on required naïve or seasonal baselines under a fixed, leakage-aware, time-based evaluation protocol.

### Secondary goals

- Define interpretable forecast outputs that rank or flag likely high-demand periods, potentially underserved geographic units, or capacity-planning priorities without claiming realized operational impact.
- Document where and when forecast errors are largest, including sparse-demand areas and relevant temporal segments.
- Establish a small pipeline that can be expanded only when evidence justifies additional data, features, or modeling complexity.

### Learning goals

- Demonstrate correct temporal validation, leakage prevention, and baseline design for grouped hourly forecasting.
- Evaluate the incremental value of temporal and geographic features; evaluate weather or event features only if their availability and usefulness are validated.
- Record enough evidence to explain model behavior, failure modes, and tradeoffs to another practitioner.

### Portfolio goals

- Deliver a reviewable case study spanning all six CRISP-DM phases.
- Make the principal result reproducible from documented data versions, configuration, scripts, experiment ID, and environment instructions.
- Provide verifiable evidence of data validation, testing, baseline comparison, error analysis, and honest limitations.

## 5. Analytical Questions

1. How accurately can hourly taxi demand be forecast at the selected geographic level and forecast horizon?
2. How does each candidate model compare with simple historical and seasonal baselines under the same time-based evaluation protocol?
3. Which temporal and geographic features improve forecasts out of sample?
4. **Optional — Requires validation:** Are weather or event-related features available, usable, leakage-safe, and incrementally useful?
5. Which geographic units and periods produce the largest absolute and scale-aware forecast errors?
6. How stable is performance across relevant hours, days, and validation periods?
7. How can forecasts be converted into interpretable capacity-planning indicators without implying that forecast accuracy alone produces operational improvement?

## 6. Project Scope

### MVP scope

The MVP will include:

- One NYC taxi service type; the type is **TBD — Requires confirmation**.
- A **Proposed** three-to-six-month study period; exact months are **TBD — Requires confirmation**.
- Hourly demand aggregation.
- One clearly defined geographic unit; its definition is **TBD — Requires confirmation**.
- A documented rule for assigning a trip to an hourly interval; the timestamp definition is **TBD — Requires confirmation**.
- Data validation and exploratory analysis.
- At least one naïve or seasonal baseline; mandatory baselines are **TBD**.
- At least one machine-learning forecasting approach; the approach and final model are **TBD** and will be selected only after evidence is available.
- Leakage-aware, time-based training, validation, and test logic.
- Reproducible training and evaluation using stored configurations and random seeds where applicable.
- Basic forecast outputs and visualizations suitable for error analysis and capacity-planning interpretation.

### Potential expansion

The following are future options, not MVP requirements:

- Additional months or years.
- Multiple taxi service types.
- Weather and event features.
- Prediction intervals.
- An interactive dashboard.
- A FastAPI forecast service.
- Performance and drift monitoring.

Expansion requires evidence from the MVP, a documented rationale, and agreement from both collaborators.

### Non-goals for the MVP

- Real-time dispatch optimization.
- Individual driver routing.
- Autonomous fleet control.
- Causal claims about reduced wait times.
- Production use by an actual transportation operator.
- Citywide traffic simulation.
- Unverified live-data integration.

## 7. Proposed Data Source

The **Proposed** primary source is official New York City Taxi and Limousine Commission (NYC TLC) trip-record data.

Before acquisition, the following must be verified against official source information: the first taxi service type; exact files and dates; file format and schema; geographic identifiers and their reference data; timestamp meanings; data licensing or terms of use; and the supported download method. Exact columns, record counts, and file sizes are intentionally not stated because they have not been verified.

| Data level | Proposed unit of observation | Status |
|---|---|---|
| Raw | One trip record | **Assumption — Requires validation** against the selected files and schema |
| Aggregated | One selected-geographic-unit and hourly-interval combination with a demand count | **Proposed**; geographic unit and timestamp rule are **TBD** |

Potential data-quality problems include missing, invalid, or out-of-range timestamps; missing, unknown, or invalid geographic identifiers; duplicate records; inconsistent schemas across files; implausible trip values; partial coverage periods; daylight-saving or timezone handling errors; and sparse or zero-demand geographic units. The applicable checks and exclusion rules must be documented after the source files and schema are verified.

Possible external datasets include weather and event information. Both are **Optional — Requires validation** for public availability, temporal and geographic coverage, lawful use, join quality, availability at prediction time, and measurable incremental value. They are not MVP requirements.

Although the proposed source is public, the project will use only data permitted by the verified source terms. Outputs should remain aggregated for the forecasting task, avoid attempts to identify drivers or passengers, and avoid presenting low-volume patterns in a way that creates unjustified privacy or fairness claims. Coverage differences and geographic error disparities will be documented. Licensing, retention requirements, and any further ethical limitations are **TBD — Requires validation**.

## 8. Success Criteria

### Data success

- Data acquisition and loading are reproducible for the documented source and version.
- Timestamps and geographic identifiers are sufficiently complete for the defined target, according to documented acceptance thresholds that are **TBD**.
- Quality rules, exclusions, and their effects are documented and reproducible.
- Hourly demand aggregation is reproducible from the selected raw data.

### Modeling success

- Candidate approaches are compared with appropriate naïve or seasonal baselines using identical evaluation periods and target definitions.
- Validation and final testing are time based; the final test data are not used for model selection.
- Evaluation reports MAE and at least one scale-aware metric such as WMAPE, with aggregation and zero-demand handling defined before final evaluation.
- Errors are analyzed by geographic unit and time segment.
- No target leakage is identified through documented feature-availability and split checks.
- Results are reproducible using stored configurations and random seeds where applicable.
- RMSE, prediction-interval coverage, and other metrics are **Proposed** until the evaluation design is finalized.
- Numerical acceptance thresholds and the primary model-selection metric are **TBD**; success requires transparent baseline comparison, not an invented performance target.

### Operational success

Forecast outputs make likely high-demand periods, potentially underserved geographic units, or capacity-planning priorities interpretable under explicitly stated capacity assumptions. A useful analytical output does not establish real operational improvement; claims about service levels, wait times, shortages, or costs require an intervention study or equivalent operational validation.

### Engineering success

- Environment setup is reproducible.
- The data pipeline and lineage from raw input to modeling table are documented.
- Critical transformations have automated tests.
- Experiments are configuration driven.
- Instructions reproduce the principal results and link them to a data version, configuration, scripts, and experiment ID.

## 9. Deliverables

| Deliverable | MVP status |
|---|---|
| Project charter | Required |
| Data documentation and data dictionary | Required |
| Reproducible data-ingestion and preprocessing pipeline | Required |
| Exploratory data analysis | Required |
| Baseline forecasts | Required |
| Candidate forecasting models | Required |
| Evaluation and error analysis | Required |
| Experiment log | Required |
| Forecast visualizations | Required |
| Final report or case study | Required |
| Reproduction instructions | Required |
| API or dashboard | Optional after analytical validation |

## 10. CRISP-DM Phases

| Phase | Objective | Principal activities | Required output | Completion evidence | Current status |
|---|---|---|---|---|---|
| Business Understanding | Define the decision, target, users, constraints, and success criteria | Confirm MVP choices, forecast horizon, operational interpretation, responsibilities, and acceptance logic | Approved project charter and resolved target definition | Both collaborators record agreement on required decisions and remaining assumptions | In progress |
| Data Understanding | Establish source suitability and data characteristics | Verify official source, inspect schema and coverage, assess quality, and perform exploratory analysis | Source record, data dictionary, quality report, and EDA | Findings are reproducible and source limitations are documented | Not started |
| Data Preparation | Create a leakage-safe modeling table | Validate, clean, aggregate, split by time, and engineer permitted features | Versioned modeling dataset or reproducible build process | Tests pass and lineage from raw data to model input is traceable | Not started |
| Modeling | Fit required baselines and candidate approaches | Configure, train, tune only on permitted periods, and log experiments | Baseline and candidate forecast artifacts with experiment records | Runs reproduce from stored configurations and seeds | Not started |
| Evaluation | Determine analytical adequacy and limitations | Apply fixed protocol, compare metrics, inspect zone/time errors, and review leakage and operational interpretation | Evaluation report and model recommendation or documented non-selection | Final test results, limitations, and decision rationale are traceable | Not started |
| Deployment | Demonstrate usable delivery of validated outputs | Package reproduction workflow and forecast outputs; optionally demonstrate an API or dashboard after validation | Reproducible portfolio demonstration; optional delivery interface | A reviewer can reproduce principal results and inspect outputs | Not started |


## 11. Constraints

- Only publicly available data may be used.
- Local computing and storage capacity are **TBD** and must be measured or declared before selecting files and modeling approaches.
- The project must be reproducible from documented source versions, environment instructions, configurations, and scripts.
- The project timeline is **TBD**; no calendar commitments are implied.
- Unnecessary infrastructure will be avoided during the MVP. An API, dashboard, live pipeline, or production platform is not required for analytical validation.
- Temporal leakage must be prevented by respecting information availability and chronological splits.
- Geographic leakage must be prevented by reviewing any feature that could encode the target or use unavailable cross-zone information. Whether generalization to unseen geographic units is required is **TBD**.
- The first iteration will remain small and testable: one taxi service type, a proposed three-to-six-month period, one geographic definition, hourly aggregation, required baselines, and at least one candidate machine-learning approach.

## 12. Assumptions

Every current assumption is provisional unless supported during a later CRISP-DM phase.

| Assumption | Status |
|---|---|
| Official NYC TLC trip-record data are publicly obtainable and suitable as the primary source for this portfolio project. | Requires validation |
| The selected files contain usable time and geographic information for constructing an hourly geographic demand target. | Requires validation |
| A raw observation represents one trip record. | Requires validation |
| Demand can be represented initially as a count of selected trips per geographic unit per hourly interval. | Proposed; requires validation |
| One taxi service type and three to six months are sufficient for a small, informative MVP. | Proposed; requires validation |
| Hourly resolution is useful for the intended capacity-planning interpretation. | Provided project premise; operational usefulness requires validation |
| A meaningful geographic service unit can be defined from the selected official data and reference information. | Requires validation |
| Historical information available before the forecast origin can provide useful predictive signal. | Requires validation |
| Plausible current planning may rely on recent observations, historical or seasonal averages, and judgment. | Requires validation; no operator has been confirmed |
| Local compute and storage can support the scoped MVP after the data subset is selected. | Requires validation |
| The two collaborators can use a shared version-controlled workflow and peer-review each other's material changes. | Proposed; requires confirmation |
| MAE and a scale-aware measure such as WMAPE can be defined appropriately for the selected target and aggregation levels. | Requires validation |
| Weather and event information may add signal, but is not necessary to complete the MVP. | Proposed; usefulness and availability require validation |
| Forecasts can be translated into planning indicators once a capacity definition or proxy is agreed. | Requires validation |
| Forecast accuracy is not by itself evidence of operational impact. | Governing analytical assumption |

## 13. Risks and Mitigations

| Risk | Practical mitigation |
|---|---|
| Large data volume exceeds local resources | Start with one service type and a proposed three-to-six-month subset; profile file size and memory needs before expansion; use efficient formats or chunked processing only if justified. |
| Missing or invalid locations and timestamps | Define validation rules, quantify failures, preserve quality summaries, document exclusions, and test the aggregation logic. |
| Demand-distribution shifts | Use chronological validation with more than one validation window if feasible, report performance by period, and avoid assuming historical stability. |
| Target leakage | Document when every feature becomes available, exclude post-forecast information, review rolling-window boundaries, and add leakage-focused tests. |
| Inappropriate random splitting | Fix chronological train, validation, and test boundaries before final evaluation and prohibit random row splits for reported forecasting performance. |
| Sparse-demand geographic units | Report volume alongside errors, define zero-demand metric handling, examine aggregation or segmentation only with evidence, and avoid hiding weak zone-level results in overall averages. |
| External features are unavailable or unsuitable | Keep weather and events optional; complete the MVP with validated TLC-derived information and add external data only after a source and incremental value are demonstrated. |
| Excessive model complexity | Require baselines, prefer the simplest approach that earns a defensible improvement, and record compute and interpretability tradeoffs. |
| Scope expansion | Treat expansion items as optional, require joint approval and evidence, and protect the MVP definition of done. |
| Unequal collaboration workload | Assign explicit owners and reviewers, review workload regularly, and record reassignment decisions; the cadence is **TBD**. |
| Forecast accuracy is confused with operational impact | Separate analytical, operational, and engineering success; label capacity indicators as decision support; require an intervention study before causal impact claims. |

## 14. Open Questions

| Open question | Status | Owner |
|---|---|---|
| Which taxi service type should be used first? | Open — Requires validation | TBD |
| Which three-to-six-month period should be selected? | Open — Requires validation | TBD |
| What geographic unit should define demand? | Open — Requires validation | TBD |
| Which timestamp should assign a trip to an hourly interval? | Open — Requires validation | TBD |
| What forecast horizon and forecast-origin schedule should be used? | Open — Requires validation | TBD |
| Which baselines should be mandatory? | Open — Requires validation | TBD |
| Which primary metric should control model selection? | Open — Requires validation | TBD |
| How should WMAPE and other metrics handle zero-demand units or periods? | Open — Requires validation | TBD |
| Are weather and event data justified for the MVP? | Open — Requires validation | TBD |
| What computing and storage constraints apply? | Open — Requires validation | TBD |
| How should responsibilities be divided? | Open — Requires agreement | TBD |
| What capacity measure or proxy should forecasts be compared with? | Open — Requires validation | TBD |
| What evidence would justify expanding beyond the MVP? | Open — Requires agreement | TBD |

<!-- ## 15. Definition of Done

The MVP is complete only when all of the following are true:

- The business question and forecasting target are clearly defined.
- The selected data source and version are documented.
- Raw-to-model transformations are reproducible.
- Time-based train, validation, and test logic is fixed before final evaluation.
- Baselines and candidate models use the same evaluation protocol.
- Results are traceable to their data, configuration, scripts, and experiment ID.
- Error analysis and limitations are documented.
- Critical tests pass.
- Reproduction instructions are complete.
- No unverified business-impact claims are presented as results. -->