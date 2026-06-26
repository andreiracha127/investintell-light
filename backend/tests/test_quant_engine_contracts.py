from __future__ import annotations

from app.contracts import quant_engine_v1


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
    assert "input_bundle_logical_hash" in schema["required"]

