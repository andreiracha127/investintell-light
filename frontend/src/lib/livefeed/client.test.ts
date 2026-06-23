// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseTick } from "./client";

describe("parseTick", () => {
  it("aceita tick real do worker", () => {
    const t = parseTick(
      '{"type":"tick","symbol":"TSLA","price":400.13,"size":100,"time":"2026-06-12T14:20:17Z"}',
    );
    expect(t).toEqual({ symbol: "TSLA", price: 400.13, size: 100, time: "2026-06-12T14:20:17Z" });
  });

  it('descarta ticks simulados (source:"sim") — nunca mostrar preço fake', () => {
    expect(
      parseTick('{"type":"tick","symbol":"TSLA","price":1.0,"size":0,"time":"t","source":"sim"}'),
    ).toBeNull();
  });

  it("descarta mensagens de controle e lixo", () => {
    expect(parseTick('{"type":"subscribed","symbols":["TSLA"]}')).toBeNull();
    expect(parseTick("not json")).toBeNull();
    expect(parseTick('{"type":"tick","symbol":"TSLA"}')).toBeNull(); // sem price
  });
});

/**
 * Mock de WebSocket controlável: nasce em CONNECTING e registra se algum
 * `close()` ocorreu enquanto ainda conectava — que é o que dispara o aviso do
 * navegador "WebSocket is closed before the connection is established".
 */
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  closeCalls = 0;
  closedWhileConnecting = false;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.closeCalls += 1;
    if (this.readyState === MockWebSocket.CONNECTING) this.closedWhileConnecting = true;
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
  /** Simula o handshake concluindo (CONNECTING → OPEN). */
  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
}

describe("SharedFeed connection lifecycle", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_LIVEFEED_WS_URL", "wss://test.local/stream");
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("não fecha o socket enquanto ainda está em CONNECTING (evita o aviso do navegador)", async () => {
    const { subscribeTicks } = await import("./client");
    const unsubscribe = subscribeTicks("AAPL", () => {});
    const ws = MockWebSocket.instances[0];
    expect(ws.readyState).toBe(MockWebSocket.CONNECTING);

    unsubscribe(); // remove o último handler → teardown do socket

    expect(ws.closedWhileConnecting).toBe(false);
  });

  it("adia o close até a conexão abrir quando desmontado durante CONNECTING", async () => {
    const { subscribeTicks } = await import("./client");
    const unsubscribe = subscribeTicks("AAPL", () => {});
    const ws = MockWebSocket.instances[0];

    unsubscribe();
    expect(ws.closeCalls).toBe(0); // adiado, não fechado em CONNECTING

    ws.open(); // handshake conclui
    expect(ws.closeCalls).toBe(1); // agora sim fecha, já em OPEN
    expect(ws.closedWhileConnecting).toBe(false);
  });

  it("fecha imediatamente quando o socket já está OPEN", async () => {
    const { subscribeTicks } = await import("./client");
    const unsubscribe = subscribeTicks("AAPL", () => {});
    const ws = MockWebSocket.instances[0];
    ws.open(); // já conectado

    unsubscribe();

    expect(ws.closeCalls).toBe(1);
    expect(ws.closedWhileConnecting).toBe(false);
  });
});
