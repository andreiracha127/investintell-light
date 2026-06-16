/**
 * Cliente WebSocket COMPARTILHADO do livefeed worker (Railway, fan-out por
 * símbolo). Um socket por aba: handlers ref-counted por símbolo, subscribe
 * aditivo / unsubscribe (protocolo do worker), reconexão com backoff
 * exponencial (1s→30s) e re-subscribe ao reconectar.
 *
 * Ticks com source:"sim" (simulador fora do pregão) são DESCARTADOS no
 * parse — esta UI nunca anima preço fake; sem feed real, fica no EOD.
 *
 * Sem NEXT_PUBLIC_LIVEFEED_WS_URL o módulo degrada para no-op silencioso
 * (status "off") — páginas funcionam 100% com REST.
 */
import type { Tick } from "@/lib/livefeed/types";

export type FeedStatus = "off" | "connecting" | "live" | "error";
export type TickHandler = (tick: Tick) => void;
export type StatusHandler = (status: FeedStatus) => void;

const URL = process.env.NEXT_PUBLIC_LIVEFEED_WS_URL ?? "";
const MAX_BACKOFF_MS = 30_000;

export function parseTick(raw: string): Tick | null {
  try {
    const m = JSON.parse(raw) as Record<string, unknown>;
    if (m.type !== "tick" || m.source === "sim") return null;
    if (typeof m.symbol !== "string" || typeof m.price !== "number") return null;
    return {
      symbol: m.symbol.toUpperCase(),
      price: m.price,
      size: typeof m.size === "number" ? m.size : 0,
      time: typeof m.time === "string" ? m.time : "",
    };
  } catch {
    return null;
  }
}

class SharedFeed {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<TickHandler>>();
  private statusHandlers = new Set<StatusHandler>();
  private status: FeedStatus = "off";
  private backoff = 1_000;
  private reconnectT: ReturnType<typeof setTimeout> | undefined;
  private closedByUs = false;

  subscribe(symbol: string, handler: TickHandler): () => void {
    if (!URL || typeof window === "undefined") return () => {};
    const sym = symbol.toUpperCase();
    let set = this.handlers.get(sym);
    const isNew = !set;
    if (!set) {
      set = new Set();
      this.handlers.set(sym, set);
    }
    set.add(handler);
    this.ensureConnected();
    if (isNew && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", symbols: [sym] }));
    }
    return () => {
      const s = this.handlers.get(sym);
      if (!s) return;
      s.delete(handler);
      if (s.size === 0) {
        this.handlers.delete(sym);
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: "unsubscribe", symbols: [sym] }));
        }
        if (this.handlers.size === 0) this.teardown();
      }
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.status);
    return () => this.statusHandlers.delete(handler);
  }

  private setStatus(next: FeedStatus): void {
    if (this.status === next) return;
    this.status = next;
    for (const h of this.statusHandlers) h(next);
  }

  private ensureConnected(): void {
    if (this.ws || !this.handlers.size) return;
    this.closedByUs = false;
    this.setStatus("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(URL);
    } catch {
      this.setStatus("error");
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 1_000;
      this.setStatus("live");
      const symbols = [...this.handlers.keys()];
      if (symbols.length) ws.send(JSON.stringify({ action: "subscribe", symbols }));
    };
    ws.onmessage = (ev) => {
      const tick = parseTick(String(ev.data));
      if (!tick) return;
      const set = this.handlers.get(tick.symbol);
      if (set) for (const h of set) h(tick);
    };
    ws.onclose = () => {
      this.ws = null;
      if (this.closedByUs || !this.handlers.size) {
        this.setStatus("off");
        return;
      }
      this.setStatus("error");
      this.reconnectT = setTimeout(() => this.ensureConnected(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    };
    ws.onerror = () => ws.close();
  }

  private teardown(): void {
    clearTimeout(this.reconnectT);
    this.closedByUs = true;
    this.ws?.close();
    this.ws = null;
    this.setStatus("off");
  }
}

const feed = new SharedFeed();

/** Inscreve um handler para os ticks reais de um símbolo; retorna o unsubscribe. */
export const subscribeTicks = (symbol: string, handler: TickHandler) =>
  feed.subscribe(symbol, handler);

/** Observa o estado do feed ("off" | "connecting" | "live" | "error"). */
export const onFeedStatus = (handler: StatusHandler) => feed.onStatus(handler);
