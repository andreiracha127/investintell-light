/**
 * Server-only API helper for Next route handlers and Server Components.
 *
 * This intentionally does not import the browser auth client. P6 fund dossier
 * proxies are public/catalog-like GETs; user-scoped routes must stay out of
 * this helper until an auth-aware cache boundary is designed.
 */

export class ServerApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ServerApiError";
    this.status = status;
    this.body = body;
  }
}

function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

function extractDetail(body: unknown, fallback: string): string {
  if (body !== null && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const isPydanticEntry = (entry: unknown): entry is { msg: string; loc: string[] } =>
        entry !== null &&
        typeof entry === "object" &&
        "msg" in entry &&
        typeof (entry as Record<string, unknown>).msg === "string" &&
        "loc" in entry &&
        Array.isArray((entry as Record<string, unknown>).loc);

      if (detail.every(isPydanticEntry)) {
        return detail
          .map((entry) => {
            const field = entry.loc.slice(1).join(".");
            return field ? `${field}: ${entry.msg}` : entry.msg;
          })
          .join("\n");
      }
      return JSON.stringify(detail);
    }
    if (detail !== undefined) return JSON.stringify(detail);
  }
  return fallback;
}

export async function serverRequest<T>(path: string): Promise<T> {
  const url = new URL(path, backendBaseUrl());
  const response = await fetch(url, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const fallback = `HTTP ${response.status} ${response.statusText}`.trim();
    let body: unknown;
    let detail = fallback;
    try {
      body = await response.json();
      detail = extractDetail(body, fallback);
    } catch {
      body = { detail: fallback };
    }
    throw new ServerApiError(response.status, detail, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
