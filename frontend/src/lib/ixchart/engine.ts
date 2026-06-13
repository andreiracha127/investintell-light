/**
 * IXChart — engine canvas 2D do chart interativo (zero deps).
 * Port de design/assets/chart-engine.js (repo investintell-datalake-workers,
 * commit 517eb41): candles/ohlc/linha/área, painéis volume/RSI, SMA20/50,
 * comparação normalizada, log/%, pan/zoom, crosshair, desenhos
 * (trend/hline/fib/régua), tick ao vivo no candle corrente.
 *
 * Diferenças deliberadas vs protótipo:
 *  - dados reais via setBars()/setCompare() — sem séries sintéticas;
 *  - tokens injetados (reage a tema), sem getComputedStyle interno;
 *  - destroy() remove listeners/observer (ciclo de vida React);
 *  - sem LiveFeed/fetchMetrics aqui — o wrapper liga o feed e chama applyTick.
 */
import { fmtD, fmtP, fmtV, niceTicks, resample, rsi, sma } from "./series";
import { MONTHS } from "./series";
import type { Bar, ChartType, DrawTool, Drawing, DrawPoint, Period } from "./types";
import type { IxTokens } from "./tokens";

export interface ChartCallbacks {
  onCrosshair?: (bar: Bar | null, prev: Bar | null) => void;
  onViewChange?: () => void;
  onToolDone?: () => void;
}

interface Pane {
  id: "price" | "volume" | "rsi";
  y: number;
  h: number;
}

interface Layout {
  axW: number;
  axH: number;
  plotW: number;
  panes: Pane[];
}

interface PriceTransform {
  fwd: (p: number) => number;
  label?: ((v: number) => string) | null;
  inv?: (v: number) => number;
}

export class Chart {
  cv: HTMLCanvasElement;
  cx: CanvasRenderingContext2D;
  tk: IxTokens;
  cb: ChartCallbacks;
  daily: Bar[] = [];
  bars: Bar[] = [];
  period: Period = "D";
  type: ChartType = "candles";
  scale = { log: false, pct: false };
  overlays = { sma20: true, sma50: false };
  panes = { volume: true, rsi: false };
  compareWith: { symbol: string; bars: Bar[] } | null = null;
  drawings: Drawing[] = [];
  tool: DrawTool | null = null;
  magnet = false;
  pending: DrawPoint | null = null;
  cross: { x: number; y: number } | null = null;
  view = { first: 0, count: 0 };
  lastTick = { dir: 0, at: 0 };

  private _compareDaily: Bar[] | null = null;
  private _pctForced = false;
  private _flashT: ReturnType<typeof setTimeout> | undefined;
  private _ro: ResizeObserver;
  private _drag: { x: number; first: number } | null = null;
  private _onWinMove!: (e: MouseEvent) => void;
  private _onWinUp!: () => void;
  private _onKeyDown!: (e: KeyboardEvent) => void;
  private ind: { sma20: (number | null)[]; sma50: (number | null)[]; rsi: (number | null)[] } = {
    sma20: [],
    sma50: [],
    rsi: [],
  };
  private L!: Layout;
  private W = 0;
  private H = 0;
  private _yP!: (p: number) => number;
  private _pMin = 0;
  private _pMax = 0;
  private _T!: PriceTransform;

  constructor(canvas: HTMLCanvasElement, tokens: IxTokens, cb: ChartCallbacks = {}) {
    this.cv = canvas;
    this.cx = canvas.getContext("2d")!;
    this.tk = tokens;
    this.cb = cb;
    this._bindEvents();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(canvas.parentElement!);
    this._resize();
  }

  /* ------------------------------------------------------------- estado */
  /** Define a série diária real (contrato do /history) e re-deriva tudo. */
  setBars(daily: Bar[]): void {
    this.daily = daily;
    this._rebuild();
  }

