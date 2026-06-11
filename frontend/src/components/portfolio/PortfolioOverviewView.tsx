"use client";

/**
 * Portfolio Overview — persisted-portfolio CRUD plus the render-ready position
 * table from `GET /portfolios/{id}/overview`.
 *
 * The frontend computes NO finance: every P&L/aggregate number comes from the
 * backend overview payload (the only client-side arithmetic is chart/legend
 * proportions of values the backend already provided). The dense table puts
 * the portfolio aggregates directly in the column headers (P&L and Mkt Value).
 *
 * Visual language: Investintell Cockpit (Carbon-inspired) — flat square
 * panels stacked with 1px separation, hairline borders, tabular numerals.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createPortfolio,
  deletePortfolio,
  deletePosition,
  fetchPortfolioOverview,
  fetchPortfolios,
  patchPortfolio,
  putPosition,
  type OverviewPosition,
  type PortfolioListItem,
  type PortfolioOverview,
  type PositionBody,
} from "@/lib/api/client";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { parseDecimal } from "@/lib/parse";
import { buildAllocationOption, type AllocationSlice } from "@/lib/charts/allocation";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { EChart } from "@/components/charts/EChart";
import { Card, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import { PortfolioNewsPanel } from "@/components/portfolio/PortfolioNewsPanel";

/** Carbon text field: flat, square, bottom rule only; accent rule on focus. */
const INPUT_CLASS =
  "h-[30px] px-2 bg-field border-0 border-b border-border-strong text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:outline-none " +
  "focus:border-b-2 focus:border-accent";

const BUTTON_CLASS =
  "h-[28px] px-3 bg-field border border-border-strong text-[12px] " +
  "text-text-secondary hover:bg-layer-hover hover:text-text-primary " +
  "transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

/** Shared retry policy: never retry 4xx (deterministic), retry 5xx/network twice. */
const retryPolicy = (failureCount: number, err: Error) =>
  !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
  failureCount < 2;

/** Display a share count without fake precision: 8 -> "8", 8.5 -> "8.50". */
const formatShares = (quantity: number) =>
  formatNumber(quantity, Number.isInteger(quantity) ? 0 : 2);

export function PortfolioOverviewView() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const portfoliosQuery = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const portfolios = portfoliosQuery.data;

  // Keep the selection valid: default to the first portfolio, fall back when
  // the selected one is deleted, clear when none remain.
  useEffect(() => {
    if (!portfolios) return;
    if (portfolios.length === 0) {
      setSelectedId(null);
    } else if (
      selectedId === null ||
      !portfolios.some((p) => p.id === selectedId)
    ) {
      setSelectedId(portfolios[0].id);
    }
  }, [portfolios, selectedId]);

  const selected = portfolios?.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <PageTitle title="Portfolio Overview">
        {portfolios && portfolios.length > 0 && (
          <PortfolioSwitcher
            portfolios={portfolios}
            selected={selected}
            onSelect={setSelectedId}
          />
        )}
      </PageTitle>

      {portfoliosQuery.isPending ? (
        <div
          aria-busy="true"
          aria-label="Loading portfolios"
          className="flex animate-pulse flex-col gap-px"
        >
          <div className="h-[88px] bg-surface-2" />
          <div className="h-[320px] bg-surface-2" />
        </div>
      ) : portfoliosQuery.isError ? (
        <ErrorPanel
          title="Failed to load portfolios"
          message={portfoliosQuery.error.message}
          onRetry={() => portfoliosQuery.refetch()}
        />
      ) : portfolios && portfolios.length === 0 ? (
        <EmptyState onCreated={setSelectedId} />
      ) : (
        <div className="flex flex-col gap-px">
          {selected && (
            <>
              <PortfolioManageBar selected={selected} onSelect={setSelectedId} />
              <OverviewSection key={selected.id} portfolioId={selected.id} />
              <PortfolioNewsPanel portfolioId={selected.id} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Shared bits ──────────────────────────────────────────────────────────── */

function ErrorPanel({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="ix-pad border border-loss bg-surface-2">
      <h2 className="mb-1 text-sm font-semibold text-loss">{title}</h2>
      <p className="break-words whitespace-pre-wrap text-[13px] text-text-secondary">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className={`mt-3 ${BUTTON_CLASS}`}
      >
        Retry
      </button>
    </div>
  );
}

/**
 * Click-to-edit numeric value: click shows a controlled input; Enter saves,
 * Escape (or blur) cancels. `parse` returns the API value (number or null) or
 * `undefined` when the raw text is invalid — invalid input never saves.
 */
function EditableValue({
  display,
  tone = "text-text-primary",
  initialText,
  ariaLabel,
  parse,
  onSave,
  pending = false,
}: {
  display: string;
  tone?: string;
  initialText: string;
  ariaLabel: string;
  parse: (raw: string) => number | null | undefined;
  onSave: (value: number | null) => void;
  pending?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setText(initialText);
          setInvalid(false);
          setEditing(true);
        }}
        disabled={pending}
        aria-label={`Edit ${ariaLabel}`}
        title={`Click to edit ${ariaLabel}`}
        className={`tabular-nums decoration-dotted decoration-[var(--color-text-muted)] underline-offset-4 hover:underline ${tone} disabled:opacity-50 disabled:cursor-wait`}
      >
        {pending ? "…" : display}
      </button>
    );
  }

  return (
    <input
      autoFocus
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          const parsed = parse(text);
          if (parsed === undefined) {
            setInvalid(true);
            return;
          }
          setEditing(false);
          onSave(parsed);
        } else if (e.key === "Escape") {
          setEditing(false);
        }
      }}
      onBlur={() => setEditing(false)}
      aria-label={ariaLabel}
      aria-invalid={invalid}
      className={`w-[90px] text-right tabular-nums ${INPUT_CLASS} ${
        invalid ? "border-b-2 border-loss focus:border-loss" : ""
      }`}
    />
  );
}

