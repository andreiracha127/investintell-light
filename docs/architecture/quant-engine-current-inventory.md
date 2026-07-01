# Quant Engine Current Inventory

Date: 2026-06-25

Scope: read-only inventory before any behavior extraction. This document covers
the workers checkout and the paired backend checkout used for Plan C allocator
inspection.

## Repositories And Branches

Workers:

- Worktree: `E:\investintell-datalake-workers-quant-engine`
- Branch: `feat/quant-engine-isolation`
- Base branch identified locally: `feat/combo-regime-gate`
- Base SHA: `285b0586213bab8d6cfd4f1e67d62ff8453cbda5`
- Status at inventory: clean
- Remote note: GitHub currently exposes only `main` for
  `andreiracha127/investintell-datalake-workers`; the user confirmed the local
  ahead branch is the source of truth. Local branch uniqueness was verified:
  only `feat/combo-regime-gate` contained the full A3 file set
  (`src/calibration_harness.py`, `qc_a3_core.py`, QC notebooks, A31/A32 configs,
  and tests).

Backend:

- Worktree: `E:\investintell-light-quant-engine-contracts`
- Branch: `feat/quant-engine-contracts`
- Base branch: `feat/combo-regime-allocator`
- Base SHA: `a6c6f3e7fae6e2e63a0f3a9214f89c12e0819174`
- Status at inventory: clean
- GitHub check: `feat/combo-regime-allocator` exists at the same SHA.

Discovery notes:

- Serena was activated for both worktrees.
- Auggie was attempted on `feat/combo-regime-gate`, but that branch was not
  indexed. Auggie `main` search did not contain the A3 calibration lane, so all
  source-of-truth findings below are from local `git`, `rg`, and direct reads.

## Workers: Canonical Current Locations

### A31 / A32 configuration

- `src/calibration_harness.py:174` - `A31Config`
- `src/calibration_harness.py:191` - `A32Config`
- `src/calibration_harness.py:206` - `A31GridConfig`
- `src/calibration_harness.py:217` - `A32GridConfig`
- `configs/a31_v03_revision_robust_g1.yaml` - v03 six-config microgrid catalog:
  `V03-G0-CONTROL`, `V03-G1-FAMILY-WEIGHTED-MEDIAN`,
  `V03-G1-REVSOFT-P50`, `V03-G1-REVSOFT-P75`,
  `V03-G1-FAMILY-CONSENSUS-60`, `V03-G1-FAMILY-CONSENSUS-67`.
- `configs/a31_a32_selected_v01.yaml` - selected provisional A31 panels for
  limited A3.2 grid, including `G2-CREDIT6040-15-SURVEY05`.
- `qc_a3_core.py:21` - default A32 name:
  `A32-G0.35-I0.35-X0.10-C0.60-D1.25`.

### L3 scoring

- `src/calibration_harness.py:2502` - `build_l3_score_panel`
- `src/calibration_harness.py:2635` - `aggregate_l3_axis`
- `src/calibration_harness.py:2740` - `l3_row_selected`
- `src/calibration_harness.py:2749` - `apply_revision_soft_threshold`
- `src/calibration_harness.py:2467` - `canonical_config_hash`
- `src/calibration_harness.py:2471` - `a31_config_hash`
- `src/calibration_harness.py:2480` - `a32_config_hash`
- `src/calibration_harness.py:2488` - `evaluation_hash`

Current behavior:

- L3 validates the L2 parent hash before scoring.
- L3 enriches L2 component z-scores, groups by `(business_date,
  selection_mode)`, selects series through `A31Config`, aggregates growth and
  inflation axes, and emits score rows plus contribution rows.
- L3 quality vector is `C/F/A/V`, with `u = 0.35*C + 0.20*F + 0.25*A + 0.20*V`.
- L3 writes no files directly; file I/O is done by grid/harness runners.

### L4 state machine, confidence, hysteresis, reason codes

