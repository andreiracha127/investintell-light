# ADR: Quant Engine Isolation

Status: accepted for implementation

Date: 2026-06-25

## Context

The current A3/A4 calibration lane lives in the datalake worker repository, with
the canonical behavior concentrated in `src/calibration_harness.py` and the QC
bridge in `qc_a3_core.py`. The backend branch contains the regime-aware Plan C
allocator, but that allocator remains a backend capability in this phase.

Governance state to preserve:

- A3 = `open_macro_v03`
- A4 = `harness_ready_provisional_A3`
- A5 = `blocked`
- `freeze_ready=false`
- `runtime_activation=false`

This phase is behavior-preserving extraction only. It is not calibration, model
selection, runtime activation, or a backend allocator move.

## Decision

Create an executable deterministic boundary using package plus container inside
the existing workers repository:

- `quant-core`: shared Python package containing pure quantitative logic and
  contracts.
- `quant-engine`: batch CLI runner in a dedicated container.
- Datalake workers: acquisition, PIT, DB/CAGG, ALFRED, and bundle
  materialization.
- Backend/API: authentication, IPS, requests, orchestration, and result reads.
- Notebooks/QC: independent clients and validators, never runtime canonical.

The engine runs offline over immutable bundles. The engine must not consult:

- a database;
- FRED or ALFRED;
- Tiingo;
- QuantConnect History;
- HTTP APIs;
- `regime_quadrant_snapshot`;
- implicit current wall clock for formulas;
- files outside paths declared in the job.

The first implementation is batch/CLI, not a permanent HTTP microservice.

## Consequences

- Notebooks are not runtime canonical.
- Calibration does not execute in the web/backend process.
- The immutable bundle is the only engine input.
- The engine is offline by contract.
- The engine image is identified by digest.
- `quant-core` becomes the shared implementation for harness and QC.
- QC remains a validator/backtester, not the canonical runtime.
- The backend does not import `quant-core` in this phase.
- The Plan C allocator is not moved in this phase.
- Plan C extraction is a separate milestone before A4 calibration resumes.
- No third repository is created in this phase.
- The package + container boundary allows a later repository split without
  changing contracts.

## Interface Direction

Workers own canonical JSON Schemas v1 for:

- `QuantEngineJobRequest`
- `QuantEngineJobResult`
- `EngineManifest`

Backend consumes generated/versioned contract models from those schemas and
records the canonical schema SHA-256. Backend must not maintain divergent manual
definitions and must not invoke the container yet.

## Determinism Requirements

- Parent hashes are validated before calculation.
- Runtime and counterfactual roles are explicit; counterfactual cannot feed
  runtime.
- Inputs are not repaired or renormalized silently.
- Output writes go to a temporary directory and finish by atomic rename.
- Resume is allowed only for complete artifacts with valid hashes.
- `run_fingerprint` is deterministic.
- `execution_id` is unique per physical execution.
- Results are sorted by config hash before consolidation.
- Formal offline mode has zero external access.
- Numerical contract path uses explicit float64 and one numerical thread per
  process.

## Non-Goals

- No A3/A4/A5 activation.
- No parameter freeze.
- No new center, half-width, gamma, beta-cap, gate, CVaR, or MaxDD selection.
- No formula, threshold, transform, metric, Pareto, or hash-policy change.
- No frontend change.
- No production write.
- No merge to main.

## Follow-Up Milestone

After quant-engine parity, extract pure Plan C allocator functions into
`quant-core` in a separate milestone. That milestone must preserve backend
request/response wrappers and prove parity for `x`, `y = M_t x`, constraints,
and structured errors before any A4 calibration resumes.

