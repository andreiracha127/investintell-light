"""Tests for InsForge JWT verification (app/core/auth.py) — HS256 shared secret.

InsForge issues HS256 access tokens signed with a shared JWT_SECRET (no JWKS,
no iss/aud claims — confirmed against the live backend). ``verify_bearer``
authenticates them locally: HMAC signature + ``exp`` + ``sub`` are enforced;
``iss``/``aud`` are NOT (InsForge does not set them). Algorithm is pinned to
HS256 so ``none``/asymmetric-confusion tokens are rejected.
"""
import base64
import json
import time
import uuid

import jwt
import pytest

from app.core.config import Settings

_SECRET = "test-insforge-shared-secret-aebf0123456789"


def test_settings_expose_insforge_jwt_secret() -> None:
    s = Settings(insforge_jwt_secret=_SECRET)
    assert s.insforge_jwt_secret == _SECRET


def _make_token(secret: str = _SECRET, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "email": "u@insforge.com",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


def _patch_secret(monkeypatch: pytest.MonkeyPatch, secret: str | None = _SECRET) -> None:
    import app.core.auth as auth

    # Patch the settings accessor at the seam so verify_bearer sees the test
    # secret without mutating process env / the lru_cache (reverts after test).
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(insforge_jwt_secret=secret))


async def test_valid_hs256_token_returns_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.auth as auth

    _patch_secret(monkeypatch)
    user = await auth.verify_bearer(_make_token(sub="u-1"))
    assert user.sub == "u-1"
    assert user.claims["role"] == "authenticated"


async def test_expired_token_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    import app.core.auth as auth

    _patch_secret(monkeypatch)
    token = _make_token(exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(token)
    assert exc.value.status_code == 401


async def test_bad_signature_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    import app.core.auth as auth

    _patch_secret(monkeypatch)  # server trusts _SECRET
    forged = _make_token(secret="a-different-secret-of-sufficient-length-xyz", sub="attacker")
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(forged)
    assert exc.value.status_code == 401


async def test_alg_none_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unsigned (alg=none) token must never authenticate (alg pinned HS256)."""
    from fastapi import HTTPException

    import app.core.auth as auth

    _patch_secret(monkeypatch)

    def _b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    unsigned = (
        _b64({"alg": "none", "typ": "JWT"})
        + "."
        + _b64({"sub": "u-1", "exp": int(time.time()) + 3600})
        + "."
    )
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(unsigned)
    assert exc.value.status_code == 401


async def test_missing_secret_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    import app.core.auth as auth

    _patch_secret(monkeypatch, secret=None)
    with pytest.raises(HTTPException) as exc:
        await auth.verify_bearer(_make_token())
    assert exc.value.status_code == 503
