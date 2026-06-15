"use client";

/**
 * Chart interativo (IXChart) com toolbar: tipo, período D/W/M, ranges,
 * SMA/VOL/RSI, log/%, compare, ferramentas de desenho e tick ao vivo
 * (subscribeTicks → chart.applyTick; barra do dia anima a cada trade).
 * O range selecionado é elevado via onRangeChange para sincronizar as
 * métricas da página (analysis) com a janela visível.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchFundTimeseries,
  fetchStockTimeseries,
  fundTimeseriesToHistoryBars,
  RANGE_PRESETS,
  stockTimeseriesToHistoryBars,
  type RangePreset,
  type SymbolSearchResult,
} from "@/lib/api/client";
import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
import { Chart } from "@/lib/ixchart/engine";
import { readIxTokens } from "@/lib/ixchart/tokens";
import { fmtP, fmtV } from "@/lib/ixchart/series";
import type { Bar, ChartType, DrawTool, Period } from "@/lib/ixchart/types";
import { onFeedStatus, subscribeTicks, type FeedStatus } from "@/lib/livefeed/client";

/** Barras visíveis por preset, em pregões (D); W/M dividem na troca de período. */
const RANGE_BARS: Record<RangePreset, number | "all"> = {
  "1M": 21, "6M": 126, "1Y": 252, "5Y": 1260, MAX: "all",
};

const PERIODS: Period[] = ["D", "W", "M"];
const TYPES: { id: ChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "ohlc", label: "OHLC" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
];
const TOOLS: { id: DrawTool; label: string }[] = [
  { id: "trend", label: "Trend" },
  { id: "hline", label: "Horizontal" },
  { id: "fib", label: "Fib" },
  { id: "measure", label: "Measure" },
];

