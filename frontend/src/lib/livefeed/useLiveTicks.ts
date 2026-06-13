"use client";

/**
 * useLiveTicks(symbols) — último preço ao vivo por símbolo, com flush em
 * requestAnimationFrame (uma re-render por frame, não por tick) — a tabela
 * de leaders assina ~25 símbolos sem virar um re-render storm.
 */
import { useEffect, useRef, useState } from "react";
import { onFeedStatus, subscribeTicks, type FeedStatus } from "./client";

export interface LivePrice {
  price: number;
  /** +1 subiu, -1 caiu vs tick anterior (para o flash). */
  dir: 1 | -1 | 0;
  time: string;
}

export function useLiveTicks(symbols: string[]): {
  ticks: Record<string, LivePrice>;
  status: FeedStatus;
} {
  const [ticks, setTicks] = useState<Record<string, LivePrice>>({});
  const [status, setStatus] = useState<FeedStatus>("off");
  const pending = useRef<Record<string, LivePrice>>({});
  const raf = useRef<number>(0);
  const key = symbols.join(",");

  useEffect(() => {
    const offStatus = onFeedStatus(setStatus);
    const flush = () => {
      raf.current = 0;
      const batch = pending.current;
      pending.current = {};
      setTicks((prev) => ({ ...prev, ...batch }));
    };
    const unsubs = key
      ? key.split(",").map((sym) =>
          subscribeTicks(sym, (tick) => {
            const prev = pending.current[sym]?.price;
            pending.current[sym] = {
              price: tick.price,
              dir: prev == null || tick.price === prev ? 0 : tick.price > prev ? 1 : -1,
              time: tick.time,
            };
            if (!raf.current) raf.current = requestAnimationFrame(flush);
          }),
        )
      : [];
    return () => {
      offStatus();
      for (const u of unsubs) u();
      if (raf.current) cancelAnimationFrame(raf.current);
      pending.current = {};
    };
  }, [key]);

  return { ticks, status };
}