  /** Comparação normalizada: barras diárias do outro símbolo (ou null p/ limpar). */
  setCompare(symbol: string | null, daily?: Bar[]): void {
    if (!symbol || !daily) {
      this.compareWith = null;
      this._compareDaily = null;
      if (!this._pctForced) this.scale.pct = false;
    } else {
      this._compareDaily = daily;
      this.compareWith = { symbol: symbol.toUpperCase(), bars: resample(daily, this.period) };
      this._pctForced = this.scale.pct;
      this.scale.pct = true; // comparação só faz sentido normalizada
    }
    this.render();
  }

  setPeriod(p: Period): void {
    this.period = p;
    this._rebuild();
  }
  setType(t: ChartType): void {
    this.type = t;
    this.render();
  }
  setRange(nBars: number | "all"): void {
    const n = nBars === "all" ? this.bars.length : Math.min(nBars, this.bars.length);
    this.view = { first: this.bars.length - n, count: n };
    this.render();
    this.cb.onViewChange?.();
  }
  toggleOverlay(k: "sma20" | "sma50"): boolean {
    this.overlays[k] = !this.overlays[k];
    this.render();
    return this.overlays[k];
  }
  togglePane(k: "volume" | "rsi"): boolean {
    this.panes[k] = !this.panes[k];
    this.render();
    return this.panes[k];
  }
  setScale(part: Partial<{ log: boolean; pct: boolean }>): void {
    Object.assign(this.scale, part);
    this.render();
  }
  setTool(t: DrawTool | null): void {
    this.tool = t;
    this.pending = null;
    this.cv.style.cursor = t ? "crosshair" : "default";
  }
  undoDrawing(): void {
    this.drawings.pop();
    this.render();
  }
  clearDrawings(): void {
    this.drawings = [];
    this.pending = null;
    this.render();
  }

  private _rebuild(): void {
    this.bars = resample(this.daily, this.period);
    if (this.compareWith && this._compareDaily) {
      this.compareWith.bars = resample(this._compareDaily, this.period);
    }
    this.ind = { sma20: sma(this.bars, 20), sma50: sma(this.bars, 50), rsi: rsi(this.bars, 14) };
    const count = Math.min(this.view.count || 130, this.bars.length) || 130;
    this.view = { first: this.bars.length - count, count };
    this.render();
    this.cb.onViewChange?.();
  }

  /* feed ao vivo: muta a última barra diária e re-deriva */
  applyTick(price: number, size: number): void {
    if (!this.daily.length || !this.bars.length) return;
    const lb = this.daily[this.daily.length - 1];
    this.lastTick = { dir: Math.sign(price - lb.c), at: performance.now() };
    lb.c = price;
    lb.h = Math.max(lb.h, price);
    lb.l = Math.min(lb.l, price);
    lb.v += size;
    const vb = this.bars[this.bars.length - 1];
    vb.c = price;
    vb.h = Math.max(vb.h, price);
    vb.l = Math.min(vb.l, price);
    vb.v += size;
    const n = this.bars.length;
    for (const k of ["sma20", "sma50"] as const) {
      const p = k === "sma20" ? 20 : 50;
      if (n >= p) this.ind[k][n - 1] = this.bars.slice(n - p).reduce((a, b) => a + b.c, 0) / p;
    }
    this.render();
    // flash do badge por ~350ms
    clearTimeout(this._flashT);
    this._flashT = setTimeout(() => {
      this.lastTick.dir = 0;
      this.render();
    }, 360);
  }

  /** Remove listeners globais e o ResizeObserver — chamar no unmount. */
  destroy(): void {
    this._ro.disconnect();
    window.removeEventListener("mousemove", this._onWinMove);
    window.removeEventListener("mouseup", this._onWinUp);
    window.removeEventListener("keydown", this._onKeyDown);
    clearTimeout(this._flashT);
  }

  /* ------------------------------------------------------------- layout */
  private _resize(): void {
    const r = this.cv.parentElement!.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.W = Math.max(200, r.width);
    this.H = Math.max(160, r.height);
    this.cv.width = this.W * dpr;
    this.cv.height = this.H * dpr;
    this.cv.style.width = this.W + "px";
    this.cv.style.height = this.H + "px";
    this.cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.render();
  }

