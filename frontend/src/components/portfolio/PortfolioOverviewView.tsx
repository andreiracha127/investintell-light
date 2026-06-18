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
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Grid } from "@highcharts/grid-pro";

import {
  createPortfolio,
  deletePortfolio,
  deletePosition,
  fetchPortfolioOverview,
  fetchPortfolios,
  patchPortfolio,
  putPosition,
  type PortfolioListItem,
  type PortfolioOverview,
  type PositionBody,
} from "@/lib/api/client";
import {
  formatCompact,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { parseDecimal } from "@/lib/parse";
import { type AllocationSlice } from "@/lib/charts/types";
import { buildHcAllocationOption } from "@/lib/charts/hc/allocation";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { DataGrid } from "@/components/ui/DataGrid";
import { positionsToGridOptions, POSITION_COLS } from "@/lib/grid/positionsGridOptions";
import type { TickDir } from "@/lib/grid/liveFlash";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { Card, InfoDot, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import { retryPolicy } from "@/components/screener/shared";
import { PortfolioNewsPanel } from "@/components/portfolio/PortfolioNewsPanel";
import { PortfolioLookthroughSection } from "@/components/portfolio/PortfolioLookthroughSection";
import { PortfolioRebalanceSection } from "@/components/portfolio/PortfolioRebalanceSection";
import { PortfolioPerformanceView } from "@/components/portfolio/PortfolioPerformanceView";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import type { Options } from "highcharts";

/** Carbon text field: flat, square, bottom rule only; accent rule on focus. */
const INPUT_CLASS =
  "h-[30px] px-2 bg-field border-0 border-b border-border-strong text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:outline-none " +
  "focus:border-b-2 focus:border-accent";

const BUTTON_CLASS =
  "h-[28px] px-3 bg-field border border-border-strong text-[12px] " +
  "text-text-secondary hover:bg-layer-hover hover:text-text-primary " +
  "transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

/**
 * Muted gain/loss background that the live-tick flash fades from (to
 * transparent) when re-triggered via the Web Animations API. Returns a `var()`
 * reference (resolved against the animated element), mirroring grid-theme.css's
 * `@keyframes ix-grid-flash-up/-down`. 0 (unchanged) → null (no flash).
 */
function flashTintForDir(dir: TickDir): string | null {
  if (dir === 1) return "var(--color-gain-muted)";
  if (dir === -1) return "var(--color-loss-muted)";
  return null;
}

const PORTFOLIO_SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "performance", label: "Performance" },
  { id: "exposure", label: "Exposure" },
  { id: "rebalance", label: "Rebalancing" },
  { id: "news", label: "News" },
] as const;

type PortfolioSectionId = (typeof PORTFOLIO_SECTIONS)[number]["id"];

function portfolioSectionFromParam(value: string | null): PortfolioSectionId {
  return PORTFOLIO_SECTIONS.some((section) => section.id === value)
    ? (value as PortfolioSectionId)
    : "overview";
}

