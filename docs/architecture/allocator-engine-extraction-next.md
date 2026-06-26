# Allocator Engine Extraction Next

Date: 2026-06-26

This document records the next backend milestone after the quant-engine
isolation work. It is intentionally a plan only: no runtime endpoint, no
container invocation, no production write, and no change to the current
`regime_aware` builder behavior is authorized here.

## Current Backend Boundary

The Plan C allocator remains implemented in `backend/app/services/portfolio_builder.py`.
The current compiled problem already carries the important v1 semantics:

- `x` is the category decision vector.
- `S` maps categories to structural sleeves.
- `M` maps categories to the final instrument book.
- The published book is `y = Mx`.
- Final-book floors and instrument caps are compiled over `M`.
- Aggregate policy constraints include `risk_assets_cap`, `defensive_floor`,
  portfolio beta cap, and daily-loss CVaR.
- Preflight runs before the primary solve and the fallback min-CVaR solve.
- Post-verification fails loud on constraint violation.

The backend must not import `investintell_quant_core` in this phase. It consumes
only mirrored v1 JSON Schemas from the workers branch:

- `backend/contracts/quant-engine/v1/job-request.schema.json`
- `backend/contracts/quant-engine/v1/job-result.schema.json`
- `backend/contracts/quant-engine/v1/engine-manifest.schema.json`

The mirrored schema SHA-256 values are registered in
`backend/app/contracts/quant_engine_v1.py` and checked by
`backend/tests/test_quant_engine_contracts.py`.

## Next Milestone

Before any A4 calibration resume, extract pure allocator-engine functions behind
the existing backend behavior:

1. Define typed in-memory contracts for universe, policy, compiled problem,
   solve result, and verification result.
2. Extract pure construction of `S`, `M`, category bounds, final-book floors,
   instrument caps, sleeve bands, aggregate exposures, beta cap, CVaR cap, and
   overlap constraints.
3. Snapshot-test compiled `S` and `M` matrices for representative universes,
   including complete-macro fills and strict missing-sleeve failures.
4. Extract preflight as a pure function that returns structured causes:
   `POLICY_INFEASIBLE`, `MISSING_REQUIRED_SLEEVES`, `SOLVER_FAILED`, or
   `CONSTRAINT_VIOLATION`.
5. Extract post-verification as a pure function over `(problem, x, y)`.
6. Keep the current solver adapter in the backend until parity tests prove the
   extracted engine produces identical books and structured errors.

## Acceptance Evidence For That Future Milestone

The future allocator extraction is complete only when:

- current `regime_aware` tests still pass;
- new snapshot tests prove identical `S`, `M`, constraints, and final `y`;
- fallback objective changes only the objective, not the constraints;
- fail-loud behavior remains unchanged;
- no backend runtime path calls the quant-engine container unless a later A5
  activation explicitly authorizes it.

## Non-goals

- No A3/A4/A5 activation.
- No endpoint for quant-engine execution.
- No builder behavior change.
- No frontend change.
- No production DB write.
- No merge to `main`.