  private _layout(): Layout {
    const axW = 64,
      axH = 24;
    const plotW = this.W - axW;
    const free = this.H - axH;
    const volH = this.panes.volume ? Math.max(56, free * 0.16) : 0;
    const rsiH = this.panes.rsi ? Math.max(64, free * 0.18) : 0;
    const priceH = free - volH - rsiH;
    const panes: Pane[] = [{ id: "price", y: 0, h: priceH }];
    if (this.panes.volume) panes.push({ id: "volume", y: priceH, h: volH });
    if (this.panes.rsi) panes.push({ id: "rsi", y: priceH + volH, h: rsiH });
    return { axW, axH, plotW, panes };
  }

  private _xAt(i: number): number {
    return (i - this.view.first + 0.5) * (this.L.plotW / this.view.count);
  }
  private _iAt(x: number): number {
    return this.view.first + x / (this.L.plotW / this.view.count) - 0.5;
  }

  private _priceTransform(): PriceTransform {
    // modo %: relativo ao primeiro close visível; modo log: log10
    const base = this.bars[Math.max(0, Math.ceil(this.view.first))]?.c || 1;
    if (this.scale.pct)
      return { fwd: (p) => (p / base - 1) * 100, label: (v) => fmtP(v, 1) + "%" };
    if (this.scale.log)
      return { fwd: (p) => Math.log10(Math.max(p, 1e-9)), label: null, inv: (v) => Math.pow(10, v) };
    return { fwd: (p) => p, label: null };
  }

