"""Quant-engine v1 contract loader.

The backend intentionally does not keep a parallel hand-written model for these
schemas. The worker repository owns the canonical JSON Schemas; this module
records the mirrored schema hashes and loads those schema files for compatibility
tests and future code generation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_SHA256: dict[str, str] = {
    "engine-manifest.schema.json": "26757f96bdff5ac90b0e6422f213faac0db5b5289def9c2f0eae7b7f9fa45b9f",
    "job-request.schema.json": "a143bafe60f8414a3b1c04cc93b4ae8568ad51264c8f7e55d83ce9b3a633d593",
    "job-result.schema.json": "95626166653241b6fed455c18b530b057cb66837e920dbfd6fe1d71880ea4fe7",
}


def schema_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "contracts" / "quant-engine" / "v1"


def schema_path(name: str) -> Path:
    if name not in SCHEMA_SHA256:
        raise KeyError(f"unknown quant-engine schema: {name}")
    return schema_dir() / name


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def schema_sha256(name: str) -> str:
    return hashlib.sha256(schema_path(name).read_bytes()).hexdigest()


def verify_schema_hashes() -> dict[str, str]:
    actual = {name: schema_sha256(name) for name in SCHEMA_SHA256}
    mismatches = {
        name: value
        for name, value in actual.items()
        if value != SCHEMA_SHA256[name]
    }
    if mismatches:
        raise ValueError(f"quant-engine schema hash mismatch: {mismatches}")
    return actual

