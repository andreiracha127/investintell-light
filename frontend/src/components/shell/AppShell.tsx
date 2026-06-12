"use client";

/**
 * Investintell Cockpit shell — Carbon UI Shell style.
 * 48px top header (brand, ticker search, density / theme / accent controls)
 * + collapsible side nav (232px expanded / 56px rail, overlay under 900px).
 * Design source: /design/investintell-cockpit/InvestintellCockpit.dc.html
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { TickerSearch } from "@/components/TickerSearch";

type Theme = "light" | "dark";
type Accent = "oxblood" | "blue" | "teal";
type Density = "compact" | "comfortable";

interface Settings {
  theme: Theme;
  accent: Accent;
  density: Density;
}

const DEFAULTS: Settings = { theme: "light", accent: "oxblood", density: "compact" };
const STORAGE_KEY = "ix-cockpit-settings";

function readSettings(): Settings {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      theme: parsed.theme === "dark" ? "dark" : "light",
      accent: parsed.accent === "blue" || parsed.accent === "teal" ? parsed.accent : "oxblood",
      density: parsed.density === "comfortable" ? "comfortable" : "compact",
    };
  } catch {
    return DEFAULTS;
  }
}

function applySettings(s: Settings) {
  const el = document.documentElement;
  el.dataset.theme = s.theme;
  el.dataset.accent = s.accent;
  el.dataset.density = s.density;
}

const NAV_ITEMS: { href: string; match: (p: string) => boolean; label: string; icon: React.ReactNode }[] = [
  {
    href: "/stocks/AAPL",
    match: (p) => p.startsWith("/stocks"),
    label: "Stock Analysis",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <rect x="2" y="6" width="2.4" height="6" fill="currentColor" />
        <rect x="6.8" y="3" width="2.4" height="9" fill="currentColor" />
        <rect x="11.6" y="8" width="2.4" height="4" fill="currentColor" />
      </svg>
    ),
  },
  {
    href: "/portfolio",
    match: (p) => p.startsWith("/portfolio"),
    label: "Portfolio",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <circle cx="8" cy="8" r="5.4" stroke="currentColor" strokeWidth="2.2" />
        <path d="M8 2.6V8h5.4" stroke="var(--color-accent)" strokeWidth="2.2" />
      </svg>
    ),
  },
  {
    href: "/statistics/scenario",
    match: (p) => p.startsWith("/statistics"),
    label: "Statistics",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M2 13V3M2 13h12" stroke="currentColor" strokeWidth="1.4" />
        <path d="M4.5 11l2.5-3 2.2 2 3-4.5" stroke="var(--color-accent)" strokeWidth="1.6" fill="none" />
      </svg>
    ),
  },
  {
    href: "/screener",
    match: (p) => p.startsWith("/screener"),
    label: "Screener",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M1.5 3h13l-5 6v4l-3 1.5V9z" stroke="currentColor" strokeWidth="1.3" fill="none" />
      </svg>
    ),
  },
  {
    href: "/funds",
    match: (p) => p.startsWith("/funds"),
    label: "Funds",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <rect x="2" y="10" width="12" height="3.6" stroke="currentColor" strokeWidth="1.3" fill="none" />
        <rect x="3.6" y="6.2" width="8.8" height="3.6" stroke="currentColor" strokeWidth="1.3" fill="none" />
        <rect x="5.2" y="2.4" width="5.6" height="3.6" stroke="var(--color-accent)" strokeWidth="1.3" fill="none" />
      </svg>
    ),
  },
  {
    href: "/builder",
    match: (p) => p.startsWith("/builder"),
    label: "Builder",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3.5 1.5v13M8 1.5v13M12.5 1.5v13" stroke="currentColor" strokeWidth="1.3" />
        <rect x="2" y="9" width="3" height="3" fill="var(--color-accent)" />
        <rect x="6.5" y="4" width="3" height="3" fill="currentColor" />
        <rect x="11" y="7" width="3" height="3" fill="currentColor" />
      </svg>
    ),
  },
  {
    href: "/macro",
    match: (p) => p.startsWith("/macro"),
    label: "Macro",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2.5 8h11" stroke="currentColor" strokeWidth="1.1" />
        <path d="M8 2.5v11" stroke="currentColor" strokeWidth="1.1" />
        <path d="M4.5 11.5C5.5 9 6.5 7 8 7s2.5 2 3.5 4.5" stroke="var(--color-accent)" strokeWidth="1.4" fill="none" />
      </svg>
    ),
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [navOpen, setNavOpen] = useState(true);
  const [narrow, setNarrow] = useState(false);

  // Hydrate persisted settings (the inline script in layout.tsx already set
  // the data attributes pre-paint; this syncs React state to match).
  useEffect(() => {
    setSettings(readSettings());
  }, []);

  useEffect(() => {
    applySettings(settings);
  }, [settings]);

  useEffect(() => {
    const onResize = () => {
      const isNarrow = window.innerWidth < 900;
      setNarrow((prev) => {
        if (prev !== isNarrow) setNavOpen(!isNarrow);
        return isNarrow;
      });
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // persistence is best-effort
      }
      return next;
    });
  }, []);

  const overlay = narrow && navOpen;
  const sidebarVisible = navOpen || !narrow;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-0 text-text-primary">
      {/* ── Top header (Carbon UI Shell) ─────────────────────────────────── */}
      <header className="relative z-60 flex h-12 shrink-0 items-center gap-1 border-b border-border bg-surface-1 pr-2">
        <button
          type="button"
          onClick={() => setNavOpen((v) => !v)}
          title="Toggle navigation"
          aria-label="Toggle navigation"
          className="flex h-12 w-12 shrink-0 items-center justify-center text-text-secondary hover:bg-layer-hover"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path d="M1 3h14M1 8h14M1 13h14" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        </button>
        <Link href="/" className="flex items-baseline gap-2 pr-3.5 no-underline">
          <span className="font-serif text-[17px] font-bold tracking-[-0.01em] text-text-primary">
            Investintell
          </span>
          <span className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-accent">
            Cockpit
          </span>
        </Link>

        <TickerSearch />

        <div className="flex-1" />

        {/* density toggle */}
        <div className="hidden h-8 items-stretch border border-border-strong sm:flex">
          <DensityButton
            label="Compact"
            active={settings.density === "compact"}
            onClick={() => update({ density: "compact" })}
          />
          <DensityButton
            label="Comfort"
            active={settings.density === "comfortable"}
            onClick={() => update({ density: "comfortable" })}
          />
        </div>

        {/* theme toggle */}
        <button
          type="button"
          onClick={() => update({ theme: settings.theme === "light" ? "dark" : "light" })}
          title="Toggle theme"
          aria-label="Toggle theme"
          className="flex h-9 w-9 items-center justify-center text-text-secondary hover:bg-layer-hover"
        >
          {settings.theme === "light" ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <circle cx="8" cy="8" r="3.4" stroke="currentColor" strokeWidth="1.3" />
              <path
                d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M13 3l-1.4 1.4M4.4 11.6L3 13"
                stroke="currentColor"
                strokeWidth="1.2"
              />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M13.5 9.5A5.5 5.5 0 016.5 2.5 5.5 5.5 0 1013.5 9.5z" stroke="currentColor" strokeWidth="1.3" />
            </svg>
          )}
        </button>

        {/* accent dots */}
        <div className="hidden items-center gap-1.5 px-2 sm:flex">
          <AccentDot color="#7A1C24" name="oxblood" title="Oxblood" settings={settings} onPick={update} />
          <AccentDot color="#0F62FE" name="blue" title="Carbon blue" settings={settings} onPick={update} />
          <AccentDot color="#007D79" name="teal" title="Teal" settings={settings} onPick={update} />
        </div>
      </header>

      {/* ── Body row: sidebar + main ─────────────────────────────────────── */}
      <div className="relative flex min-h-0 flex-1">
        {overlay && (
          <div
            onClick={() => setNavOpen(false)}
            className="fixed inset-x-0 bottom-0 top-12 z-40 bg-black/40"
            aria-hidden
          />
        )}

        {sidebarVisible && (
          <nav
            aria-label="Primary"
            className={`flex shrink-0 flex-col overflow-hidden border-r border-border bg-surface-1 transition-[width] duration-150 ${
              navOpen ? "w-[232px]" : "w-14"
            } ${overlay ? "fixed bottom-0 left-0 top-12 z-50" : "relative"}`}
          >
            <div className="pb-1.5 pt-3.5">
              {navOpen && (
                <div className="px-4 pb-2 text-[10px] font-bold uppercase tracking-[0.1em] text-text-muted">
                  Workspace
                </div>
              )}
              {NAV_ITEMS.map((item) => {
                const active = item.match(pathname);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => {
                      if (narrow) setNavOpen(false);
                    }}
                    title={item.label}
                    className={`relative flex h-10 w-full items-center gap-3 overflow-hidden whitespace-nowrap px-4 text-[13px] no-underline hover:bg-layer-hover ${
                      active
                        ? "bg-layer-active font-bold text-accent shadow-[inset_3px_0_0_var(--color-accent)]"
                        : "font-medium text-text-secondary"
                    }`}
                  >
                    <span className="flex w-[18px] shrink-0 items-center justify-center">{item.icon}</span>
                    {navOpen && <span>{item.label}</span>}
                  </Link>
                );
              })}
            </div>

            {navOpen && (
              <div className="mt-auto border-t border-border px-4 py-3.5 text-[10.5px] leading-normal text-text-muted">
                <div className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 bg-gain" />
                  Markets · EOD
                </div>
              </div>
            )}
          </nav>
        )}

        {/* Keyed on settings so ECharts options (built from chartColors() in
            useMemo) are rebuilt when theme/accent/density tokens change. */}
        <main
          key={`${settings.theme}-${settings.accent}-${settings.density}`}
          className="min-w-0 flex-1 overflow-auto bg-surface-0"
        >
          {children}
        </main>
      </div>
    </div>
  );
}

function DensityButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${label} density`}
      className={`flex items-center px-3 text-[11.5px] ${
        active ? "bg-accent font-bold text-on-accent" : "font-medium text-text-secondary hover:bg-layer-hover"
      }`}
    >
      {label}
    </button>
  );
}

function AccentDot({
  color,
  name,
  title,
  settings,
  onPick,
}: {
  color: string;
  name: Accent;
  title: string;
  settings: Settings;
  onPick: (patch: Partial<Settings>) => void;
}) {
  const active = settings.accent === name;
  return (
    <button
      type="button"
      onClick={() => onPick({ accent: name })}
      title={title}
      aria-label={`${title} accent`}
      aria-pressed={active}
      className="h-4 w-4 cursor-pointer rounded-full p-0 outline-offset-1"
      style={{
        background: color,
        border: active ? "2px solid var(--color-text-primary)" : "1px solid var(--color-border-strong)",
        outline: active ? "1px solid var(--color-text-primary)" : "1px solid transparent",
      }}
    />
  );
}