/** parse() for share counts: required, > 0. */
const parseShares = (raw: string): number | undefined => {
  const v = parseDecimal(raw);
  return Number.isFinite(v) && v > 0 ? v : undefined;
};

/** parse() for acquisition price: empty = unknown (null), else > 0. */
const parseCost = (raw: string): number | null | undefined => {
  if (raw.trim() === "") return null;
  const v = parseDecimal(raw);
  return Number.isFinite(v) && v > 0 ? v : undefined;
};

/** parse() for cash: required, >= 0. */
const parseCash = (raw: string): number | undefined => {
  const v = parseDecimal(raw);
  return Number.isFinite(v) && v >= 0 ? v : undefined;
};

/* ── Create form + empty state ────────────────────────────────────────────── */

function CreatePortfolioForm({
  onCreated,
  autoFocus = false,
}: {
  onCreated: (id: number) => void;
  autoFocus?: boolean;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const mutation = useMutation({
    mutationFn: (portfolioName: string) =>
      createPortfolio({ name: portfolioName, cash: 0 }),
    onSuccess: (portfolio) => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      onCreated(portfolio.id);
    },
  });

  const canSubmit = name.trim().length > 0 && !mutation.isPending;
  const submit = () => {
    if (canSubmit) mutation.mutate(name.trim());
  };

  return (
    <div>
      <div className="flex items-center gap-2">
        <input
          autoFocus={autoFocus}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="Portfolio name"
          aria-label="New portfolio name"
          className={`w-[180px] ${INPUT_CLASS}`}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className={BUTTON_CLASS}
        >
          {mutation.isPending ? "Creating…" : "Create"}
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="mt-1.5 break-words text-[12px] text-loss">
          {mutation.error.message}
        </p>
      )}
    </div>
  );
}

function EmptyState({ onCreated }: { onCreated: (id: number) => void }) {
  return (
    <div className="flex flex-col items-center gap-3 border border-border bg-surface-2 px-6 py-12">
      <h2 className="text-sm font-semibold text-text-primary">
        No portfolios yet
      </h2>
      <p className="text-[13px] text-text-secondary">
        Create your first portfolio to track positions, P&amp;L and news.
      </p>
      <CreatePortfolioForm onCreated={onCreated} autoFocus />
    </div>
  );
}

