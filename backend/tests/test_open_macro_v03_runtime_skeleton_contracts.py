from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from app.contracts import open_macro_v03_runtime_skeleton as runtime_skeleton
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = runtime_skeleton.contract_dir()

_SCHEMA_BY_PREFIX = {
    "runtime-job-envelope": "runtime_job_envelope.schema.json",
    "runtime-result": "runtime_result_manifest.schema.json",
}


def _fixture(kind: str, name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_ROOT / "fixtures" / kind / name).read_text(encoding="utf-8"))


def _valid_envelope() -> dict[str, Any]:
    return _fixture("valid", "runtime-job-envelope.inert.json")


def _valid_result() -> dict[str, Any]:
    return _fixture("valid", "runtime-result.not-executed.json")


def _schema_for(fixture: Path) -> dict[str, Any]:
    for prefix, schema_name in _SCHEMA_BY_PREFIX.items():
        if fixture.name.startswith(prefix):
            return runtime_skeleton.load_schema(schema_name)
    raise AssertionError(f"no schema mapped for fixture {fixture.name}")


def test_runtime_skeleton_schema_hashes_match_source_and_constants() -> None:
    assert runtime_skeleton.verify_schema_hashes() == runtime_skeleton.SCHEMA_SHA256

    source = runtime_skeleton.verify_source_metadata()
    assert source["source_pr"] == 9
    assert source["source_merged_pr_head"] == "70c8ce37cc59354c5cbdf6dfbcaa01190d443952"
    assert source["source_merge_commit"] == "87e69a8cfb7aa646d1d0c7c9d7610ce914514cc7"


def test_runtime_skeleton_source_metadata_preserves_inert_governance() -> None:
    source = runtime_skeleton.verify_source_metadata()
    governance = source["governance"]

    assert governance["A5"] == "blocked"
    assert governance["runtime_activation"] is False
    assert governance["freeze_ready"] is False
    assert governance["official_result"] is False
    assert governance["feature_flag_name"] == "open_macro_v03_runtime_activation"
    assert governance["feature_flag_default"] is False
    assert governance["backend_runtime_execution"] == "none"
    assert governance["db_writes"] == "none"
    assert governance["allocator_publish"] == "none"
    assert governance["production_endpoint_activation"] == "none"


def test_runtime_skeleton_valid_fixtures_pass_schema_and_offline_validator() -> None:
    fixtures = sorted((CONTRACT_ROOT / "fixtures" / "valid").glob("*.json"))
    assert fixtures

    for fixture in fixtures:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        jsonschema.validate(payload, _schema_for(fixture))
        if fixture.name.startswith("runtime-job-envelope"):
            runtime_skeleton.validate_job_envelope(payload)
        else:
            runtime_skeleton.validate_result_manifest(payload)


def test_runtime_skeleton_invalid_fixtures_fail_schema_or_offline_validator() -> None:
    fixtures = sorted((CONTRACT_ROOT / "fixtures" / "invalid").glob("*.json"))
    assert fixtures

    for fixture in fixtures:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        schema_failed = False
        try:
            jsonschema.validate(payload, _schema_for(fixture))
        except jsonschema.ValidationError:
            schema_failed = True

        validator_failed = False
        try:
            if fixture.name.startswith("runtime-job-envelope"):
                runtime_skeleton.validate_job_envelope(payload)
            else:
                runtime_skeleton.validate_result_manifest(payload)
        except runtime_skeleton.RuntimeSkeletonContractError:
            validator_failed = True

        assert schema_failed or validator_failed, fixture.name


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("runtime_activation", True),
        ("allow_db_write", True),
        ("allow_allocator_publish", True),
        ("official_result", True),
        ("production_endpoint_activation", "public"),
        ("engine_commit", "0" * 40),
        ("engine_image_digest", "sha256:" + "0" * 64),
        ("input_pack_sha256", "0" * 64),
        ("calibration_config_sha256", "0" * 64),
        ("contract_bundle_sha256", "0" * 64),
    ],
)
def test_runtime_skeleton_envelope_rejects_activation_and_identity_drift(
    field: str, bad: object
) -> None:
    envelope = _valid_envelope()
    runtime_skeleton.validate_job_envelope(envelope)

    broken = deepcopy(envelope)
    broken[field] = bad
    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_job_envelope(broken)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("runtime_activation", True),
        ("allow_db_write", True),
        ("allow_allocator_publish", True),
        ("official_result", True),
        ("production_endpoint_activation", "public"),
        ("allocator_publish", True),
        ("db_write_official", True),
        ("docker_execution_from_backend", True),
        ("feature_flag_default", True),
    ],
)
def test_runtime_skeleton_result_rejects_side_effect_pins(field: str, bad: object) -> None:
    result = _valid_result()
    runtime_skeleton.validate_result_manifest(result)

    broken = deepcopy(result)
    broken[field] = bad
    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(broken)


def test_runtime_skeleton_result_rejects_side_effect_evidence_without_rejection() -> None:
    result = _valid_result()
    result["side_effect_attempt_count"] = 1
    result["side_effect_attempt_evidence_sha256"] = "a" * 64

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(result)


def test_runtime_skeleton_result_requires_side_effect_evidence_on_allocator_attempt() -> None:
    result = _valid_result()
    result.update({"status": "rejected", "failure_class": "allocator_publish_attempt"})

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(result)

    result["side_effect_attempt_count"] = 1
    result["side_effect_attempt_evidence_sha256"] = "a" * 64
    runtime_skeleton.validate_result_manifest(result)


def test_runtime_skeleton_result_rejects_identity_drift_without_actual_drift() -> None:
    drift = _fixture("valid", "runtime-result.identity-drift.json")
    drift.update(
        {
            "observed_input_pack_id": drift["input_pack_id"],
            "observed_input_pack_sha256": drift["input_pack_sha256"],
            "observed_calibration_id": drift["calibration_id"],
            "observed_calibration_config_sha256": drift["calibration_config_sha256"],
            "observed_engine_commit": drift["engine_commit"],
            "observed_engine_image_digest": drift["engine_image_digest"],
        }
    )

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(drift)


def test_runtime_skeleton_validator_is_offline_and_imports_no_runtime_paths() -> None:
    validator_source = (
        ROOT / "app" / "contracts" / "open_macro_v03_runtime_skeleton.py"
    ).read_text(encoding="utf-8")
    script_source = (ROOT / "scripts" / "verify_open_macro_v03_runtime_skeleton.py").read_text(
        encoding="utf-8"
    )
    forbidden_roots = {
        "asyncio",
        "subprocess",
        "docker",
        "sqlalchemy",
        "fastapi",
        "app.core.db",
        "app.services.portfolio_builder",
        "app.services.builder_save",
        "app.services.jobs",
        "app.optimizer.engine",
        "app.rebalance.evaluator",
    }

    for source in (validator_source, script_source):
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports |= {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imports.isdisjoint(forbidden_roots)


def test_runtime_skeleton_no_production_endpoint_is_registered() -> None:
    app = create_app()
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert not any("open_macro_v03" in path for path in route_paths)
    assert not any("runtime_skeleton" in path for path in route_paths)
    assert "/builder/optimize" in route_paths


def test_runtime_skeleton_no_official_db_write_contract_is_exposed() -> None:
    result = _valid_result()
    assert result["db_write_official"] is False
    assert result["official_result"] is False
    assert result["allocator_publish"] is False
    assert result["production_endpoint_activation"] == "none"
    runtime_skeleton.validate_result_manifest(result)
