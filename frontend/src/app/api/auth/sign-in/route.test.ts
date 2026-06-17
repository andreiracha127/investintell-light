import { beforeEach, describe, expect, it, vi } from "vitest";

const signInWithPassword = vi.hoisted(() => vi.fn());
const setAuthCookies = vi.hoisted(() => vi.fn());

vi.mock("@insforge/sdk/ssr", () => ({
  createServerClient: () => ({
    auth: { signInWithPassword },
  }),
  setAuthCookies,
}));

import { POST } from "./route";

function signInRequest(body: unknown): Request {
  return new Request("https://app.test/api/auth/sign-in", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

describe("POST /api/auth/sign-in", () => {
  beforeEach(() => {
    signInWithPassword.mockReset();
    setAuthCookies.mockReset();
  });

  it("falls back to 401 when the auth SDK returns an invalid status code", async () => {
    signInWithPassword.mockResolvedValue({
      data: null,
      error: {
        error: "AUTH_UNAUTHORIZED",
        message: "Sign in failed",
        statusCode: 0,
      },
    });

    const response = await POST(signInRequest({ email: "a@test.dev", password: "bad" }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      error: "AUTH_UNAUTHORIZED",
      message: "Sign in failed",
    });
    expect(setAuthCookies).not.toHaveBeenCalled();
  });
});
