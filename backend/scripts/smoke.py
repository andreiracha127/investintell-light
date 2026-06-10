"""Smoke test: verify the backend /health endpoint is up and returning the expected payload.

Run from backend/:
    uv run python scripts/smoke.py
"""

import sys

import httpx

URL = "http://localhost:8000/health"
EXPECTED = {"status": "ok", "database": "ok"}


def main() -> None:
    try:
        response = httpx.get(URL, timeout=5)
    except httpx.ConnectError:
        print(f"FAIL  — backend is not running (connection refused at {URL})")
        sys.exit(1)
    except httpx.RequestError as exc:
        print(f"FAIL  — request error: {exc}")
        sys.exit(1)

    if response.status_code != 200:
        print(f"FAIL  — expected HTTP 200, got {response.status_code}")
        print(f"       body: {response.text}")
        sys.exit(1)

    body = response.json()
    if body != EXPECTED:
        print(f"FAIL  — unexpected payload: {body!r}")
        print(f"       expected: {EXPECTED!r}")
        sys.exit(1)

    print("PASS  — /health returned 200 with expected payload")


if __name__ == "__main__":
    main()
