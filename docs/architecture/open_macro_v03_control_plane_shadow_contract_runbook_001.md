# open_macro_v03 Control-Plane Shadow Contract Runbook 001

This runbook documents the inert backend boundary for the merged workers runtime
skeleton `open_macro_v03_runtime_skeleton_001`. It is not an A5 runbook and does
not authorize runtime activation.

## Current State

- A3: `open_macro_v03`.
- A4: `control_plane_shadow_contract_prepared` after this PR only.
- A5: `blocked`.
- `runtime_activation=false`.
- `freeze_ready=false`.
- `official_result=false`.
- `feature_flag_default=false`.
- Backend runtime execution: `none`.
- Allocator impact: `none`.
- Production impact: `none`.

## Allowed Backend Behavior

- Load mirrored runtime skeleton schemas from
  `backend/contracts/runtime/open_macro_v03_runtime_skeleton_001/`.
- Verify schema hashes and `SOURCE.json` governance metadata offline.
- Validate inert job envelopes and result manifests with
  `app.contracts.open_macro_v03_runtime_skeleton`.
- Run the standalone offline verifier:
  `uv run python scripts/verify_open_macro_v03_runtime_skeleton.py`.
- Reject any envelope or manifest that changes pinned input, calibration,
  contract, engine, feature flag, DB-write, allocator, endpoint, or activation
  fields.

## Forbidden Backend Behavior

- Do not create a production endpoint for runtime skeleton execution.
- Do not call Docker or spawn a subprocess to run the engine.
- Do not import or call builder/allocator runtime modules from the validator.
- Do not enqueue a backend job or connect to a worker executor.
- Do not write official results to the DB.
- Do not publish to the allocator.
- Do not alter formulas, input packs, calibration packs, or quant-engine contract v1.
- Do not mark A5 unblocked or `freeze_ready=true`.

## Validation Procedure

Run from `backend/`:

```powershell
uv run python scripts/verify_open_macro_v03_runtime_skeleton.py
uv run pytest tests/test_open_macro_v03_runtime_skeleton_contracts.py -q
uv run pytest tests/test_quant_engine_contracts.py -q
uv run ruff check .
uv run mypy app
uv run pytest -q
```

Run from the repository root:

```powershell
git diff --check
```

OpenAPI/type generation is intentionally not part of this runbook because the
inert contract branch must not add or activate API routes.

## Next Phase Boundary

Only after this inert backend PR is merged, a separate future branch may plan the
external executor handshake:

`feat/open-macro-v03-external-executor-handshake-001`

That future phase still must remain non-productive until separately approved.