export function InteractiveChart({
  symbol,
  bars,
  range,
  onRangeChange,
  mode = "ohlcv",
  className,
}: {
  symbol: string;
  bars: Bar[];
  range: RangePreset;
  onRangeChange: (next: RangePreset) => void;
  /** "nav" = série de NAV (mutual fund): só Line/Area, sem VOL nem live. */
  mode?: "ohlcv" | "nav";
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const legendRef = useRef<HTMLDivElement>(null);

  const [period, setPeriod] = useState<Period>("D");
  const [type, setType] = useState<ChartType>(mode === "nav" ? "line" : "candles");
  const [overlays, setOverlays] = useState({ sma20: true, sma50: false });
  const [panes, setPanes] = useState({ volume: mode !== "nav", rsi: false });
  const [scale, setScale] = useState({ log: false, pct: false });
  const [tool, setTool] = useState<DrawTool | null>(null);
  const [compareSel, setCompareSel] = useState<SymbolSearchResult | null>(null);
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<FeedStatus>("off");

  const { data: compareBars } = useQuery<Bar[]>({
    queryKey: [
      "compare-timeseries",
      compareSel?.kind,
      compareSel?.symbol,
      compareSel?.instrument_id,
      range,
    ],
    queryFn: async ({ signal }) => {
      if (
        compareSel!.instrument_id &&
        (compareSel!.kind === "mutual_fund" || compareSel!.kind === "mmf")
      ) {
        const data = await fetchFundTimeseries(
          compareSel!.instrument_id,
          range,
          signal,
        );
        return fundTimeseriesToHistoryBars(data);
      }
      const data = await fetchStockTimeseries(compareSel!.symbol, range, signal);
      return stockTimeseriesToHistoryBars(data);
    },
    enabled: compareSel != null,
    staleTime: 60 * 60 * 1000,
  });

  const applyRange = (c: Chart, preset: RangePreset, p: Period) => {
    const n = RANGE_BARS[preset];
    if (n === "all") c.setRange("all");
    else c.setRange(Math.max(15, Math.round(n / (p === "D" ? 1 : p === "W" ? 5 : 21))));
  };

  // mount/unmount do engine
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const chart = new Chart(canvas, readIxTokens(), {
      onCrosshair: (bar, prev) => {
        const el = legendRef.current;
        if (!el) return;
        if (!bar) {
          el.textContent = "";
          return;
        }
        const chg = prev ? ((bar.c / prev.c - 1) * 100).toFixed(2) : "0.00";
        el.textContent =
          `O ${fmtP(bar.o, 2)}  H ${fmtP(bar.h, 2)}  L ${fmtP(bar.l, 2)}  ` +
          `C ${fmtP(bar.c, 2)}  Δ ${chg}%  VOL ${fmtV(bar.v)}`;
      },
      onToolDone: () => setTool(null),
    });
    chartRef.current = chart;
    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, []);

  // dados / período / range
  useEffect(() => {
    const c = chartRef.current;
    if (!c || !bars.length) return;
    c.setPeriod(period); // _rebuild com a série atual (no-op de dados)
    c.setBars(bars);
    applyRange(c, range, period);
  }, [bars, period, range]);

  // comparação
  useEffect(() => {
    chartRef.current?.setCompare(compareSel?.symbol ?? null, compareBars);
  }, [compareSel, compareBars]);

  // opções de render
  useEffect(() => { chartRef.current?.setType(type); }, [type]);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    if (c.overlays.sma20 !== overlays.sma20) c.toggleOverlay("sma20");
    if (c.overlays.sma50 !== overlays.sma50) c.toggleOverlay("sma50");
  }, [overlays]);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    if (c.panes.volume !== panes.volume) c.togglePane("volume");
    if (c.panes.rsi !== panes.rsi) c.togglePane("rsi");
  }, [panes]);
  useEffect(() => { chartRef.current?.setScale(scale); }, [scale]);
  useEffect(() => { chartRef.current?.setTool(tool); }, [tool]);

  // feed ao vivo
  useEffect(() => onFeedStatus(setFeed), []);
  useEffect(() => {
    if (!live || mode === "nav") return;
    return subscribeTicks(symbol, (tick) => chartRef.current?.applyTick(tick.price, tick.size));
  }, [symbol, live, mode]);

  const typeOptions = mode === "nav" ? TYPES.filter((t) => t.id === "line" || t.id === "area") : TYPES;

  const btn = (active: boolean) =>
    `px-2 h-7 text-[11px] border-r border-border last:border-r-0 transition-colors ${
      active ? "bg-accent font-bold text-on-accent" : "text-text-muted hover:bg-layer-hover hover:text-text-primary"
    }`;

  const group = "flex items-stretch border border-border-strong";

  return (
    <div className={className}>
      {/* ── toolbar ── */}
      <div className="flex flex-wrap items-center gap-2 border border-b-0 border-border bg-surface-1 px-2 py-1.5 text-[11px]">
        <div role="group" aria-label="Chart type" className={group}>
          {typeOptions.map((t) => (
            <button key={t.id} type="button" aria-pressed={type === t.id}
              className={btn(type === t.id)} onClick={() => setType(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Period" className={group}>
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={period === p}
              className={btn(period === p)} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Range" className={group}>
          {RANGE_PRESETS.map((r) => (
            <button key={r} type="button" aria-pressed={range === r}
              className={btn(range === r)} onClick={() => onRangeChange(r)}>
              {r}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Overlays" className={group}>
          <button type="button" aria-pressed={overlays.sma20} className={btn(overlays.sma20)}
            onClick={() => setOverlays((o) => ({ ...o, sma20: !o.sma20 }))}>SMA20</button>
          <button type="button" aria-pressed={overlays.sma50} className={btn(overlays.sma50)}
            onClick={() => setOverlays((o) => ({ ...o, sma50: !o.sma50 }))}>SMA50</button>
          {mode !== "nav" && (
            <button type="button" aria-pressed={panes.volume} className={btn(panes.volume)}
              onClick={() => setPanes((p) => ({ ...p, volume: !p.volume }))}>VOL</button>
          )}
          <button type="button" aria-pressed={panes.rsi} className={btn(panes.rsi)}
            onClick={() => setPanes((p) => ({ ...p, rsi: !p.rsi }))}>RSI</button>
        </div>
        <div role="group" aria-label="Scale" className={group}>
          <button type="button" aria-pressed={scale.log} className={btn(scale.log)}
            onClick={() => setScale((s) => ({ ...s, log: !s.log, pct: false }))}>Log</button>
          <button type="button" aria-pressed={scale.pct} className={btn(scale.pct)}
            onClick={() => setScale((s) => ({ ...s, pct: !s.pct, log: false }))}>%</button>
        </div>
        <div role="group" aria-label="Draw" className={group}>
          {TOOLS.map((t) => (
            <button key={t.id} type="button" aria-pressed={tool === t.id}
              className={btn(tool === t.id)} onClick={() => setTool(tool === t.id ? null : t.id)}>
              {t.label}
            </button>
          ))}
          <button type="button" className={btn(false)}
            onClick={() => chartRef.current?.undoDrawing()}>Undo</button>
          <button type="button" className={btn(false)}
            onClick={() => chartRef.current?.clearDrawings()}>Clear</button>
        </div>
        <SymbolSearchInput
          active={compareSel?.symbol ?? null}
          onSelect={(item) => setCompareSel(item)}
          onClear={() => setCompareSel(null)}
        />
        <div className="flex-1" />
        {mode !== "nav" && (
          <button
            type="button"
            aria-pressed={live}
            onClick={() => setLive((v) => !v)}
            className={`flex h-7 items-center gap-1.5 border border-border-strong px-2 text-[11px] ${
              live && feed === "live" ? "text-gain" : "text-text-muted"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${
              live && feed === "live" ? "bg-gain" : "bg-border-strong"
            }`} />
            {live && feed === "live" ? "LIVE" : "EOD"}
          </button>
        )}
      </div>

      {/* ── legenda OHLC (atualizada via ref, sem re-render) ── */}
      <div
        ref={legendRef}
        aria-live="off"
        className="border border-b-0 border-border bg-surface-1 px-3 py-1 font-mono text-[10.5px] tabular-nums text-text-secondary min-h-[24px]"
      />

      {/* ── canvas ── */}
      <div className="relative h-[58vh] min-h-[380px] border border-border bg-surface-1">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