  /* ------------------------------------------------------------- render */
  render(): void {
    if (!this.bars || !this.W) return;
    const cx = this.cx;
    this.L = this._layout();
    const { axW, axH, plotW, panes } = this.L;
    cx.clearRect(0, 0, this.W, this.H);
    cx.font = `10.5px ${this.tk.mono}`;

    const i0 = Math.max(0, Math.floor(this.view.first));
    const i1 = Math.min(this.bars.length - 1, Math.ceil(this.view.first + this.view.count));
    const vis = this.bars.slice(i0, i1 + 1);
    if (!vis.length) return;

    const T = this._priceTransform();
    let pMin = Infinity,
      pMax = -Infinity;
    for (const b of vis) {
      pMin = Math.min(pMin, T.fwd(b.l));
      pMax = Math.max(pMax, T.fwd(b.h));
    }
    if (this.compareWith) {
      const cb = this.compareWith.bars,
        cBase = cb[Math.max(0, Math.min(cb.length - 1, i0))]?.c || 1;
      for (let i = i0; i <= Math.min(i1, cb.length - 1); i++) {
        const val = this.scale.pct ? (cb[i].c / cBase - 1) * 100 : T.fwd(cb[i].c);
        pMin = Math.min(pMin, val);
        pMax = Math.max(pMax, val);
      }
    }
    const pad = (pMax - pMin) * 0.07 || 1;
    pMin -= pad;
    pMax += pad;
    const pricePane = panes[0];
    const yP = (p: number): number =>
      pricePane.y + pricePane.h * (1 - (T.fwd(p) - pMin) / (pMax - pMin));
    const yRaw = (v: number): number =>
      pricePane.y + pricePane.h * (1 - (v - pMin) / (pMax - pMin));
    this._yP = yP;
    this._pMin = pMin;
    this._pMax = pMax;
    this._T = T;

    /* grid + eixo Y do painel de preço */
    cx.strokeStyle = this.tk.grid;
    cx.fillStyle = this.tk.text3;
    cx.lineWidth = 1;
    const ticks = niceTicks(pMin, pMax, Math.round(pricePane.h / 56));
    cx.textAlign = "left";
    cx.textBaseline = "middle";
    for (const tv of ticks) {
      const y = Math.round(yRaw(tv)) + 0.5;
      cx.beginPath();
      cx.moveTo(0, y);
      cx.lineTo(plotW, y);
      cx.stroke();
      const lab = this.scale.pct
        ? fmtP(tv, 1) + "%"
        : this.scale.log
          ? fmtP(Math.pow(10, tv), Math.pow(10, tv) < 10 ? 2 : 2)
          : fmtP(tv, 2);
      cx.fillText(lab, plotW + 8, y);
    }

    /* eixo X: marcas por mês (ou ano em zoom amplo) */
    const barW = plotW / this.view.count;
    cx.textAlign = "center";
    cx.textBaseline = "top";
    let lastKey: number | null = null;
    const monthly =
      this.view.count * (this.period === "D" ? 1 : this.period === "W" ? 5 : 21) < 420;
    for (let i = i0; i <= i1; i++) {
      const d = new Date(this.bars[i].t);
      const key = monthly ? d.getFullYear() * 100 + d.getMonth() : d.getFullYear();
      if (key !== lastKey) {
        lastKey = key;
        if (i > i0) {
          const x = Math.round(this._xAt(i)) + 0.5;
          cx.strokeStyle = this.tk.grid;
          cx.beginPath();
          cx.moveTo(x, 0);
          cx.lineTo(x, this.H - axH);
          cx.stroke();
          cx.fillStyle = this.tk.text3;
          cx.fillText(
            monthly
              ? `${MONTHS[d.getMonth()]}${d.getMonth() === 0 ? " " + d.getFullYear() : ""}`
              : String(d.getFullYear()),
            x,
            this.H - axH + 7,
          );
        }
      }
    }

    /* separadores de painéis */
    cx.strokeStyle = this.tk.border;
    for (const pn of panes.slice(1)) {
      cx.beginPath();
      cx.moveTo(0, pn.y + 0.5);
      cx.lineTo(this.W, pn.y + 0.5);
      cx.stroke();
    }
    cx.beginPath();
    cx.moveTo(plotW + 0.5, 0);
    cx.lineTo(plotW + 0.5, this.H - axH);
    cx.stroke();
    cx.beginPath();
    cx.moveTo(0, this.H - axH + 0.5);
    cx.lineTo(this.W, this.H - axH + 0.5);
    cx.stroke();

    /* marca d'água */
    cx.save();
    cx.font = `700 26px ${this.tk.ui}`;
    cx.fillStyle = "rgba(43,47,54,.06)";
    cx.textAlign = "left";
    cx.textBaseline = "bottom";
    cx.fillText("investintell", 16, pricePane.y + pricePane.h - 10);
    cx.restore();

    /* série principal */
    cx.save();
    cx.beginPath();
    cx.rect(0, pricePane.y, plotW, pricePane.h);
    cx.clip();
    const bodyW = Math.max(1, barW * 0.62);
    if (this.type === "line" || this.type === "area") {
      cx.beginPath();
      for (let i = i0; i <= i1; i++) {
        const x = this._xAt(i),
          y = yP(this.bars[i].c);
        if (i === i0) cx.moveTo(x, y);
        else cx.lineTo(x, y);
      }
      if (this.type === "area") {
        const g = cx.createLinearGradient(0, pricePane.y, 0, pricePane.y + pricePane.h);
        g.addColorStop(0, "rgba(43,47,54,.16)");
        g.addColorStop(1, "rgba(43,47,54,0)");
        cx.save();
        cx.lineTo(this._xAt(i1), pricePane.y + pricePane.h);
        cx.lineTo(this._xAt(i0), pricePane.y + pricePane.h);
        cx.fillStyle = g;
        cx.fill();
        cx.restore();
        cx.beginPath();
        for (let i = i0; i <= i1; i++) {
          const x = this._xAt(i),
            y = yP(this.bars[i].c);
          if (i === i0) cx.moveTo(x, y);
          else cx.lineTo(x, y);
        }
      }
      cx.strokeStyle = this.tk.graphite;
      cx.lineWidth = 1.6;
      cx.stroke();
    } else {
      for (let i = i0; i <= i1; i++) {
        const b = this.bars[i],
          x = this._xAt(i);
        const up = b.c >= b.o,
          col = up ? this.tk.pos : this.tk.neg;
        cx.strokeStyle = col;
        cx.fillStyle = col;
        cx.lineWidth = 1;
        if (this.type === "ohlc" || barW < 3) {
          cx.beginPath();
          cx.moveTo(x, yP(b.h));
          cx.lineTo(x, yP(b.l));
          if (this.type === "ohlc" && barW >= 3) {
            cx.moveTo(x - bodyW / 2, yP(b.o));
            cx.lineTo(x, yP(b.o));
            cx.moveTo(x, yP(b.c));
            cx.lineTo(x + bodyW / 2, yP(b.c));
          }
          cx.stroke();
        } else {
          cx.beginPath();
          cx.moveTo(x, yP(b.h));
          cx.lineTo(x, yP(b.l));
          cx.stroke();
          const yO = yP(b.o),
            yC = yP(b.c);
          const top = Math.min(yO, yC),
            hh = Math.max(1, Math.abs(yO - yC));
          if (up) {
            // candle de alta: vazado, traço verde sobre fundo claro
            cx.fillStyle = this.tk.bg;
            cx.fillRect(x - bodyW / 2, top, bodyW, hh);
            cx.strokeRect(x - bodyW / 2 + 0.5, top + 0.5, bodyW - 1, Math.max(1, hh - 1));
          } else {
            cx.fillRect(x - bodyW / 2, top, bodyW, hh);
          }
        }
      }
    }

    /* overlays */
    const drawLine = (
      vals: (number | null)[],
      color: string,
      width: number,
      mapper: (v: number) => number,
    ): void => {
      cx.beginPath();
      let started = false;
      for (let i = i0; i <= i1; i++) {
        const v = vals[i];
        if (v == null) continue;
        const x = this._xAt(i),
          y = mapper(v);
        if (started) cx.lineTo(x, y);
        else cx.moveTo(x, y);
        started = true;
      }
      cx.strokeStyle = color;
      cx.lineWidth = width;
      cx.stroke();
    };
    if (this.overlays.sma20) drawLine(this.ind.sma20, this.tk.sma20, 1.3, yP);
    if (this.overlays.sma50) drawLine(this.ind.sma50, this.tk.sma50, 1.3, yP);
    if (this.compareWith) {
      const cb = this.compareWith.bars,
        cBase = cb[Math.max(0, Math.min(cb.length - 1, i0))]?.c || 1;
      cx.setLineDash([5, 3]);
      drawLine(
        cb.map((b) => b.c),
        this.tk.compare,
        1.5,
        this.scale.pct ? (v) => yRaw((v / cBase - 1) * 100) : yP,
      );
      cx.setLineDash([]);
    }

    /* desenhos do usuário */
    this._renderDrawings(cx);
    cx.restore();

    /* último preço: linha + badge */
    const last = this.bars[this.bars.length - 1];
    const yLast = yP(last.c);
    if (yLast > pricePane.y && yLast < pricePane.y + pricePane.h) {
      cx.setLineDash([2, 3]);
      cx.strokeStyle = last.c >= last.o ? this.tk.pos : this.tk.neg;
      cx.lineWidth = 1;
      cx.beginPath();
      cx.moveTo(0, yLast + 0.5);
      cx.lineTo(plotW, yLast + 0.5);
      cx.stroke();
      cx.setLineDash([]);
      const flash = this.lastTick.dir !== 0;
      const bg = flash ? (this.lastTick.dir > 0 ? this.tk.pos : this.tk.neg) : this.tk.graphite;
      cx.fillStyle = bg;
      cx.fillRect(plotW, yLast - 9, axW, 18);
      cx.fillStyle = "#ffffff";
      cx.textAlign = "left";
      cx.textBaseline = "middle";
      const labP = this.scale.pct ? fmtP(T.fwd(last.c), 1) + "%" : fmtP(last.c, 2);
      cx.fillText(labP, plotW + 8, yLast);
    }

    /* painel de volume */
    const volPane = panes.find((p) => p.id === "volume");
    if (volPane) {
      let vMax = 0;
      for (const b of vis) vMax = Math.max(vMax, b.v);
      cx.save();
      cx.beginPath();
      cx.rect(0, volPane.y, plotW, volPane.h);
      cx.clip();
      for (let i = i0; i <= i1; i++) {
        const b = this.bars[i],
          x = this._xAt(i);
        const h = (b.v / vMax) * (volPane.h - 14);
        cx.fillStyle = b.c >= b.o ? this.tk.pos : this.tk.neg;
        cx.globalAlpha = 0.75;
        cx.fillRect(x - Math.max(0.5, bodyW / 2), volPane.y + volPane.h - h, Math.max(1, bodyW), h);
      }
      cx.globalAlpha = 1;
      cx.restore();
      cx.fillStyle = this.tk.text3;
      cx.font = `10px ${this.tk.ui}`;
      cx.textAlign = "left";
      cx.textBaseline = "top";
      cx.fillText("VOL", 8, volPane.y + 5);
      cx.font = `10.5px ${this.tk.mono}`;
      cx.fillText(fmtV(last.v), plotW + 8, volPane.y + 5);
    }

    /* painel RSI */
    const rsiPane = panes.find((p) => p.id === "rsi");
    if (rsiPane) {
      const yR = (v: number): number => rsiPane.y + 6 + (rsiPane.h - 12) * (1 - v / 100);
      cx.fillStyle = "rgba(43,47,54,.035)";
      cx.fillRect(0, yR(70), plotW, yR(30) - yR(70));
      cx.setLineDash([3, 3]);
      cx.strokeStyle = this.tk.borderS;
      for (const lv of [30, 70]) {
        cx.beginPath();
        cx.moveTo(0, yR(lv) + 0.5);
        cx.lineTo(plotW, yR(lv) + 0.5);
        cx.stroke();
      }
      cx.setLineDash([]);
      cx.save();
      cx.beginPath();
      cx.rect(0, rsiPane.y, plotW, rsiPane.h);
      cx.clip();
      drawLine(this.ind.rsi, this.tk.graphite, 1.3, yR);
      cx.restore();
      cx.fillStyle = this.tk.text3;
      cx.font = `10px ${this.tk.ui}`;
      cx.textAlign = "left";
      cx.textBaseline = "top";
      cx.fillText("RSI 14", 8, rsiPane.y + 5);
      const rv = this.ind.rsi[this.bars.length - 1];
      cx.font = `10.5px ${this.tk.mono}`;
      cx.fillText(rv == null ? "—" : fmtP(rv, 1), plotW + 8, rsiPane.y + 5);
    }

    /* crosshair */
    if (this.cross) this._renderCrosshair(cx);
  }

