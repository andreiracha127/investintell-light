"use client";

/**
 * Investintell Cockpit shell — Carbon UI Shell style.
 * 48px top header (brand, ticker search, density / theme / accent controls)
 * + collapsible side nav (232px expanded / 56px rail, overlay under 900px).
 * Design source: /design/investintell-cockpit/InvestintellCockpit.dc.html
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  Header,
  HeaderName,
  HeaderGlobalBar,
  HeaderGlobalAction,
  HeaderMenuButton,
  OverflowMenu,
  OverflowMenuItem,
  SkipToContent,
} from "@carbon/react";
import { Light, Asleep, Logout } from "@carbon/icons-react";
import { TickerSearch } from "@/components/TickerSearch";
import { useAuth } from "@/lib/auth/context";
import { gateDecision } from "@/lib/auth/authState";

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
    href: "/stocks",
    match: (p) => p.startsWith("/stocks"),
    label: "Stocks",
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

  const router = useRouter();
  const { status, signOut } = useAuth();

  useEffect(() => {
    const target = gateDecision(status, pathname);
    if (target) router.replace(target);
  }, [status, pathname, router]);

  // The login route renders bare (no shell chrome).
  if (pathname === "/login") return <>{children}</>;

  // Don't flash the app or bounce a valid user while the session resolves.
  if (status === "loading") {
    return <div className="flex h-screen items-center justify-center text-text-muted">Loading…</div>;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-0 text-text-primary">
      {/* ── Top header (Carbon UI Shell) ─────────────────────────────────── */}
      <Header aria-label="Investintell Cockpit" className="ix-carbon-scope">
        <SkipToContent />
        <HeaderMenuButton
          aria-label="Toggle navigation"
          isCollapsible
          isActive={navOpen}
          onClick={() => setNavOpen((v) => !v)}
        />
        <HeaderName href="/" prefix="Investintell">Cockpit</HeaderName>

        <div className="flex flex-1 items-center">
          <TickerSearch />
        </div>

        <div className="hidden h-8 items-stretch border border-border-strong sm:flex">
          <DensityButton label="Compact" active={settings.density === "compact"} onClick={() => update({ density: "compact" })} />
          <DensityButton label="Comfort" active={settings.density === "comfortable"} onClick={() => update({ density: "comfortable" })} />
        </div>

        <HeaderGlobalBar>
          <HeaderGlobalAction
            aria-label={settings.theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
            onClick={() => update({ theme: settings.theme === "light" ? "dark" : "light" })}
            tooltipAlignment="center"
          >
            {settings.theme === "light" ? <Asleep size={20} /> : <Light size={20} />}
          </HeaderGlobalAction>

          <OverflowMenu
            aria-label="Accent color"
            renderIcon={() => <span className="h-4 w-4 rounded-full" style={{ background: "var(--color-accent)" }} />}
            flipped
          >
            <OverflowMenuItem itemText="Oxblood" onClick={() => update({ accent: "oxblood" })} />
            <OverflowMenuItem itemText="Carbon blue" onClick={() => update({ accent: "blue" })} />
            <OverflowMenuItem itemText="Teal" onClick={() => update({ accent: "teal" })} />
          </OverflowMenu>

          <HeaderGlobalAction aria-label="Sign out" onClick={() => void signOut()} tooltipAlignment="end">
            <Logout size={20} />
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>

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
          id="main-content"
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
