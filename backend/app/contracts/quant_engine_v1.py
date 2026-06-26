"""Quant-engine v1 contract loader and bundle verifier.

The worker repository (``investintell-datalake-workers-quant-engine``) owns the
canonical quant-engine JSON Schemas and fixtures. This backend module mirrors
that versioned bundle and *independently re-verifies it*: it recomputes every
file hash and the aggregate ``bundle_sha256`` and asserts they match the frozen
expected digest. Any drift — an edited schema, a changed fixture, a stale
``manifest.json``, or a moved source commit without a re-sync — fails loud.

The hashed set is the schemas (``*.schema.json``) plus the positive/negative
fixtures (``fixtures/**/*.json``). ``manifest.json``, ``CHANGELOG.md`` and
``SOURCE.json`` are never part of the set, matching the worker's bundler exactly
so the same digest is reproduced on both sides of the contract boundary.

This module is dependency-free (stdlib only); JSON Schema *validation* of the
fixtures lives in the tests / the standalone verifier script, which import
``jsonschema`` there.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
SOURCE_NAME = "SOURCE.json"

# Frozen, expected aggregate digest of the quant-engine v1 contract bundle.
# This is the formal handshake value: it must equal both the mirrored manifest's
# ``bundle_sha256`` and ``SOURCE.json``'s ``bundle_sha256``. Updating it is a
# deliberate, reviewed contract re-sync, never an incidental edit.
EXPECTED_BUNDLE_SHA256 = (
    "sha256:2cdea4d41608562bb3eff1cddd56769450adeb17e84899e31272d81a8f43b0d8"
)

# Per-schema hashes kept for back-compat with the original mirror tests.
SCHEMA_SHA256: dict[str, str] = {
    "engine-manifest.schema.json": "26757f96bdff5ac90b0e6422f213faac0db5b5289def9c2f0eae7b7f9fa45b9f",
    "job-request.schema.json": "a143bafe60f8414a3b1c04cc93b4ae8568ad51264c8f7e55d83ce9b3a633d593",
    "job-result.schema.json": "95626166653241b6fed455c18b530b057cb66837e920dbfd6fe1d71880ea4fe7",
}


def bundle_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "contracts" / "quant-engine" / "v1"


# Back-compat alias: the schemas live in the bundle directory.
def schema_dir() -> Path:
    return bundle_dir()


def schema_path(name: str) -> Path:
    if name not in SCHEMA_SHA256:
        raise KeyError(f"unknown quant-engine schema: {name}")
    return bundle_dir() / name


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def compute_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema_sha256(name: str) -> str:
    return compute_file_sha256(schema_path(name))


def verify_schema_hashes() -> dict[str, str]:
    actual = {name: schema_sha256(name) for name in SCHEMA_SHA256}
    mismatches = {
        name: value for name, value in actual.items() if value != SCHEMA_SHA256[name]
    }
    if mismatches:
        raise ValueError(f"quant-engine schema hash mismatch: {mismatches}")
    return actual


def iter_bundle_files(directory: str | Path | None = None) -> list[Path]:
    """Return the contract files in the bundle: schemas + fixtures, sorted.

    ``manifest.json`` is excluded so the manifest never hashes itself; this
    mirrors the worker's ``iter_bundle_files`` exactly (``SOURCE.json`` and
    ``CHANGELOG.md`` are likewise outside the ``*.schema.json`` / ``fixtures``
    globs and so are excluded too).
    """
    root = Path(directory) if directory is not None else bundle_dir()
    files: list[Path] = []
    files.extend(root.glob("*.schema.json"))
    files.extend(p for p in root.glob("fixtures/**/*.json") if p.is_file())
    return sorted(f for f in files if f.name != MANIFEST_NAME)


def bundle_sha256(files: list[dict[str, str]]) -> str:
    """Single digest over the (path, sha256) set, independent of input order."""
    canonical = json.dumps(
        sorted(
            ({"path": f["path"], "sha256": f["sha256"]} for f in files),
            key=lambda x: x["path"],
        ),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_manifest(directory: str | Path | None = None) -> dict[str, Any]:
    root = Path(directory) if directory is not None else bundle_dir()
    return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))


def load_source_metadata(directory: str | Path | None = None) -> dict[str, Any]:
    root = Path(directory) if directory is not None else bundle_dir()
    return json.loads((root / SOURCE_NAME).read_text(encoding="utf-8"))


def verify_bundle(
    directory: str | Path | None = None,
    *,
    expected_bundle_sha256: str | None = EXPECTED_BUNDLE_SHA256,
) -> dict[str, Any]:
    """Recompute every hash and the bundle digest; return a closed verdict.

    Mirrors the worker's verifier and additionally pins the result to the frozen
    ``expected_bundle_sha256`` so a re-synced manifest cannot silently move the
    backend's accepted contract without updating the frozen constant under review.
    """
    root = Path(directory) if directory is not None else bundle_dir()
    manifest = load_manifest(root)
    recorded = {f["path"]: f["sha256"] for f in manifest.get("files", [])}

    actual = {
        p.relative_to(root).as_posix(): compute_file_sha256(p)
        for p in iter_bundle_files(root)
    }

    missing = sorted(set(recorded) - set(actual))
    unexpected = sorted(set(actual) - set(recorded))
    mismatched = sorted(
        p for p in (set(recorded) & set(actual)) if recorded[p] != actual[p]
    )

    expected_files = [{"path": p, "sha256": s} for p, s in recorded.items()]
    recomputed = bundle_sha256(expected_files)
    manifest_sha = manifest.get("bundle_sha256")
    bundle_sha256_match = manifest_sha == recomputed
    expected_match = (
        expected_bundle_sha256 is None or manifest_sha == expected_bundle_sha256
    )

    ok = (
        not missing
        and not unexpected
        and not mismatched
        and bundle_sha256_match
        and expected_match
    )
    return {
        "contract_version": manifest.get("contract_version"),
        "bundle_sha256": manifest_sha,
        "recomputed_bundle_sha256": recomputed,
        "expected_bundle_sha256": expected_bundle_sha256,
        "missing": missing,
        "unexpected": unexpected,
        "mismatched": mismatched,
        "bundle_sha256_match": bundle_sha256_match,
        "expected_match": expected_match,
        "ok": ok,
    }
