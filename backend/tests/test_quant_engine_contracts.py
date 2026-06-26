from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.contracts import quant_engine_v1

EXPECTED_BUNDLE_SHA256 = (
    "sha256:a0770412040a582aebd3cc8e37de532739916cb239833e07fe23ba9cca683277"
)

_SCHEMA_BY_PREFIX = {
    "engine-manifest": "engine-manifest.schema.json",
    "job-request": "job-request.schema.json",
    "job-result": "job-result.schema.json",
}


def _schema_for(fixture_name: str) -> str:
    for prefix, schema in _SCHEMA_BY_PREFIX.items():
        if fixture_name.startswith(prefix):
            return schema
    raise AssertionError(f"no schema mapped for fixture {fixture_name}")


def _fixtures(kind: str) -> list[Path]:
    return sorted((quant_engine_v1.bundle_dir() / "fixtures" / kind).glob("*.json"))


# ── Existing schema-mirror guarantees (preserved) ─────────────────────────────


def test_quant_engine_schema_hashes_match_mirror_constants() -> None:
    assert quant_engine_v1.verify_schema_hashes() == quant_engine_v1.SCHEMA_SHA256


def test_job_result_contract_preserves_non_activation_governance() -> None:
    schema = quant_engine_v1.load_schema("job-result.schema.json")

    assert schema["properties"]["runtime_activation"]["const"] is False
    assert schema["properties"]["a3_status"]["const"] == "open_macro_v03"
    assert schema["properties"]["a4_status"]["const"] == "harness_ready_provisional_A3"
    assert schema["properties"]["a5_status"]["const"] == "blocked"


def test_job_request_contract_requires_offline_execution() -> None:
    schema = quant_engine_v1.load_schema("job-request.schema.json")

    assert schema["properties"]["offline"]["const"] is True
    assert "engine_image_digest" in schema["required"]
    assert schema["properties"]["engine_image_digest"]["pattern"] == "^sha256:[0-9a-f]{64}$"
    assert "input_bundle_logical_hash" in schema["required"]


# ── Bundle handshake: backend re-verifies the full versioned bundle ───────────


def test_quant_engine_contract_bundle_sha256_matches_manifest() -> None:
    """The formal handshake: the mirrored bundle recomputes to the frozen digest.

    Fails if any schema/fixture is edited, the manifest is inconsistent, a file
    is missing or extra, or the bundle_sha256 drifts from the expected value.
    """
    verdict = quant_engine_v1.verify_bundle()

    assert verdict["missing"] == [], verdict
    assert verdict["unexpected"] == [], verdict
    assert verdict["mismatched"] == [], verdict
    assert verdict["bundle_sha256_match"] is True
    assert verdict["expected_match"] is True
    assert (
        verdict["bundle_sha256"]
        == verdict["recomputed_bundle_sha256"]
        == EXPECTED_BUNDLE_SHA256
    )
    assert verdict["ok"] is True


def test_source_metadata_pins_inert_runtime_and_bundle() -> None:
    src = quant_engine_v1.load_source_metadata()

    assert src["bundle_sha256"] == EXPECTED_BUNDLE_SHA256
    assert src["contract_version"] == "v1"
    assert src["source_branch"] == "feat/quant-engine-isolation"

    gov = src["governance"]
    assert gov["a3_status"] == "open_macro_v03"
    assert gov["a4_status"] == "harness_ready_provisional_A3"
    assert gov["a5_status"] == "blocked"
    assert gov["freeze_ready"] is False
    assert gov["runtime_activation"] is False


def test_bundle_drift_guard_detects_tampered_fixture(tmp_path: Path) -> None:
    """A mutated fixture must surface as a mismatch, not pass silently."""
    src = quant_engine_v1.bundle_dir()
    dst = tmp_path / "v1"
    shutil.copytree(src, dst)

    target = dst / "fixtures" / "valid" / "job-request.minimal.json"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n",  # one trailing byte = new hash
        encoding="utf-8",
    )

    verdict = quant_engine_v1.verify_bundle(dst)
    assert verdict["ok"] is False
    assert "fixtures/valid/job-request.minimal.json" in verdict["mismatched"]


def test_bundle_drift_guard_detects_extra_file(tmp_path: Path) -> None:
    """An unexpected schema/fixture not recorded in the manifest must fail."""
    src = quant_engine_v1.bundle_dir()
    dst = tmp_path / "v1"
    shutil.copytree(src, dst)

    (dst / "fixtures" / "valid" / "job-request.smuggled.json").write_text(
        "{}", encoding="utf-8"
    )

    verdict = quant_engine_v1.verify_bundle(dst)
    assert verdict["ok"] is False
    assert "fixtures/valid/job-request.smuggled.json" in verdict["unexpected"]


def test_bundle_drift_guard_detects_stale_expected_constant(tmp_path: Path) -> None:
    """If the frozen expected digest no longer matches the manifest, fail loud."""
    verdict = quant_engine_v1.verify_bundle(
        expected_bundle_sha256="sha256:" + "0" * 64
    )
    assert verdict["expected_match"] is False
    assert verdict["ok"] is False


# ── Consumer-side schema validation of the bundled fixtures ───────────────────


def test_valid_fixtures_pass_their_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    fixtures = _fixtures("valid")
    assert fixtures, "expected positive fixtures in the bundle"
    for fx in fixtures:
        schema = quant_engine_v1.load_schema(_schema_for(fx.name))
        jsonschema.validate(json.loads(fx.read_text(encoding="utf-8")), schema)


def test_invalid_fixtures_are_rejected_by_their_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    fixtures = _fixtures("invalid")
    assert fixtures, "expected negative fixtures in the bundle"
    for fx in fixtures:
        schema = quant_engine_v1.load_schema(_schema_for(fx.name))
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(json.loads(fx.read_text(encoding="utf-8")), schema)