/* ── Portfolio switcher (segmented control in the title row) ──────────────── */

function PortfolioSwitcher({
  portfolios,
  selected,
  onSelect,
}: {
  portfolios: PortfolioListItem[];
  selected: PortfolioListItem | null;
  onSelect: (id: number | null) => void;
}) {
  const [creating, setCreating] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex h-[34px] items-stretch border border-border-strong text-[12px]">
        {portfolios.map((portfolio, index) => {
          const active = portfolio.id === selected?.id;
          return (
            <button
              key={portfolio.id}
              type="button"
              onClick={() => onSelect(portfolio.id)}
              aria-pressed={active}
              className={`flex items-center gap-[7px] px-3.5 transition-colors ${
                active
                  ? "bg-accent font-bold text-on-accent"
                  : `text-text-secondary hover:bg-layer-hover ${
                      index > 0 ? "border-l border-border" : ""
                    }`
              }`}
            >
              {portfolio.name}
              <span
                className={`tabular-nums ${
                  active ? "opacity-75" : "text-text-muted"
                }`}
              >
                {portfolio.position_count}
              </span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setCreating((open) => !open)}
          aria-label="Create portfolio"
          aria-expanded={creating}
          title="Create portfolio"
          className="flex items-center border-l border-border px-3 text-[16px] text-text-muted hover:bg-layer-hover hover:text-text-primary"
        >
          +
        </button>
      </div>
      {creating && (
        <CreatePortfolioForm
          autoFocus
          onCreated={(id) => {
            setCreating(false);
            onSelect(id);
          }}
        />
      )}
    </div>
  );
}

/* ── Manage bar (rename / cash / delete for the selected portfolio) ───────── */

function PortfolioManageBar({
  selected,
  onSelect,
}: {
  selected: PortfolioListItem;
  onSelect: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState("");

  const invalidatePortfolio = (id: number) => {
    queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    queryClient.invalidateQueries({ queryKey: ["overview", id] });
  };

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      patchPortfolio(id, { name }),
    onSuccess: (_, { id }) => {
      setRenaming(false);
      invalidatePortfolio(id);
    },
  });

  const cashMutation = useMutation({
    mutationFn: ({ id, cash }: { id: number; cash: number }) =>
      patchPortfolio(id, { cash }),
    onSuccess: (_, { id }) => invalidatePortfolio(id),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deletePortfolio(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.removeQueries({ queryKey: ["overview", id] });
      queryClient.removeQueries({ queryKey: ["portfolio-news", id] });
      onSelect(null); // the list effect reselects the first remaining portfolio
    },
  });

  const mutationError =
    renameMutation.error ?? cashMutation.error ?? deleteMutation.error;

  return (
    <div className="border border-border bg-surface-2 px-[var(--ix-pad)] py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-text-secondary">
        {renaming ? (
          <input
            autoFocus
            value={renameText}
            onChange={(e) => setRenameText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && renameText.trim().length > 0) {
                renameMutation.mutate({
                  id: selected.id,
                  name: renameText.trim(),
                });
              } else if (e.key === "Escape") {
                setRenaming(false);
              }
            }}
            onBlur={() => setRenaming(false)}
            aria-label="New name for selected portfolio"
            className={`w-[180px] ${INPUT_CLASS}`}
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              setRenameText(selected.name);
              setRenaming(true);
            }}
            disabled={renameMutation.isPending}
            className={BUTTON_CLASS}
          >
            {renameMutation.isPending ? "Renaming…" : "Rename"}
          </button>
        )}

        <span className="flex items-center gap-1.5">
          Cash:
          <EditableValue
            display={formatCurrency(selected.cash)}
            initialText={String(selected.cash)}
            ariaLabel={`cash for ${selected.name}`}
            parse={parseCash}
            onSave={(value) => {
              // parseCash never yields null; the guard keeps types honest.
              if (value !== null) {
                cashMutation.mutate({ id: selected.id, cash: value });
              }
            }}
            pending={cashMutation.isPending}
          />
        </span>

        <button
          type="button"
          onClick={() => {
            // Native confirm: deletion is destructive and cascades positions.
            if (window.confirm(`Delete portfolio "${selected.name}"?`)) {
              deleteMutation.mutate(selected.id);
            }
          }}
          disabled={deleteMutation.isPending}
          className={`${BUTTON_CLASS} ml-auto hover:text-loss hover:border-loss`}
        >
          {deleteMutation.isPending ? "Deleting…" : "Delete"}
        </button>
      </div>

      {mutationError && (
        <p role="alert" className="mt-1.5 break-words text-[12px] text-loss">
          {mutationError.message}
        </p>
      )}
    </div>
  );
}

