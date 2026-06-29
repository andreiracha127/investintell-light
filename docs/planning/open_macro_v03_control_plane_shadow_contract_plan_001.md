# open_macro_v03 control-plane shadow contract plan 001

## Decision

Prepare an inert backend/control-plane contract boundary for the merged
`open_macro_v03_runtime_skeleton_001` workers artifact. This branch must only
recognize and validate shadow/runtime envelopes and manifests offline. It must
not execute the engine, call Docker, start a job, write official results, publish
to the allocator, create a production endpoint, or advance A5.

## Dependency Baseline

```json
{
  "runtime_skeleton_id": "open_macro_v03_runtime_skeleton_001",
  "runtime_skeleton_pr": "andreiracha127/investintell-datalake-workers#9",
  "runtime_skeleton_original_pr_head": "70ca3a7a3a995a20f09013a5f62a0d8acba6ec0a",
  "runtime_skeleton_merged_pr_head": "70c8ce37cc59354c5cbdf6dfbcaa01190d443952",
  "runtime_skeleton_001_merge_commit": "87e69a8cfb7aa646d1d0c7c9d7610ce914514cc7",
  "A5": "blocked",
  "runtime_activation": false,
  "freeze_ready": false,
  "official_result": false,
  "backend_runtime_wiring": "none",
  "db_writes": "none",
  "allocator_publish": "none",
  "production_endpoint_activation": "none",
  "validated": true
}
```

Post-merge workers validation on `main`:

- `python -m pytest tests/test_runtime_integration_skeleton.py -q`: 56 passed.
- Railway-equivalent pytest gate: 314 passed.
- `python scripts/contract_bundle.py verify`: ok.
- `docker/railway-ci/verify_input_pack.py`: ok with CI `PYTHONPATH`.
- `docker/railway-ci/verify_calibration_artifacts.py`: ok with CI `PYTHONPATH`.
- `compileall` gate: pass.
- `git diff --check`: pass.
- Remote runner on PR head push: `REMOTE_CI_STATUS=PASS` for
  `70c8ce37cc59354c5cbdf6dfbcaa01190d443952`.

## Files Read

Read-only discovery covered:

- `AGENTS.md`: InsForge guidance, credentials policy, insert/auth/storage patterns.
- `CLAUDE.md`: generic Claude prompt; no project-specific engineering constraints
  beyond what is superseded by local AGENTS/Kilo instructions.
- `backend/pyproject.toml`: Python 3.12, FastAPI backend, pytest/ruff/mypy/jsonschema gates.
- `package.json`: root package manager pin `pnpm@10.28.1`.
- `.github/workflows/ci.yml`: backend `uv sync`, `ruff`, `mypy`, `pytest`; frontend
  lint/typecheck/build; OpenAPI typegen diff gate.
- `docs/architecture/allocator-engine-extraction-next.md`: current backend boundary,
  explicit non-goals, and no quant-engine runtime endpoint/container invocation.
- `backend/app/contracts/quant_engine_v1.py`: existing stdlib-only mirrored contract
  verifier and bundle hash policy.
- `backend/scripts/verify_quant_engine_contract.py`: standalone offline verifier.
- `backend/tests/test_quant_engine_contracts.py`: existing contract mirror, source
  metadata, fixture validation, and drift guard tests.
- `backend/contracts/quant-engine/v1/SOURCE.json`: current source/governance metadata.
- `backend/contracts/quant-engine/v1/manifest.json`: current bundle digest and file list.
- `backend/app/core/config.py`: feature flags default false pattern.
- `backend/app/api/routes/builder.py`: builder optimize/save route entrypoints.
- `backend/app/main.py`: API router registration and app creation entrypoint.

Read-only subagent discovery also mapped:

- `backend/app/services/portfolio_builder.py`.
- `backend/app/services/builder_save.py`.
- `backend/app/services/portfolio_crud.py`.
- `backend/app/rebalance/evaluator.py`.
- `backend/app/optimizer/*`.
- `backend/app/services/jobs.py`.
- `backend/railway*.toml`, `backend/Dockerfile`, `docker-compose.yml`.
- `backend/app/schemas/*`, `backend/alembic/versions/*`, `backend/db/ddl/*`,
  root `migrations/*`.

## Real Backend Entrypoints

- FastAPI app factory: `backend/app/main.py::create_app`.
- Runtime builder route: `backend/app/api/routes/builder.py::optimize`, registered
  at `POST /builder/optimize`, calls `portfolio_builder.run_optimize(...)`.
- Builder persistence route: `backend/app/api/routes/builder.py::save`, registered
  at `POST /builder/save`, calls `builder_save.run_save(...)`.
- Existing quant-engine mirror verifier: `backend/app/contracts/quant_engine_v1.py::verify_bundle`.
- Standalone verifier CLI: `backend/scripts/verify_quant_engine_contract.py::main`.
- Feature flags source: `backend/app/core/config.py::Settings`.

## Paths That Will Not Be Touched

This branch must not touch runtime behavior or productive surfaces:

