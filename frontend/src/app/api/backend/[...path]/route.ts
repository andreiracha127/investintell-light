import { NextResponse } from "next/server";

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

function backendUrl(pathParts: string[] | undefined, requestUrl: string): URL {
  const path = (pathParts ?? []).map(encodeURIComponent).join("/");
  const url = new URL(`/${path}`, backendBaseUrl());
  url.search = new URL(requestUrl).search;
  return url;
}

function forwardedHeaders(request: Request): Headers {
  const headers = new Headers();
  for (const name of ["accept", "authorization", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

function responseHeaders(response: Response): Headers {
  const headers = new Headers();
  for (const name of ["cache-control", "content-disposition", "content-type"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

async function proxyBackend(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD"].includes(method);

  try {
    const response = await fetch(backendUrl(path, request.url), {
      method,
      headers: forwardedHeaders(request),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
    });

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders(response),
    });
  } catch (error) {
    const detail =
      error instanceof Error ? error.message : "Backend proxy request failed";
    return NextResponse.json({ detail }, { status: 502 });
  }
}

export function GET(request: Request, context: RouteContext) {
  return proxyBackend(request, context);
}

export function POST(request: Request, context: RouteContext) {
  return proxyBackend(request, context);
}

export function PUT(request: Request, context: RouteContext) {
  return proxyBackend(request, context);
}

export function PATCH(request: Request, context: RouteContext) {
  return proxyBackend(request, context);
}

export function DELETE(request: Request, context: RouteContext) {
  return proxyBackend(request, context);
}
