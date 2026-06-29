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
from scripts import verify_open_macro_v03_runtime_skeleton as verifier_script

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


def _valid_contract_drift_result() -> dict[str, Any]:
    result = _valid_result()
    result.update(
        {
            "status": "rejected",
            "failure_class": "contract_drift",
            "contract_bundle_sha256": runtime_skeleton.PINNED_IDENTITY[
                "contract_bundle_sha256"
            ],
            "contract_version": runtime_skeleton.PINNED_IDENTITY["contract_version"],
            "engine_commit": runtime_skeleton.PINNED_IDENTITY["engine_commit"],
            "engine_image_digest": runtime_skeleton.PINNED_IDENTITY["engine_image_digest"],
            "observed_contract_bundle_sha256": "0" * 64,
            "observed_contract_version": "2.0.0",
            "observed_engine_commit": "1" * 40,
            "observed_engine_image_digest": "sha256:" + "2" * 64,
        }
    )
    return result


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


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("contract_name", "different_contract"),
        ("contract_id", "different_contract_001"),
        ("source_original_pr_head", "0" * 40),
        ("source_merged_pr_head", "1" * 40),
        ("A3", "different_strategy"),
        ("A4", "runtime_active"),
        ("feature_flag_name", "different_flag"),
        ("backend_runtime_wiring", "enabled"),
    ],
)
def test_runtime_skeleton_source_metadata_pins_all_inert_governance(
    monkeypatch: pytest.MonkeyPatch, field: str, bad: object
) -> None:
    source = runtime_skeleton.load_source_metadata()
    if field in source:
        source[field] = bad
    else:
        source["governance"][field] = bad
    monkeypatch.setattr(runtime_skeleton, "load_source_metadata", lambda: source)

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.verify_source_metadata()


def test_runtime_skeleton_standalone_verifier_fails_when_fixtures_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verifier_script.runtime_skeleton, "verify_schema_hashes", lambda: {})
    monkeypatch.setattr(verifier_script.runtime_skeleton, "verify_source_metadata", lambda: {})
    monkeypatch.setattr(verifier_script.runtime_skeleton, "contract_dir", lambda: tmp_path)

    assert verifier_script.main() == 1
    output = capsys.readouterr().out
    assert "FAIL missing valid runtime skeleton fixtures" in output
    assert "FAIL missing invalid runtime skeleton fixtures" in output


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


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("input_pack_id", "open_macro_v03_certified_input_pack_drifted"),
        ("input_pack_sha256", "0" * 64),
        ("calibration_id", "open_macro_v03_calibration_drifted"),
        ("calibration_config_sha256", "0" * 64),
        ("contract_bundle_sha256", "0" * 64),
        ("contract_version", "2.0.0"),
        ("engine_commit", "0" * 40),
        ("engine_image_digest", "sha256:" + "0" * 64),
    ],
)
def test_runtime_skeleton_result_rejects_drifted_optional_identity_pins(
    field: str, bad: object
) -> None:
    result = _valid_result()
    result[field] = bad

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_input_pack_id", "open_macro_v03_certified_input_pack_drifted"),
        ("observed_input_pack_sha256", "0" * 64),
        ("observed_calibration_id", "open_macro_v03_calibration_drifted"),
        ("observed_calibration_config_sha256", "1" * 64),
        ("observed_contract_bundle_sha256", "2" * 64),
        ("observed_contract_version", "2.0.0"),
        ("observed_engine_commit", "3" * 40),
        ("observed_engine_image_digest", "sha256:" + "4" * 64),
    ],
)
def test_runtime_skeleton_not_executed_result_rejects_observed_drift_evidence(
    field: str, value: object
) -> None:
    result = _valid_result()
    result[field] = value

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(result)


def test_runtime_skeleton_schema_rejects_not_executed_observed_drift_evidence() -> None:
    result = _valid_result()
    result["observed_engine_commit"] = "3" * 40

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            result, runtime_skeleton.load_schema("runtime_result_manifest.schema.json")
        )


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


def test_runtime_skeleton_side_effect_rejection_rejects_observed_drift_evidence() -> None:
    result = _valid_result()
    result.update(
        {
            "status": "rejected",
            "failure_class": "allocator_publish_attempt",
            "side_effect_attempt_count": 1,
            "side_effect_attempt_evidence_sha256": "a" * 64,
            "observed_engine_commit": "1" * 40,
        }
    )

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(result)


def test_runtime_skeleton_schema_rejects_observed_drift_on_side_effect_rejection() -> None:
    result = _valid_result()
    result.update(
        {
            "status": "rejected",
            "failure_class": "allocator_publish_attempt",
            "side_effect_attempt_count": 1,
            "side_effect_attempt_evidence_sha256": "a" * 64,
            "observed_engine_commit": "1" * 40,
        }
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            result, runtime_skeleton.load_schema("runtime_result_manifest.schema.json")
        )


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("side_effect_attempt_count", 1),
        ("side_effect_attempt_evidence_sha256", "a" * 64),
        ("observed_contract_bundle_sha256", "0" * 64),
        ("observed_contract_version", "2.0.0"),
    ],
)
def test_runtime_skeleton_identity_drift_rejects_incompatible_evidence(
    field: str, value: object
) -> None:
    drift = _fixture("valid", "runtime-result.identity-drift.json")
    drift[field] = value

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(drift)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            drift, runtime_skeleton.load_schema("runtime_result_manifest.schema.json")
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("observed_input_pack_sha256", "not-a-sha"),
        ("observed_calibration_config_sha256", "A" * 64),
        ("observed_engine_commit", 123),
        ("observed_engine_commit", "0" * 39),
        ("observed_engine_image_digest", "0" * 64),
        ("observed_engine_image_digest", "sha256:" + "G" * 64),
        ("observed_input_pack_id", ""),
        ("observed_calibration_id", None),
    ],
)
def test_runtime_skeleton_identity_drift_rejects_malformed_observed_evidence(
    field: str, bad: object
) -> None:
    drift = _fixture("valid", "runtime-result.identity-drift.json")
    drift[field] = bad

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(drift)


def test_runtime_skeleton_contract_drift_result_passes_with_well_formed_evidence() -> None:
    runtime_skeleton.validate_result_manifest(_valid_contract_drift_result())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("side_effect_attempt_count", 1),
        ("side_effect_attempt_evidence_sha256", "a" * 64),
        ("observed_input_pack_id", "open_macro_v03_certified_input_pack_drifted"),
        ("observed_input_pack_sha256", "0" * 64),
        ("observed_calibration_id", "open_macro_v03_calibration_drifted"),
        ("observed_calibration_config_sha256", "1" * 64),
    ],
)
def test_runtime_skeleton_contract_drift_rejects_incompatible_evidence(
    field: str, value: object
) -> None:
    drift = _valid_contract_drift_result()
    drift[field] = value

    with pytest.raises(runtime_skeleton.RuntimeSkeletonContractError):
        runtime_skeleton.validate_result_manifest(drift)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            drift, runtime_skeleton.load_schema("runtime_result_manifest.schema.json")
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("observed_contract_bundle_sha256", "not-a-sha"),
        ("observed_contract_bundle_sha256", "A" * 64),
        ("observed_contract_version", ""),
        ("observed_engine_commit", 123),
        ("observed_engine_commit", "0" * 39),
        ("observed_engine_image_digest", "0" * 64),
        ("observed_engine_image_digest", "sha256:" + "G" * 64),
    ],
)
def test_runtime_skeleton_contract_drift_rejects_malformed_observed_evidence(
    field: str, bad: object
) -> None:
    drift = _valid_contract_drift_result()
    drift[field] = bad

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