  private _renderDrawings(cx: CanvasRenderingContext2D): void {
    const yP = this._yP;
    const all: Drawing[] = [...this.drawings];
    if (this.pending && this.cross && this.tool) {
      all.push({
        type: this.tool,
        p1: this.pending,
        p2: this._dataPoint(this.cross.x, this.cross.y),
      });
    }
    for (const d of all) {
      cx.strokeStyle = this.tk.accent;
      cx.fillStyle = this.tk.accent;
      cx.lineWidth = 1.2;
      const x1 = this._xAt(d.p1.i),
        y1 = yP(d.p1.p);
      if (d.type === "hline") {
        cx.setLineDash([6, 3]);
        cx.beginPath();
        cx.moveTo(0, y1 + 0.5);
        cx.lineTo(this.L.plotW, y1 + 0.5);
        cx.stroke();
        cx.setLineDash([]);
        cx.font = `10px ${this.tk.mono}`;
        cx.textAlign = "left";
        cx.textBaseline = "bottom";
        cx.fillText(fmtP(d.p1.p, 2), 6, y1 - 2);
        continue;
      }
      if (!d.p2) continue;
      const x2 = this._xAt(d.p2.i),
        y2 = yP(d.p2.p);
      if (d.type === "trend") {
        cx.beginPath();
        cx.moveTo(x1, y1);
        cx.lineTo(x2, y2);
        cx.stroke();
        for (const [x, y] of [
          [x1, y1],
          [x2, y2],
        ]) {
          cx.beginPath();
          cx.arc(x, y, 2.5, 0, 7);
          cx.fill();
        }
      } else if (d.type === "fib") {
        const lv = [0, 0.236, 0.382, 0.5, 0.618, 1];
        cx.font = `10px ${this.tk.mono}`;
        cx.textAlign = "right";
        cx.textBaseline = "bottom";
        for (const f of lv) {
          const p = d.p1.p + (d.p2.p - d.p1.p) * f;
          const y = yP(p) + 0.5;
          cx.globalAlpha = f === 0 || f === 1 ? 0.9 : 0.55;
          cx.beginPath();
          cx.moveTo(Math.min(x1, x2), y);
          cx.lineTo(Math.max(x1, x2), y);
          cx.stroke();
          cx.fillText(`${(f * 100).toFixed(1)} · ${fmtP(p, 2)}`, Math.max(x1, x2) - 4, y - 2);
        }
        cx.globalAlpha = 1;
      } else if (d.type === "measure") {
        const dp = d.p2.p - d.p1.p,
          dpc = (d.p2.p / d.p1.p - 1) * 100;
        const nb = Math.round(Math.abs(d.p2.i - d.p1.i));
        cx.globalAlpha = 0.1;
        cx.fillStyle = dp >= 0 ? this.tk.pos : this.tk.neg;
        cx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
        cx.globalAlpha = 1;
        cx.strokeStyle = dp >= 0 ? this.tk.pos : this.tk.neg;
        cx.strokeRect(
          Math.min(x1, x2) + 0.5,
          Math.min(y1, y2) + 0.5,
          Math.abs(x2 - x1),
          Math.abs(y2 - y1),
        );
        const lab = `${dp >= 0 ? "+" : ""}${fmtP(dp, 2)} (${dp >= 0 ? "+" : ""}${fmtP(dpc, 2)}%) · ${nb} barras`;
        cx.font = `10.5px ${this.tk.mono}`;
        const tw = cx.measureText(lab).width + 12;
        const bx = (x1 + x2) / 2 - tw / 2,
          by = Math.min(y1, y2) - 22;
        cx.fillStyle = this.tk.graphite;
        cx.fillRect(bx, by, tw, 17);
        cx.fillStyle = "#fff";
        cx.textAlign = "center";
        cx.textBaseline = "middle";
        cx.fillText(lab, (x1 + x2) / 2, by + 8.5);
      }
    }
  }