- `src/calibration_harness.py:3089` - `run_l4_state_machine`
- `src/calibration_harness.py:3256` - `l4_axis_status_payload`
- `src/calibration_harness.py:3279` - `resolve_candidate_status_with_config`
- `src/calibration_harness.py:1900` - legacy/general `resolve_candidate_status`
- `src/calibration_harness.py:1920` - `primary_reason`
- `src/calibration_harness.py:1947` - `reason_groups`
- `src/calibration_harness.py` constants:
  `L4_STATE_SCHEMA_VERSION`, `L4_STATE_CODE_VERSION`,
  `CONFIDENCE_MODEL_VERSION`, `U_FLOOR`, `MIN_CONFIDENCE`,
  `GROWTH_ENTER`, `INFLATION_ENTER`, `AXIS_EXIT`, `DISPERSION_ABSTAIN`.

Current behavior:

- L4 runs separately for `selection_mode="latest"` and
  `selection_mode="first_release"`.
- Hysteresis is implemented by axis internal signs via `transition_axis`, then
  effective signs feed `quadrant_from_signs`.
- If `information_set_hash` is unchanged, the previous record is carried forward
  without reevaluation.
- Confidence formula is:
  `0.60 * u + 0.40 * sqrt(growth_margin * inflation_margin)`.
- Candidate status fails loud into reason codes for no score, coverage,
  freshness, insufficient families, missing anchor family, family dispersion,
  axis deadband/neutrality, `u_floor`, and `min_confidence`.
- Runtime role is explicit: latest is `pit_runtime_candidate`; first release is
  `revised_vintage_counterfactual`.

### Revision diagnostics

- `src/calibration_harness.py:2325` - `build_revision_attribution`
- `src/calibration_harness.py:3725` - `replay_revision_diagnostics`
- `src/calibration_harness.py:7603` -
  `load_revision_uncertainty_from_manifest`
- `src/calibration_harness.py:5020` - `run_v02_fetch_alfred`
- `src/calibration_harness.py:5112` - `fetch_v02_candidate_vintages`

I/O note:

- `run_v02_fetch_alfred` and `fetch_v02_candidate_vintages` are intentionally
  external-data functions. They read `FRED_API_KEY` and use `httpx`; they must
  stay outside `quant-core` and outside formal offline engine execution.

### Metrics

- `src/calibration_harness.py:2055` - `build_macro_metrics`
- `src/calibration_harness.py:3607` - `evaluation_metric_rows`
- `src/calibration_harness.py:3792` - `operational_state_metrics`
- `src/calibration_harness.py:3593` - `classify_a32_grid_result`
- `src/calibration_harness.py:8127` - `classify_a31_grid_result`
- `src/calibration_harness.py:9310` - `mark_a31_pareto`
- `src/calibration_harness.py:9345` - `pareto_projection`
- `src/calibration_harness.py:9352` - `a31_pareto_sort_key`
- `qc_a3_core.py:544` - `metric_rows_logical_hash`
- `qc_a3_core.py:549` - `metric_rows_raw_sha256`
- `qc_a3_core.py:559` - `metrics_hash_policy_payload`
- `qc_a3_core.py:596` - `canonical_metric_rows`

Current behavior:

- Full metrics are produced from runtime replay and optional first-release
  counterfactual replay.
- Fold metrics are emitted by `evaluation_metric_rows`.
- A31 Pareto is selected after sorting eligible rows by revision and transition
  metrics; output is sorted by `a31_config_hash`.
- QC bridge metric hashes have a raw SHA-256 path and a canonical float-tolerant
  path. The current code exposes `metrics_canonical_logical_hash`.

### Canonical hashes and serialization

- `src/calibration_harness.py:4655` - `logical_records_hash`
- `src/calibration_harness.py:4668` - `logical_payload_hash`
- `src/calibration_harness.py:4701` - `write_parquet`
- `src/calibration_harness.py:4715` - `write_json`
- `src/calibration_harness.py:7631` - `read_parquet_records`
- `src/calibration_harness.py:8098` - A31 worker writes `result_manifest.json`
  with replay, counterfactual, metrics, and file hashes.