/* ── Overview (KPIs + allocation + table) ─────────────────────────────────── */

function OverviewSection({ portfolioId }: { portfolioId: number }) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const overviewQuery = useQuery({
    queryKey: ["overview", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioOverview(portfolioId, signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });

  if (overviewQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading portfolio overview"
        className="h-[320px] animate-pulse bg-surface-2"
      />
    );
  }
  if (overviewQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load portfolio overview"
        message={overviewQuery.error.message}
        onRetry={() => overviewQuery.refetch()}
      />
    );
  }

  const overview = overviewQuery.data;
  return (
    <>
      <KpiStrip overview={overview} />
      {colors && overview.positions.length > 0 && (
        <AllocationPanel overview={overview} colors={colors} />
      )}
      <PositionsTable overview={overview} portfolioId={portfolioId} />
    </>
  );
}

/** Carbon KPI tile strip — 1px-gap grid over the hairline border color. */
function KpiStrip({ overview }: { overview: PortfolioOverview }) {
  const { aggregates, positions } = overview;
  // Display-only ratio of two backend-provided values (cash share of total).
  const cashWeight =
    aggregates.total_value > 0 ? aggregates.cash / aggregates.total_value : null;

  return (
    <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
      <KpiTile
        label="Total Value"
        value={formatCurrency(aggregates.total_value)}
      />
      <KpiTile
        label="Total P&L"
        value={
          aggregates.total_pnl !== null
            ? formatCurrency(aggregates.total_pnl, { signed: true })
            : "—"
        }
        tone={
          aggregates.total_pnl !== null
            ? valueTone(aggregates.total_pnl)
            : "text-text-muted"
        }
        detail={
          aggregates.total_pnl_pct !== null
            ? formatPercent(aggregates.total_pnl_pct, 2, { signed: true })
            : undefined
        }
        detailTone={
          aggregates.total_pnl_pct !== null
            ? valueTone(aggregates.total_pnl_pct)
            : "text-text-muted"
        }
      />
      <KpiTile
        label="Mkt Value"
        value={formatCurrency(aggregates.total_market_value)}
      />
      <KpiTile
        label="Cash"
        value={formatCurrency(aggregates.cash)}
        detail={
          cashWeight !== null
            ? `${formatPercent(cashWeight, 1)} weight`
            : undefined
        }
      />
      <KpiTile
        label="Positions"
        value={formatNumber(positions.length, 0)}
        detail={
          aggregates.as_of ? `EOD ${formatDate(aggregates.as_of)}` : undefined
        }
      />
    </div>
  );
}

/**
 * Allocation donut + square-swatch legend. Slice values are the backend's
 * per-position market values (plus cash); percentages shown are the slices'
 * shares of the donut total — chart proportions, not finance.
 */
