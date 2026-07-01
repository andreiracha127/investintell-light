#!/usr/bin/env node

import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

const DEFAULT_ROUTES = [
  "/portfolio",
  "/screener",
  "/macro",
  "/stocks",
  "/funds",
  "/statistics/scenario",
  "/builder",
];

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function importPackage(name, installHint) {
  try {
    return await import(name);
  } catch (error) {
    if (error?.code !== "ERR_MODULE_NOT_FOUND") throw error;
    throw new Error(`${name} is not resolvable. ${installHint}`);
  }
}

function splitSetCookie(header) {
  if (!header) return [];
  return header.split(/,(?=\s*[^;,]+=)/g);
}

async function signIn(baseUrl, email, password) {
  const response = await fetch(new URL("/api/auth/sign-in", baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    redirect: "manual",
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Sign-in failed with HTTP ${response.status}: ${body.slice(0, 240)}`);
  }
  const setCookies =
    typeof response.headers.getSetCookie === "function"
      ? response.headers.getSetCookie()
      : splitSetCookie(response.headers.get("set-cookie"));
  const cookie = setCookies.map((item) => item.split(";")[0]).filter(Boolean).join("; ");
  if (!cookie) throw new Error("Sign-in did not return auth cookies");
  return cookie;
}

function routesFromEnv() {
  return (process.env.PERF_ROUTES ?? DEFAULT_ROUTES.join(","))
    .split(",")
    .map((route) => route.trim())
    .filter(Boolean)
    .map((route) => (route.startsWith("/") ? route : `/${route}`));
}

function routeSlug(route) {
  return route.replace(/^\/+/, "").replace(/[^a-z0-9]+/gi, "-") || "root";
}

function lighthouseConfig(formFactor) {
  if (formFactor === "mobile") return undefined;
  return {
    extends: "lighthouse:default",
    settings: {
      formFactor: "desktop",
      screenEmulation: {
        mobile: false,
        width: 1350,
        height: 940,
        deviceScaleFactor: 1,
        disabled: false,
      },
    },
  };
}

function auditValue(lhr, id) {
  const audit = lhr.audits[id];
  return typeof audit?.numericValue === "number" ? audit.numericValue : null;
}

function summarize(route, lhr) {
  return {
    route,
    finalUrl: lhr.finalDisplayedUrl,
    performance: Math.round((lhr.categories.performance?.score ?? 0) * 100),
    fcpMs: auditValue(lhr, "first-contentful-paint"),
    lcpMs: auditValue(lhr, "largest-contentful-paint"),
    tbtMs: auditValue(lhr, "total-blocking-time"),
    cls: auditValue(lhr, "cumulative-layout-shift"),
    ttiMs: auditValue(lhr, "interactive"),
    totalBytes: auditValue(lhr, "total-byte-weight"),
    bootupMs: auditValue(lhr, "bootup-time"),
    mainThreadMs: auditValue(lhr, "mainthread-work-breakdown"),
  };
}

async function main() {
  const baseUrl = requiredEnv("PERF_BASE_URL").replace(/\/+$/, "");
  const email = requiredEnv("PERF_EMAIL");
  const password = requiredEnv("PERF_PASSWORD");
  const formFactor = (process.env.PERF_FORM_FACTOR ?? "desktop").trim();
  if (!["desktop", "mobile"].includes(formFactor)) {
    throw new Error("PERF_FORM_FACTOR must be desktop or mobile");
  }

  const [{ default: lighthouse }, chromeLauncher] = await Promise.all([
    importPackage("lighthouse", "Install it in the frontend workspace before running this script."),
    importPackage("chrome-launcher", "It is normally installed with Lighthouse."),
  ]);

  const cookie = await signIn(baseUrl, email, password);
  const outDir = join(root, ".perf", new Date().toISOString().replace(/[:.]/g, "-"));
  await mkdir(outDir, { recursive: true });

  const launcher = chromeLauncher.launch ? chromeLauncher : chromeLauncher.default;
  if (!launcher?.launch) throw new Error("chrome-launcher does not expose launch()");
  const chrome = await launcher.launch({
    chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"],
  });
  const summaries = [];

  try {
    for (const route of routesFromEnv()) {
      const url = new URL(route, baseUrl).toString();
      const result = await lighthouse(
        url,
        {
          port: chrome.port,
          output: ["json", "html"],
          onlyCategories: ["performance"],
          disableStorageReset: true,
          extraHeaders: { Cookie: cookie },
          logLevel: "error",
        },
        lighthouseConfig(formFactor),
      );
      if (!result?.lhr || !Array.isArray(result.report)) {
        throw new Error(`Lighthouse did not return reports for ${route}`);
      }
      const slug = routeSlug(route);
      await writeFile(join(outDir, `${slug}.json`), result.report[0], "utf8");
      await writeFile(join(outDir, `${slug}.html`), result.report[1], "utf8");
      const summary = summarize(route, result.lhr);
      summaries.push(summary);
      console.log(
        `${route}: perf=${summary.performance} lcp=${Math.round(summary.lcpMs ?? 0)}ms ` +
          `tbt=${Math.round(summary.tbtMs ?? 0)}ms cls=${summary.cls ?? 0}`,
      );
    }
  } finally {
    await chrome.kill();
  }

  const summary = {
    baseUrl,
    formFactor,
    generatedAt: new Date().toISOString(),
    routes: summaries,
  };
  await writeFile(join(outDir, "summary.json"), JSON.stringify(summary, null, 2), "utf8");
  console.log(`summary=${join(outDir, "summary.json")}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
