"""InsForge JWT verification (RS256 against a cached JWKS).

Auth stays on InsForge: the frontend obtains tokens via @insforge/sdk; this
module verifies them LOCALLY (no per-request round-trip). Applied only to
user-data routes — public catalog/timeseries routes stay open (CORS-gated),
matching the boundary CatalogCacheMiddleware already encodes.

Failure is closed: missing/invalid token on a protected route -> 401; the
auth backend being unconfigured -> 503 (declared, never silently open).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=True)
_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class CurrentUser:
    """Identity extracted from a verified InsForge JWT."""

    sub: str
    org_id: str | None
    claims: dict[str, Any]


def _get_jwks_client() -> PyJWKClient:
    """Process-cached JWKS client (refreshes its key set on a kid miss)."""
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        if not settings.insforge_jwks_url:
            raise HTTPException(
                status_code=503,
                detail="Auth backend not configured (INSFORGE_JWKS_URL).",
            )
        _jwks_client = PyJWKClient(settings.insforge_jwks_url)
    return _jwks_client


async def verify_bearer(token: str) -> CurrentUser:
    """Verify an RS256 InsForge JWT and return the identity, else raise 401."""
    settings = get_settings()
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.insforge_audience,
            issuer=settings.insforge_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc
    return CurrentUser(
        sub=str(claims["sub"]),
        org_id=claims.get("org_id"),
        claims=claims,
    )


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> CurrentUser:
    """FastAPI dependency: 401 on missing/invalid token, else the identity."""
    return await verify_bearer(creds.credentials)