- `qc_a3_core.py:575` - `bundle_evaluation_hash`
- `qc_a3_core.py:897` - export path computes runtime, counterfactual, and
  metric hashes for Object Store manifests.

Current behavior:

- Logical hashes use stable JSON normalization through harness helpers.
- A31 grid worker writes to a temporary directory, validates persisted hashes by
  reading back Parquet artifacts, then renames the temp directory into place.
- Resume is supported by `load_existing_a31_result`, which checks expected L2,
  A31, A32, evaluation, replay, counterfactual, and metrics hashes.

### CLIs and runners

Current `src/calibration_harness.py` commands:

- `a31-grid` -> `parse_a31_grid_args`, `run_a31_grid`
- `revision-uncertainty` -> `parse_revision_uncertainty_args`,
  `run_revision_uncertainty`
- `a31-v03-grid` -> `parse_a31_v03_grid_args`, `run_a31_v03_grid`
- `a32-grid` -> `parse_a32_grid_args`, `run_a32_grid`
- `a3-freeze-readiness` -> `parse_a3_freeze_readiness_args`,
  `run_a3_freeze_readiness_package`
- `market-grid` -> `parse_market_grid_args`, `run_market_grid`
- `a3-scope-decision` -> `parse_a3_scope_decision_args`,
  `run_a3_scope_decision`
- `v02-fetch-alfred` -> `parse_v02_fetch_alfred_args`, `run_v02_fetch_alfred`
- `v02-qualify` -> `parse_v02_qualification_args`, `run_v02_qualification`
- Legacy default replay path -> `parse_args`, `run_harness`

Current `qc_a3_core.py` commands:

- `run-parity` -> `run_parity`
- `export-bundle` -> `export_bundle`
- `upload-object-store` -> `upload_object_store_bundle`

Runner notes:

- `run_a31_grid`, `run_a32_grid`, and `run_market_grid` require `--offline`.
- `run_a31_grid` supports `jobs`, `resume`, and sorted consolidation.
- `run_a31_grid` uses `ProcessPoolExecutor` when `jobs > 1`.
- `run_a32_grid` is serial over selected A31 panels and A32 configs.
- `run_market_grid` is offline over market feature primitives and optional macro
  comparison inputs.

### QC bridge and notebooks

- `qc_a3_core.py` - canonical local QC bridge.
- `qc-a3-parity/qc_a3_core.py` - duplicate bridge copy for QC project payload.
- `qc-a3-parity/microgrid_worker.py` - QC/local microgrid execution helper.
- `notebooks/qc_a3_parity.ipynb` and
  `qc-a3-parity/qc_a3_parity.ipynb` - parity notebooks.
- `notebooks/qc_hmm_challenger.ipynb` and
  `qc-a3-parity/qc_hmm_challenger.ipynb` - market/HMM diagnostic notebooks.
- `qc-a3-parity/README.md` - states notebooks are diagnostic-only,
  `runtime_activation=false`, `A4=harness_ready_provisional_A3`,
  `A5=blocked`, and approval counts for QC parity.

Duplication to remove by strangler:

- Formula/runtime-equivalent logic currently lives in `src/calibration_harness.py`.
- QC imports the harness via `qc_a3_core.py`, but a copied QC project directory
  also carries `qc-a3-parity/qc_a3_core.py`.
- Notebooks are clients/validators and must not become runtime canonical.

## Pure Functions Versus I/O

Candidate pure / quant-core-suitable units:

- `A31Config`, `A32Config`, and small deterministic config dataclasses.
- `canonical_config_hash`, `a31_config_hash`, `a32_config_hash`,
  `evaluation_hash`.
- L3 core: `build_l3_score_panel`, `aggregate_l3_axis`, `l3_row_selected`,
  `apply_revision_soft_threshold`, `family_consensus_status`,
  `series_score_from_l2_row`, `series_direction`, `aggregate_values`,
  `weighted_median`, `huberized_weighted_mean_with_limit`,
  `l2_information_set_hash`, `l3_contribution_rows`.
