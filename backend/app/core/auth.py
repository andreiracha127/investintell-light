"""InsForge JWT verification (HS256 against a shared secret).

Auth stays on InsForge: the frontend obtains tokens via @insforge/sdk; this
module verifies them LOCALLY (no per-request round-trip). Applied only to
user-data routes — public catalog/timeseries routes stay open (CORS-gated),
matching the boundary CatalogCacheMiddleware already encodes.

InsForge signs access tokens with HS256 using a shared ``JWT_SECRET`` (no JWKS,
no ``iss``/``aud`` claims — verified against the live backend). We enforce the
HMAC signature plus ``exp`` and ``sub``, and pin the algorithm to HS256 so an
``alg: none`` / asymmetric-confusion token can never authenticate.

Failure is closed: missing/invalid token on a protected route -> 401; the
auth backend being unconfigured (no secret) -> 503 (declared, never silently
open).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class CurrentUser:
    """Identity extracted from a verified InsForge JWT."""

    sub: str
    org_id: str | None
    claims: dict[str, Any]


async def verify_bearer(token: str) -> CurrentUser:
    """Verify an HS256 InsForge JWT and return the identity, else raise 401."""
    settings = get_settings()
    if not settings.insforge_jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="Auth backend not configured (INSFORGE_JWT_SECRET).",
        )
    try:
        claims = jwt.decode(
            token,
            settings.insforge_jwt_secret,
            algorithms=["HS256"],
            # InsForge tokens carry no iss/aud — verify signature + exp + sub.
            options={"require": ["exp", "sub"], "verify_aud": False},
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
