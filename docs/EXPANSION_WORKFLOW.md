w# Project expansion workflow

Drafted November 13, 2026. This plan connects the requested capabilities to the implemented April–June 2025 pipeline. The user requested the expansion; dataset choices, revised evaluation boundaries and resource estimates below are proposals for the next iteration. The original charter remains the record of the completed benchmark. Update its expansion decisions before new experiments.

## Starting evidence

- 12,885,358 source records scanned; 12,856,543 accepted pickups aggregated to 572,208 zone-hours across 262 zones.
- Own-zone calendar, lag and rolling features with the latest available count at lag 2.
- Fixed chronological validation followed by a frozen June 15–30 test.
- Final LightGBM MAE 4.383744 and WMAPE 19.640898%, compared with weekly baseline WMAPE 24.936262%.
- Local MLflow tracking, input fingerprints, saved native model, fresh-process prediction verification, and automated tests.
- Published Tableau dashboard and documented planning indicators.

See [final metrics](../reports/final_evaluation/71dcb809d5c0409484d8b55b21751f17/metrics.csv), [reproduction report](../reports/reproducibility/d9510d7a170f45518a7d633a0a1dcecf/report.json), and [dashboard guide](../dashboards/tableau/README.md).

## Notion reference review

Reviewed through the connected Notion integration, including the four SVG workflow diagrams. The pages provide learning references and tool inventories. Their production examples and illustrative numbers require independent evidence before applying them to this project.

