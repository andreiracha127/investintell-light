import { describe, expect, it } from "vitest";
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
