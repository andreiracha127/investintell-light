"use client";

/**
 * Portfolio Overview — persisted-portfolio CRUD plus the render-ready position
 * table from `GET /portfolios/{id}/overview`.
 *
 * The frontend computes NO finance: every P&L/aggregate number comes from the
 * backend overview payload. The Tiingo-style table puts the portfolio
 * aggregates directly in the column headers (P&L and Mkt Value).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

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
import { valueTone } from "@/components/ui/panels";
import { PortfolioNewsPanel } from "@/components/portfolio/PortfolioNewsPanel";

const INPUT_CLASS =
  "px-2 py-1 rounded-[6px] bg-surface-1 border border-border text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:border-accent-muted focus:outline-none";

const BUTTON_CLASS =
  "px-3 py-1 rounded-[6px] bg-surface-1 border border-border text-[12px] " +
  "text-text-secondary hover:text-text-primary hover:border-accent-muted " +
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
    <div className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5">
      <h1 className="text-2xl font-bold tracking-tight text-text-primary">
        Portfolio Overview
      </h1>

      {portfoliosQuery.isPending ? (
        <div aria-busy="true" aria-label="Loading portfolios" className="flex flex-col gap-5 animate-pulse">
          <div className="h-[44px] rounded-xl bg-surface-2" />
          <div className="h-[320px] rounded-xl bg-surface-2" />
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
        <>
          <PortfolioStrip
            portfolios={portfolios ?? []}
            selected={selected}
            onSelect={setSelectedId}
          />
          {selected && (
            <>
              <OverviewSection key={selected.id} portfolioId={selected.id} />
              <PortfolioNewsPanel portfolioId={selected.id} />
            </>
          )}
        </>
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
    <div role="alert" className="bg-surface-2 border border-loss rounded-xl px-5 py-4">
      <h2 className="text-sm font-semibold text-loss mb-1">{title}</h2>
      <p className="text-[13px] text-text-secondary break-words whitespace-pre-wrap">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-4 py-1.5 rounded-[6px] bg-surface-3 border border-border text-sm text-text-primary hover:border-accent-muted transition-colors"
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
        invalid ? "border-[var(--color-loss)]" : ""
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
        <p role="alert" className="mt-1.5 text-[12px] text-loss break-words">
          {mutation.error.message}
        </p>
      )}
    </div>
  );
}

function EmptyState({ onCreated }: { onCreated: (id: number) => void }) {
  return (
    <div className="bg-surface-2 border border-border rounded-xl px-6 py-12 flex flex-col items-center gap-3">
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

/* ── Selector strip ───────────────────────────────────────────────────────── */

function PortfolioStrip({
  portfolios,
  selected,
  onSelect,
}: {
  portfolios: PortfolioListItem[];
  selected: PortfolioListItem | null;
  onSelect: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
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
    <div className="bg-surface-2 border border-border rounded-xl px-4 py-3 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {portfolios.map((portfolio) => (
          <button
            key={portfolio.id}
            type="button"
            onClick={() => onSelect(portfolio.id)}
            aria-pressed={portfolio.id === selected?.id}
            className={`px-3 py-1 rounded-[6px] border text-[12px] font-medium transition-colors ${
              portfolio.id === selected?.id
                ? "bg-surface-3 border-accent-muted text-accent"
                : "bg-surface-1 border-border text-text-secondary hover:text-text-primary"
            }`}
          >
            {portfolio.name}
            <span className="ml-1.5 tabular-nums text-[10px] text-text-muted">
              {portfolio.position_count}
            </span>
          </button>
        ))}

        {creating ? (
          <CreatePortfolioForm
            autoFocus
            onCreated={(id) => {
              setCreating(false);
              onSelect(id);
            }}
          />
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className={BUTTON_CLASS}
          >
            + New portfolio
          </button>
        )}
      </div>

      {selected && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-2 border-t border-border text-[12px] text-text-secondary">
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
            className={`${BUTTON_CLASS} ml-auto hover:text-loss hover:border-[var(--color-loss)]`}
          >
            {deleteMutation.isPending ? "Deleting…" : "Delete"}
          </button>
        </div>
      )}

      {mutationError && (
        <p role="alert" className="text-[12px] text-loss break-words">
          {mutationError.message}
        </p>
      )}
    </div>
  );
}

/* ── Overview table ───────────────────────────────────────────────────────── */