  private _renderCrosshair(cx: CanvasRenderingContext2D): void {
    const { plotW, axW, axH, panes } = this.L;
    const { x, y } = this.cross!;
    if (x < 0 || x > plotW || y < 0 || y > this.H - axH) return;
    cx.setLineDash([3, 3]);
    cx.strokeStyle = this.tk.text3;
    cx.lineWidth = 1;
    cx.beginPath();
    cx.moveTo(x + 0.5, 0);
    cx.lineTo(x + 0.5, this.H - axH);
    cx.stroke();
    cx.beginPath();
    cx.moveTo(0, y + 0.5);
    cx.lineTo(plotW, y + 0.5);
    cx.stroke();
    cx.setLineDash([]);
    // label de preço (apenas no painel de preço)
    const pp = panes[0];
    if (y >= pp.y && y <= pp.y + pp.h) {
      const v = this._pMin + (1 - (y - pp.y) / pp.h) * (this._pMax - this._pMin);
      const lab = this.scale.pct
        ? fmtP(v, 1) + "%"
        : this.scale.log
          ? fmtP(Math.pow(10, v), 2)
          : fmtP(v, 2);
      cx.fillStyle = this.tk.graphite;
      cx.fillRect(plotW, y - 9, axW, 18);
      cx.fillStyle = "#fff";
      cx.textAlign = "left";
      cx.textBaseline = "middle";
      cx.font = `10.5px ${this.tk.mono}`;
      cx.fillText(lab, plotW + 8, y);
    }
    // label de data
    const i = Math.round(this._iAt(x));
    if (i >= 0 && i < this.bars.length) {
      const lab = fmtD(this.bars[i].t);
      cx.font = `10.5px ${this.tk.mono}`;
      const tw = cx.measureText(lab).width + 14;
      cx.fillStyle = this.tk.graphite;
      cx.fillRect(x - tw / 2, this.H - axH, tw, axH);
      cx.fillStyle = "#fff";
      cx.textAlign = "center";
      cx.textBaseline = "middle";
      cx.fillText(lab, x, this.H - axH / 2);
    }
  }

