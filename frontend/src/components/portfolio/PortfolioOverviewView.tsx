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
  createPortfolioTransaction,
  deletePortfolio,
  deletePosition,
  fetchPortfolioOverview,
  fetchPortfolios,
  patchPortfolio,
  putPosition,
  type PortfolioListItem,
  type PortfolioOverview,
  type PortfolioTransactionBody,
  type PositionBody,
} from "@/lib/api/client";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/format";
import { parseDecimal } from "@/lib/parse";
import { type AllocationSlice } from "@/lib/charts/types";
import { buildHcAllocationOption } from "@/lib/charts/hc/allocation";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { DataGrid } from "@/components/ui/DataGrid";
import {
  countMatchingPositions,
  formatShares,
  positionsToGridOptions,
  POSITION_COLS,
} from "@/lib/grid/positionsGridOptions";
import type { TickDir } from "@/lib/grid/liveFlash";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { Card, InfoDot, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import { retryPolicy } from "@/components/screener/shared";
import { PortfolioNewsPanel } from "@/components/portfolio/PortfolioNewsPanel";
import { PortfolioLookthroughSection } from "@/components/portfolio/PortfolioLookthroughSection";
import { PortfolioRebalanceSection } from "@/components/portfolio/PortfolioRebalanceSection";
import { PortfolioPerformanceView } from "@/components/portfolio/PortfolioPerformanceView";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { compactDatetimeXAxis, formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import {
  buildAmountAdd,
  resolveSpot,
  type ExistingHolding,
} from "@/lib/portfolio/addPosition";
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
              <PortfolioManageBar
                selected={selected}
                activeSection={activeSection}
                onSelect={setSelectedId}
              />
              <PortfolioSectionTabs activeSection={activeSection} />
              {activeSection === "overview" && (
                <OverviewSection
                  key={selected.id}
                  portfolioId={selected.id}
                  inceptionDate={selected.inception_date ?? selected.created_at}
                />
              )}
              {activeSection === "performance" && (
                <PerformanceSection
                  key={selected.id}
                  portfolioId={selected.id}
                />
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

const todayIsoDate = (): string => new Date().toISOString().slice(0, 10);

const isoDateOnly = (value: string | null | undefined): string =>
  value ? value.slice(0, 10) : "";

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
  const [inceptionDate, setInceptionDate] = useState("");

  const mutation = useMutation({
    mutationFn: (portfolioName: string) =>
      createPortfolio({
        name: portfolioName,
        cash: 0,
        inception_date: inceptionDate || null,
      }),
    onSuccess: (portfolio) => {
      setName("");
      setInceptionDate("");
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
        <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
          Inception
          <input
            type="date"
            value={inceptionDate}
            onChange={(e) => setInceptionDate(e.target.value)}
            className={`w-[136px] ${INPUT_CLASS}`}
          />
        </label>
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

/* ── Manage bar (selected portfolio actions) ──────────────────────────────── */

function PortfolioManageBar({
  selected,
  activeSection,
  onSelect,
}: {
  selected: PortfolioListItem;
  activeSection: PortfolioSectionId;
  onSelect: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const showAsOf = activeSection === "overview";

  // Shares the overview cache with the section views — only for the EOD as-of.
  const overviewQuery = useQuery({
    queryKey: ["overview", selected.id],
    queryFn: ({ signal }) => fetchPortfolioOverview(selected.id, signal),
    enabled: showAsOf,
    staleTime: 60_000,
    retry: retryPolicy,
  });
  const asOf = showAsOf ? (overviewQuery.data?.aggregates.as_of ?? null) : null;

  const invalidatePortfolio = (id: number) => {
    queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    queryClient.invalidateQueries({ queryKey: ["overview", id] });
  };

  const editPortfolioMutation = useMutation({
    mutationFn: ({
      id,
      name,
      inceptionDate,
      cash,
    }: {
      id: number;
      name: string;
      inceptionDate: string | null;
      cash: number;
    }) => patchPortfolio(id, { name, inception_date: inceptionDate, cash }),
    onSuccess: (_, { id }) => {
      setEditing(false);
      invalidatePortfolio(id);
    },
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
    editPortfolioMutation.error ??
    deleteMutation.error;

  return (
    <div className="border border-border bg-surface-2 px-[var(--ix-pad)] py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-text-secondary">
        <button
          type="button"
          onClick={() => setEditing(true)}
          disabled={editPortfolioMutation.isPending}
          className={BUTTON_CLASS}
        >
          {editPortfolioMutation.isPending ? "Saving…" : "Edit"}
        </button>

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

      </div>

      {mutationError && (
        <p role="alert" className="mt-1.5 break-words text-[12px] text-loss">
          {mutationError.message}
        </p>
      )}

      {editing && (
        <PortfolioEditDialog
          portfolio={selected}
          pending={editPortfolioMutation.isPending}
          deletePending={deleteMutation.isPending}
          error={mutationError?.message ?? null}
          onClose={() => {
            editPortfolioMutation.reset();
            deleteMutation.reset();
            setEditing(false);
          }}
          onSubmit={(payload) => editPortfolioMutation.mutate(payload)}
          onDelete={() => {
            // Native confirm: deletion is destructive and cascades positions.
            if (window.confirm(`Delete portfolio "${selected.name}"?`)) {
              deleteMutation.mutate(selected.id);
            }
          }}
        />
      )}
    </div>
  );
}

function PortfolioEditDialog({
  portfolio,
  pending,
  deletePending,
  error,
  onClose,
  onSubmit,
  onDelete,
}: {
  portfolio: PortfolioListItem;
  pending: boolean;
  deletePending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: {
    id: number;
    name: string;
    inceptionDate: string | null;
    cash: number;
  }) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(portfolio.name);
  const [inceptionDate, setInceptionDate] = useState(
    isoDateOnly(portfolio.inception_date ?? portfolio.created_at),
  );
  const [cashText, setCashText] = useState(String(portfolio.cash));
  const [cashInvalid, setCashInvalid] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSave = name.trim().length > 0 && !pending && !deletePending;
  const save = () => {
    if (!canSave) return;
    const cash = parseCash(cashText);
    if (cash === undefined) {
      setCashInvalid(true);
      return;
    }
    onSubmit({
      id: portfolio.id,
      name: name.trim(),
      inceptionDate: inceptionDate || null,
      cash,
    });
  };

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(0,0,0,0.32)] p-4"
    >
      <div
        role="dialog"
        aria-label={`Edit portfolio ${portfolio.name}`}
        onClick={(e) => e.stopPropagation()}
        className="w-[420px] max-w-[96vw] border border-border-strong bg-surface-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3.5">
          <div>
            <div className="ix-title text-[18px] text-accent">Edit portfolio</div>
            <div className="mt-0.5 text-[12px] text-text-secondary">
              Name, cash, and inception date
            </div>
          </div>
          <button
            type="button"
            aria-label="Close edit portfolio"
            onClick={onClose}
            className="text-[18px] leading-none text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="grid gap-3 px-[var(--ix-pad)] py-4">
          <label className="grid gap-1 text-[11px] text-text-muted">
            Name
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
              }}
              className={`w-full ${INPUT_CLASS}`}
            />
          </label>
          <label className="grid gap-1 text-[11px] text-text-muted">
            Inception date
            <input
              type="date"
              value={inceptionDate}
              onChange={(e) => setInceptionDate(e.target.value)}
              className={`w-full ${INPUT_CLASS}`}
            />
          </label>
          <label className="grid gap-1 text-[11px] text-text-muted">
            Cash
            <input
              value={cashText}
              inputMode="decimal"
              onChange={(e) => {
                setCashText(e.target.value);
                setCashInvalid(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
              }}
              aria-invalid={cashInvalid}
              className={`w-full text-right tabular-nums ${INPUT_CLASS} ${
                cashInvalid ? "border-b-2 border-loss focus:border-loss" : ""
              }`}
            />
          </label>
          {cashInvalid && (
            <p role="alert" className="m-0 text-[12px] text-loss">
              Enter a cash amount greater than or equal to zero.
            </p>
          )}
          {error && (
            <p role="alert" className="m-0 break-words text-[12px] text-loss">
              {error}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-[var(--ix-pad)] py-3">
          <button
            type="button"
            onClick={onDelete}
            disabled={pending || deletePending}
            className="h-[30px] border border-[var(--color-loss)] bg-[var(--color-loss)] px-4 text-[12px] font-bold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {deletePending ? "Deleting…" : "Delete"}
          </button>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={BUTTON_CLASS}>
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!canSave}
              className="h-[30px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {pending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Overview (KPIs + allocation + table) ─────────────────────────────────── */

function OverviewSection({
  portfolioId,
  inceptionDate,
}: {
  portfolioId: number;
  inceptionDate: string;
}) {
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
      <KpiStrip
        portfolioId={portfolioId}
        overview={overview}
        inceptionDate={inceptionDate}
      />
      {colors && (
        <div className="grid items-stretch gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
          {(overview.positions.length > 0 || overview.aggregates.cash > 0) && (
            <AllocationPanel overview={overview} colors={colors} />
          )}
          <NavPanel portfolioId={portfolioId} colors={colors} />
        </div>
      )}
      <PositionsTable overview={overview} portfolioId={portfolioId} />
    </div>
  );
}

/* ── Performance (persisted NAV + contribution breakdown) ─────────────────── */

function PerformanceSection({
  portfolioId,
}: {
  portfolioId: number;
}) {
  return <PortfolioPerformanceView portfolioId={portfolioId} />;
}

/* ── Portfolio NAV mini-panel (Overview, beside the allocation donut) ─────── */

const NAV_RANGES = [
  { key: "1M", label: "1M", bars: 21 },
  { key: "6M", label: "6M", bars: 126 },
  { key: "1Y", label: "1Y", bars: 252 },
  { key: "MAX", label: "Max", bars: Infinity },
] as const;
type NavRangeKey = (typeof NAV_RANGES)[number]["key"];

const SYNTH_NAV_TIP =
  "Persisted daily portfolio NAV index from the real transaction ledger and portfolio inception date.";

function NavPanel({
  portfolioId,
  colors,
}: {
  portfolioId: number;
  colors: ChartColors;
}) {
  const { recon, isLoading, isError } = usePortfolioNav(portfolioId);
  const [range, setRange] = useState<NavRangeKey>("1Y");

  const bars = NAV_RANGES.find((r) => r.key === range)!.bars;
  const slice = useMemo(
    () => (bars === Infinity ? recon.navIndex : recon.navIndex.slice(-bars)),
    [recon.navIndex, bars],
  );
  const change =
    slice.length > 1 ? slice[slice.length - 1]![1] / slice[0]![1] - 1 : 0;

  const option = useMemo<Options | null>(() => {
    if (slice.length === 0) return null;
    // Baseline NAV (range start) for the "% from range start" tooltip line.
    const base0 = slice[0]![1];
    return {
      chart: { type: "line", height: 200, zooming: { type: "x" } },
      legend: { enabled: false },
      xAxis: compactDatetimeXAxis({
        crosshair: { color: colors.grid },
        tickPixelInterval: 92,
      }),
      yAxis: {
        title: {
          text: "NAV Index",
          style: { color: colors.textSecondary, fontSize: "10px" },
        },
        labels: {
          formatter() {
            return formatNumber(this.value as number, 0);
          },
        },
      },
      tooltip: {
        formatter() {
          const ctx = this as unknown as { x: number; y: number };
          const chg = base0 > 0 ? ctx.y / base0 - 1 : 0;
          const tone = chg >= 0 ? colors.gain : colors.loss;
          return (
            `${formatTimestampDate(ctx.x)}<br/>NAV Index: <b>${formatNumber(ctx.y, 2)}</b>` +
            `<br/><span style="color:${tone}">${formatPercent(chg, 2, { signed: true })} from range start</span>`
          );
        },
      },
      series: [
        {
          type: "line",
          name: "NAV Index",
          data: slice,
          color: colors.accent,
          lineWidth: 2,
          marker: { enabled: false },
        },
      ],
    };
  }, [slice, colors]);

  return (
    <section className="ix-pad flex flex-col border border-border bg-surface-2">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <h2 className="ix-label m-0 flex items-center gap-1.5">
          Portfolio NAV
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
            ? "Could not load materialized portfolio NAV."
            : "Portfolio NAV has not been materialized yet."}
        </div>
      )}
    </section>
  );
}

/** Carbon KPI tile strip — 1px-gap grid over the hairline border color. */
function KpiStrip({
  portfolioId,
  overview,
  inceptionDate,
}: {
  portfolioId: number;
  overview: PortfolioOverview;
  inceptionDate: string;
}) {
  const { aggregates, positions } = overview;
  const { recon, isLoading, isError } = usePortfolioNav(portfolioId);
  // Display-only ratio of two backend-provided values (cash share of total).
  const cashWeight =
    aggregates.total_value > 0 ? aggregates.cash / aggregates.total_value : null;
  const sinceInception =
    recon.navIndex.length > 1
      ? recon.navIndex[recon.navIndex.length - 1]![1] / recon.navIndex[0]![1] - 1
      : null;

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
      <KpiTile
        label="Return Since Inception"
        value={
          isLoading && sinceInception === null
            ? "…"
            : sinceInception !== null && !isError
              ? formatPercent(sinceInception, 2, { signed: true })
              : "—"
        }
        tone={
          sinceInception !== null && !isError
            ? valueTone(sinceInception)
            : "text-text-muted"
        }
        detail={`Inception ${formatDate(inceptionDate)}`}
      />
    </div>
  );
}

/**
 * Allocation donut. Slice values are the backend's per-position market values
 * (plus cash); percentages shown are the slices' shares of the donut total —
 * chart proportions, not finance.
 */
function AllocationPanel({
  overview,
  colors,
}: {
  overview: PortfolioOverview;
  colors: ChartColors;
}) {
  const { aggregates, positions } = overview;

  const slices = useMemo<Array<AllocationSlice & { displayName?: string }>>(() => {
    const positionSlices = positions.map((position) => ({
      assetClass: position.asset_class ?? "equity",
      name: position.ticker,
      displayName: position.name ?? undefined,
      value: position.market_value,
    }));
    return aggregates.cash > 0
      ? [...positionSlices, { assetClass: "cash", name: "Cash", value: aggregates.cash }]
      : positionSlices;
  }, [positions, aggregates.cash]);

  const options = useMemo(
    () =>
      buildHcAllocationOption(slices, colors, {
        // Tooltip shows the $ market value above the "% of portfolio" line.
        valueFormatter: (value) => formatCurrency(value),
      }),
    [slices, colors],
  );

  return (
    <Card title="Allocation" subtitle="· share by market value">
      <HighchartsChart options={options} className="h-[360px] w-full" />
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
    queryClient.invalidateQueries({ queryKey: ["portfolio-nav", portfolioId] });
  };

  // Two mutations over the same PUT endpoint so the Add row and the inline
  // edits surface their errors independently (an add typo must not look like
  // an edit failure).
  const addMutation = useMutation({
    mutationFn: (body: PortfolioTransactionBody) =>
      createPortfolioTransaction(portfolioId, body),
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
  const tradeMutation = useMutation({
    mutationFn: (body: PortfolioTransactionBody) =>
      createPortfolioTransaction(portfolioId, body),
    onSuccess: invalidate,
  });

  const rowError = editMutation.error ?? removeMutation.error;

  // Stabilize the row actions so gridOptions does not re-run on every render.
  // Field edits open small dialogs; destructive remove still lives in the
  // detail drawer, not in the main table action column.
  const removeMutate = removeMutation.mutate;
  const [tradeTicker, setTradeTicker] = useState<string | null>(null);
  const [dateTicker, setDateTicker] = useState<string | null>(null);
  const [sharesTicker, setSharesTicker] = useState<string | null>(null);
  const [costTicker, setCostTicker] = useState<string | null>(null);
  const onTrade = useCallback((ticker: string) => setTradeTicker(ticker), []);
  const onEditTradeDate = useCallback(
    (ticker: string) => setDateTicker(ticker),
    [],
  );
  const onEditShares = useCallback((ticker: string) => setSharesTicker(ticker), []);
  const onEditCost = useCallback((ticker: string) => setCostTicker(ticker), []);

  // Search box + Load-more, both presentation-only (slice already-fetched
  // overview data). PAGE_SIZE rows show first; "Load more" reveals the rest.
  const PAGE_SIZE = 12;
  const [search, setSearch] = useState("");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const matchCount = countMatchingPositions(positions, search);
  const shownCount = Math.min(visible, matchCount);
  const remaining = matchCount - shownCount;
  // Reset the page window whenever the search term changes.
  useEffect(() => {
    setVisible(PAGE_SIZE);
  }, [search]);

  // Position detail side panel (drawer): open on a row click (non-interactive
  // cell). Closes itself when its position is removed (detailPos → null).
  const [detailTicker, setDetailTicker] = useState<string | null>(null);
  const onOpenDetail = useCallback((ticker: string) => setDetailTicker(ticker), []);
  const detailPos = detailTicker
    ? (positions.find((p) => p.ticker === detailTicker) ?? null)
    : null;
  const tradePos = tradeTicker
    ? (positions.find((p) => p.ticker === tradeTicker) ?? null)
    : null;
  const datePos = dateTicker
    ? (positions.find((p) => p.ticker === dateTicker) ?? null)
    : null;
  const sharesPos = sharesTicker
    ? (positions.find((p) => p.ticker === sharesTicker) ?? null)
    : null;
  const costPos = costTicker
    ? (positions.find((p) => p.ticker === costTicker) ?? null)
    : null;

  // Wire the grid's pure edit/remove callbacks to the mutations. Invalid edits
  // never persist; they re-fetch the overview so the grid reverts the cell to
  // the server value. Only recomputes when the position DATA (overview) or a
  // stabilized handler changes — never on an unrelated re-render.
  const gridOptions = useMemo(
    () =>
      positionsToGridOptions(
        overview,
        { onEditShares, onEditCost, onEditTradeDate, onTrade, onOpenDetail },
        { search, limit: visible },
      ),
    [
      overview,
      onEditShares,
      onEditCost,
      onEditTradeDate,
      onTrade,
      onOpenDetail,
      search,
      visible,
    ],
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
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-border px-[var(--ix-pad)] py-3">
        <h2 className="m-0 flex items-baseline gap-2 text-[13px] font-bold">
          Positions
          <span className="text-[11px] font-normal text-text-muted">
            {search
              ? `${shownCount} of ${matchCount} (filtered)`
              : `${positions.length} holding${positions.length === 1 ? "" : "s"}`}
          </span>
        </h2>
        <div className="flex h-[32px] min-w-[240px] items-center gap-2 border border-border-strong bg-field px-2.5">
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden
            className="text-text-muted"
          >
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
            <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbol or company"
            aria-label="Search positions table"
            className="flex-1 border-none bg-transparent text-[12.5px] text-text-primary outline-none placeholder:text-text-muted"
          />
        </div>
      </div>

      <AddPositionRowForm
        pending={addMutation.isPending}
        error={addMutation.error?.message ?? null}
        existingFor={(t) => {
          const p = positions.find((pos) => pos.ticker === t);
          return p
            ? { quantity: p.quantity, acqPrice: p.acq_price, lastClose: p.last_close }
            : null;
        }}
        defaultDate={aggregates.as_of ?? todayIsoDate()}
        onAdd={async (ticker, body) => {
          try {
            await addMutation.mutateAsync(body);
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

      {positions.length > 0 && matchCount === 0 && (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-text-muted">
          <p className="text-[13px] text-text-secondary">
            No positions match “{search}”.
          </p>
          <button
            type="button"
            onClick={() => setSearch("")}
            className={BUTTON_CLASS}
          >
            Clear search
          </button>
        </div>
      )}

      {remaining > 0 && (
        <div className="flex justify-center border-t border-border p-2.5">
          <button
            type="button"
            onClick={() => setVisible((v) => v + PAGE_SIZE)}
            className={BUTTON_CLASS}
          >
            Load more ({remaining})
          </button>
        </div>
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
              <>End of day · {formatDate(aggregates.as_of!)}</>
            )}
          </span>
        )}
        <span className="tabular-nums">Cash: {formatCurrency(aggregates.cash)}</span>
        <span className="ml-auto font-bold tabular-nums text-text-primary">
          Total value: {formatCurrency(aggregates.total_value)}
        </span>
      </div>

      {detailPos && (
        <PositionDetailPanel
          position={detailPos}
          aggregates={aggregates}
          portfolioId={portfolioId}
          onClose={() => setDetailTicker(null)}
          onRemove={(ticker) => {
            removeMutate(ticker);
            setDetailTicker(null);
          }}
        />
      )}

      {tradePos && (
        <TradeTicketDialog
          position={tradePos}
          defaultDate={aggregates.as_of ?? todayIsoDate()}
          pending={tradeMutation.isPending}
          error={tradeMutation.error?.message ?? null}
          onClose={() => {
            tradeMutation.reset();
            setTradeTicker(null);
          }}
          onSubmit={async (body) => {
            await tradeMutation.mutateAsync(body);
            tradeMutation.reset();
            setTradeTicker(null);
          }}
        />
      )}

      {costPos && (
        <PositionNumberDialog
          position={costPos}
          title="Avg cost"
          fieldLabel="Average cost"
          initialText={costPos.acq_price != null ? String(costPos.acq_price) : ""}
          parse={parseCost}
          pending={editMutation.isPending}
          error={editMutation.error?.message ?? null}
          onClose={() => {
            editMutation.reset();
            setCostTicker(null);
          }}
          onSubmit={async (cost) => {
            await editMutation.mutateAsync({
              ticker: costPos.ticker,
              body: {
                quantity: costPos.quantity,
                acq_price: cost,
                trade_date: costPos.trade_date ?? null,
              },
            });
            editMutation.reset();
            setCostTicker(null);
          }}
        />
      )}

      {sharesPos && (
        <PositionNumberDialog
          position={sharesPos}
          title="Qty"
          fieldLabel="Quantity"
          initialText={String(sharesPos.quantity)}
          parse={parseShares}
          pending={editMutation.isPending}
          error={editMutation.error?.message ?? null}
          onClose={() => {
            editMutation.reset();
            setSharesTicker(null);
          }}
          onSubmit={async (quantity) => {
            if (quantity == null) return;
            await editMutation.mutateAsync({
              ticker: sharesPos.ticker,
              body: {
                quantity,
                acq_price: sharesPos.acq_price ?? null,
                trade_date: sharesPos.trade_date ?? null,
              },
            });
            editMutation.reset();
            setSharesTicker(null);
          }}
        />
      )}

      {datePos && (
        <TradeDateDialog
          position={datePos}
          pending={editMutation.isPending}
          error={editMutation.error?.message ?? null}
          onClose={() => {
            editMutation.reset();
            setDateTicker(null);
          }}
          onSubmit={async (tradeDate) => {
            await editMutation.mutateAsync({
              ticker: datePos.ticker,
              body: {
                quantity: datePos.quantity,
                acq_price: datePos.acq_price ?? null,
                trade_date: tradeDate,
              },
            });
            editMutation.reset();
            setDateTicker(null);
          }}
        />
      )}
    </section>
  );
}

function PositionNumberDialog({
  position,
  title,
  fieldLabel,
  initialText,
  parse,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  position: PortfolioOverview["positions"][number];
  title: string;
  fieldLabel: string;
  initialText: string;
  parse: (raw: string) => number | null | undefined;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (value: number | null) => Promise<void>;
}) {
  const [text, setText] = useState(initialText);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = () => {
    const parsed = parse(text);
    if (parsed === undefined) {
      setInvalid(true);
      return;
    }
    void onSubmit(parsed);
  };

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(0,0,0,0.28)] p-4"
    >
      <div
        role="dialog"
        aria-label={`Set ${fieldLabel.toLowerCase()} for ${position.ticker}`}
        onClick={(e) => e.stopPropagation()}
        className="w-[360px] max-w-[96vw] border border-border-strong bg-surface-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3.5">
          <div>
            <div className="ix-title text-[18px] text-accent">{title}</div>
            <div className="mt-0.5 text-[12px] text-text-secondary">
              {position.ticker}
            </div>
          </div>
          <button
            type="button"
            aria-label={`Close ${fieldLabel.toLowerCase()} editor`}
            onClick={onClose}
            className="text-[18px] leading-none text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="grid gap-3 px-[var(--ix-pad)] py-4">
          <label className="grid gap-1 text-[11px] text-text-muted">
            {fieldLabel}
            <input
              autoFocus
              value={text}
              inputMode="decimal"
              onChange={(e) => {
                setText(e.target.value);
                setInvalid(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
              aria-invalid={invalid}
              className={`w-full text-right tabular-nums ${INPUT_CLASS} ${
                invalid ? "border-b-2 border-loss focus:border-loss" : ""
              }`}
            />
          </label>
          {invalid && (
            <p role="alert" className="m-0 text-[12px] text-loss">
              Enter a positive number.
            </p>
          )}
          {error && (
            <p role="alert" className="m-0 break-words text-[12px] text-loss">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-[var(--ix-pad)] py-3">
          <button type="button" onClick={onClose} className={BUTTON_CLASS}>
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={pending}
            className="h-[30px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function TradeDateDialog({
  position,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  position: PortfolioOverview["positions"][number];
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (tradeDate: string | null) => Promise<void>;
}) {
  const [date, setDate] = useState(position.trade_date ?? "");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(0,0,0,0.28)] p-4"
    >
      <div
        role="dialog"
        aria-label={`Set buy date for ${position.ticker}`}
        onClick={(e) => e.stopPropagation()}
        className="w-[360px] max-w-[96vw] border border-border-strong bg-surface-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3.5">
          <div>
            <div className="ix-title text-[18px] text-accent">
              Buy date
            </div>
            <div className="mt-0.5 text-[12px] text-text-secondary">
              {position.ticker}
            </div>
          </div>
          <button
            type="button"
            aria-label="Close buy date editor"
            onClick={onClose}
            className="text-[18px] leading-none text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="grid gap-3 px-[var(--ix-pad)] py-4">
          <label className="grid gap-1 text-[11px] text-text-muted">
            Trade date
            <input
              autoFocus
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={`w-full ${INPUT_CLASS}`}
            />
          </label>
          {error && (
            <p role="alert" className="m-0 break-words text-[12px] text-loss">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-[var(--ix-pad)] py-3">
          <button type="button" onClick={onClose} className={BUTTON_CLASS}>
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void onSubmit(date || null)}
            disabled={pending}
            className="h-[30px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save date"}
          </button>
        </div>
      </div>
    </div>
  );
}

function TradeTicketDialog({
  position,
  defaultDate,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  position: PortfolioOverview["positions"][number];
  defaultDate: string;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (body: PortfolioTransactionBody) => Promise<void>;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState(String(position.last_close || ""));
  const [tradeDate, setTradeDate] = useState(isoDateOnly(defaultDate) || todayIsoDate());
  const [commission, setCommission] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = parseShares(quantity);
  const px = parseShares(price);
  const comm = commission.trim() === "" ? 0 : parseCash(commission);
  const oversell = side === "sell" && q != null && q > position.quantity;
  const canSubmit =
    !pending &&
    q !== undefined &&
    px !== undefined &&
    comm !== undefined &&
    tradeDate.length > 0 &&
    !oversell;

  const submit = () => {
    if (!canSubmit) return;
    void onSubmit({
      ticker: position.ticker,
      side,
      quantity: q,
      price: px,
      commission: comm,
      trade_date: tradeDate,
    });
  };

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(0,0,0,0.32)] p-4"
    >
      <div
        role="dialog"
        aria-label={`Trade ${position.ticker}`}
        onClick={(e) => e.stopPropagation()}
        className="w-[420px] max-w-[96vw] border border-border-strong bg-surface-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3.5">
          <div>
            <div className="ix-title text-[18px] text-accent">
              Trade {position.ticker}
            </div>
            <div className="mt-0.5 text-[12px] text-text-secondary">
              Current qty {formatShares(position.quantity)} · Last{" "}
              {formatCurrency(position.last_close)}
            </div>
          </div>
          <button
            type="button"
            aria-label="Close trade ticket"
            onClick={onClose}
            className="text-[18px] leading-none text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="grid gap-3 px-[var(--ix-pad)] py-4">
          <div className="inline-flex w-max border border-border-strong bg-field">
            {(["buy", "sell"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setSide(option)}
                className={`h-[30px] px-4 text-[12px] font-bold capitalize ${
                  side === option
                    ? "bg-accent text-on-accent"
                    : "text-text-secondary hover:bg-layer-hover"
                }`}
              >
                {option}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1 text-[11px] text-text-muted">
              Quantity
              <input
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="0"
                inputMode="decimal"
                className={`w-full text-right ${INPUT_CLASS}`}
              />
            </label>
            <label className="grid gap-1 text-[11px] text-text-muted">
              Price
              <input
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                inputMode="decimal"
                className={`w-full text-right ${INPUT_CLASS}`}
              />
            </label>
            <label className="grid gap-1 text-[11px] text-text-muted">
              Trade date
              <input
                type="date"
                value={tradeDate}
                onChange={(e) => setTradeDate(e.target.value)}
                className={`w-full ${INPUT_CLASS}`}
              />
            </label>
            <label className="grid gap-1 text-[11px] text-text-muted">
              Commission
              <input
                value={commission}
                onChange={(e) => setCommission(e.target.value)}
                placeholder="0"
                inputMode="decimal"
                className={`w-full text-right ${INPUT_CLASS}`}
              />
            </label>
          </div>

          {oversell && (
            <p role="alert" className="m-0 text-[12px] text-loss">
              Sell quantity cannot exceed current quantity.
            </p>
          )}
          {error && (
            <p role="alert" className="m-0 break-words text-[12px] text-loss">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-[var(--ix-pad)] py-3">
          <button type="button" onClick={onClose} className={BUTTON_CLASS}>
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="h-[30px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pending ? "Saving…" : side === "buy" ? "Buy" : "Sell"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Position detail side panel (drawer) ──────────────────────────────────── */

function PositionDetailPanel({
  position,
  aggregates,
  portfolioId,
  onClose,
  onRemove,
}: {
  position: PortfolioOverview["positions"][number];
  aggregates: PortfolioOverview["aggregates"];
  portfolioId: number;
  onClose: () => void;
  onRemove: (ticker: string) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const weight =
    aggregates.total_value > 0 ? position.market_value / aggregates.total_value : 0;

  const rows: Array<{ label: string; value: string; tone?: string }> = [
    { label: "Quantity", value: formatShares(position.quantity) },
    {
      label: "Avg cost",
      value: position.acq_price != null ? formatCurrency(position.acq_price) : "—",
    },
    { label: "Price", value: formatCurrency(position.last_close) },
    { label: "Market value", value: formatCurrency(position.market_value) },
    {
      label: "Total cost",
      value: position.cost_basis != null ? formatCurrency(position.cost_basis) : "—",
      tone: "text-text-secondary",
    },
    {
      label: "P&L",
      value: position.pnl != null ? formatCurrency(position.pnl, { signed: true }) : "—",
      tone: position.pnl != null ? valueTone(position.pnl) : "text-text-muted",
    },
    {
      label: "P&L %",
      value:
        position.pnl_pct != null
          ? formatPercent(position.pnl_pct, 2, { signed: true })
          : "—",
      tone: position.pnl_pct != null ? valueTone(position.pnl_pct) : "text-text-muted",
    },
  ];

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[80] flex justify-end bg-[rgba(0,0,0,0.28)]"
    >
      <aside
        role="dialog"
        aria-label={`Position detail ${position.ticker}`}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-[340px] max-w-[90vw] flex-col overflow-auto border-l border-border-strong bg-surface-2 shadow-[-8px_0_30px_rgba(0,0,0,0.18)]"
      >
        <div className="flex items-start justify-between gap-2 border-b border-border px-[var(--ix-pad)] py-4">
          <div>
            <div className="ix-title text-[18px] text-accent">{position.ticker}</div>
            {position.name && (
              <div className="mt-0.5 text-[12px] text-text-secondary">{position.name}</div>
            )}
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="text-[18px] leading-none text-text-muted hover:text-text-primary"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col px-[var(--ix-pad)] py-3.5">
          {(position.asset_class || position.strategy_label) && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {position.asset_class && (
                <span className="border border-border bg-field px-[7px] py-0.5 text-[10px] text-text-secondary">
                  {position.asset_class}
                </span>
              )}
              {position.strategy_label && (
                <span className="border border-border bg-field px-[7px] py-0.5 text-[10px] text-text-secondary">
                  {position.strategy_label}
                </span>
              )}
            </div>
          )}

          <dl className="m-0 flex flex-col">
            {rows.map((r) => (
              <div
                key={r.label}
                className="flex items-baseline justify-between gap-3 border-b border-border py-[7px] text-[12.5px] last:border-b-0"
              >
                <dt className="text-text-secondary">{r.label}</dt>
                <dd className={`m-0 font-bold tabular-nums ${r.tone ?? "text-text-primary"}`}>
                  {r.value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="mt-3.5">
            <div className="mb-1.5 flex items-center justify-between text-[11px] text-text-muted">
              <span>Portfolio weight</span>
              <span className="font-bold tabular-nums text-text-primary">
                {formatPercent(weight, 1)}
              </span>
            </div>
            <div className="h-2 overflow-hidden bg-layer-active">
              <div
                className="h-full bg-accent"
                style={{ width: `${(weight * 100).toFixed(1)}%` }}
              />
            </div>
          </div>
        </div>

        <div className="mt-auto flex gap-2 border-t border-border px-[var(--ix-pad)] py-3.5">
          <Link
            href={`/builder?portfolio=${portfolioId}`}
            className="h-[34px] flex-1 border border-accent bg-accent text-center text-[12.5px] font-bold leading-[34px] text-on-accent"
          >
            Optimize in Builder →
          </Link>
          <button
            type="button"
            onClick={() => onRemove(position.ticker)}
            className="h-[34px] border border-border-strong bg-field px-3.5 text-[12.5px] text-text-secondary hover:border-loss hover:text-loss"
          >
            Remove
          </button>
        </div>
      </aside>
    </div>
  );
}

/**
 * Add-position form. The grid hosts no native editable "add" row, so this lives
 * as a field row above the grid (same panel, 1px rule). Two entry modes:
 *
 *  - Shares: symbol + quantity + price.
 *  - Amount ($): symbol + dollar amount + price → quantity is computed as
 *    amount / price. The price doubles as the acquisition price; for a ticker
 *    already held, an empty price falls back to its latest close (the spot), so
 *    the user just types how much they put in. No mental "amount ÷ price" math.
 *
 * Either way the form submits a buy transaction into the ledger.
 */
function AddPositionRowForm({
  pending,
  error,
  onAdd,
  onDirty,
  existingFor,
  defaultDate,
}: {
  pending: boolean;
  error: string | null;
  /** Resolves true on success — only then are the inputs cleared. */
  onAdd: (ticker: string, body: PortfolioTransactionBody) => Promise<boolean>;
  onDirty: () => void;
  /** Existing holding for a ticker (qty/cost/last close); spot + accumulation. */
  existingFor: (ticker: string) => ExistingHolding | null;
  defaultDate: string;
}) {
  const [mode, setMode] = useState<"shares" | "amount">("shares");
  const [ticker, setTicker] = useState("");
  const [shares, setShares] = useState("");
  const [amount, setAmount] = useState("");
  const [cost, setCost] = useState("");
  const [touched, setTouched] = useState(false);

  const isAmount = mode === "amount";
  const t = ticker.trim().toUpperCase();

  const parsedShares = parseShares(shares);
  // null = empty (use spot), undefined = invalid, number = explicit price > 0.
  const parsedCost = parseCost(cost);
  const parsedAmount = parseShares(amount); // finite > 0, else undefined
  const explicitPrice = typeof parsedCost === "number" ? parsedCost : null;
  const existing = t ? existingFor(t) : null;
  const existingSpot = existing?.lastClose ?? null;
  const spot = resolveSpot(explicitPrice, existing);
  const spotOk = spot != null && spot > 0;
  // Both modes register a buy lot. The backend ledger updates the position
  // snapshot; the UI only computes the lot quantity/price for the transaction.
  const amountAdd =
    isAmount && parsedAmount !== undefined && spotOk
      ? buildAmountAdd(parsedAmount, spot, existing)
      : null;
  const shareLotPrice = !isAmount && parsedCost !== undefined ? spot : null;
  const shareLotQuantity = !isAmount ? parsedShares : undefined;

  const canAdd = isAmount
    ? t.length > 0 &&
      parsedAmount !== undefined &&
      parsedCost !== undefined &&
      spotOk &&
      !pending
    : t.length > 0 &&
      parsedShares !== undefined &&
      parsedCost !== undefined &&
      shareLotPrice != null &&
      shareLotPrice > 0 &&
      !pending;

  const reset = () => {
    setTicker("");
    setShares("");
    setAmount("");
    setCost("");
    setTouched(false);
  };

  const submit = () => {
    if (!canAdd) {
      setTouched(true);
      return;
    }
    const lotQuantity = isAmount ? amountAdd?.addedQuantity : shareLotQuantity;
    const lotPrice = isAmount ? spot : shareLotPrice;
    if (!lotQuantity || !lotPrice) return;
    void onAdd(t, {
      ticker: t,
      side: "buy",
      quantity: lotQuantity,
      price: lotPrice,
      commission: 0,
      trade_date: isoDateOnly(defaultDate) || todayIsoDate(),
    }).then((ok) => {
      if (ok) reset();
    });
  };

  const dirty = () => {
    setTouched(true);
    onDirty();
  };

  const sharesInvalid =
    !isAmount && touched && shares.trim() !== "" && parsedShares === undefined;
  const amountInvalid =
    isAmount && touched && amount.trim() !== "" && parsedAmount === undefined;
  const costInvalid = touched && cost.trim() !== "" && parsedCost === undefined;

  let computedStr = "";
  if (isAmount) {
    if (parsedAmount === undefined) computedStr = "Enter an amount in USD";
    else if (!spotOk)
      computedStr = "Enter a price — no spot is known for this symbol yet";
    else if (amountAdd) {
      const at = `${formatCurrency(spot!)}${explicitPrice == null ? " (spot)" : ""}`;
      computedStr = existing
        ? `+${formatNumber(amountAdd.addedQuantity, 4)} shares at ${at} · new total ${formatNumber(amountAdd.quantity, 4)}`
        : `≈ ${formatNumber(amountAdd.addedQuantity, 4)} shares at ${at}`;
    }
  } else if (!isAmount && parsedShares !== undefined) {
    if (!shareLotPrice) {
      computedStr = "Enter a price — no spot is known for this symbol yet";
    } else if (existing) {
      computedStr = `+${formatNumber(parsedShares, 4)} shares at ${formatCurrency(shareLotPrice)} · new total ${formatNumber(existing.quantity + parsedShares, 4)}`;
    }
  }

  const modeBtn = (active: boolean) =>
    `h-[30px] whitespace-nowrap border-r border-border-strong px-3 text-[11px] last:border-r-0 ${
      active ? "bg-accent font-bold text-on-accent" : "text-text-secondary hover:bg-layer-hover"
    }`;
  const fieldClass = (invalid: boolean) =>
    `w-[118px] text-right tabular-nums ${INPUT_CLASS} ${
      invalid ? "border-b-2 border-loss focus:border-loss" : ""
    }`;
  const onFieldKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submit();
  };

  return (
    <div className="border-b border-border bg-zebra px-[var(--ix-pad)] py-2.5">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <div
          role="group"
          aria-label="Add by"
          className="flex h-[30px] self-end border border-border-strong"
        >
          <button
            type="button"
            aria-pressed={!isAmount}
            onClick={() => {
              setMode("shares");
              setTouched(false);
            }}
            className={modeBtn(!isAmount)}
          >
            Shares
          </button>
          <button
            type="button"
            aria-pressed={isAmount}
            onClick={() => {
              setMode("amount");
              setTouched(false);
            }}
            className={modeBtn(isAmount)}
          >
            Amount&nbsp;($)
          </button>
        </div>

        <label className="flex flex-col gap-1">
          <span className="ix-fs text-text-muted">Symbol</span>
          <input
            value={ticker}
            onChange={(e) => {
              setTicker(e.target.value.toUpperCase());
              dirty();
            }}
            onKeyDown={onFieldKey}
            placeholder="E.G. AAPL"
            aria-label="New position symbol"
            className={`w-[108px] uppercase ${INPUT_CLASS}`}
          />
        </label>

        {isAmount ? (
          <label className="flex flex-col gap-1">
            <span className="ix-fs text-text-muted">Amount ($)</span>
            <input
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                dirty();
              }}
              onKeyDown={onFieldKey}
              inputMode="decimal"
              placeholder="0.00"
              aria-label="New position amount in USD"
              aria-invalid={amountInvalid}
              className={fieldClass(amountInvalid)}
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1">
            <span className="ix-fs text-text-muted">Quantity</span>
            <input
              value={shares}
              onChange={(e) => {
                setShares(e.target.value);
                dirty();
              }}
              onKeyDown={onFieldKey}
              inputMode="decimal"
              placeholder="0"
              aria-label="New position quantity"
              aria-invalid={sharesInvalid}
              className={fieldClass(sharesInvalid)}
            />
          </label>
        )}

        <label className="flex flex-col gap-1">
          <span className="ix-fs text-text-muted">Price</span>
          <input
            value={cost}
            onChange={(e) => {
              setCost(e.target.value);
              dirty();
            }}
            onKeyDown={onFieldKey}
            inputMode="decimal"
            placeholder={
              isAmount
                ? existingSpot != null
                  ? `spot ${formatCurrency(existingSpot)}`
                  : "price"
                : existingSpot != null
                  ? `spot ${formatCurrency(existingSpot)}`
                  : "required"
            }
            aria-label="New position trade price"
            aria-invalid={costInvalid}
            className={fieldClass(costInvalid)}
          />
        </label>

        <button type="button" onClick={submit} disabled={!canAdd} className={BUTTON_CLASS}>
          {pending ? "Adding…" : "Add"}
        </button>
      </div>

      {computedStr && (
        <div className="mt-1.5 text-[11px] tabular-nums text-text-muted">{computedStr}</div>
      )}
      {error && (
        <p role="alert" className="mt-1.5 break-words text-[12px] text-loss">
          {error}
        </p>
      )}
    </div>
  );
}
