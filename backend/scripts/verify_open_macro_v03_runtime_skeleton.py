#!/usr/bin/env python3
"""Standalone open_macro_v03 runtime skeleton contract verifier.

This is an offline gate. It imports only the stdlib-only contract validator and
optionally ``jsonschema`` for fixture/schema checks; it never imports the FastAPI
app, DB sessions, jobs, Docker/subprocess helpers, builder, or allocator code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.contracts import open_macro_v03_runtime_skeleton as runtime_skeleton  # noqa: E402

_SCHEMA_BY_PREFIX = {
    "runtime-job-envelope": "runtime_job_envelope.schema.json",
    "runtime-result": "runtime_result_manifest.schema.json",
}


def _schema_for(fixture_name: str) -> str | None:
    for prefix, schema in _SCHEMA_BY_PREFIX.items():
        if fixture_name.startswith(prefix):
            return schema
    return None


def main() -> int:
    ok = True

    try:
        print(json.dumps(runtime_skeleton.verify_schema_hashes(), indent=2, sort_keys=True))
        runtime_skeleton.verify_source_metadata()
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"FAIL runtime skeleton source/schema verification: {exc}")
        ok = False

    root = runtime_skeleton.contract_dir()
    for fx in sorted((root / "fixtures" / "valid").glob("*.json")):
        payload = json.loads(fx.read_text(encoding="utf-8"))
        try:
            if fx.name.startswith("runtime-job-envelope"):
                runtime_skeleton.validate_job_envelope(payload)
            else:
                runtime_skeleton.validate_result_manifest(payload)
        except Exception as exc:  # pragma: no cover - CLI guard
            print(f"FAIL fixture valid/{fx.name}: {exc}")
            ok = False
        else:
            print(f"OK   fixture valid/{fx.name}")

    for fx in sorted((root / "fixtures" / "invalid").glob("*.json")):
        payload = json.loads(fx.read_text(encoding="utf-8"))
        try:
            if fx.name.startswith("runtime-job-envelope"):
                runtime_skeleton.validate_job_envelope(payload)
            else:
                runtime_skeleton.validate_result_manifest(payload)
        except runtime_skeleton.RuntimeSkeletonContractError:
            print(f"OK   fixture invalid/{fx.name}")
        else:
            print(f"FAIL fixture invalid/{fx.name}: unexpectedly accepted")
            ok = False

    try:
        import jsonschema
    except ImportError:
        print("[warn] jsonschema not installed; skipped JSON Schema fixture validation")
    else:
        for kind, expect_valid in (("valid", True), ("invalid", False)):
            for fx in sorted((root / "fixtures" / kind).glob("*.json")):
                schema_name = _schema_for(fx.name)
                if schema_name is None:
                    print(f"FAIL no schema mapped for fixture {fx.name}")
                    ok = False
                    continue
                payload = json.loads(fx.read_text(encoding="utf-8"))
                schema = runtime_skeleton.load_schema(schema_name)
                try:
                    jsonschema.validate(payload, schema)
                    is_valid = True
                except jsonschema.ValidationError:
                    is_valid = False
                if is_valid != expect_valid:
                    print(f"FAIL JSON Schema fixture {kind}/{fx.name}")
                    ok = False

    print("\nRESULT:", "OK" if ok else "DRIFT DETECTED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
