"use client";

/**
 * Botão "+ Portfolio": popover com a lista de portfólios persistidos e um
 * campo de quantidade → PUT /portfolios/{id}/positions/{ticker}. Usado nas
 * linhas da LeadersTable e no header do detalhe da ação.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchPortfolios, putPosition } from "@/lib/api/client";

export function AddToPortfolio({ ticker }: { ticker: string }) {
  const [open, setOpen] = useState(false);
  const [qty, setQty] = useState("1");
  const [done, setDone] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const add = useMutation({
    mutationFn: ({ portfolioId }: { portfolioId: number }) =>
      putPosition(portfolioId, ticker, { quantity: Number(qty) || 1 }),
    onSuccess: (_data, vars) => {
      setDone(String(vars.portfolioId));
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        title={`Add ${ticker} to a portfolio`}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
          setDone(null);
        }}
        className="flex h-6 items-center border border-border-strong px-1.5 text-[11px] font-bold text-text-secondary hover:bg-layer-hover hover:text-text-primary"
      >
        +
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 z-30 mt-1 w-56 border border-border-strong bg-surface-1 p-2 shadow-lg"
        >
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-text-muted">
            Add {ticker}
          </div>
          <label className="mb-2 flex items-center gap-2 text-[11px] text-text-secondary">
            Qty
            <input
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              inputMode="decimal"
              className="h-6 w-20 border border-border-strong bg-field px-1.5 tabular-nums text-text-primary"
            />
          </label>
          {portfolios?.length === 0 && (
            <p className="text-[11px] text-text-muted">
              No portfolios yet — create one in Portfolio.
            </p>
          )}
          {portfolios?.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={add.isPending}
              onClick={() => add.mutate({ portfolioId: p.id })}
              className="flex w-full items-center justify-between px-1.5 py-1 text-left text-[12px] text-text-primary hover:bg-layer-hover disabled:opacity-50"
            >
              <span className="truncate">{p.name}</span>
              {done === String(p.id) && <span className="text-gain">✓</span>}
            </button>
          ))}
          {add.isError && (
            <p className="mt-1 text-[11px] text-loss">{(add.error as Error).message}</p>
          )}
        </div>
      )}
    </div>
  );
}
