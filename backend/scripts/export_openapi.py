"""Export the FastAPI OpenAPI schema to backend/openapi.json.

Run from backend/:
    uv run python scripts/export_openapi.py
"""

import json
import pathlib
import sys

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
# when running as a plain script rather than an installed package.
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import create_app  # noqa: E402


def main() -> None:
    application = create_app()
    schema = application.openapi()
    out = _BACKEND_ROOT / "openapi.json"
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