- L4 core: `run_l4_state_machine`, `transition_axis`, `axis_margin`,
  `quadrant_from_signs`, `quadrant_from_scores`, `l4_axis_status_payload`,
  `resolve_candidate_status_with_config`, `primary_reason`, `reason_groups`.
- Metrics/classification: `build_macro_metrics`, `evaluation_metric_rows`,
  `replay_revision_diagnostics`, `operational_state_metrics`,
  `classify_a31_grid_result`, `classify_a32_grid_result`,
  `mark_a31_pareto`, `pareto_projection`, `a31_pareto_sort_key`.
- Hash normalization: `logical_records_hash`, `logical_payload_hash`,
  `normalize_logical_value` and QC metric canonicalization.

I/O / runner units to keep out of quant-core:

- DB access: default `run_harness` uses `connect(resolve_dsn(os.getenv("DATABASE_URL")))`.
- FRED/ALFRED: `load_fred_api_key`, `read_env_file_value`,
  `fetch_v02_candidate_vintages`, `run_v02_fetch_alfred`.
- Tiingo/market external access: `replay_market_tiingo`.
- Filesystem: all `read_*`, `write_*`, `hash_file`, `hash_artifacts`,
  `read_parquet_records`, `write_parquet`, `write_json`, `write_yaml`,
  `write_text`, bundle export/upload.
- Git/environment metadata: `run_text(["git", ...])`,
  `collect_environment_metadata`, `package_version`.
- Parallel execution: `run_a31_grid` ProcessPool path.
- QuantConnect/Lean/Object Store: `qc_a3_core.py` upload and QC materialization
  helpers.

## Current Dependencies

DB:

- `src/calibration_harness.py:9482` imports `src.db.connect` and calls
  `connect(resolve_dsn(os.getenv("DATABASE_URL")))` for legacy default replay.
- Runtime workers under `src/workers` use `src.db.connect` and advisory locks.
- Backend Plan C reads DB sessions on request path for returns, taxonomy,
  quadrant snapshot, gate snapshot, proxy returns, SPY beta signal, and optional
  look-through constraints.

Filesystem:

- Harness reads/writes Parquet, JSON, YAML, CSV/gzip, NPZ, temporary output
  directories, and QC bundle directories.
- A31 worker currently writes to temp dir and renames into final result dir.

Timezone / clock:

- Runners stamp `started_at` / `finished_at` with `dt.datetime.now(UTC)`.
- `decision_time` exists for ALFRED availability semantics.
- Backend `regime_aware` uses one decision timestamp for quadrant and gate reads.

Environment variables:

- Workers: `DATABASE_URL`, `FRED_API_KEY`, QC/Lean variables such as
  `QC_ORGANIZATION_ID`.
- Backend: service DB settings, datalake settings, and request-path sessions.

Networking:

- Workers: `httpx` for ALFRED/FRED; Tiingo client for market paths; Lean/QC
  object-store upload.
- Quant-engine offline target must exclude all of these.

Numerical/data libraries:

- Workers requirements include numpy, pandas, pyarrow, PyYAML, scipy, arch,
  httpx, websockets, psycopg.
- Quant-core candidate path needs numpy/pandas/scipy only where the pure formulas
  actually require them.

Multiprocessing/threading:

- `run_a31_grid` uses `concurrent.futures.ProcessPoolExecutor` for per-config
  parallelism.
- Runtime ingestion workers also use process/thread pools, but those are outside
  quant-engine core.

Backend:

- Current A3 harness is not imported by backend.
- Backend Plan C allocator is independent and must remain in backend in this
  phase.

## Golden Baseline And Local Artifacts

Required golden contract from the task:

