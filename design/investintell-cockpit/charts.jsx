/* ===========================================================================
   charts.jsx — Investintell Cockpit data-viz
   Lightweight SVG charts drawn at measured pixel size (crisp at any width).
   All colors reference inherited CSS custom properties (--accent, --graphite,
   --grey-bar, --grid, --text-3, --pos, --neg) so charts recolor with the theme.
   Mock data is deterministic (seeded) so the mock is stable across renders.
   Mounted from the DC template via <x-import component="…" from="./charts.jsx">.
   =========================================================================== */
(function () {
  const R = React;
  const { useState, useRef, useLayoutEffect } = R;

  /* seeded RNG so mock data is stable */
  function rng(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }

  /* measure container -> {w,h} in px (synchronous first read + RO for resize) */
  function useMeasure() {
    const ref = useRef(null);
    const [size, setSize] = useState({ w: 0, h: 0 });
    useLayoutEffect(() => {
      const el = ref.current;
      if (!el) return;
      const measure = () => {
        const w = Math.round(el.clientWidth);
        const h = Math.round(el.clientHeight);
        setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
      };
      measure();
      let ro;
      if (typeof ResizeObserver !== "undefined") {
        ro = new ResizeObserver(measure);
        ro.observe(el);
      } else {
        window.addEventListener("resize", measure);
      }
      return () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", measure); };
    }, []);
    return [ref, size];
  }

  function Wrap({ children }) {
    const [ref, { w, h }] = useMeasure();
    return R.createElement(
      "div",
      { ref, style: { width: "100%", height: "100%", minHeight: 0 } },
      w > 0 && h > 0 ? children(w, h) : null
    );
  }

  const c = {
    accent: "var(--accent, #7A1C24)",
    accentWash: "var(--accent-wash, #F4EAEB)",
    graphite: "var(--graphite, #2B2F36)",
    grey: "var(--grey-bar, #C4C8CF)",
    grid: "var(--grid, #E3E5E9)",
    t3: "var(--text-3, #6f6f6f)",
    pos: "var(--pos, #1F6B3B)",
    neg: "var(--neg, #7A1C24)",
    layer: "var(--layer, #ffffff)",
  };

  const FONT = "var(--font-sans, Arial, sans-serif)";
  const STROKE = { vectorEffect: "non-scaling-stroke" };

  function path(pts) {
    return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
  }
  function scaleY(v, min, max, top, bot) {
    return bot - ((v - min) / (max - min || 1)) * (bot - top);
  }
  function gridLines(top, bot, left, right, n, key) {
    const out = [];
    for (let i = 0; i <= n; i++) {
      const y = top + ((bot - top) * i) / n;
      out.push(R.createElement("line", { key: key + i, x1: left, x2: right, y1: y, y2: y, stroke: c.grid, strokeWidth: 1, ...STROKE }));
    }
    return out;
  }
  function axisLabel(x, y, txt, anchor, size) {
    return R.createElement("text", { x, y, fill: c.t3, fontSize: size || 10, fontFamily: FONT, textAnchor: anchor || "middle", style: { fontVariantNumeric: "tabular-nums" } }, txt);
  }

  /* ── Candlestick + volume (flagship price) ──────────────────────────────── */
  function PriceCandles() {
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(7);
      const n = 64;
      let price = 168;
      const rows = [];
      for (let i = 0; i < n; i++) {
        const drift = 0.18 + Math.sin(i / 7) * 0.4;
        const o = price;
        const ch = (r() - 0.46 + drift * 0.04) * 3.4;
        const cl = Math.max(120, o + ch);
        const hi = Math.max(o, cl) + r() * 1.8;
        const lo = Math.min(o, cl) - r() * 1.8;
        rows.push({ o, c: cl, hi, lo, v: 0.4 + r() * 0.6 });
        price = cl;
      }
      const padL = 6, padR = 44, padT = 10;
      const volH = Math.min(54, h * 0.22);
      const priceBot = h - volH - 24;
      const hiV = Math.max(...rows.map((d) => d.hi));
      const loV = Math.min(...rows.map((d) => d.lo));
      const plotW = w - padL - padR;
      const step = plotW / n;
      const bw = Math.max(2, step * 0.58);
      // moving average
      const ma = rows.map((_, i) => {
        const s = Math.max(0, i - 9);
        const seg = rows.slice(s, i + 1);
        return seg.reduce((a, d) => a + d.c, 0) / seg.length;
      });
      const x = (i) => padL + step * i + step / 2;
      const py = (v) => scaleY(v, loV, hiV, padT, priceBot);
      const maxV = Math.max(...rows.map((d) => d.v));
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        ...gridLines(padT, priceBot, padL, w - padR, 4, "g"),
        // price axis labels
        [0, 1, 2, 3, 4].map((i) => {
          const v = hiV - ((hiV - loV) * i) / 4;
          const y = padT + ((priceBot - padT) * i) / 4;
          return axisLabel(w - padR + 6, y + 3, "$" + v.toFixed(0), "start");
        }),
        // candles
        rows.map((d, i) => {
          const up = d.c >= d.o;
          const col = up ? c.graphite : c.accent;
          const bx = x(i) - bw / 2;
          const yO = py(d.o), yC = py(d.c);
          return R.createElement(
            "g",
            { key: i },
            R.createElement("line", { x1: x(i), x2: x(i), y1: py(d.hi), y2: py(d.lo), stroke: col, strokeWidth: 1, ...STROKE }),
            R.createElement("rect", {
              x: bx, width: bw, y: Math.min(yO, yC), height: Math.max(1.5, Math.abs(yC - yO)),
              fill: up ? c.layer : col, stroke: col, strokeWidth: 1, ...STROKE,
            })
          );
        }),
        // MA line
        R.createElement("path", { d: path(ma.map((v, i) => [x(i), py(v)])), fill: "none", stroke: c.accent, strokeWidth: 1.5, ...STROKE }),
        // volume
        rows.map((d, i) =>
          R.createElement("rect", {
            key: "v" + i, x: x(i) - bw / 2, width: bw,
            y: h - 22 - (d.v / maxV) * volH, height: (d.v / maxV) * volH,
            fill: d.c >= d.o ? c.grey : c.accent, opacity: 0.55,
          })
        ),
        axisLabel(padL, h - 6, "Apr", "start"),
        axisLabel(w / 2, h - 6, "Aug", "middle"),
        axisLabel(w - padR, h - 6, "Dec", "end")
      );
    });
  }

  /* ── Cumulative return: ticker (accent) vs benchmark (grey) ─────────────── */
  function ReturnArea() {
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(21);
      const n = 80;
      const a = [], b = [];
      let va = 0, vb = 0;
      for (let i = 0; i < n; i++) {
        va += (r() - 0.42) * 1.4 + 0.22;
        vb += (r() - 0.46) * 1.1 + 0.14;
        a.push(va); b.push(vb);
      }
      const padL = 8, padR = 40, padT = 10, padB = 20;
      const all = a.concat(b);
      const mn = Math.min(0, ...all), mx = Math.max(...all);
      const x = (i) => padL + ((w - padL - padR) * i) / (n - 1);
      const y = (v) => scaleY(v, mn, mx, padT, h - padB);
      const aPts = a.map((v, i) => [x(i), y(v)]);
      const area = path(aPts) + ` L${x(n - 1)} ${y(0)} L${x(0)} ${y(0)} Z`;
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        ...gridLines(padT, h - padB, padL, w - padR, 4, "g"),
        [0, 1, 2, 3, 4].map((i) => {
          const v = mx - ((mx - mn) * i) / 4;
          const yy = padT + ((h - padB - padT) * i) / 4;
          return axisLabel(w - padR + 6, yy + 3, v.toFixed(0) + "%", "start");
        }),
        R.createElement("path", { d: area, fill: c.accent, opacity: 0.08 }),
        R.createElement("path", { d: path(b.map((v, i) => [x(i), y(v)])), fill: "none", stroke: c.grey, strokeWidth: 1.5, ...STROKE }),
        R.createElement("path", { d: path(aPts), fill: "none", stroke: c.accent, strokeWidth: 2, ...STROKE })
      );
    });
  }

  /* ── Rolling metric (single line, optional band) ────────────────────────── */
  function RollingLine(props) {
    const seed = props.seed || 3, band = props.band;
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(seed);
      const n = 70;
      const pts = [];
      let v = props.start != null ? props.start : 0.2;
      for (let i = 0; i < n; i++) {
        v += (r() - 0.5) * (props.vol || 0.03);
        pts.push(v);
      }
      const padL = 6, padR = 34, padT = 8, padB = 6;
      const mn = Math.min(...pts), mx = Math.max(...pts);
      const x = (i) => padL + ((w - padL - padR) * i) / (n - 1);
      const y = (val) => scaleY(val, mn, mx, padT, h - padB);
      const mean = pts.reduce((a, b) => a + b, 0) / n;
      const fmt = props.pct ? (z) => (z * 100).toFixed(0) + "%" : (z) => z.toFixed(2);
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        ...gridLines(padT, h - padB, padL, w - padR, 2, "g"),
        R.createElement("line", { x1: padL, x2: w - padR, y1: y(mean), y2: y(mean), stroke: c.t3, strokeWidth: 1, strokeDasharray: "3 3", ...STROKE }),
        R.createElement("path", { d: path(pts.map((val, i) => [x(i), y(val)])), fill: "none", stroke: c.accent, strokeWidth: 1.75, ...STROKE }),
        axisLabel(w - padR + 5, y(mx) + 3, fmt(mx), "start", 9),
        axisLabel(w - padR + 5, y(mn) + 3, fmt(mn), "start", 9)
      );
    });
  }

  /* ── Histogram of daily returns ─────────────────────────────────────────── */
  function Histogram() {
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(11);
      const bins = 25;
      const counts = [];
      for (let i = 0; i < bins; i++) {
        const d = (i - bins / 2) / (bins / 2);
        counts.push(Math.exp(-d * d * 3) * (60 + r() * 14));
      }
      const padL = 6, padR = 6, padT = 10, padB = 20;
      const mx = Math.max(...counts);
      const plotW = w - padL - padR;
      const bw = plotW / bins;
      const varIdx = 4; // VaR marker bucket (left tail)
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        ...gridLines(padT, h - padB, padL, w - padR, 3, "g"),
        counts.map((v, i) => {
          const bh = (v / mx) * (h - padB - padT);
          const tail = i <= varIdx;
          return R.createElement("rect", {
            key: i, x: padL + bw * i + 1, width: bw - 2,
            y: h - padB - bh, height: bh,
            fill: tail ? c.accent : c.graphite, opacity: tail ? 0.85 : 0.7,
          });
        }),
        R.createElement("line", { x1: padL + bw * (varIdx + 1), x2: padL + bw * (varIdx + 1), y1: padT, y2: h - padB, stroke: c.accent, strokeWidth: 1.25, strokeDasharray: "2 2", ...STROKE }),
        axisLabel(padL + bw * (varIdx + 1), padT - 1, "VaR 95", "middle", 9),
        axisLabel(padL, h - 6, "−6%", "start"),
        axisLabel(w / 2, h - 6, "0%", "middle"),
        axisLabel(w - padR, h - 6, "+6%", "end")
      );
    });
  }

  /* ── Allocation donut ───────────────────────────────────────────────────── */
  function AllocationDonut() {
    return R.createElement(Wrap, null, (w, h) => {
      const segs = [
        { v: 31, col: c.accent },
        { v: 22, col: c.graphite },
        { v: 16, col: "#565b63" },
        { v: 13, col: "#7f858d" },
        { v: 10, col: c.grey },
        { v: 8, col: "#d8dbe0" },
      ];
      const total = segs.reduce((a, s) => a + s.v, 0);
      const cx = w / 2, cy = h / 2;
      const rad = Math.min(w, h) / 2 - 8;
      const inner = rad * 0.62;
      let ang = -Math.PI / 2;
      const arcs = segs.map((s, i) => {
        const a0 = ang;
        const a1 = ang + (s.v / total) * Math.PI * 2;
        ang = a1;
        const large = a1 - a0 > Math.PI ? 1 : 0;
        const p = (a, rr) => [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
        const [x0, y0] = p(a0, rad), [x1, y1] = p(a1, rad);
        const [x2, y2] = p(a1, inner), [x3, y3] = p(a0, inner);
        const d = `M${x0} ${y0} A${rad} ${rad} 0 ${large} 1 ${x1} ${y1} L${x2} ${y2} A${inner} ${inner} 0 ${large} 0 ${x3} ${y3} Z`;
        return R.createElement("path", { key: i, d, fill: s.col });
      });
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        arcs,
        R.createElement("text", { x: cx, y: cy - 2, fill: "var(--text, #161616)", fontSize: 17, fontWeight: 700, fontFamily: FONT, textAnchor: "middle", style: { fontVariantNumeric: "tabular-nums" } }, "12"),
        R.createElement("text", { x: cx, y: cy + 13, fill: c.t3, fontSize: 9, fontFamily: FONT, textAnchor: "middle", letterSpacing: "0.08em" }, "HOLDINGS")
      );
    });
  }

  /* ── Portfolio performance line vs benchmark ────────────────────────────── */
  function PerfLine() {
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(33);
      const n = 90;
      const a = [], b = [];
      let va = 100, vb = 100;
      for (let i = 0; i < n; i++) {
        va *= 1 + (r() - 0.44) * 0.018;
        vb *= 1 + (r() - 0.47) * 0.013;
        a.push(va); b.push(vb);
      }
      const padL = 8, padR = 44, padT = 10, padB = 20;
      const all = a.concat(b);
      const mn = Math.min(...all), mx = Math.max(...all);
      const x = (i) => padL + ((w - padL - padR) * i) / (n - 1);
      const y = (v) => scaleY(v, mn, mx, padT, h - padB);
      const aPts = a.map((v, i) => [x(i), y(v)]);
      const area = path(aPts) + ` L${x(n - 1)} ${h - padB} L${x(0)} ${h - padB} Z`;
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        ...gridLines(padT, h - padB, padL, w - padR, 4, "g"),
        [0, 1, 2, 3, 4].map((i) => {
          const v = mx - ((mx - mn) * i) / 4;
          const yy = padT + ((h - padB - padT) * i) / 4;
          return axisLabel(w - padR + 6, yy + 3, (v / 100).toFixed(2) + "×", "start");
        }),
        R.createElement("path", { d: area, fill: c.accent, opacity: 0.08 }),
        R.createElement("path", { d: path(b.map((v, i) => [x(i), y(v)])), fill: "none", stroke: c.grey, strokeWidth: 1.5, ...STROKE }),
        R.createElement("path", { d: path(aPts), fill: "none", stroke: c.accent, strokeWidth: 2, ...STROKE })
      );
    });
  }

  /* ── Correlation heatmap ────────────────────────────────────────────────── */
  function CorrHeatmap(props) {
    const labels = props.labels || ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM"];
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(5);
      const n = labels.length;
      const pad = 38;
      const grid = Math.min(w - pad, h - pad);
      const cell = grid / n;
      const ox = pad, oy = 6;
      const rects = [];
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
          const val = i === j ? 1 : 0.15 + r() * 0.75;
          const op = 0.12 + val * 0.85;
          rects.push(
            R.createElement("rect", {
              key: i + "-" + j, x: ox + j * cell, y: oy + i * cell,
              width: cell - 1.5, height: cell - 1.5, fill: c.accent, opacity: op,
            }),
            R.createElement("text", {
              key: "t" + i + "-" + j, x: ox + j * cell + (cell - 1.5) / 2, y: oy + i * cell + (cell - 1.5) / 2 + 3,
              fill: op > 0.55 ? "#fff" : "var(--text, #161616)", fontSize: Math.min(11, cell * 0.28),
              fontFamily: FONT, textAnchor: "middle", style: { fontVariantNumeric: "tabular-nums" },
            }, val.toFixed(2))
          );
        }
      }
      const colLabels = labels.map((l, j) =>
        axisLabel(ox + j * cell + cell / 2, oy + n * cell + 12, l, "middle", 9)
      );
      const rowLabels = labels.map((l, i) =>
        R.createElement("text", { key: "r" + i, x: ox - 5, y: oy + i * cell + cell / 2 + 3, fill: c.t3, fontSize: 9, fontFamily: FONT, textAnchor: "end" }, l)
      );
      return R.createElement("svg", { width: w, height: h, style: { display: "block" } }, rects, colLabels, rowLabels);
    });
  }

  /* ── Scenario P&L bars (horizontal, signed) ─────────────────────────────── */
  function ScenarioBars() {
    return R.createElement(Wrap, null, (w, h) => {
      const data = [
        { k: "2008 GFC", v: -34.2 },
        { k: "2020 COVID", v: -21.7 },
        { k: "2018 Q4", v: -12.4 },
        { k: "Rates +100bp", v: -6.8 },
        { k: "Base case", v: 4.3 },
        { k: "Soft landing", v: 11.9 },
      ];
      const padL = 96, padR = 44, padT = 6, padB = 6;
      const mx = Math.max(...data.map((d) => Math.abs(d.v)));
      const rowH = (h - padT - padB) / data.length;
      const zeroX = padL + ((w - padL - padR) * mx) / (2 * mx);
      const scale = (w - padL - padR) / (2 * mx);
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        R.createElement("line", { x1: zeroX, x2: zeroX, y1: padT, y2: h - padB, stroke: c.grid, strokeWidth: 1, ...STROKE }),
        data.map((d, i) => {
          const cy = padT + rowH * i + rowH / 2;
          const bh = Math.min(rowH * 0.56, 18);
          const len = Math.abs(d.v) * scale;
          const neg = d.v < 0;
          return R.createElement(
            "g",
            { key: i },
            R.createElement("text", { x: padL - 8, y: cy + 3, fill: "var(--text-2, #525252)", fontSize: 11, fontFamily: FONT, textAnchor: "end" }, d.k),
            R.createElement("rect", { x: neg ? zeroX - len : zeroX, y: cy - bh / 2, width: len, height: bh, fill: neg ? c.accent : c.pos, opacity: 0.9 }),
            R.createElement("text", { x: neg ? zeroX - len + 6 : zeroX + len + 5, y: cy + 3, fill: neg ? "#fff" : c.pos, fontSize: 10.5, fontWeight: 700, fontFamily: FONT, textAnchor: neg ? "start" : "start", style: { fontVariantNumeric: "tabular-nums" } }, (d.v > 0 ? "+" : "") + d.v.toFixed(1) + "%")
          );
        })
      );
    });
  }

  /* ── Tiny sparkline (table cells / KPI tiles) ───────────────────────────── */
  function Sparkline(props) {
    const seed = props.seed || 1, down = props.down;
    return R.createElement(Wrap, null, (w, h) => {
      const r = rng(seed);
      const n = 24;
      const pts = [];
      let v = 0;
      for (let i = 0; i < n; i++) { v += (r() - (down ? 0.56 : 0.44)) * 1; pts.push(v); }
      const mn = Math.min(...pts), mx = Math.max(...pts);
      const x = (i) => (w * i) / (n - 1);
      const y = (val) => scaleY(val, mn, mx, 2, h - 2);
      const col = down ? c.neg : c.pos;
      return R.createElement(
        "svg",
        { width: w, height: h, style: { display: "block" } },
        R.createElement("path", { d: path(pts.map((val, i) => [x(i), y(val)])), fill: "none", stroke: col, strokeWidth: 1.5, ...STROKE })
      );
    });
  }

  Object.assign(window, {
    PriceCandles, ReturnArea, RollingLine, Histogram,
    AllocationDonut, PerfLine, CorrHeatmap, ScenarioBars, Sparkline,
  });
})();