- [Open Source Vault](https://app.notion.com/p/dacfa34310f04a46ba5fd37e5cd40d0d)
- [Concept Notes](https://app.notion.com/p/Concept-Notes-4126e4108158814f942acfcdd5b848cf)
- [Role-Specific Workflow and Tools at each step](https://app.notion.com/p/Role-Specific-Workflow-and-Tools-at-each-step-4176e41081588073bd48d98348e4594a)

The role diagrams connect directly to the proposed execution sequence.

| Reference | Application here |
|---|---|
| Data Scientist workflow | Extend the existing framing, EDA and feature work into rolling validation, model-family comparisons and SHAP; retain Git and MLflow evidence. |
| AIML Engineer workflow | Implement Spark preparation, recoverable data versions, model packaging, FastAPI, Docker, CI and monitoring. |
| Data Analyst workflow | Reuse the validated export and Tableau calculations when building Power BI; verify shared totals and KPI definitions. |
| AI Engineer workflow | An optional later alert explanation assistant can consume computed monitoring evidence. Its development depends on a working monitoring job and a separate evaluation of its explanations. |
| Concept Notes | Implement scoring, immediate data/prediction checks, and delayed-label error checks. Investigate alerts with versioned evidence. |
| Open Source Vault | The relevant entries reviewed include PyTorch Concepts and PyMC ecosystem resources. These are potential later interpretability/uncertainty approaches; the requested SHAP and interval work should first use the selected forecasting models. |

The churn deciles and illustrative PSI bands in Concept Notes need adaptation. This project predicts counts, so MAE, WMAPE, RMSE and interval coverage are direct performance checks. Rank-based pickup capture can be a supplementary planning diagnostic. Drift limits should be calibrated using development windows with comparable seasonal composition and adequate zone volume. Feature or prediction drift alone does not establish a changed relationship between predictors and demand.

## Execution sequence

### 1. Preserve the benchmark and specify the expanded experiment

Keep the completed data/report fingerprints, selected settings and June final-test scores as the first benchmark. Record the expansion separately, including intended capabilities, forecast origins, training-label availability, shared metrics, compute limits and model-selection rules.

**Deliverable:** revised charter decisions and a versioned experiment configuration.

**Completion evidence:** every new comparison has a declared training period, tuning/calibration periods, and future final holdout. The historical June results remain traceable.

### 2. Extend the time coverage and make data versions recoverable

**Proposed:** verify availability and sizes for July–September 2025 yellow-taxi files. Use April–June as initial history, July for rolling development folds, August for chronological interval calibration, and September as the next untouched final holdout, subject to source verification and protocol agreement. Declare the model refit schedule and calibration residual generation before evaluation. This six-month window offers additional temporal checks; annual-seasonality evidence would require longer coverage.

Reuse manifest integrity checks, exclusions, schema validation and complete zone-hour grids. Review cross-file date exceptions with the established rules. Keep final-holdout analysis limited to predefined integrity checks until selection freezes.

Adopt DVC for the raw, reference and prepared snapshots, with Git storing pointer metadata and configuration. Select a persistent remote or backup destination. A local DVC cache alone cannot make the data recoverable on another machine.

**Deliverable:** versioned data snapshots, source manifest and restoration instructions.

**Completion evidence:** retrieve one exact data version into a clean directory and reproduce its hashes. Verify all added monthly counts and zone-hour boundaries. Check Java, package storage and source download sizes against the free-disk floor before installation or acquisition.

### 3. Implement the PySpark preparation path

Translate the existing ingestion, timestamp interpretation, zone filtering and hourly aggregation to PySpark. Use local CPU mode initially and record the actual execution mode. Explicitly set session timezone and test conversion from Parquet timestamp types.

Reuse the existing pandas/PyArrow outputs as a reference on the same snapshots. Spark dataframes need explicit ordering before time windows, and joins must preserve one reference match per zone ID.

**Deliverable:** configurable Spark ingestion/preparation command and MLflow data-preparation provenance.

**Completion evidence:** exact parity of accepted counts, exclusions, zone universe, hourly keys and counts. Demonstrate the existing 12.9-million-record scope through the Spark path before claiming PySpark processing. Record memory/runtime measurements.

### 4. Add weather and event features with availability evidence

Verify public sources, terms, timezone semantics, coverage and geographic mapping. Establish whether each field would have been available at the forecast origin.

**Proposed weather path:** lagged observations with documented release timing, or archived forecasts issued before origin. Observed weather during the future target hour requires availability justification.

**Proposed event path:** scheduled start/end, location and announced event type from dated public schedules. Realized attendance requires separate availability evidence.

Preserve the current calendar/history-only feature set for an ablation. Resolve timezone alignment before external joins. If appropriate historical sources are unavailable, report that limitation.

**Deliverable:** external-data manifests, availability contracts and deterministic joins.

**Completion evidence:** uniqueness, coverage, missingness and as-of leakage tests; recorded comparison of features with and without external data.

### 5. Implement rolling-origin validation

Define multiple forecast cutoffs in the development period. At each cutoff fit only labels available at that time, then replay later hours using the same reporting delay. Fit scalers, imputers, encoders and feature selection within each training fold.

Make fold dates, tuning budgets, shared forecast cells, selection aggregation and final-refit logic configuration-driven. Reserve the new future holdout for one frozen final assessment. Previously inspected June data can be explicitly designated development history in this expanded protocol.

**Deliverable:** reusable fold generator and fold-level MLflow run structure.

**Completion evidence:** tests for fitting-label cutoffs, feature availability, fold isolation and identical evaluation keys across methods.

### 6. Compare all requested model families

Retain the three baselines. Add SARIMA, Prophet, XGBoost and LSTM alongside LightGBM with bounded, declared parameter searches.

Specify the architecture per family. SARIMA and Prophet need a per-zone strategy, including all-zero and sparse zones. Pooled tree models preserve categorical zone identity. An LSTM needs sequences restricted to each zone and training-fitted scaling.

Use the same forecasting horizon, availability rule and cells for every contender. Document any sparse-zone fallback and evaluate it as part of the complete method. Keep model search sequential under an approved resource budget.

At origin t, a univariate model's newest observed bucket is t-2. SARIMA, Prophet and sequence-model adapters must bridge the unavailable t-1 bucket when forecasting t. Updating model parameters at every origin would be a separate refit schedule and must be declared for a fair comparison.

**Deliverable:** common model interface, logged configurations, learning history and fold scores.

**Completion evidence:** each family trains successfully, produces valid forecasts on every required cell, and has measured runtime and memory. Select using the predeclared rule; retain negative findings.

### 7. Evaluate uncertainty and expanded metrics

Keep MAE and pooled WMAPE, add RMSE, and retain zone/time error analysis. Treat zero-total WMAPE as undefined while reporting its absolute errors and volumes.

**Proposed:** 90% prediction intervals calibrated using past residuals with a separate chronological calibration period, where appropriate. Establish a method for each model's intervals and retain nonnegative, ordered bounds. Report empirical coverage alongside average interval width, by fold and zone-volume group.

**Deliverable:** shared metrics and interval-evaluation module.

**Completion evidence:** metric edge-case tests, calibration isolation, coverage/width reports and a frozen new final-test assessment. RMSE, coverage and new model results are identified as measurements from the expanded experiment.

### 8. Explain forecasts using SHAP

Apply SHAP to the selected tree model, with a background/reference sample drawn from training data. Record sampling, runtime limits and the model output scale being explained.

Create global feature summaries, zone/time comparisons and a few representative local explanations. Compare them with the feature ablation and evaluate plausibility. Feature attribution does not establish causal effects.

**Deliverable:** explanation artifacts and a model interpretation section.

**Completion evidence:** exact model/data/run identity, valid explanation dimensions, documented output units and reviewed examples.

### 9. Build and verify the FastAPI inference service

Package the selected model with its feature schema, zone categories, history requirements and metadata. Define forecast-origin and historical-data inputs.

Build health/readiness, metadata and prediction endpoints. Validate zones, timestamps, missing history and delayed-count availability. Reuse tested feature computation so service features match offline features.

Log request IDs, model/run version, latency and failures. Add contract and integration tests, a container build and CI checks. Keep serving claims tied to measured local behavior until deployment is tested.

**Deliverable:** runnable service with documented requests, responses and model provenance.

**Completion evidence:** saved offline examples match API predictions within tolerance; invalid inputs produce explicit errors; measure representative latency and resource use. Keep secrets outside version control.

### 10. Build the web demonstration frontend

**Proposed:** a React/TypeScript frontend consuming the FastAPI service. Start design with the planner's tasks, a page sketch, and a tested request/response contract. Default to a labeled historical replay using a preloaded, versioned history dataset. Offer forecast origins only where the required history exists. Display data cutoff, forecast interval, assumed timezone and model version together.

The forecast view includes origin/zone selection, an explicit forecast action, predicted pickups, hourly zone ranks, a selected-zone history chart and the training reference. Add interval bounds and SHAP explanations when the corresponding backend artifacts are verified. Show realized pickups as retrospective evaluation information after the forecast. The evaluation view includes the declared test period, baseline comparison, zone/time errors and model/data lineage. Add a scenario view after the allocation simulator passes its checks, with assumptions, equal-resource policy comparison and measured outcomes. Monitoring adds data-quality, drift, service-latency and delayed-label performance views after those jobs exist.

Use accessible text labels, consistent numeric units, visible legends and responsive layouts. Pair color with text for flags. Provide loading, empty, insufficient-history, unsupported-zone, out-of-range and API-error states. Render API-produced predictions and model/version identifiers. Preserve the selected origin and forecast provenance when users navigate between views.

**Deliverable:** working frontend connected to FastAPI, documented local startup and a demonstration recording or hosted URL when deployed.

**Completion evidence:** browser-to-API integration checks reproduce saved forecasts, history cutoffs and selected zones; errors appear clearly; charts and tables reconcile to the API response. Define a representative latency target before measuring the complete interaction. Add simulator and monitoring panels incrementally with their verified dependencies.

### 11. Deliver the Power BI planning dashboard

Reuse the verified planning export and its definitions to create the requested Power BI view while retaining the Tableau artifact. Confirm Power BI authoring access and the available Windows or browser workflow before implementation.

Include recorded/forecast traces, zone/time errors, demand ranks, historical flags, and interval displays once verified. Supply model/data version and evaluation period.

**Deliverable:** Power BI artifact and screenshots/share link as supported by the chosen authoring environment.

**Completion evidence:** totals and sample cells match the same source exports. Capacity scenario displays identify their inputs and units.

### 12. Build the driver-allocation simulation

Define the simulation's demand, supply, action frequency, service duration, repositioning/travel limits, and treatment of waiting, abandonment and carryover. TLC completed trips alone do not identify all passenger requests or the available fleet.

Begin with a clearly labeled scenario using recorded pickups as a demand proxy if independent request/supply data are unavailable. Specify the meaning and limits of simulated unmet demand in that scenario.

Compare a fixed-allocation policy with a forecast-informed policy using the same total capacity, timing, constraints and realized scenario demand. Fit policy choices in development history, then evaluate the frozen policies on a future period. Use repeated seeds where stochastic assumptions apply and sensitivity checks across capacity/service assumptions.

**Deliverable:** reproducible simulator, policy comparison, assumptions and uncertainty/sensitivity results.

**Completion evidence:** conservation/accounting tests, equal-resource comparison, no policy access to future actuals, and traceable effect estimates. Report the measured result. The earlier resume's 12% figure remains unsupported until an experiment produces it.

### 13. Implement monitoring and update decisions

Persist forecasts with model version and origin, then attach actual outcomes only when available. Create scheduled or replayed batch checks for schema violations, missingness, input distributions and forecast errors. Add interval coverage and width once intervals exist.

Freeze reference windows, minimum sample sizes and alert thresholds using development data. Distinguish sparse-volume instability, data failures and performance deterioration in the investigation guide. Record alert evidence and the action taken.

**Proposed tools:** Evidently for batch drift/quality reports, MLflow for run/model lineage, and Python logging for structured job/API events. Distinguish simulated replay availability from TLC's actual publication delay. Exercise the workflow with historical batches before claiming live monitoring.

**Deliverable:** monitoring job, versioned thresholds and an investigation/update runbook.

**Completion evidence:** replay a deliberately corrupted input and a changed distribution to exercise alerts; verify delayed-label metric computation and small-sample handling. Model updates require a fresh tracked evaluation and acceptance decision.

### 14. Assemble the final production-oriented demonstration

Run data restoration, preparation, training/evaluation, model reload, API prediction and monitoring checks from documented commands. Verify the dashboard references the demonstrated model/data version.

Summarize results and limitations in the final case study. Maintain a claim-to-evidence table for PySpark, model families, uncertainty, SHAP, serving, dashboards and simulation.

**Deliverable:** reproducible case study, architecture diagram, model documentation and accurate resume bullets.

**Completion evidence:** a clean-environment run and links to retained artifacts for every quantitative or tool-specific claim.

## Immediate first task

The user approved the [expansion protocol](../configs/expansion_v1.json) on November 15, 2026. The last hour of July and August is excluded from the respective scoring windows because its label arrives after the next decision time.

On November 15, the official TLC listing and HTTP HEAD requests confirmed the three yellow-taxi files were available. July is 66,943,728 bytes, August is 62,293,743 bytes, and September is 72,432,945 bytes. Their combined download is 201,670,416 bytes, approximately 192.33 MiB. Available local disk space was approximately 12 GiB. The downloads fit above the approved 10 GiB free-space floor. The full 5 GiB persistent growth and 1 GiB temporary budget requires additional storage headroom before the complete expansion.

Acquire the three files into the existing raw-data directory, then record download dates, source URLs, byte sizes and SHA-256 hashes in the manifest. Source integrity and predefined quality checks precede model work. September remains reserved for the declared final assessment.

## Completion and claim rules

- A dependency being installed is insufficient evidence that a capability was implemented.
- Preserve validation and final-test labels on reported metrics.
- Record every experiment, including failures, in MLflow with configuration, code revision, data identities, predictions and metrics.
- Recoverable data storage, model serving and monitoring are separate deliverables with their own verification.
- The project may yield weaker model scores or small simulation gains. Report measured outcomes without tuning toward an earlier resume number.