- `backend/app/services/portfolio_builder.py`.
- `backend/app/optimizer/`.
- `backend/app/rebalance/evaluator.py`.
- `backend/app/api/routes/builder.py`.
- `backend/app/api/routes/rebalance.py`.
- `backend/app/api/routes/portfolios.py`.
- `backend/app/main.py`.
- `backend/app/services/builder_save.py`.
- `backend/app/services/portfolio_crud.py`.
- `backend/app/services/portfolio_constraints.py`.
- `backend/app/services/portfolio_drift.py`.
- `backend/app/services/portfolio_ledger.py`.
- `backend/app/services/jobs.py`.
- `backend/app/ingestion/`.
- `backend/app/sync/`.
- `backend/app/jobs/workers/`.
- `backend/alembic/versions/`.
- `backend/db/ddl/`.
- `migrations/`.
- `backend/openapi.json`.
- `frontend/`.
- `backend/railway.toml`, `backend/railway.api.toml`,
  `backend/railway.proxy-etf.toml`, `backend/Dockerfile`, `docker-compose.yml`.

## Schemas To Mirror Or Validate

Add an inert runtime skeleton contract namespace separate from existing
`quant-engine/v1`:

- `backend/contracts/runtime/open_macro_v03_runtime_skeleton_001/runtime_job_envelope.schema.json`.
- `backend/contracts/runtime/open_macro_v03_runtime_skeleton_001/runtime_result_manifest.schema.json`.
- `backend/contracts/runtime/open_macro_v03_runtime_skeleton_001/runtime_skeleton_manifest.schema.json`, if the backend needs to validate the artifact index.
- `backend/contracts/runtime/open_macro_v03_runtime_skeleton_001/SOURCE.json` or equivalent source metadata recording workers PR #9, merged head, merge commit, and governance pins.
- Positive and negative fixtures under the runtime skeleton contract directory.

Validation must pin or reject:

- `runtime_activation=false`.
- `allow_db_write=false`.
- `allow_allocator_publish=false`.
- `official_result=false`.
- `production_endpoint_activation=none`.
- `docker_execution_from_backend=false`.
- expected `input_pack_id`, `input_pack_sha256`, `calibration_id`,
  `calibration_config_sha256`, `contract_bundle_sha256`, `contract_version`,
  `engine_commit`, and `engine_image_digest`.
- `formula_changes=input_pack_changes=calibration_pack_changes=contract_v1_changes=none`.
- side-effect rejection evidence can only appear on rejected manifests.
- drift rejection evidence must include observed values and demonstrate at least one
  observed value differs from the pinned identity.

## Implementation Pieces

- Add a stdlib-only backend module, likely `backend/app/contracts/open_macro_v03_runtime_skeleton.py`, that loads schemas/fixtures, verifies source metadata, and exposes an offline validation function.
- Extend `backend/scripts/verify_quant_engine_contract.py` or add a separate verifier script only if it stays offline and imports no FastAPI app, DB, Docker, subprocess, builder, allocator, or job runner modules.
- Add contract fixtures for valid inert envelope/result and invalid side effects.
- Add tests in a focused file such as `backend/tests/test_open_macro_v03_runtime_skeleton_contracts.py`.
- Add a runbook under docs, such as `docs/architecture/open_macro_v03_control_plane_shadow_contract_runbook_001.md`, documenting the backend-to-external-executor boundary and prohibitions.

## Tests To Create

Add tests for:

- valid inert envelope passes.
- `runtime_activation=true` fails.
- `allow_db_write=true` fails.
- `allow_allocator_publish=true` fails.
- `official_result=true` fails.
- `production_endpoint_activation != none` fails.
- `engine_commit` drift fails.
- `engine_image_digest` drift fails.
- `input_pack_sha256` drift fails.
- `calibration_config_sha256` drift fails.
- `contract_bundle_sha256` drift fails.
- validator is offline and does not import/call Docker, subprocess, backend jobs, DB sessions, builder, or allocator runtime.
- feature flag default remains false.
- no production endpoint is registered.
- no official DB write path is introduced.

## Gates

Run from `backend/` unless noted otherwise:

- `uv run pytest tests/test_quant_engine_contracts.py -q`.
- `uv run pytest tests/test_open_macro_v03_runtime_skeleton_contracts.py -q`.
- `uv run python scripts/verify_quant_engine_contract.py`.
- `uv run ruff check .`.
- `uv run mypy app`.
- `uv run pytest -q`.
- From repo root: `git diff --check`.

OpenAPI/typegen is intentionally not required because this branch must not add API
routes or production endpoints.

## Risks

- Accidentally updating the older `quant-engine/v1` bundle digest would imply a
  contract v1 resync; keep runtime skeleton contracts separate unless an explicit
  bundle update is approved.
- Adding a FastAPI route would create an activation surface; keep validation as
  offline module/tests/scripts only.
- Importing builder/allocator/job modules from the validator could create runtime
  coupling; use stdlib/jsonschema-only validation.
- Adding migrations or DB models would imply a persistence path; do not add DB schema.
- Naming the work as A5/shadow activation could overstate state; keep A5 blocked and
  runtime inactive throughout.

## Prohibited Scope

- No production endpoint.
- No Docker/container execution from backend.
- No subprocess invocation for engine execution.
- No official DB result write.
- No allocator publish.
- No builder/allocator runtime change.
- No feature flag activation.
- No formula change.
- No input pack change.
- No calibration pack change.
- No contract v1 change without a new approved bundle.
- No A5 unblock.
- No `freeze_ready=true`.

## Explicit Engine Execution Decision

The backend will not execute `open_macro_v03`, will not call Docker, will not start
an internal job, and will not connect to a worker executor in this branch. The only
allowed behavior is offline recognition and validation of inert shadow/runtime
contract documents produced by a later external executor workflow.