- A31: `V03-G0-CONTROL`
- A32: `A32-G0.35-I0.35-X0.10-C0.60-D1.25`
- L2 hash: `9d46ac84d89df7b0ea72d2162aac9d5fa1ce0eb6b6d4cb9c69e0c47d82bfee43`
- Revision uncertainty hash:
  `bc4b7fad71d942ec2529a3a9cfb4e81f54ea803037e6e384e828dc142d029fb3`
- Runtime rows: 3221
- Counterfactual rows: 3221
- Metric rows: 5
- Runtime replay hash:
  `de46dfb7acaf40bf368cfa9a06192a655b9f938e9000edc01d8a34fddf4a3024`
- Counterfactual replay hash:
  `0238d3b5583e06381c3ae2914a80b64f58bc04c50fac455d7e6285228922b021`
- Canonical metrics hash:
  `70014a0a04fa26faf8aec88227f0f1fea381091acb6ac307fae30b77172300d3`
- `mismatch_count=0`

Observed local artifact state:

- The active worktree is clean and intentionally does not contain untracked
  `_tmp_*` bundles.
- The base local checkout `E:\investintell-datalake-workers-combo` contains
  non-versioned QC parity bundles and v03 manifests.
- Clean committed reports at worker commit `25375bb...` reproduce runtime and
  counterfactual hashes, but older reports use metric hash
  `e760d1e926c8717a6d9c2a63fc80e1a139aca3cf73bd17525631855f6a7d0f03`.
- Later local artifacts with the current metric hash policy contain the required
  canonical metrics hash `70014a...` with `mismatch_count=0`, including
  `_tmp_qc_a3_parity_precommit_policy_v2_20260625` and
  `_tmp_qc_a3_parity_dockerfix_20260625`.
- Before extraction, the formal baseline must be rerun or copied from an
  immutable local bundle into the active worktree and revalidated under current
  code. If that cannot be done, extraction must stop.

## Backend: Plan C / Allocator Inventory

### Taxonomy and sleeve mapping

- `backend/app/optimizer/sleeves.py:1` - 7-sleeve allocator model.
- `backend/app/optimizer/sleeves.py:27` - `CategorySpec`
- `backend/app/optimizer/sleeves.py:33` - `LABEL_TO_PROXY`
- `backend/app/optimizer/sleeves.py:64` - `PROXY_TO_GROUP`
- `backend/app/optimizer/sleeves.py:92` - `SLEEVE_GROUPS`
- `backend/app/optimizer/sleeves.py:99` - `GROUP_BENCHMARK`
- `backend/app/optimizer/sleeves.py:209` - `category_for_proxy`
- `backend/app/optimizer/sleeves.py:217` - `category_for_fund`
- `backend/app/optimizer/sleeves.py:233` - `fund_sleeve_group`

Accepted canonical fills in this branch:

- `cash -> BIL`
- `equity -> IVV`
- `fixed_income -> GOVT`
- `thematic -> XLK`
- `alternatives -> QAI`
- `gold -> GLD`
- `long_short -> FTLS`

### Effective policy, quadrant policy, gate overlay

- `backend/app/services/quadrant_policy.py:53` - `QuadrantPolicy`
- `backend/app/services/quadrant_policy.py:62` - `policy_bands`
- `backend/app/services/quadrant_policy.py:125` - `QUADRANT_POLICIES`
- `backend/app/services/quadrant_policy.py:267` - `validate_quadrant_policies`
- `backend/app/optimizer/gate_overlay.py:23` - `GateOverlayShape`
- `backend/app/optimizer/gate_overlay.py:44` - current v0.1 gate overlay shape:
  `cvar_tightening=0.35`, `beta_tightening=0.25`,
  `risk_assets_reduction=0.07`.
- `backend/app/optimizer/gate_overlay.py:101` - `apply_gate_overlay`
- `backend/app/services/effective_policy.py:61` - `EffectiveRegimePolicy`
- `backend/app/services/effective_policy.py:84` - `build_effective_policy`

Current behavior:

