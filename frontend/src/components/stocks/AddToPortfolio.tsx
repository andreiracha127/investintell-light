"use client";

/**
 * Botão "+ Portfolio": popover com a lista de portfólios persistidos e dois
 * modos de entrada → PUT /portfolios/{id}/positions/{ticker}.
 *
 *  - Shares: quantidade direta (define a posição).
 *  - Amount ($): valor em dólares ÷ preço → quantidade, ACUMULANDO sobre a
 *    posição existente daquele portfólio (qty somada, custo médio ponderado).
 *    O preço usa o `price` atual da ação por padrão; pode ser sobrescrito.
 *
 * Usado nas linhas da LeadersTable e no header do detalhe da ação. A posição
 * existente é lida do overview do portfólio escolhido (cache compartilhado) no
 * momento do clique, então a acumulação reflete o estado atual.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  fetchPortfolioOverview,
  fetchPortfolios,
  putPosition,
} from "@/lib/api/client";
import { buildAmountAdd, resolveSpot } from "@/lib/portfolio/addPosition";
import { formatCurrency, formatNumber } from "@/lib/format";

export function AddToPortfolio({
  ticker,
  price,
  variant = "icon",
}: {
  ticker: string;
  /** Current price for the ticker — the default spot in Amount mode. */
  price?: number | null;
  /** "icon" = "+" compacto (tabelas); "button" = botão accent rotulado (header). */
  variant?: "icon" | "button";
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"shares" | "amount">("shares");
  const [qty, setQty] = useState("1");
  const [amount, setAmount] = useState("");
  const [priceText, setPriceText] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const amountVal = Number(amount);
  const amountOk = Number.isFinite(amountVal) && amountVal > 0;
  const explicitPrice = priceText.trim() === "" ? null : Number(priceText);
  const explicitOk =
    explicitPrice != null && Number.isFinite(explicitPrice) && explicitPrice > 0;
  const priceBad = priceText.trim() !== "" && !explicitOk;
  const previewSpot = explicitOk
    ? explicitPrice!
    : price != null && price > 0
      ? price
      : null;
  const canAddAmount = amountOk && previewSpot != null && !priceBad;

  const add = useMutation({
    mutationFn: async ({ portfolioId }: { portfolioId: number }) => {
      if (mode === "shares") {
        const q = Number(qty);
        await putPosition(portfolioId, ticker, {
          quantity: Number.isFinite(q) && q > 0 ? q : 1,
        });
        return portfolioId;
      }
      // Amount mode: read the target portfolio's current holding, then
      // accumulate amount/spot onto it (cost blended).
      const overview = await queryClient.fetchQuery({
        queryKey: ["overview", portfolioId],
        queryFn: ({ signal }) => fetchPortfolioOverview(portfolioId, signal),
        staleTime: 60_000,
      });
      const pos = overview.positions.find((p) => p.ticker === ticker);
      const existing = pos
        ? { quantity: pos.quantity, acqPrice: pos.acq_price, lastClose: pos.last_close }
        : null;
      let spot = resolveSpot(explicitOk ? explicitPrice! : null, existing);
      if (spot == null && price != null && price > 0) spot = price;
      if (spot == null) throw new Error("No price available — enter a price.");
      const result = buildAmountAdd(amountVal, spot, existing);
      await putPosition(portfolioId, ticker, {
        quantity: result.quantity,
        acq_price: result.acqPrice,
      });
      return portfolioId;
    },
    onSuccess: (portfolioId) => {
      setDone(String(portfolioId));
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["overview", portfolioId] });
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

  const isAmount = mode === "amount";
  const modeBtn = (active: boolean) =>
    `h-6 flex-1 border-r border-border-strong text-[10.5px] font-bold last:border-r-0 ${
      active ? "bg-accent text-on-accent" : "text-text-secondary hover:bg-layer-hover"
    }`;
  const previewStr = isAmount
    ? !amountOk
      ? "Enter an amount in USD"
      : previewSpot == null
        ? "Enter a price"
        : `≈ ${formatNumber(amountVal / previewSpot, 4)} sh at ${formatCurrency(previewSpot)}`
    : "";
  const portfolioDisabled = add.isPending || (isAmount && !canAddAmount);

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
        className={
          variant === "button"
            ? "inline-flex h-[34px] items-center gap-1.5 border border-accent bg-accent px-3.5 text-[12.5px] font-bold text-on-accent hover:bg-accent-muted hover:border-accent-muted"
            : "flex h-6 items-center border border-border-strong px-1.5 text-[11px] font-bold text-text-secondary hover:bg-layer-hover hover:text-text-primary"
        }
      >
        {variant === "button" ? (
          <>
            <span className="text-[15px] leading-none">+</span> Add to portfolio
          </>
        ) : (
          "+"
        )}
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 z-30 mt-1 w-64 border border-border-strong bg-surface-1 p-2 shadow-lg"
        >
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-text-muted">
            Add {ticker}
          </div>

          <div
            role="group"
            aria-label="Add by"
            className="mb-2 flex h-6 border border-border-strong"
          >
            <button
              type="button"
              aria-pressed={!isAmount}
              onClick={() => setMode("shares")}
              className={modeBtn(!isAmount)}
            >
              Shares
            </button>
            <button
              type="button"
              aria-pressed={isAmount}
              onClick={() => setMode("amount")}
              className={modeBtn(isAmount)}
            >
              Amount ($)
            </button>
          </div>

          {isAmount ? (
            <div className="mb-2 flex flex-col gap-1.5">
              <label className="flex items-center justify-between gap-2 text-[11px] text-text-secondary">
                Amount ($)
                <input
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  inputMode="decimal"
                  placeholder="0.00"
                  aria-invalid={amount.trim() !== "" && !amountOk}
                  className="h-6 w-28 border border-border-strong bg-field px-1.5 text-right tabular-nums text-text-primary"
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-[11px] text-text-secondary">
                Price
                <input
                  value={priceText}
                  onChange={(e) => setPriceText(e.target.value)}
                  inputMode="decimal"
                  placeholder={price != null && price > 0 ? formatCurrency(price) : "price"}
                  aria-invalid={priceBad}
                  className={`h-6 w-28 border bg-field px-1.5 text-right tabular-nums text-text-primary ${
                    priceBad ? "border-loss" : "border-border-strong"
                  }`}
                />
              </label>
              <div className="text-[10.5px] tabular-nums text-text-muted">{previewStr}</div>
            </div>
          ) : (
            <label className="mb-2 flex items-center gap-2 text-[11px] text-text-secondary">
              Qty
              <input
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                inputMode="decimal"
                className="h-6 w-20 border border-border-strong bg-field px-1.5 tabular-nums text-text-primary"
              />
            </label>
          )}

          {portfolios?.length === 0 && (
            <p className="text-[11px] text-text-muted">
              No portfolios yet — create one in Portfolio.
            </p>
          )}
          {portfolios?.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={portfolioDisabled}
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