function AllocationPanel({
  overview,
  colors,
}: {
  overview: PortfolioOverview;
  colors: ChartColors;
}) {
  const { aggregates, positions } = overview;

  const slices = useMemo<AllocationSlice[]>(() => {
    const positionSlices = positions.map((position) => ({
      name: position.ticker,
      value: position.market_value,
    }));
    return aggregates.cash > 0
      ? [...positionSlices, { name: "Cash", value: aggregates.cash }]
      : positionSlices;
  }, [positions, aggregates.cash]);

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const option = useMemo(
    () => buildAllocationOption(slices, colors),
    [slices, colors],
  );

  return (
    <Card title="Allocation">
      <div className="flex flex-wrap items-center gap-[18px]">
        <EChart option={option} className="h-[150px] w-[150px] shrink-0" />
        <div className="flex min-w-[150px] max-w-[260px] flex-1 flex-col gap-1.5 tabular-nums">
          {slices.map((slice, i) => (
            <div
              key={slice.name}
              className="flex items-center gap-[9px] text-[12px]"
            >
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0"
                style={{
                  background: colors.categories[i % colors.categories.length],
                }}
              />
              <span className="flex-1 text-text-secondary">{slice.name}</span>
              <span className="font-bold text-text-primary">
                {total > 0 ? formatPercent(slice.value / total, 1) : "—"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

/* ── Positions table ──────────────────────────────────────────────────────── */

const TH_BASE =
  "sticky top-0 bg-field px-2.5 py-2 ix-fs font-semibold " +
  "text-text-secondary border-b border-border-strong whitespace-nowrap";
// Tailwind class conflicts (text-left vs text-right) resolve by stylesheet
// order, not attribute order — keep alignment out of the shared base.
const TH_CLASS = `${TH_BASE} text-right`;

function PositionsTable({
  overview,
  portfolioId,
}: {
  overview: PortfolioOverview;
  portfolioId: number;
}) {
  const queryClient = useQueryClient();
  const { aggregates, positions } = overview;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] });
    queryClient.invalidateQueries({ queryKey: ["portfolios"] }); // position_count
  };

  // Two mutations over the same PUT endpoint so the Add row and the inline
  // edits surface their errors independently (an add typo must not look like
  // an edit failure).
  const addMutation = useMutation({
    mutationFn: ({ ticker, body }: { ticker: string; body: PositionBody }) =>
      putPosition(portfolioId, ticker, body),
    onSuccess: invalidate,
  });
  const editMutation = useMutation({
    mutationFn: ({ ticker, body }: { ticker: string; body: PositionBody }) =>
      putPosition(portfolioId, ticker, body),
    onSuccess: invalidate,
  });
  const removeMutation = useMutation({
    mutationFn: (ticker: string) => deletePosition(portfolioId, ticker),
    onSuccess: invalidate,
  });

  const rowError = editMutation.error ?? removeMutation.error;

  return (
    <section className="border border-border bg-surface-2">
      <div className="px-[var(--ix-pad)] py-3">
        <h2 className="ix-label m-0">
          Positions
          <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
            {overview.name}
          </span>
        </h2>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse ix-fs tabular-nums">
          <thead>
            <tr className="align-top">
              <th className={`${TH_BASE} text-left pl-[var(--ix-pad)]`}>
                Ticker
              </th>
              <th className={TH_CLASS}>Last</th>
              <th className={TH_CLASS}>Change</th>
              <th className={TH_CLASS}>Cost</th>
              <th className={TH_CLASS}>Shares</th>
              {/* Aggregates live IN the column headers (Tiingo pattern, D6). */}
              <th className={TH_CLASS}>
                P&amp;L
                <span
                  className={`block text-[11px] font-bold tabular-nums ${
                    aggregates.total_pnl !== null
                      ? valueTone(aggregates.total_pnl)
                      : "text-text-muted"
                  }`}
                >
                  {aggregates.total_pnl !== null
                    ? formatCurrency(aggregates.total_pnl, { signed: true })
                    : "—"}
                  {aggregates.total_pnl_pct !== null &&
                    ` (${formatPercent(aggregates.total_pnl_pct, 2, { signed: true })})`}
                </span>
              </th>
              <th className={TH_CLASS}>
                Mkt Value
                <span className="block text-[11px] font-bold tabular-nums text-text-primary">
                  {formatCurrency(aggregates.total_market_value)}
                </span>
              </th>
              <th
                className={`${TH_CLASS} w-[36px] pr-[var(--ix-pad)]`}
                aria-label="Row actions"
              />
            </tr>
          </thead>
          <tbody>
            <AddPositionRow
              pending={addMutation.isPending}
              error={addMutation.error?.message ?? null}
              onAdd={async (ticker, body) => {
                try {
                  await addMutation.mutateAsync({ ticker, body });
                  return true;
                } catch {
                  // Not a swallow: the failure is surfaced via
                  // addMutation.error inside the Add row; the boolean only
                  // tells the row whether to clear its inputs.
                  return false;
                }
              }}
              onDirty={() => addMutation.reset()}
            />
            {positions.map((position, index) => (
              <PositionRow
                key={position.ticker}
                position={position}
                zebra={index % 2 === 1}
                pending={
                  (editMutation.isPending &&
                    editMutation.variables?.ticker === position.ticker) ||
                  (removeMutation.isPending &&
                    removeMutation.variables === position.ticker)
                }
                onEdit={(body) =>
                  editMutation.mutate({ ticker: position.ticker, body })
                }
                onRemove={() => removeMutation.mutate(position.ticker)}
              />
            ))}
            {positions.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="py-4 text-center text-[13px] text-text-muted"
                >
                  No positions yet — add one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {rowError && (
        <p
          role="alert"
          className="break-words px-[var(--ix-pad)] py-2 text-[12px] text-loss"
        >
          {rowError.message}
        </p>
      )}

      {/* Footer: EOD tag + cash + total value */}
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-t border-border px-[var(--ix-pad)] py-2.5 text-[12px] text-text-secondary">
        {aggregates.as_of && (
          <span className="border border-border bg-field px-[7px] py-[2px] text-[10px] text-text-muted">
            EOD · {formatDate(aggregates.as_of)}
          </span>
        )}
        <span className="tabular-nums">Cash: {formatCurrency(aggregates.cash)}</span>
        <span className="ml-auto font-bold tabular-nums text-text-primary">
          Total value: {formatCurrency(aggregates.total_value)}
        </span>
      </div>
    </section>
  );
}

function AddPositionRow({
  pending,
  error,
  onAdd,
  onDirty,
}: {
  pending: boolean;
  error: string | null;
  /** Resolves true on success — only then are the inputs cleared. */
  onAdd: (ticker: string, body: PositionBody) => Promise<boolean>;
  onDirty: () => void;
}) {
  const [ticker, setTicker] = useState("");
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");

  const parsedShares = parseShares(shares);
  const parsedCost = parseCost(cost);
  const canAdd =
    ticker.trim().length > 0 &&
    parsedShares !== undefined &&
    parsedCost !== undefined &&
    !pending;

  const submit = () => {
    if (!canAdd) return;
    void onAdd(ticker.trim().toUpperCase(), {
      quantity: parsedShares,
      acq_price: parsedCost,
    }).then((ok) => {
      if (ok) {
        setTicker("");
        setShares("");
        setCost("");
      }
    });
  };

  return (
    <>
      <tr className="border-b border-border bg-zebra">
        <td className="ix-cell pl-[var(--ix-pad)] pr-2.5">
          <input
            value={ticker}
            onChange={(e) => {
              setTicker(e.target.value.toUpperCase());
              onDirty();
            }}
            placeholder="TICKER"
            aria-label="New position ticker"
            className={`w-[110px] uppercase ${INPUT_CLASS}`}
          />
        </td>
        <td className="px-2.5" />
        <td className="px-2.5" />
        <td className="px-2.5 text-right">
          <input
            value={cost}
            onChange={(e) => {
              setCost(e.target.value);
              onDirty();
            }}
            placeholder="Cost (opt.)"
            aria-label="New position acquisition price (optional)"
            aria-invalid={cost.trim() !== "" && parsedCost === undefined}
            className={`w-[90px] text-right tabular-nums ${INPUT_CLASS} ${
              cost.trim() !== "" && parsedCost === undefined
                ? "border-b-2 border-loss focus:border-loss"
                : ""
            }`}
          />
        </td>
        <td className="px-2.5 text-right">
          <input
            value={shares}
            onChange={(e) => {
              setShares(e.target.value);
              onDirty();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Shares"
            aria-label="New position share count"
            aria-invalid={shares.trim() !== "" && parsedShares === undefined}
            className={`w-[90px] text-right tabular-nums ${INPUT_CLASS} ${
              shares.trim() !== "" && parsedShares === undefined
                ? "border-b-2 border-loss focus:border-loss"
                : ""
            }`}
          />
        </td>
        <td className="px-2.5" />
        <td className="px-2.5 text-right">
          <button
            type="button"
            onClick={submit}
            disabled={!canAdd}
            className={BUTTON_CLASS}
          >
            {pending ? "Adding…" : "Add"}
          </button>
        </td>
        <td className="pr-[var(--ix-pad)]" />
      </tr>
      {error && (
        <tr className="border-b border-border">
          <td colSpan={8} className="px-[var(--ix-pad)] py-1.5">
            <p role="alert" className="break-words text-[12px] text-loss">
              {error}
            </p>
          </td>
        </tr>
      )}
    </>
  );
}

function PositionRow({
  position,
  zebra,
  pending,
  onEdit,
  onRemove,
}: {
  position: OverviewPosition;
  zebra: boolean;
  pending: boolean;
  onEdit: (body: PositionBody) => void;
  onRemove: () => void;
}) {
  const changeTone =
    position.change !== null ? valueTone(position.change) : "text-text-muted";
  const pnlTone =
    position.pnl !== null ? valueTone(position.pnl) : "text-text-muted";

  return (
    <tr
      className={`border-b border-border last:border-b-0 hover:bg-accent-wash ${
        zebra ? "bg-zebra" : ""
      }`}
    >
      <td className="ix-cell pl-[var(--ix-pad)] pr-2.5">
        <Link
          href={`/stocks/${encodeURIComponent(position.ticker)}`}
          className="font-bold text-accent hover:text-accent-strong transition-colors"
        >
          {position.ticker}
        </Link>
        {position.name && (
          <span className="block max-w-[220px] truncate text-[10px] text-text-muted">
            {position.name}
          </span>
        )}
      </td>
      <td className="ix-cell px-2.5 text-right tabular-nums text-text-primary">
        {formatCurrency(position.last_close)}
      </td>
      <td className={`ix-cell px-2.5 text-right tabular-nums ${changeTone}`}>
        {position.change !== null && position.change_pct !== null ? (
          <>
            {formatCurrency(position.change, { signed: true })}
            <span className="block text-[11px]">
              {formatPercent(position.change_pct, 2, { signed: true })}
            </span>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="ix-cell px-2.5 text-right">
        <EditableValue
          display={
            position.acq_price !== null
              ? formatCurrency(position.acq_price)
              : "—"
          }
          tone="text-text-secondary"
          initialText={position.acq_price !== null ? String(position.acq_price) : ""}
          ariaLabel={`acquisition price for ${position.ticker}`}
          parse={parseCost}
          onSave={(acqPrice) =>
            onEdit({ quantity: position.quantity, acq_price: acqPrice })
          }
          pending={pending}
        />
      </td>
      <td className="ix-cell px-2.5 text-right">
        <EditableValue
          display={formatShares(position.quantity)}
          tone="text-text-secondary"
          initialText={String(position.quantity)}
          ariaLabel={`share count for ${position.ticker}`}
          parse={parseShares}
          onSave={(quantity) => {
            // parseShares never yields null; the guard keeps types honest.
            if (quantity !== null) {
              onEdit({ quantity, acq_price: position.acq_price });
            }
          }}
          pending={pending}
        />
      </td>
      <td className={`ix-cell px-2.5 text-right font-bold tabular-nums ${pnlTone}`}>
        {position.pnl !== null && position.pnl_pct !== null ? (
          <>
            {formatCurrency(position.pnl, { signed: true })}
            <span className="block text-[11px] font-normal">
              {formatPercent(position.pnl_pct, 2, { signed: true })}
            </span>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="ix-cell px-2.5 text-right font-bold tabular-nums text-text-primary">
        {formatCurrency(position.market_value)}
      </td>
      <td className="ix-cell pl-2 pr-[var(--ix-pad)] text-right">
        <button
          type="button"
          onClick={onRemove}
          disabled={pending}
          aria-label={`Remove position ${position.ticker}`}
          title={`Remove ${position.ticker}`}
          className="px-1.5 py-0.5 text-text-muted hover:bg-layer-hover hover:text-loss transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ×
        </button>
      </td>
    </tr>
  );
}
