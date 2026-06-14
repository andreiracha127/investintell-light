"""Tests for InsForge JWT verification (app/core/auth.py)."""
import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings


def test_settings_expose_insforge_auth_fields() -> None:
    s = Settings(
        insforge_issuer="https://proj.insforge.app",
        insforge_jwks_url="https://proj.insforge.app/.well-known/jwks.json",
        insforge_audience="investintell-light",
    )
    assert s.insforge_issuer == "https://proj.insforge.app"
    assert s.insforge_jwks_url.endswith("/jwks.json")
    assert s.insforge_audience == "investintell-light"


_ISSUER = "https://proj.insforge.app"
_AUD = "investintell-light"


@pytest.fixture
def rsa_keys() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _make_token(private_pem: bytes, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iss": _ISSUER,
        "aud": _AUD,
        "exp": int(time.time()) + 3600,
        "org_id": "org-123",
    }
    payload.update(overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _patch_jwks(monkeypatch: pytest.MonkeyPatch, public_pem: bytes) -> None:
    import app.core.auth as auth

    # Patch the settings accessor (and the JWKS client) at the seam so
    # verify_bearer sees the test issuer/audience without mutating the process
    # env or the lru_cache — monkeypatch reverts both after the test, so no
    # cached config leaks into the rest of the suite.
    test_settings = Settings(
        insforge_issuer=_ISSUER,
        insforge_jwks_url=_ISSUER + "/.well-known/jwks.json",
        insforge_audience=_AUD,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        auth,
        "_get_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_pem)
        ),
    )


async def test_valid_token_returns_claims(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    import app.core.auth as auth

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    user = await auth.verify_bearer(_make_token(private_pem, sub="u-1"))
    assert user.sub == "u-1"
    assert user.org_id == "org-123"


async def test_expired_token_is_401(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    from fastapi import HTTPException

    import app.core.auth as auth

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    token = _make_token(private_pem, exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(token)
    assert exc.value.status_code == 401


async def test_wrong_audience_is_401(
    monkeypatch: pytest.MonkeyPatch, rsa_keys: tuple[bytes, bytes]
) -> None:
    from fastapi import HTTPException

    import app.core.auth as auth

    private_pem, public_pem = rsa_keys
    _patch_jwks(monkeypatch, public_pem)
    token = _make_token(private_pem, aud="some-other-api")
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(token)
    assert exc.value.status_code == 401
