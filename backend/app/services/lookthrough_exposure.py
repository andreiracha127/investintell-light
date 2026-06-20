"""Per-fund equity look-through exposure matrix (Sprint B / Task 3).

Given a set of fund instrument ids, ``fund_equity_exposure`` returns, for each
fund, a map ``security_key -> pct_of_nav`` (fraction 0..1) covering ONLY equity
holdings. This feeds the per-equity overlap constraint in Task 4.

Reuse, not reimplementation
---------------------------
The decomposition is the same engine the portfolio drilldown uses:
``app.services.lookthrough.build_portfolio_exposure_tree``. We run it once per
fund at portfolio weight 1.0, so each leaf's ``value_pct`` is the holding's
percentage of that fund's NAV (the tree normalizes each fund's positive
holdings to 100 points — see ``test_portfolio_exposure_tree_normalizes_each_
fund_to_portfolio_weight``). Dividing by 100 yields the 0..1 fraction. The
``security_key`` is the tree leaf's ``key``, which is exactly
``lookthrough._cusip_key(cusip, isin)`` — the canonical stable security id.

Equity filter
-------------
The tree tags each leaf's asset bucket via ``_series_taxonomy`` /
``_fallback_taxonomy_from_nport`` (N-PORT ``EC``/``EP`` -> ``equity``). Equity
leaves carry the asset_key ``equity`` in their node id (``cusip|equity|...``).
We keep only those; fixed_income / cash / alternatives / derivatives leaves are
dropped. ``UNKNOWN`` security keys (synthetic/unidentified) are also dropped —
they cannot anchor a per-security overlap constraint.

Recursion scope
---------------
Full fund-of-fund recursion IS performed: ``build_portfolio_exposure_tree``
follows identifiable child-series edges down to underlying equity leaves
(capped at ``MAX_TREE_DEPTH``). When a child fund cannot be resolved, its
position remains a non-equity / fund leaf and is naturally excluded. So this is
NOT merely first-level: it is the same best-effort recursive look-through the
rest of the app exposes.

Best-effort / absence semantics
-------------------------------
Funds with no resolvable series, or with no equity leaves after decomposition,
are simply ABSENT from the returned dict (they contribute 0 downstream — the
documented best-effort behavior). The per-fund call is independent, so one
fund's missing data never suppresses another's.

Limitations
-----------
- Equity pct is normalized to the fund's positive holdings (gross long base),
  matching the tree's convention; it is not a signed/net exposure.
- The CUSIP tail per series is capped by ``MAX_TREE_HOLDINGS_PER_SERIES`` /
  ``MAX_TREE_LEAVES`` inherited from the tree; a very long equity tail collapses
  into an aggregated "Other holdings" leaf (key ``__OTHER__``), which is dropped
  here because it is not a single security. For typical funds this tail is tiny.
"""

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lookthrough import (
    LookthroughSummary,
    SeriesLookthrough,
    build_portfolio_exposure_tree,
    get_fund_series,
    get_fund_taxonomy_by_series,
)

# A SeriesLookthrough seed needs a summary; the tree never reads its fields, so
# an all-None summary is fine — it re-fetches holdings from N-PORT itself.
_EMPTY_SUMMARY = LookthroughSummary(
    sum_pct_total=None,
    direct_pct=None,
    indirect_pct=None,
    expanded_fund_pct=None,
    nondecomposable_fund_pct=None,
    derivatives_gross_pct=None,
    derivatives_net_pct=None,
    unidentified_pct=None,
    coverage_pct=None,
    n_holdings=None,
    n_children_expanded=None,
    oldest_report_date=None,
)

# Asset bucket key that the exposure tree assigns to equity leaves.
_EQUITY_ASSET_KEY = "equity"
# Synthetic/unidentified security key emitted by ``_cusip_key`` — never a real
# security, so it cannot anchor a per-security overlap constraint.
_UNKNOWN_KEY = "UNKNOWN"


async def fund_equity_exposure(
    session: AsyncSession,
    datalake: AsyncSession,
    fund_instrument_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, float]]:
    """Per-fund map ``security_key -> pct_of_nav`` (0..1) for EQUITY holdings.

    For each fund instrument id we resolve its SEC series, run the shared
    recursive look-through tree at weight 1.0, and keep only equity CUSIP
    leaves. ``security_key`` is the canonical ``_cusip_key`` (normalized CUSIP).
    Funds with no series or no equity leaves are absent from the result; they
    contribute 0 to any downstream overlap constraint. See the module docstring
    for the recursion scope and normalization details.
    """
    out: dict[uuid.UUID, dict[str, float]] = {}
    if not fund_instrument_ids:
        return out

    # De-dup while preserving order; resolve each fund's series.
    seen: set[uuid.UUID] = set()
    ordered_ids: list[uuid.UUID] = []
    for fid in fund_instrument_ids:
        if fid not in seen:
            seen.add(fid)
            ordered_ids.append(fid)

    series_by_fund: dict[uuid.UUID, str] = {}
    for fund_id in ordered_ids:
        series_id = await get_fund_series(session, fund_id)
        if series_id:
            series_by_fund[fund_id] = series_id

    # Pre-load catalog taxonomy once for all series. It only refines display
    # labels / asset bucket; the equity classification falls back to the N-PORT
    # asset_class (EC/EP -> equity) when the catalog row is missing, so the
    # matrix is correct even with no catalog hit.
    taxonomy_by_series = await get_fund_taxonomy_by_series(
        session, sorted(set(series_by_fund.values()))
    )

    as_of = dt.date.today()
    for fund_id, series_id in series_by_fund.items():
        # Seed the recursive tree with this single fund at full weight. The
        # tree re-fetches holdings from N-PORT, picking the latest report
        # ``<= report_date``; ``today`` therefore selects the freshest report.
        seed = SeriesLookthrough(
            series_id=series_id,
            report_date=as_of,
            exposures=[],
            summary=_EMPTY_SUMMARY,
        )
        nodes = await build_portfolio_exposure_tree(
            datalake,
            [(1.0, seed)],
            series_taxonomy=taxonomy_by_series,
        )
        equity: dict[str, float] = {}
        for node in nodes:
            if node.kind not in ("cusip", "security"):
                continue
            # Leaf node ids are ``<kind>|<asset_key>|...|<security_key>``; the
            # asset bucket is the second segment.
            parts = node.id.split("|")
            if len(parts) < 2 or parts[1] != _EQUITY_ASSET_KEY:
                continue
            if node.key == _UNKNOWN_KEY or node.key == "__OTHER__":
                continue
            # value_pct is percentage points of fund NAV at weight 1.0.
            equity[node.key] = equity.get(node.key, 0.0) + node.value_pct / 100.0
        if equity:
            out[fund_id] = equity

    return out