  /* --------------------------------------------------------- interações */
  private _dataPoint(x: number, y: number): DrawPoint {
    let i = this._iAt(x);
    const pp = this.L.panes[0];
    const vRaw = this._pMin + (1 - (y - pp.y) / pp.h) * (this._pMax - this._pMin);
    let p = this.scale.log ? Math.pow(10, vRaw) : vRaw; // em modo % desenhos ficam aproximados
    if (this.magnet) {
      const bi = Math.max(0, Math.min(this.bars.length - 1, Math.round(i)));
      const b = this.bars[bi];
      const cands = [b.o, b.h, b.l, b.c];
      p = cands.reduce((best, c) => (Math.abs(c - p) < Math.abs(best - p) ? c : best), cands[0]);
      i = bi;
    }
    return { i, p };
  }

  private _bindEvents(): void {
    const cv = this.cv;
    cv.addEventListener("mousedown", (e) => {
      const { offsetX: x, offsetY: y } = e;
      if (this.tool) {
        const pt = this._dataPoint(x, y);
        if (this.tool === "hline") {
          this.drawings.push({ type: "hline", p1: pt });
          this.setTool(null);
          this.cb.onToolDone?.();
        } else if (!this.pending) this.pending = pt;
        else {
          this.drawings.push({ type: this.tool, p1: this.pending, p2: pt });
          this.pending = null;
          this.setTool(null);
          this.cb.onToolDone?.();
        }
        this.render();
        return;
      }
      this._drag = { x, first: this.view.first };
      cv.style.cursor = "grabbing";
    });
    this._onWinMove = (e: MouseEvent) => {
      if (!this._drag) return;
      const dx = e.clientX - cv.getBoundingClientRect().left - this._drag.x;
      const perBar = this.L.plotW / this.view.count;
      this.view.first = Math.max(
        -this.view.count * 0.5,
        Math.min(this.bars.length - this.view.count * 0.5, this._drag.first - dx / perBar),
      );
      this.render();
      this.cb.onViewChange?.();
    };
    window.addEventListener("mousemove", this._onWinMove);
    this._onWinUp = () => {
      this._drag = null;
      cv.style.cursor = this.tool ? "crosshair" : "default";
    };
    window.addEventListener("mouseup", this._onWinUp);

    cv.addEventListener("mousemove", (e) => {
      this.cross = { x: e.offsetX, y: e.offsetY };
      const i = Math.round(this._iAt(e.offsetX));
      this.cb.onCrosshair?.(
        i >= 0 && i < this.bars.length ? this.bars[i] : null,
        i > 0 ? this.bars[i - 1] : null,
      );
      if (!this._drag) this.render();
    });
    cv.addEventListener("mouseleave", () => {
      this.cross = null;
      this.cb.onCrosshair?.(null, null);
      this.render();
    });

    cv.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const k = Math.exp(e.deltaY * 0.0012);
        const anchor = this._iAt(e.offsetX);
        const count = Math.max(15, Math.min(this.bars.length * 1.2, this.view.count * k));
        const ratio = (anchor - this.view.first) / this.view.count;
        this.view.count = count;
        this.view.first = anchor - ratio * count;
        this.render();
        this.cb.onViewChange?.();
      },
      { passive: false },
    );

    cv.addEventListener("dblclick", () => this.setRange(130));
    this._onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        this.setTool(null);
        this.cb.onToolDone?.();
        this.render();
      }
    };
    window.addEventListener("keydown", this._onKeyDown);
  }
}
