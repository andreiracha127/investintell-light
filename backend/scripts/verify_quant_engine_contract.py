#!/usr/bin/env python3
"""Standalone quant-engine contract bundle verifier (no FastAPI / DB needed).

Mirrors the worker's ``scripts/contract_bundle.py verify``. It recomputes the
bundle digest, checks it against the frozen expected value and ``SOURCE.json``,
and — when ``jsonschema`` is installed — validates every positive fixture
against its schema and every negative fixture as a rejection. Exit code is
non-zero on any drift, so this is a usable CI gate that imports only the tiny
``app.contracts.quant_engine_v1`` module (stdlib), not the application.

Usage:
    python scripts/verify_quant_engine_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.contracts import quant_engine_v1 as qe  # noqa: E402

# Fixture filename prefix -> schema it must validate against.
_SCHEMA_BY_PREFIX = {
    "engine-manifest": "engine-manifest.schema.json",
    "job-request": "job-request.schema.json",
    "job-result": "job-result.schema.json",
}


def _schema_for(fixture_name: str) -> str | None:
    for prefix, schema in _SCHEMA_BY_PREFIX.items():
        if fixture_name.startswith(prefix):
            return schema
    return None


def main() -> int:
    verdict = qe.verify_bundle()
    print(json.dumps(verdict, indent=2, sort_keys=True))
    ok = bool(verdict["ok"])

    src = qe.load_source_metadata()
    if not verdict["source_bundle_sha256_match"]:
        print(
            "FAIL SOURCE.json bundle_sha256 != recomputed bundle: "
            f"{src.get('bundle_sha256')}"
        )
        ok = False
    if src.get("governance", {}).get("runtime_activation") is not False:
        print("FAIL SOURCE.json governance.runtime_activation is not False")
        ok = False
    if src.get("governance", {}).get("a5_status") != "blocked":
        print("FAIL SOURCE.json governance.a5_status is not 'blocked'")
        ok = False

    try:
        import jsonschema
    except ImportError:
        print("[warn] jsonschema not installed; skipped fixture schema validation")
    else:
        root = qe.bundle_dir()
        for kind, expect_valid in (("valid", True), ("invalid", False)):
            for fx in sorted((root / "fixtures" / kind).glob("*.json")):
                schema_name = _schema_for(fx.name)
                if schema_name is None:
                    print(f"FAIL no schema mapped for fixture {fx.name}")
                    ok = False
                    continue
                schema = qe.load_schema(schema_name)
                payload = json.loads(fx.read_text(encoding="utf-8"))
                try:
                    jsonschema.validate(payload, schema)
                    is_valid = True
                except jsonschema.ValidationError:
                    is_valid = False
                if is_valid != expect_valid:
                    print(
                        f"FAIL fixture {kind}/{fx.name}: "
                        f"expected valid={expect_valid}, got valid={is_valid}"
                    )
                    ok = False
                else:
                    print(f"OK   fixture {kind}/{fx.name}")

    print("\nRESULT:", "OK" if ok else "DRIFT DETECTED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
