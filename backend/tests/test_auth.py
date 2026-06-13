"""Tests for InsForge JWT verification (app/core/auth.py)."""
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