export function PortfolioOverviewView() {
  const searchParams = useSearchParams();
  const activeSection = portfolioSectionFromParam(searchParams.get("section"));
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
              <PortfolioSectionTabs activeSection={activeSection} />
              {activeSection === "overview" && (
                <OverviewSection key={selected.id} portfolioId={selected.id} />
              )}
              {activeSection === "performance" && (
                <PerformanceSection key={selected.id} portfolioId={selected.id} />
              )}
              {activeSection === "exposure" && (
                <PortfolioLookthroughSection portfolioId={selected.id} />
              )}
              {activeSection === "rebalance" && (
                <PortfolioRebalanceSection portfolioId={selected.id} />
              )}
              {activeSection === "news" && (
                <PortfolioNewsPanel portfolioId={selected.id} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PortfolioSectionTabs({
  activeSection,
}: {
  activeSection: PortfolioSectionId;
}) {
  return (
    <nav aria-label="Portfolio sections" className="border border-border bg-field">
      <div role="tablist" aria-label="Portfolio sections" className="flex overflow-x-auto">
        {PORTFOLIO_SECTIONS.map((section) => {
          const active = activeSection === section.id;
          return (
            <Link
              key={section.id}
              href={`/portfolio?section=${section.id}`}
              scroll={false}
              role="tab"
              aria-selected={active}
              aria-current={active ? "page" : undefined}
              className={`flex h-[38px] flex-none items-center border-b-2 px-[18px] text-[12.5px] transition-colors ${
                active
                  ? "border-accent bg-[var(--color-accent-wash)] font-bold text-accent"
                  : "border-transparent text-text-secondary hover:bg-layer-hover hover:text-text-primary"
              }`}
            >
              {section.label}
            </Link>
          );
        })}
      </div>
    </nav>
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
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Select portfolio"
          onClick={() => setOpen((o) => !o)}
          className="flex h-[34px] min-w-[210px] items-center gap-2.5 border border-border-strong bg-field px-3 text-left text-[12.5px] text-text-primary"
        >
          <span className="flex min-w-0 flex-1 items-center gap-[7px]">
            <span aria-hidden className="h-[9px] w-[9px] flex-none bg-accent" />
            <span className="truncate font-bold">{selected?.name ?? "—"}</span>
            <span className="flex-none tabular-nums text-text-muted">
              {selected?.position_count ?? ""}
            </span>
          </span>
          <span
            aria-hidden
            className={`flex-none text-[10px] text-text-muted transition-transform ${
              open ? "rotate-180" : ""
            }`}
          >
            ▾
          </span>
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-[55]" onClick={() => setOpen(false)} />
            <ul
              role="listbox"
              aria-label="Portfolios"
              className="absolute left-0 top-[38px] z-[56] max-h-[300px] min-w-[240px] max-w-[320px] overflow-y-auto border border-border-strong bg-surface-2 py-1 shadow-[0_6px_20px_rgba(0,0,0,0.16)]"
            >
              {portfolios.map((p) => {
                const active = p.id === selected?.id;
                return (
                  <li key={p.id} role="option" aria-selected={active}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(p.id);
                        setOpen(false);
                      }}
                      className={`flex w-full items-center gap-[9px] px-3 py-2 text-left text-[12.5px] ${
                        active
                          ? "bg-[var(--color-accent-wash)] font-bold text-accent"
                          : "text-text-primary hover:bg-layer-hover"
                      }`}
                    >
                      <span
                        aria-hidden
                        className="h-2 w-2 flex-none"
                        style={{
                          background: active
                            ? "var(--color-accent)"
                            : "var(--color-border-strong)",
                        }}
                      />
                      <span className="min-w-0 flex-1 truncate">{p.name}</span>
                      <span className="flex-none tabular-nums text-text-muted">
                        {p.position_count}
                      </span>
                      <span className="w-3 flex-none font-bold text-accent">
                        {active ? "✓" : ""}
                      </span>
                    </button>
                  </li>
                );
              })}
              <li
                role="option"
                aria-selected={false}
                className="mt-1 border-t border-border pt-0.5"
              >
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    setCreating(true);
                  }}
                  className="flex w-full items-center gap-[9px] px-3 py-2 text-left text-[12.5px] text-text-secondary hover:bg-layer-hover"
                >
                  <span aria-hidden className="w-2 flex-none text-center text-text-muted">
                    +
                  </span>
                  <span>New portfolio…</span>
                </button>
              </li>
            </ul>
          </>
        )}
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

  // Shares the overview cache with the section views — only for the EOD as-of.
  const overviewQuery = useQuery({
    queryKey: ["overview", selected.id],
    queryFn: ({ signal }) => fetchPortfolioOverview(selected.id, signal),
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const asOf = overviewQuery.data?.aggregates.as_of ?? null;

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

        {asOf && (
          <span className="flex items-center gap-1.5 text-text-muted">
            Last updated
            <span className="tabular-nums text-text-secondary">{formatDate(asOf)}</span>
            <InfoDot tip="End-of-day closing prices, updated after the market closes." />
          </span>
        )}

        <Link
          href={`/builder?portfolio=${selected.id}`}
          className={`${BUTTON_CLASS} ml-auto inline-flex items-center hover:border-accent hover:text-accent`}
        >
          Optimize in Builder →
        </Link>

        <button
          type="button"
          onClick={() => {
            // Native confirm: deletion is destructive and cascades positions.
            if (window.confirm(`Delete portfolio "${selected.name}"?`)) {
              deleteMutation.mutate(selected.id);
            }
          }}
          disabled={deleteMutation.isPending}
          className={`${BUTTON_CLASS} hover:text-loss hover:border-loss`}
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
    <div className="flex flex-col gap-px">
      <KpiStrip overview={overview} />
      {colors && overview.positions.length > 0 && (
        <div className="grid items-stretch gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
          <AllocationPanel overview={overview} colors={colors} />
          <NavPanel overview={overview} colors={colors} />
        </div>
      )}
      <PositionsTable overview={overview} portfolioId={portfolioId} />
    </div>
  );
}

