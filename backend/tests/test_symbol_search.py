"""Tests do ranking puro do symbol search (sem DB)."""

import uuid

from app.services.symbol_search import SymbolHit, _escape_like, rank_hits

FID = uuid.uuid4()


def _stock(sym: str, name: str = "") -> SymbolHit:
    return SymbolHit(symbol=sym, name=name or f"{sym} Inc", kind="stock", instrument_id=None)


def _fund(sym: str, kind: str = "etf") -> SymbolHit:
    return SymbolHit(symbol=sym, name=f"{sym} Fund", kind=kind, instrument_id=FID)


def test_exact_ticker_first_then_prefix_then_name() -> None:
    hits = [_stock("SPYX"), _stock("XSPY", name="Spy Holdings"), _stock("SPY")]
    out = rank_hits(hits, "SPY", 10)
    assert [h.symbol for h in out] == ["SPY", "SPYX", "XSPY"]


def test_fund_wins_dedup_over_stock() -> None:
    out = rank_hits([_stock("SPY"), _fund("SPY")], "SPY", 10)
    assert len(out) == 1
    assert out[0].kind == "etf" and out[0].instrument_id == FID


def test_limit_applied_after_ranking() -> None:
    hits = [_stock(f"AB{i}") for i in range(30)] + [_stock("AB")]
    out = rank_hits(hits, "AB", 5)
    assert len(out) == 5 and out[0].symbol == "AB"


def test_case_insensitive_query() -> None:
    out = rank_hits([_stock("MSFT")], "msft", 10)
    assert out[0].symbol == "MSFT"


# ---------------------------------------------------------------------------
# _escape_like — pure unit tests (no DB)
# ---------------------------------------------------------------------------


def test_escape_like_percent() -> None:
    assert _escape_like("100%") == "100\\%"


def test_escape_like_underscore() -> None:
    assert _escape_like("A_B") == "A\\_B"


def test_escape_like_backslash() -> None:
    assert _escape_like("C:\\path") == "C:\\\\path"


def test_escape_like_combined() -> None:
    assert _escape_like("50%_off\\") == "50\\%\\_off\\\\"


def test_escape_like_no_special_chars() -> None:
    assert _escape_like("AAPL") == "AAPL"


def test_escape_like_empty_string() -> None:
    assert _escape_like("") == ""
