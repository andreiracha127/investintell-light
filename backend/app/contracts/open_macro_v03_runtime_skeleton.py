"""Offline validator for the open_macro_v03 runtime skeleton contract.

This module is intentionally stdlib-only. It validates inert runtime skeleton
envelopes and result manifests without importing FastAPI, DB sessions, job
runners, Docker/subprocess helpers, or allocator/builder runtime code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, Mapping, cast

SOURCE_NAME: Final = "SOURCE.json"
RUNTIME_SKELETON_ID: Final = "open_macro_v03_runtime_skeleton_001"
ARTIFACT_URI_PREFIX: Final = f"artifact://runtime/{RUNTIME_SKELETON_ID}/"

SCHEMA_SHA256: Final[dict[str, str]] = {
    "runtime_job_envelope.schema.json": (
        "1bb904ff44f8afaf08f51bcf15195547054dba9c1a9ceaf343d8ff902d96d110"
    ),
    "runtime_result_manifest.schema.json": (
        "51eeabfdece3936f12826f7dc3feae14aa585149954a71e4f6b6d598bafe9cfa"
    ),
}

EXPECTED_SOURCE: Final[dict[str, object]] = {
    "source_repo": "andreiracha127/investintell-datalake-workers",
    "source_pr": 9,
    "source_merged_pr_head": "70c8ce37cc59354c5cbdf6dfbcaa01190d443952",
    "source_merge_commit": "87e69a8cfb7aa646d1d0c7c9d7610ce914514cc7",
}

PINNED_IDENTITY: Final[dict[str, object]] = {
    "input_pack_id": "open_macro_v03_certified_input_pack_001",
    "input_pack_sha256": "ae8b76e5959cb5e9c10ced7b33fc13a01a3484865deeead56c5b83b1c440e08f",
    "calibration_id": "open_macro_v03_calibration_001",
    "calibration_config_sha256": "869e392bd49c8f7e0bf60890d1658ef3cf0483655af3a1c9f105b99cd29c268c",
    "contract_bundle_sha256": "4ff92bba49ccd178348e4646bd4ba0afe45c7d6036a72f00c52bc02c29ea683a",
    "contract_version": "1.0.0",
    "engine_commit": "ee39adbe6cb6541d4fdfa78f1428478ffffaf638",
    "engine_image_digest": "sha256:cdcf05768ad6e44543567cd0b5106ecc2b88a2f49ef5080c25c52a601a91598b",
}

COMMON_PINS: Final[dict[str, object]] = {
    "schema_version": 1,
    "runtime_skeleton_id": RUNTIME_SKELETON_ID,
    "strategy": "open_macro_v03",
    "a5_preflight_id": "open_macro_v03_a5_preflight_001",
    "runtime_activation": False,
    "A5": "blocked",
    "freeze_ready": False,
    "official_result": False,
    "allow_db_write": False,
    "allow_allocator_publish": False,
    "allocator_publish": False,
    "db_write_official": False,
    "production_endpoint_activation": "none",
    "feature_flag_name": "open_macro_v03_runtime_activation",
    "feature_flag_default": False,
    "docker_execution_from_backend": False,
    "formula_changes": "none",
    "input_pack_changes": "none",
    "calibration_pack_changes": "none",
    "contract_v1_changes": "none",
}

ENVELOPE_PINS: Final[dict[str, object]] = {
    **COMMON_PINS,
    **PINNED_IDENTITY,
    "mode": "inert_skeleton",
    "execution_policy": "artifact_only_external_orchestrator_no_productive_backend_docker",
}

RESULT_PINS: Final[dict[str, object]] = {
    **COMMON_PINS,
    "result_mode": "artifact_only_inert_manifest",
}

SIDE_EFFECT_FAILURE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "runtime_activation_attempt",
        "official_db_write_attempt",
        "allocator_publish_attempt",
        "production_endpoint_activation_attempt",
        "docker_execution_from_backend_attempt",
    }
)
DRIFT_FAILURE_CLASSES: Final[frozenset[str]] = frozenset({"identity_drift", "contract_drift"})
FAILURE_CLASSES: Final[frozenset[str]] = SIDE_EFFECT_FAILURE_CLASSES | DRIFT_FAILURE_CLASSES

ENVELOPE_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    set(ENVELOPE_PINS) | {"request_id", "correlation_id", "execution_id", "output_artifact_uri"}
)
RESULT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    set(RESULT_PINS)
    | set(PINNED_IDENTITY)
    | {
        "request_id",
        "correlation_id",
        "execution_id",
        "artifact_uri",
        "status",
        "failure_class",
        "side_effect_attempt_count",
        "side_effect_attempt_evidence_sha256",
        "observed_input_pack_id",
        "observed_input_pack_sha256",
        "observed_calibration_id",
        "observed_calibration_config_sha256",
        "observed_contract_bundle_sha256",
        "observed_contract_version",
        "observed_engine_commit",
        "observed_engine_image_digest",
    }
)


class RuntimeSkeletonContractError(ValueError):
    """Raised when an inert runtime skeleton contract payload is invalid."""


def contract_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "contracts" / "runtime" / RUNTIME_SKELETON_ID


def schema_path(name: str) -> Path:
    if name not in SCHEMA_SHA256:
        raise KeyError(f"unknown runtime skeleton schema: {name}")
    return contract_dir() / name


def load_schema(name: str) -> dict[str, Any]:
    return _load_json_object(schema_path(name))


def load_source_metadata() -> dict[str, Any]:
    return _load_json_object(contract_dir() / SOURCE_NAME)


def compute_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema_sha256(name: str) -> str:
    return compute_file_sha256(schema_path(name))


def verify_schema_hashes() -> dict[str, str]:
    actual = {name: schema_sha256(name) for name in SCHEMA_SHA256}
    mismatches = {name: value for name, value in actual.items() if value != SCHEMA_SHA256[name]}
    if mismatches:
        raise RuntimeSkeletonContractError(f"runtime skeleton schema hash mismatch: {mismatches}")
    return actual


def verify_source_metadata() -> dict[str, Any]:
    source = load_source_metadata()
    for key, expected in EXPECTED_SOURCE.items():
        _require_equal(source, key, expected)

    schema_hashes = source.get("schema_sha256")
    if schema_hashes != SCHEMA_SHA256:
        raise RuntimeSkeletonContractError("SOURCE.json schema_sha256 does not match mirror constants")

    governance = source.get("governance")
    if not isinstance(governance, Mapping):
        raise RuntimeSkeletonContractError("SOURCE.json governance must be an object")
    for key, expected in {
        "A5": "blocked",
        "runtime_activation": False,
        "freeze_ready": False,
        "official_result": False,
        "feature_flag_default": False,
        "backend_runtime_execution": "none",
        "db_writes": "none",
        "allocator_publish": "none",
        "production_endpoint_activation": "none",
        "formula_changes": "none",
        "input_pack_changes": "none",
        "calibration_pack_changes": "none",
        "contract_v1_changes": "none",
    }.items():
        _require_equal(governance, key, expected)
    return source


def validate_job_envelope(payload: Mapping[str, Any]) -> None:
    _reject_unknown(payload, ENVELOPE_ALLOWED_KEYS)
    _require_pins(payload, ENVELOPE_PINS)
    _require_string(payload, "request_id", min_length=12)
    _require_string(payload, "correlation_id", min_length=12)
    _require_string(payload, "execution_id", min_length=12)
    _require_artifact_uri(payload, "output_artifact_uri")


def validate_result_manifest(payload: Mapping[str, Any]) -> None:
    _reject_unknown(payload, RESULT_ALLOWED_KEYS)
    _require_pins(payload, RESULT_PINS)
    _require_string(payload, "request_id", min_length=12)
    _require_string(payload, "correlation_id", min_length=12)
    _require_string(payload, "execution_id", min_length=12)
    _require_artifact_uri(payload, "artifact_uri")

    status = payload.get("status")
    if status not in {"not_executed", "rejected"}:
        raise RuntimeSkeletonContractError("status must be not_executed or rejected")

    failure_class = payload.get("failure_class")
    if status == "not_executed":
        if failure_class is not None:
            raise RuntimeSkeletonContractError("not_executed result cannot carry failure_class")
        if "side_effect_attempt_count" in payload or "side_effect_attempt_evidence_sha256" in payload:
            raise RuntimeSkeletonContractError("not_executed result cannot carry side-effect evidence")
        return

    if failure_class not in FAILURE_CLASSES:
        raise RuntimeSkeletonContractError("rejected result requires a recognized failure_class")

    if failure_class in SIDE_EFFECT_FAILURE_CLASSES:
        _require_positive_int(payload, "side_effect_attempt_count")
        _require_sha256_hex(payload, "side_effect_attempt_evidence_sha256")
    elif failure_class == "identity_drift":
        _validate_identity_drift(payload)
    elif failure_class == "contract_drift":
        _validate_contract_drift(payload)


def _validate_identity_drift(payload: Mapping[str, Any]) -> None:
    expected = {
        key: PINNED_IDENTITY[key]
        for key in (
            "input_pack_id",
            "input_pack_sha256",
            "calibration_id",
            "calibration_config_sha256",
            "engine_commit",
            "engine_image_digest",
        )
    }
    _require_pins(payload, expected)
    observed = {
        "observed_input_pack_id": expected["input_pack_id"],
        "observed_input_pack_sha256": expected["input_pack_sha256"],
        "observed_calibration_id": expected["calibration_id"],
        "observed_calibration_config_sha256": expected["calibration_config_sha256"],
        "observed_engine_commit": expected["engine_commit"],
        "observed_engine_image_digest": expected["engine_image_digest"],
    }
    _require_observed_drift(payload, observed)


def _validate_contract_drift(payload: Mapping[str, Any]) -> None:
    expected = {
        key: PINNED_IDENTITY[key]
        for key in ("contract_bundle_sha256", "contract_version", "engine_commit", "engine_image_digest")
    }
    _require_pins(payload, expected)
    observed = {
        "observed_contract_bundle_sha256": expected["contract_bundle_sha256"],
        "observed_contract_version": expected["contract_version"],
        "observed_engine_commit": expected["engine_commit"],
        "observed_engine_image_digest": expected["engine_image_digest"],
    }
    _require_observed_drift(payload, observed)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeSkeletonContractError(f"{path} did not contain a JSON object")
    return cast(dict[str, Any], payload)


def _reject_unknown(payload: Mapping[str, Any], allowed: frozenset[str]) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        raise RuntimeSkeletonContractError(f"unexpected runtime skeleton fields: {extra}")


def _require_pins(payload: Mapping[str, Any], pins: Mapping[str, object]) -> None:
    for key, expected in pins.items():
        _require_equal(payload, key, expected)


def _require_equal(payload: Mapping[str, Any], key: str, expected: object) -> None:
    if key not in payload:
        raise RuntimeSkeletonContractError(f"missing required field: {key}")
    if payload[key] != expected:
        raise RuntimeSkeletonContractError(f"{key} mismatch: expected {expected!r}, got {payload[key]!r}")


def _require_string(payload: Mapping[str, Any], key: str, *, min_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or len(value) < min_length:
        raise RuntimeSkeletonContractError(f"{key} must be a string with length >= {min_length}")
    return value


def _require_artifact_uri(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, min_length=len(ARTIFACT_URI_PREFIX) + 1)
    if not value.startswith(ARTIFACT_URI_PREFIX) or any(ch.isspace() for ch in value):
        raise RuntimeSkeletonContractError(f"{key} must be an inert runtime artifact URI")
    return value


def _require_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeSkeletonContractError(f"{key} must be a positive integer")
    return value


def _require_sha256_hex(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, min_length=64)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeSkeletonContractError(f"{key} must be a lowercase sha256 hex digest")
    return value


def _require_observed_drift(payload: Mapping[str, Any], observed_to_pinned: Mapping[str, object]) -> None:
    drifted = False
    for key, pinned in observed_to_pinned.items():
        if key not in payload:
            raise RuntimeSkeletonContractError(f"missing observed drift field: {key}")
        if payload[key] != pinned:
            drifted = True
    if not drifted:
        raise RuntimeSkeletonContractError("drift rejection must include at least one observed value that differs from pins")