/* ── Performance (synthetic NAV + contribution breakdown) ─────────────────── */

function PerformanceSection({ portfolioId }: { portfolioId: number }) {
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
        aria-label="Loading performance"
        className="flex flex-col gap-px"
      >
        <div className="h-[400px] animate-pulse bg-surface-2" />
        <div className="h-[340px] animate-pulse bg-surface-2" />
      </div>
    );
  }
  if (overviewQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load portfolio"
        message={overviewQuery.error.message}
        onRetry={() => overviewQuery.refetch()}
      />
    );
  }
  return <PortfolioPerformanceView overview={overviewQuery.data} />;
}

/* ── Synthetic NAV mini-panel (Overview, beside the allocation donut) ─────── */

const NAV_RANGES = [
  { key: "1M", label: "1M", bars: 21 },
  { key: "6M", label: "6M", bars: 126 },
  { key: "1Y", label: "1Y", bars: 252 },
  { key: "MAX", label: "Max", bars: Infinity },
] as const;
type NavRangeKey = (typeof NAV_RANGES)[number]["key"];

const SYNTH_NAV_TIP =
  "Reconstructed portfolio value over time from the current holdings — illustrative, not a booked track record.";

function NavPanel({
  overview,
  colors,
}: {
  overview: PortfolioOverview;
  colors: ChartColors;
}) {
  const { recon, isLoading, isError } = usePortfolioNav(overview);
  const [range, setRange] = useState<NavRangeKey>("1Y");

  const bars = NAV_RANGES.find((r) => r.key === range)!.bars;
  const slice = useMemo(
    () => (bars === Infinity ? recon.nav : recon.nav.slice(-bars)),
    [recon.nav, bars],
  );
  const change =
    slice.length > 1 ? slice[slice.length - 1]![1] / slice[0]![1] - 1 : 0;

  const option = useMemo<Options | null>(() => {
    if (slice.length === 0) return null;
    const fill0 = `${colors.accent}30`;
    const fill1 = `${colors.accent}00`;
    return {
      chart: { type: "areaspline", height: 200 },
      legend: { enabled: false },
      xAxis: { type: "datetime", crosshair: true, tickPixelInterval: 84 },
      yAxis: {
        title: { text: undefined },
        labels: {
          formatter() {
            return `$${formatCompact(this.value as number)}`;
          },
        },
      },
      tooltip: {
        formatter() {
          const ctx = this as unknown as { x: number; y: number };
          return `${formatTimestampDate(ctx.x)}<br/>NAV: <b>${formatCurrency(ctx.y)}</b>`;
        },
      },
      series: [
        {
          type: "areaspline",
          name: "NAV",
          data: slice,
          color: colors.accent,
          lineWidth: 1.8,
          marker: { enabled: false },
          fillColor: {
            linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
            stops: [
              [0, fill0],
              [1, fill1],
            ],
          },
        },
      ],
    };
  }, [slice, colors]);

  return (
    <section className="ix-pad flex flex-col border border-border bg-surface-2">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <h2 className="ix-label m-0 flex items-center gap-1.5">
          Synthetic NAV
          <InfoDot tip={SYNTH_NAV_TIP} />
        </h2>
        <div className="flex items-center gap-2.5">
          <span className={`text-[12px] font-bold tabular-nums ${valueTone(change)}`}>
            {formatPercent(change, 2, { signed: true })}
          </span>
          <div
            role="group"
            aria-label="NAV range"
            className="flex border border-border-strong"
          >
            {NAV_RANGES.map((r) => {
              const active = r.key === range;
              return (
                <button
                  key={r.key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setRange(r.key)}
                  className={`h-[26px] border-r border-border-strong px-2.5 text-[11px] last:border-r-0 ${
                    active
                      ? "bg-accent font-bold text-on-accent"
                      : "text-text-muted hover:bg-layer-hover"
                  }`}
                >
                  {r.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      {isLoading && slice.length === 0 ? (
        <div className="h-[200px] flex-1 animate-pulse bg-layer-active" />
      ) : option ? (
        <HighchartsChart options={option} className="h-[200px] w-full flex-1" />
      ) : (
        <div className="flex h-[200px] flex-1 items-center justify-center px-4 text-center text-[12px] text-text-muted">
          {isError
            ? "Could not load price history."
            : "Not enough price history to reconstruct a NAV."}
        </div>
      )}
    </section>
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
  const options = useMemo(
    () => buildHcAllocationOption(slices, colors),
    [slices, colors],
  );

  return (
    <Card title="Allocation" subtitle="· share by market value">
      <div className="flex flex-col gap-3">
        <HighchartsChart options={options} className="h-[190px] w-full" />
        <div className="ix-thin-scroll flex max-h-[128px] flex-col overflow-y-auto tabular-nums">
          {slices.map((slice, i) => (
            <div
              key={slice.name}
              className="flex items-center gap-[9px] border-b border-border py-[3px] text-[12px] last:border-b-0"
            >
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0"
                style={{
                  background:
                    slice.name === "Cash"
                      ? colors.barMute
                      : colors.categories[i % colors.categories.length],
                }}
              />
              <span className="min-w-0 flex-1 truncate font-bold text-text-primary">
                {slice.name}
              </span>
              <span className="shrink-0 text-text-muted">
                ${formatCompact(slice.value)}
              </span>
              <span className="w-12 shrink-0 text-right font-bold text-text-primary">
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

  // Stabilize the edit/remove handlers so the gridOptions memo below doesn't
  // re-run on every render. React Query's `mutate` is referentially stable, so
  // we depend on `editMutation.mutate` / `removeMutation.mutate` rather than the
  // whole mutation objects (which are fresh each render). Deps are only the
  // values these handlers actually read: positions (for the sibling field) and
  // portfolioId/queryClient (for the revert invalidation).
  const editMutate = editMutation.mutate;
  const removeMutate = removeMutation.mutate;
  const onEditShares = useCallback(
    (ticker: string, value: number) => {
      if (Number.isFinite(value) && value > 0) {
        const pos = positions.find((p) => p.ticker === ticker);
        editMutate({
          ticker,
          body: { quantity: value, acq_price: pos?.acq_price ?? null },
        });
      } else {
        queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] });
      }
    },
    [positions, portfolioId, queryClient, editMutate],
  );
  const onEditCost = useCallback(
    (ticker: string, value: number | null) => {
      if (value === null || (Number.isFinite(value) && value > 0)) {
        const pos = positions.find((p) => p.ticker === ticker);
        if (pos) {
          editMutate({
            ticker,
            body: { quantity: pos.quantity, acq_price: value },
          });
        }
      } else {
        queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] });
      }
    },
    [positions, portfolioId, queryClient, editMutate],
  );
  const onRemove = useCallback(
    (ticker: string) => removeMutate(ticker),
    [removeMutate],
  );

  // Wire the grid's pure edit/remove callbacks to the mutations. Invalid edits
  // never persist; they re-fetch the overview so the grid reverts the cell to
  // the server value. Only recomputes when the position DATA (overview) or a
  // stabilized handler changes — never on an unrelated re-render.
  const gridOptions = useMemo(
    () =>
      positionsToGridOptions(overview, {
        onEditShares,
        onEditCost,
        onRemove,
      }),
    [overview, onEditShares, onEditCost, onRemove],
  );

  // ── Live price ticks (path: targeted DOM flash) ──────────────────────────
  // Subscribe to the rendered positions' tickers. The hook degrades to a no-op
  // ("off") without a configured feed, so this is silent when no WS is set.
  const tickers = useMemo(() => positions.map((p) => p.ticker), [positions]);
  const { ticks, status: feedStatus } = useLiveTicks(tickers);

  // The live Grid instance, captured via DataGrid's onReady. We update the
  // "Last" cell DOM directly instead of re-running positionsToGridOptions +
  // grid.update(), which would clobber an in-progress Pro cell edit (cost /
  // shares). Positions render NON-virtualized, so every row is in viewport.rows.
  const gridRef = useRef<Grid | null>(null);
  // Bumped whenever DataGrid re-fires onReady (after create AND after every
  // update()). Adding it to the live-tick effect deps re-flushes the current
  // ticks onto a (re)built viewport — otherwise grid.update() (overview
  // refetch, or a cost/shares edit re-memoizing gridOptions) rebuilds the
  // cells and lastFormatter reverts "Last" to the EOD close until the next
  // tick. It also covers the case where the grid becomes ready after the first
  // tick batch arrives. setGridEpoch only fires inside onReady (a grid-lib
  // callback), never during render, so there's no render loop.
  const [gridEpoch, setGridEpoch] = useState(0);

  useEffect(() => {
    const vp = gridRef.current?.viewport;
    if (!vp) return;
    for (const row of vp.rows) {
      const sym = String(row.getCell(POSITION_COLS.ticker)?.value ?? "");
      const tick = ticks[sym];
      if (!tick) continue;
      const el = row.getCell(POSITION_COLS.last)?.htmlElement;
      if (!el) continue;
      el.textContent = formatCurrency(tick.price);
      const tint = flashTintForDir(tick.dir);
      if (!tint) continue;
      // Re-trigger the gain/loss flash without touching layout. The old path
      // removed/added a CSS class and read `el.offsetWidth` to force a reflow
      // per row — N forced synchronous layouts per frame (layout thrashing).
      // The Web Animations API restarts the animation outright (each call gets
      // a fresh Animation), so no reflow read is needed. Keyframes mirror
      // grid-theme.css's `ix-grid-flash-*`: muted gain/loss bg fading to
      // transparent over 0.6s ease-out. `var()` resolves against `el`.
      el.animate(
        [{ background: tint }, { background: "transparent" }],
        { duration: 600, easing: "ease-out" },
      );
    }
  }, [ticks, gridEpoch]);

  const liveActive = feedStatus === "live" && Object.keys(ticks).length > 0;

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

      <AddPositionRowForm
        pending={addMutation.isPending}
        error={addMutation.error?.message ?? null}
        onAdd={async (ticker, body) => {
          try {
            await addMutation.mutateAsync({ ticker, body });
            return true;
          } catch {
            // Not a swallow: the failure is surfaced via addMutation.error in
            // the form; the boolean only tells the form whether to clear inputs.
            return false;
          }
        }}
        onDirty={() => addMutation.reset()}
      />
      <div className="border-t border-border">
        <DataGrid
          options={gridOptions}
          className="min-h-[120px] w-full"
          onReady={(g) => {
            gridRef.current = g;
            setGridEpoch((n) => n + 1);
          }}
        />
      </div>
      {positions.length === 0 && (
        <p className="py-4 text-center text-[13px] text-text-muted">
          No positions yet — add one above.
        </p>
      )}

      {rowError && (
        <p
          role="alert"
          className="break-words px-[var(--ix-pad)] py-2 text-[12px] text-loss"
        >
          {rowError.message}
        </p>
      )}

      {/* Footer: LIVE/EOD badge + cash + total value */}
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-t border-border px-[var(--ix-pad)] py-2.5 text-[12px] text-text-secondary">
        {(liveActive || aggregates.as_of) && (
          <span className="border border-border bg-field px-[7px] py-[2px] text-[10px] text-text-muted">
            {liveActive ? (
              <span className="text-gain">● LIVE</span>
            ) : (
              <>EOD · {formatDate(aggregates.as_of!)}</>
            )}
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

/**
 * Add-position form. The grid does not host a native editable "add" row, so
 * this lives as a contiguous field row above the grid (same panel, 1px rule),
 * preserving the original UX. Same validation/submit logic as before.
 */
function AddPositionRowForm({
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
    <div className="border-b border-border bg-zebra px-[var(--ix-pad)] py-2.5">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <label className="flex flex-col gap-1">
          <span className="ix-fs text-text-muted">Ticker</span>
          <input
            value={ticker}
            onChange={(e) => {
              setTicker(e.target.value.toUpperCase());
              onDirty();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="TICKER"
            aria-label="New position ticker"
            className={`w-[110px] uppercase ${INPUT_CLASS}`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="ix-fs text-text-muted">Cost</span>
          <input
            value={cost}
            onChange={(e) => {
              setCost(e.target.value);
              onDirty();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
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
        </label>
        <label className="flex flex-col gap-1">
          <span className="ix-fs text-text-muted">Shares</span>
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
        </label>
        <button
          type="button"
          onClick={submit}
          disabled={!canAdd}
          className={BUTTON_CLASS}
        >
          {pending ? "Adding…" : "Add"}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-1.5 break-words text-[12px] text-loss">
          {error}
        </p>
      )}
    </div>
  );
}
