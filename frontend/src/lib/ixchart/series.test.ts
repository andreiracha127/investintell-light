import { describe, expect, it } from "vitest";
import { fmtP, fmtV, niceTicks, resample, rsi, sma } from "./series";
import type { Bar } from "./types";

const DAY = 86_400_000;
// Seg 2026-06-01 00:00 UTC — duas semanas úteis contíguas
const MON = Date.UTC(2026, 5, 1);

function bars(closes: number[]): Bar[] {
  return closes.map((c, i) => ({
    // pula fins de semana: 5 barras por semana
    t: MON + (Math.floor(i / 5) * 7 + (i % 5)) * DAY,
    o: c - 1, h: c + 2, l: c - 2, c, v: 1000 + i,
  }));
}

describe("resample", () => {
  it("D devolve as barras como estão", () => {
    const b = bars([1, 2, 3]);
    expect(resample(b, "D")).toEqual(b);
  });

  it("W agrega OHLC por semana ISO: o do 1º dia, c do último, h/l extremos, v somado", () => {
    const b = bars([10, 12, 8, 11, 13, 20, 22, 18, 21, 23]); // 2 semanas × 5 dias
    const w = resample(b, "W");
    expect(w).toHaveLength(2);
    expect(w[0].o).toBe(10 - 1);
    expect(w[0].c).toBe(13);
    expect(w[0].h).toBe(13 + 2);
    expect(w[0].l).toBe(8 - 2);
    expect(w[0].v).toBe(1000 + 1001 + 1002 + 1003 + 1004);
    expect(w[1].c).toBe(23);
  });
});

describe("sma", () => {
  it("é null até a janela encher e correto depois", () => {
    const out = sma(bars([1, 2, 3, 4, 5]), 3);
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(out[2]).toBeCloseTo(2);
    expect(out[4]).toBeCloseTo(4);
  });
});

describe("rsi", () => {
  it("alta monotônica → RSI 100; mistura fica em (0,100)", () => {
    const up = rsi(bars([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]), 14);
    expect(up[15]).toBe(100);
    const mixed = rsi(bars([10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18]), 14);
    expect(mixed[15]).toBeGreaterThan(0);
    expect(mixed[15]).toBeLessThan(100);
  });
});

describe("niceTicks", () => {
  it("gera ticks redondos dentro do intervalo", () => {
    const ticks = niceTicks(0, 100, 5);
    expect(ticks[0]).toBeGreaterThanOrEqual(0);
    expect(ticks.at(-1)).toBeLessThanOrEqual(100);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });
  it("intervalo vazio → []", () => {
    expect(niceTicks(5, 5, 5)).toEqual([]);
  });
});

describe("formatters", () => {
  it("fmtP en-US com casas fixas; null → em-dash", () => {
    expect(fmtP(1234.5, 2)).toBe("1,234.50");
    expect(fmtP(null, 2)).toBe("—");
  });
  it("fmtV abrevia K/M/B", () => {
    expect(fmtV(1_500)).toBe("1.5K");
    expect(fmtV(2_500_000)).toBe("2.50M");
    expect(fmtV(3_100_000_000)).toBe("3.10B");
  });
});
