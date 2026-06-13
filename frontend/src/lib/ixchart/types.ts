/** Barra OHLCV — mesmo contrato do GET /stocks/{ticker}/history. */
export interface Bar {
  t: number; // epoch ms UTC
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type ChartType = "candles" | "ohlc" | "line" | "area";
export type Period = "D" | "W" | "M";
export type DrawTool = "trend" | "hline" | "fib" | "measure";

export interface DrawPoint {
  i: number; // índice fracionário da barra
  p: number; // preço
}

export interface Drawing {
  type: DrawTool;
  p1: DrawPoint;
  p2?: DrawPoint;
}

/** Tick do livefeed worker; source === "sim" é descartado pelo parser. */
export interface Tick {
  symbol: string;
  price: number;
  size: number;
  time: string;
}