- `build_effective_policy` composes separate quadrant and gate snapshots.
- Non-consumable quadrant/gate/policy fail loud with structured prefixes:
  `QUADRANT_UNAVAILABLE`, `GATE_UNAVAILABLE`, `POLICY_NOT_FOUND`,
  `UNKNOWN_PROFILE`.
- Gate overlay tightens CVaR, aggregate beta cap, and risk-assets cap only in
  `risk_off`; it is identity in `risk_on`.

### S, M_t, constraints, preflight, optimizer/fallback

- `backend/app/services/portfolio_builder.py:235` - `_ActiveInstrument`
- `backend/app/services/portfolio_builder.py:246` - `CompiledRegimeProblem`
- `backend/app/services/portfolio_builder.py:603` -
  `_aggregate_policy_constraints`
- `backend/app/services/portfolio_builder.py:728` -
  `_compile_regime_problem`
- `backend/app/services/portfolio_builder.py:917` - `M` matrix construction
- `backend/app/services/portfolio_builder.py:923` - `S` matrix construction
- `backend/app/services/portfolio_builder.py:951` - instrument cap
  constraints over `M`
- `backend/app/services/portfolio_builder.py:961` - final-book
  `instrument_floor` constraints over `M`
- `backend/app/services/portfolio_builder.py:991` - aggregate
  `risk_assets_cap` and `defensive_floor`
- `backend/app/services/portfolio_builder.py:1007` - aggregate
  `portfolio_beta_cap`
- `backend/app/services/portfolio_builder.py:1046` - compiled
  `BoundsBundle`
- `backend/app/services/portfolio_builder.py:1052` -
  `_preflight_compiled_problem`
- `backend/app/services/portfolio_builder.py:1106` -
  `_solve_compiled_regime_problem`
- `backend/app/services/portfolio_builder.py:1151` -
  `_post_verify_compiled_solution`
- `backend/app/services/portfolio_builder.py:1315` -
  `_solve_regime_two_level`
- `backend/app/services/portfolio_builder.py:1774` - request dispatch for
  `payload.objective == "regime_aware"`

Current behavior:

- Solver variable `x` lives in category space.
- `S` maps categories to seven policy sleeves: `s = Sx`.
- `M` maps categories to deduplicated final instruments: `y = Mx`.
- Final weights are verified on `y`, including sum, non-negativity, linear
  constraints, sleeve blocks, and realized CVaR.
- Primary solver is BL max-utility with hard CVaR:
  `engine.solve_bl_utility_cvar`.
- Fallback is `engine.solve_min_cvar` with the same bounds and linear
  constraints.
- Post-check failures raise `CONSTRAINT_VIOLATION`; no silent relaxation or
  warning-only return path is allowed.

### Engine tests and focused backend tests

Relevant focused tests found:

- `backend/tests/test_builder_regime_two_level.py`
- `backend/tests/test_builder_regime_cvar.py`
- `backend/tests/test_builder_regime_aware.py`
- `backend/tests/test_builder_regime_aware_schema.py`
- `backend/tests/test_effective_policy.py`
- `backend/tests/test_gate_overlay.py`
- `backend/tests/test_quadrant_policy.py`
- `backend/tests/test_optimizer_engine.py`
- `backend/tests/test_optimizer_momentum_view.py`
- `backend/tests/test_optimizer_sleeves.py`

## Extraction Boundaries

First phase must extract only shared quant logic and executable contracts:

- Move/copy pure A3 formulas into `investintell_quant_core` by strangler.
- Keep `calibration_harness.py` command compatibility and I/O wrappers.
- Make QC bridge and notebooks import the same quant-core implementation.
- Do not move backend Plan C in this phase.
- Do not make backend import quant-core in this phase.
- Do not alter `quadrant_macro`, `quadrant_market`, or
  `regime_quadrant_snapshot` runtime semantics.

Forbidden in this phase:

- Any A3/A4/A5 activation or parameter freeze.
- Any formula, threshold, weight, transform, metric, Pareto, or hash-policy
  change except to preserve and relocate behavior.
- Any frontend change.
- Any production write.

