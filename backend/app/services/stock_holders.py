"""Stocks → Holders: full 13F institutional holder list for a single stock.

Resolves ticker → CUSIP via sec_cusip_ticker_map, then returns every filer in
sec_13f_holdings holding that CUSIP in the latest reported period — the whole
>$5bn universe, NOT the curated subset. Manager identity comes from
sec_managers.firm_name (cik is not unique there → highest-AUM row via LATERAL).

The frontend computes no finance; numbers come straight from this payload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.stock_holders_mv import StockFundHolderRow, StockInstitutionalHolder
from app.schemas.fund_analysis import EmptyState
from app.schemas.stock_holders import (
    FundFamily,
    FundHolder,
    StockFundHoldersResponse,
    StockHolder,
    StockHoldersResponse,
)


class StockHoldersSourceError(RuntimeError):
    """A real datalake source failed (not a 'missing relation' empty-state)."""


# Latest-period holders of the CUSIP(s) a ticker maps to. No curated filter and
# no row cap — the Holders grid is dynamic and the >$5bn universe is bounded
# (hundreds of filers per popular stock).
_HOLDERS_SQL = text(
    """
    WITH tgt AS (
        SELECT DISTINCT upper(cusip) AS cusip
        FROM sec_cusip_ticker_map
        WHERE upper(ticker) = :ticker AND cusip IS NOT NULL
    ),
    -- 13F is filed synchronously each quarter, so the global max report_date is
    -- the current quarter for every active stock — and reads via the report_date
    -- index instead of decompressing chunks per cusip (10x faster).
    latest AS (
        SELECT max(report_date) AS period FROM sec_13f_holdings
    ),
    base AS (
        SELECT
            h.cik,
            COALESCE(fn.filer_name, mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
            h.report_date,
            upper(h.cusip) AS cusip,
            h.issuer_name,
            h.shares,
            h.market_value,
            entry.entry_date
        FROM sec_13f_holdings h
        JOIN tgt ON upper(h.cusip) = tgt.cusip
        -- canonical filer name from COVERPAGE (10-digit CIK; fixes leading-zero
        -- mismatches like Blackstone/BNP that left big managers showing as 'CIK …')
        LEFT JOIN sec_13f_filer_name fn ON fn.cik = lpad(h.cik, 10, '0')
        LEFT JOIN LATERAL (
            SELECT m.firm_name
            FROM sec_managers m
            WHERE m.cik = lpad(h.cik, 10, '0') AND m.firm_name IS NOT NULL
            ORDER BY m.aum_total DESC NULLS LAST
            LIMIT 1
        ) mgr ON true
        -- entry quarter, precomputed in the sec_13f_entry MV (indexed by cusip,cik)
        LEFT JOIN sec_13f_entry entry ON entry.cik = h.cik AND entry.cusip = h.cusip
        WHERE h.report_date = (SELECT period FROM latest)
    ),
    -- resolve the entry price once per DISTINCT entry date (handful), not per holder
    eprices AS (
        SELECT d.entry_date,
            (SELECT p.adj_close FROM eod_prices p
             WHERE p.ticker = :ticker AND p.date >= d.entry_date
             ORDER BY p.date ASC LIMIT 1) AS entry_price
        FROM (SELECT DISTINCT entry_date FROM base WHERE entry_date IS NOT NULL) d
    ),
    consts AS (
        SELECT
            (SELECT p.adj_close FROM eod_prices p
             WHERE p.ticker = :ticker ORDER BY p.date DESC LIMIT 1) AS current_price,
            (SELECT f.shares_outstanding FROM fundamentals_snapshot f
             WHERE upper(f.ticker) = :ticker AND f.shares_outstanding > 0
             ORDER BY f.period_end DESC LIMIT 1) AS shares_outstanding
    )
    SELECT
        base.cik, base.manager_name, base.report_date, base.cusip, base.issuer_name,
        base.shares, base.market_value, base.entry_date,
        consts.shares_outstanding,
        ep.entry_price,
        consts.current_price
    FROM base
    LEFT JOIN eprices ep ON ep.entry_date = base.entry_date
    CROSS JOIN consts
    ORDER BY base.market_value DESC NULLS LAST
    """
)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _empty(reason: str, source: str | None = None) -> EmptyState:
    return EmptyState(reason=reason, source=source)


def _build_holders_response(
    norm: str, rows: Sequence[Mapping[str, Any]]
) -> StockHoldersResponse:
    if not rows:
        return StockHoldersResponse(
            ticker=norm,
            empty_state=_empty(
                f"No 13F institutional holders are mapped for {norm}.",
                "sec_13f_holdings",
            ),
        )
    typed = cast(Sequence[Mapping[str, Any]], rows)
    # shares_outstanding is the same scalar on every row (latest fundamentals);
    # used to express each holder's stake as % of shares outstanding (ownership).
    shares_out = _float(typed[0]["shares_outstanding"])

    def _pct(shares: float | None) -> float | None:
        if not shares_out or shares is None:
            return None
        return shares / shares_out

    def _ret(row: Mapping[str, Any]) -> float | None:
        entry = _float(row["entry_price"])
        cur = _float(row["current_price"])
        if not entry or cur is None:
            return None
        return cur / entry - 1.0

    holders = []
    for row in typed:
        shares = _float(row["shares"])
        holders.append(
            StockHolder(
                cik=row["cik"],
                manager_name=row["manager_name"],
                shares=shares,
                market_value=_float(row["market_value"]),
                pct_outstanding=_pct(shares),
                position_return=_ret(row),
                entry_date=row["entry_date"],
            )
        )
    total_mv = sum(h.market_value for h in holders if h.market_value is not None)
    first = typed[0]
    return StockHoldersResponse(
        ticker=norm,
        cusip=first["cusip"],
        security_name=first["issuer_name"],
        period=first["report_date"],
        holder_count=len(holders),
        total_market_value=total_mv or None,
        shares_outstanding=shares_out,
        holders=holders,
    )


async def _fetch_stock_holders_legacy(
    datalake: AsyncSession, norm: str
) -> StockHoldersResponse:
    try:
        rows = (
            await datalake.execute(_HOLDERS_SQL, {"ticker": norm})
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read 13F holders for {norm}."
        ) from exc
    return _build_holders_response(norm, rows)


async def fetch_stock_holders(
    datalake: AsyncSession,
    ticker: str,
    *,
    use_db_first: bool | None = None,
) -> StockHoldersResponse:
    """Latest-period 13F institutional holders for a ticker.

    Source = stock_institutional_holders_mv (datalake) when use_holders_db_first
    is on, with a fallback to the legacy hypertable SQL for tickers absent from
    the MV (covers refresh lag and the MV not yet being deployed). The MV is
    refreshed on a cron by the matview_refresh worker, so a freshly-ingested 13F
    holding surfaces only after the next refresh; freshness is exposed to the
    frontend via the response period/report_date fields. Reshape is the same
    helper for both paths, so payloads are identical.
    """
    norm = ticker.strip().upper()
    if not norm:
        raise ValueError("Ticker must not be empty.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first
    if not use_db_first:
        return await _fetch_stock_holders_legacy(datalake, norm)

    try:
        rows = (
            await datalake.execute(
                select(
                    StockInstitutionalHolder.cik,
                    StockInstitutionalHolder.manager_name,
                    StockInstitutionalHolder.report_date,
                    StockInstitutionalHolder.cusip,
                    StockInstitutionalHolder.issuer_name,
                    StockInstitutionalHolder.shares,
                    StockInstitutionalHolder.market_value,
                    StockInstitutionalHolder.entry_date,
                    StockInstitutionalHolder.shares_outstanding,
                    StockInstitutionalHolder.entry_price,
                    StockInstitutionalHolder.current_price,
                )
                .where(StockInstitutionalHolder.ticker == norm)
                .order_by(StockInstitutionalHolder.market_value.desc().nullslast())
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read 13F holders for {norm}."
        ) from exc
    if not rows:
        # MV vazio para este ticker → fallback ao SQL legado (cobre lag de refresh
        # e MV ainda não aplicada).
        return await _fetch_stock_holders_legacy(datalake, norm)
    return _build_holders_response(norm, rows)


# Registered funds (N-PORT) holding the CUSIP, named via the SEC series-class
# crosswalk (registrant -> family, series -> fund name). Reads the
# `nport_latest_holdings` MV (latest report per series/cusip, indexed by cusip)
# instead of the 96M-row compressed hypertable — ms instead of seconds. Grouped
# into the family -> fund tree by the service below.
_FUND_HOLDERS_SQL = text(
    """
    WITH tgt AS (
        SELECT DISTINCT upper(cusip) AS cusip
        FROM sec_cusip_ticker_map
        WHERE upper(ticker) = :ticker AND cusip IS NOT NULL
    ),
    bounds AS (SELECT max(report_date) AS m FROM nport_holdings_history)
    SELECT
        n.cik AS registrant_cik,
        -- family name belongs to the registrant: resolve by cik first, then by
        -- series, else fall back to the bare CIK.
        COALESCE(fam.entity_name, sc.entity_name, 'CIK ' || n.cik) AS family,
        n.series_id,
        COALESCE(sc.series_name, n.series_id) AS fund_name,
        fv.instrument_id AS instrument_id,
        max(n.issuer_name) AS issuer_name,
        sum(n.quantity) AS quantity,
        sum(n.market_value) AS market_value,
        max(n.pct_nav_0) AS pct_of_nav,
        max(n.pct_nav_1) AS pct_nav_q1,
        max(n.pct_nav_2) AS pct_nav_q2,
        max(n.pct_nav_3) AS pct_nav_q3,
        max(n.report_date) AS report_date,
        (SELECT cusip FROM tgt ORDER BY cusip LIMIT 1) AS cusip
    FROM nport_holdings_history n
    JOIN tgt ON n.cusip = tgt.cusip
    LEFT JOIN LATERAL (
        SELECT entity_name, series_name
        FROM sec_investment_company_series_class c
        WHERE c.series_id = n.series_id
        LIMIT 1
    ) sc ON true
    LEFT JOIN LATERAL (
        SELECT entity_name
        FROM sec_investment_company_series_class c
        WHERE c.registrant_cik = n.cik
        LIMIT 1
    ) fam ON true
    -- instrument id from the pre-materialized map (one row per series_id), NOT
    -- the live funds_v view — that view recomputes the whole catalogue per call
    -- and is catastrophic (144s cold) when joined per series at request time.
    LEFT JOIN fund_instrument_map fv ON fv.series_id = n.series_id
    -- only funds whose latest report is recent (drop those that already sold out)
    WHERE n.report_date >= (SELECT m FROM bounds) - interval '130 days'
    GROUP BY n.cik, fam.entity_name, sc.entity_name, n.series_id, sc.series_name, fv.instrument_id
    ORDER BY family, market_value DESC NULLS LAST
    """
)


def _build_fund_holders_response(
    norm: str, rows: Sequence[Mapping[str, Any]]
) -> StockFundHoldersResponse:
    if not rows:
        return StockFundHoldersResponse(
            ticker=norm,
            empty_state=_empty(
                f"No registered-fund (N-PORT) holdings are mapped for {norm}.",
                "sec_nport_holdings",
            ),
        )
    typed = cast(Sequence[Mapping[str, Any]], rows)
    families: dict[str, FundFamily] = {}
    for row in typed:
        key = row["registrant_cik"]
        fam = families.get(key)
        if fam is None:
            fam = FundFamily(registrant_cik=key, family=row["family"], market_value=0.0)
            families[key] = fam
        mv = _float(row["market_value"])
        fam.funds.append(
            FundHolder(
                series_id=row["series_id"],
                fund_name=row["fund_name"],
                instrument_id=row["instrument_id"],
                quantity=_float(row["quantity"]),
                market_value=mv,
                pct_of_nav=_float(row["pct_of_nav"]),
                pct_nav_q1=_float(row["pct_nav_q1"]),
                pct_nav_q2=_float(row["pct_nav_q2"]),
                pct_nav_q3=_float(row["pct_nav_q3"]),
            )
        )
        fam.fund_count += 1
        if mv is not None:
            fam.market_value = (fam.market_value or 0.0) + mv

    ordered = sorted(families.values(), key=lambda f: f.market_value or 0.0, reverse=True)
    total_mv = sum(f.market_value for f in ordered if f.market_value is not None)
    first = typed[0]
    return StockFundHoldersResponse(
        ticker=norm,
        cusip=first["cusip"] if "cusip" in first else None,
        security_name=first["issuer_name"],
        period=first["report_date"] if "report_date" in first else None,
        family_count=len(ordered),
        fund_count=len(typed),
        total_market_value=total_mv or None,
        families=ordered,
    )


async def _fetch_stock_fund_holders_legacy(
    datalake: AsyncSession, norm: str
) -> StockFundHoldersResponse:
    try:
        rows = (
            await datalake.execute(_FUND_HOLDERS_SQL, {"ticker": norm})
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read N-PORT fund holders for {norm}."
        ) from exc
    return _build_fund_holders_response(norm, rows)


async def fetch_stock_fund_holders(
    datalake: AsyncSession,
    ticker: str,
    *,
    use_db_first: bool | None = None,
) -> StockFundHoldersResponse:
    """Registered-fund (N-PORT) holders of a ticker, grouped into a family tree.

    Source = stock_fund_holders_mv (datalake) when use_holders_db_first is on,
    with a fallback to the legacy hypertable SQL for tickers absent from the MV
    (covers refresh lag and the MV not yet being deployed). The MV is refreshed
    on a cron by the matview_refresh worker; the family→funds grouping is plain
    Python assembly (no compute) shared by both paths, so payloads are identical.
    """
    norm = ticker.strip().upper()
    if not norm:
        raise ValueError("Ticker must not be empty.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first
    if not use_db_first:
        return await _fetch_stock_fund_holders_legacy(datalake, norm)

    try:
        rows = (
            await datalake.execute(
                select(
                    StockFundHolderRow.registrant_cik,
                    StockFundHolderRow.family,
                    StockFundHolderRow.series_id,
                    StockFundHolderRow.fund_name,
                    StockFundHolderRow.instrument_id,
                    StockFundHolderRow.issuer_name,
                    StockFundHolderRow.quantity,
                    StockFundHolderRow.market_value,
                    StockFundHolderRow.pct_of_nav,
                    StockFundHolderRow.pct_nav_q1,
                    StockFundHolderRow.pct_nav_q2,
                    StockFundHolderRow.pct_nav_q3,
                    StockFundHolderRow.report_date,
                    StockFundHolderRow.cusip,
                )
                .where(StockFundHolderRow.ticker == norm)
                .order_by(
                    StockFundHolderRow.family,
                    StockFundHolderRow.market_value.desc().nullslast(),
                )
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read N-PORT fund holders for {norm}."
        ) from exc
    if not rows:
        return await _fetch_stock_fund_holders_legacy(datalake, norm)
    return _build_fund_holders_response(norm, rows)