function OverviewSection({ portfolioId }: { portfolioId: number }) {
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
        className="h-[320px] rounded-xl bg-surface-2 animate-pulse"
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
  return <PositionsTable overview={overviewQuery.data} portfolioId={portfolioId} />;
}

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
    <section className="bg-surface-2 border border-border rounded-xl p-4">
      <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-3">
        Positions
        <span className="ml-1.5 normal-case tracking-normal font-normal">
          {overview.name}
        </span>
      </h2>

      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.06em] text-text-muted border-b border-border align-top">
              <th className="py-2 pr-3 text-left font-semibold">Ticker</th>
              <th className="py-2 px-3 text-right font-semibold">Last</th>
              <th className="py-2 px-3 text-right font-semibold">Change</th>
              <th className="py-2 px-3 text-right font-semibold">Cost</th>
              <th className="py-2 px-3 text-right font-semibold">Shares</th>
              {/* Aggregates live IN the column headers (Tiingo pattern, D6). */}
              <th className="py-2 px-3 text-right font-semibold">
                P&amp;L
                <span
                  className={`block tabular-nums normal-case tracking-normal text-[12px] ${
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
              <th className="py-2 pl-3 text-right font-semibold">
                Mkt Value
                <span className="block tabular-nums normal-case tracking-normal text-[12px] text-text-primary">
                  {formatCurrency(aggregates.total_market_value)}
                </span>
              </th>
              <th className="py-2 pl-2 w-[32px]" aria-label="Row actions" />
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
            {positions.map((position) => (
              <PositionRow
                key={position.ticker}
                position={position}
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
                <td colSpan={8} className="py-4 text-center text-[13px] text-text-muted">
                  No positions yet — add one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {rowError && (
        <p role="alert" className="mt-2 text-[12px] text-loss break-words">
          {rowError.message}
        </p>
      )}

      {/* Footer: EOD badge + cash + total value */}
      <div className="mt-3 pt-3 border-t border-border flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-text-secondary">
        {aggregates.as_of && (
          <span className="px-1.5 py-px rounded-[4px] bg-surface-3 border border-border text-[10px] text-text-muted">
            EOD · {formatDate(aggregates.as_of)}
          </span>
        )}
        <span className="tabular-nums">Cash: {formatCurrency(aggregates.cash)}</span>
        <span className="ml-auto tabular-nums font-semibold text-text-primary">
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
      <tr className="border-b border-border bg-surface-1/40">
        <td className="py-2 pr-3">
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
        <td className="px-3" />
        <td className="px-3" />
        <td className="px-3 text-right">
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
                ? "border-[var(--color-loss)]"
                : ""
            }`}
          />
        </td>
        <td className="px-3 text-right">
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
                ? "border-[var(--color-loss)]"
                : ""
            }`}
          />
        </td>
        <td className="px-3" />
        <td className="pl-3 text-right">
          <button
            type="button"
            onClick={submit}
            disabled={!canAdd}
            className={BUTTON_CLASS}
          >
            {pending ? "Adding…" : "Add"}
          </button>
        </td>
        <td className="pl-2" />
      </tr>
      {error && (
        <tr className="border-b border-border">
          <td colSpan={8} className="py-1.5">
            <p role="alert" className="text-[12px] text-loss break-words">
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
  pending,
  onEdit,
  onRemove,
}: {
  position: OverviewPosition;
  pending: boolean;
  onEdit: (body: PositionBody) => void;
  onRemove: () => void;
}) {
  const changeTone =
    position.change !== null ? valueTone(position.change) : "text-text-muted";
  const pnlTone =
    position.pnl !== null ? valueTone(position.pnl) : "text-text-muted";

  return (
    <tr className="border-b border-border last:border-b-0">
      <td className="py-2 pr-3">
        <Link
          href={`/stocks/${encodeURIComponent(position.ticker)}`}
          className="font-semibold text-text-primary hover:text-accent transition-colors"
        >
          {position.ticker}
        </Link>
        {position.name && (
          <span className="block text-[11px] text-text-muted truncate max-w-[220px]">
            {position.name}
          </span>
        )}
      </td>
      <td className="px-3 text-right tabular-nums text-text-primary">
        {formatCurrency(position.last_close)}
      </td>
      <td className={`px-3 text-right tabular-nums ${changeTone}`}>
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
      <td className="px-3 text-right">
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
      <td className="px-3 text-right">
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
      <td className={`px-3 text-right tabular-nums ${pnlTone}`}>
        {position.pnl !== null && position.pnl_pct !== null ? (
          <>
            {formatCurrency(position.pnl, { signed: true })}
            <span className="block text-[11px]">
              {formatPercent(position.pnl_pct, 2, { signed: true })}
            </span>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="pl-3 text-right tabular-nums font-semibold text-text-primary">
        {formatCurrency(position.market_value)}
      </td>
      <td className="pl-2 text-right">
        <button
          type="button"
          onClick={onRemove}
          disabled={pending}
          aria-label={`Remove position ${position.ticker}`}
          title={`Remove ${position.ticker}`}
          className="px-1.5 py-0.5 rounded-[6px] text-text-muted hover:text-loss hover:bg-surface-1 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ×
        </button>
      </td>
    </tr>
  );
}
