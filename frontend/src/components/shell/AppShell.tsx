"use client";

/**
 * Investintell Cockpit shell — Claude Design.
 * 52px top header (brand, centered search, settings menu, account menu)
 * + a floating "drop menu" sidebar: closed by default, opened from the
 * hamburger, overlaid on the content (it does not push the main column),
 * revealed with a clip-path animation.
 * Design source: Macro.dc.html (shared chrome across all pages).
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ChartColumn,
  ChartLineData,
  ChevronDown,
  DataVis_4,
  EarthAmericas,
  Filter,
  Finance,
  Logout,
  Menu,
  Moon,
  Portfolio,
  SettingsAdjust,
  Sun,
} from "@carbon/icons-react";
import { TickerSearch } from "@/components/TickerSearch";
import { useAuth } from "@/lib/auth/context";
import { gateDecision, isPublicPath } from "@/lib/auth/authState";

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

/** Derive a friendly name + initials from the signed-in email (no fabricated identity). */
function identityFromEmail(email: string | undefined): { name: string; initials: string; email: string } {
  const addr = email ?? "";
  const local = addr.split("@")[0] ?? "";
  const parts = local.split(/[._-]+/).filter(Boolean);
  const name = parts.length
    ? parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ")
    : "Account";
  const initials = (parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2) || "AC").toUpperCase();
  return { name, initials, email: addr };
}

const NAV_ITEMS: { href: string; match: (p: string) => boolean; label: string; icon: React.ReactNode }[] = [
  {
    href: "/stocks",
    match: (p) => p.startsWith("/stocks"),
    label: "Stocks",
    icon: <ChartColumn size={16} aria-hidden />,
  },
  {
    href: "/portfolio",
    match: (p) => p.startsWith("/portfolio"),
    label: "Portfolio",
    icon: <Portfolio size={16} aria-hidden />,
  },
  {
    href: "/statistics/scenario",
    match: (p) => p.startsWith("/statistics"),
    label: "Statistics",
    icon: <ChartLineData size={16} aria-hidden />,
  },
  {
    href: "/screener",
    match: (p) => p.startsWith("/screener"),
    label: "Screener",
    icon: <Filter size={16} aria-hidden />,
  },
  {
    href: "/funds",
    match: (p) => p.startsWith("/funds"),
    label: "Funds",
    icon: <Finance size={16} aria-hidden />,
  },
  {
    href: "/builder",
    match: (p) => p.startsWith("/builder"),
    label: "Builder",
    icon: <DataVis_4 size={16} aria-hidden />,
  },
  {
    href: "/macro",
    match: (p) => p.startsWith("/macro"),
    label: "Macro",
    icon: <EarthAmericas size={16} aria-hidden />,
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { status, user, signOut } = useAuth();
  const isPublicRoute = isPublicPath(pathname);

  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [navOpen, setNavOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const closeAll = useCallback(() => {
    setNavOpen(false);
    setSettingsOpen(false);
    setUserMenuOpen(false);
  }, []);

  // Hydrate persisted settings (the inline script in layout.tsx already set
  // the data attributes pre-paint; this syncs React state to match).
  useEffect(() => {
    setSettings(readSettings());
  }, []);

  useEffect(() => {
    applySettings(settings);
  }, [settings]);

  // Close every menu whenever the route changes.
  useEffect(() => {
    closeAll();
  }, [pathname, closeAll]);

  // Escape closes any open menu.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAll();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeAll]);

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

  useEffect(() => {
    const target = gateDecision(status, pathname);
    if (target) router.replace(target);
  }, [status, pathname, router]);

  // The login route renders bare (no shell chrome).
  if (pathname === "/login") return <>{children}</>;

  // Don't flash the app or bounce a valid user while the session resolves.
  if (status === "loading" && !isPublicRoute) {
    return <div className="flex h-screen items-center justify-center text-text-muted">Loading…</div>;
  }

  const identity = identityFromEmail(user?.email);
  const anyMenuOpen = navOpen || settingsOpen || userMenuOpen;

  return (
    <div className="ix-carbon-scope flex h-screen flex-col overflow-hidden bg-surface-0 text-text-primary">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[80] focus:bg-surface-1 focus:px-3 focus:py-2 focus:text-[13px] focus:shadow-lg"
      >
        Skip to content
      </a>

      {/* ── Top header ───────────────────────────────────────────────────── */}
      <header
        className="flex flex-none items-center border-b border-border bg-surface-1"
        style={{ height: "var(--ix-header-h)" }}
      >
        <div className="flex flex-none items-center gap-2 pl-2.5">
          <button
            type="button"
            aria-label="Toggle navigation menu"
            aria-expanded={navOpen}
            aria-pressed={navOpen}
            onClick={() => {
              setNavOpen((v) => !v);
              setSettingsOpen(false);
              setUserMenuOpen(false);
            }}
            className={`flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-layer-hover ${
              navOpen ? "bg-layer-hover" : ""
            }`}
          >
            <Menu size={20} aria-hidden />
          </button>
          <Link href="/" className="flex items-baseline gap-1.5 no-underline">
            <span className="text-[15px] font-bold text-text-primary">Investintell</span>
            <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-text-muted">Cockpit</span>
          </Link>
        </div>

        {/* Centered search */}
        <div className="flex min-w-0 flex-1 items-center justify-center px-4">
          <div className="w-full max-w-[440px]">
            <TickerSearch />
          </div>
        </div>

        {/* Right cluster */}
        <div className="flex flex-none items-center gap-1 pr-3">
          <button
            type="button"
            aria-label={settings.theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={settings.theme === "dark" ? "Light mode" : "Dark mode"}
            onClick={() => {
              update({ theme: settings.theme === "dark" ? "light" : "dark" });
              setUserMenuOpen(false);
              setSettingsOpen(false);
            }}
            className="flex h-[34px] w-[34px] items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-layer-hover hover:text-text-primary"
          >
            {settings.theme === "dark" ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </button>

          <div className="mx-1.5 h-6 w-px bg-border" />

          {/* Account menu */}
          <div className="relative">
            <button
              type="button"
              aria-label="Account"
              aria-expanded={userMenuOpen}
              onClick={() => {
                setUserMenuOpen((v) => !v);
                setSettingsOpen(false);
                setNavOpen(false);
              }}
              className={`flex h-10 items-center gap-2 rounded-lg py-0 pl-1.5 pr-2 transition-colors hover:bg-layer-hover ${
                userMenuOpen ? "bg-layer-hover" : ""
              }`}
            >
              <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full bg-accent text-[11px] font-bold text-on-accent">
                {identity.initials}
              </span>
              <span className="hidden min-w-0 flex-col items-start leading-tight sm:flex">
                <span className="max-w-[140px] truncate text-[12px] font-semibold text-text-primary">{identity.name}</span>
                <span className="max-w-[140px] truncate text-[10px] text-text-muted">{identity.email}</span>
              </span>
              <ChevronDown size={16} className="text-text-muted" aria-hidden />
            </button>
            {userMenuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-[calc(100%+6px)] z-[60] w-[236px] overflow-hidden rounded-lg border border-border-strong bg-surface-1 shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
              >
                <div className="flex items-center gap-2.5 border-b border-border p-3.5">
                  <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-accent text-[13px] font-bold text-on-accent">
                    {identity.initials}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[12.5px] font-semibold text-text-primary">{identity.name}</div>
                    <div className="truncate text-[11px] text-text-muted">{identity.email}</div>
                  </div>
                </div>
                <div className="p-1.5">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void signOut()}
                    className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[12.5px] text-loss transition-colors hover:bg-loss-muted"
                  >
                    <Logout size={16} aria-hidden />
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* ── Body row: floating sidebar + main ────────────────────────────── */}
      <div className="relative flex min-h-0 flex-1">
        {/* Click-away backdrop (covers the content area only, keeping the header
            and its menus interactive). */}
        {anyMenuOpen && (
          <div
            onClick={closeAll}
            className="fixed inset-x-0 bottom-0 z-40"
            style={{ top: "var(--ix-header-h)" }}
            aria-hidden
          />
        )}

        {/* Sidebar as a floating drop menu — overlays the content, animated via
            clip-path, closed by default. It never pushes the main column. */}
        <nav
          aria-label="Primary"
          aria-hidden={!navOpen}
          className="absolute left-2 top-2 z-50 flex w-[242px] flex-col overflow-hidden rounded-[10px] border border-border-strong bg-surface-1 pb-1 shadow-[0_18px_44px_rgba(0,0,0,0.22)]"
          style={{
            willChange: "clip-path, opacity",
            transition: "clip-path .26s cubic-bezier(.2,.7,.25,1), opacity .18s ease",
            clipPath: navOpen ? "inset(0 0 0 0)" : "inset(0 100% 100% 0 round 10px)",
            opacity: navOpen ? 1 : 0,
            pointerEvents: navOpen ? "auto" : "none",
          }}
        >
          <div className="px-4 pb-2 pt-3.5 text-[10px] font-bold uppercase tracking-[0.1em] text-text-muted">
            Workspace
          </div>
          {NAV_ITEMS.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                tabIndex={navOpen ? undefined : -1}
                onClick={closeAll}
                className={`relative flex h-10 w-full items-center gap-3 overflow-hidden whitespace-nowrap px-4 text-[13px] no-underline hover:bg-layer-hover ${
                  active
                    ? "bg-layer-active font-bold text-accent shadow-[inset_3px_0_0_var(--color-accent)]"
                    : "font-medium text-text-secondary"
                }`}
              >
                <span className="flex w-[18px] shrink-0 items-center justify-center">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
          <div className="mt-1 border-t border-border pt-1">
            <button
              type="button"
              tabIndex={navOpen ? undefined : -1}
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen((v) => !v)}
              className={`relative flex h-10 w-full items-center gap-3 overflow-hidden whitespace-nowrap px-4 text-left text-[13px] hover:bg-layer-hover ${
                settingsOpen
                  ? "bg-layer-active font-bold text-accent shadow-[inset_3px_0_0_var(--color-accent)]"
                  : "font-medium text-text-secondary"
              }`}
            >
              <span className="flex w-[18px] shrink-0 items-center justify-center">
                <SettingsAdjust size={16} aria-hidden />
              </span>
              <span>Settings</span>
            </button>
            {settingsOpen && (
              <div className="mx-3 mb-2 mt-1 border border-border bg-field p-2.5">
                <Segmented label="Density">
                  <SegBtn active={settings.density === "compact"} onClick={() => update({ density: "compact" })}>Compact</SegBtn>
                  <SegBtn active={settings.density === "comfortable"} onClick={() => update({ density: "comfortable" })}>Comfort</SegBtn>
                </Segmented>
                <div className="mt-3">
                  <div className="mb-1.5 text-[11px] text-text-secondary">Accent</div>
                  <div className="flex gap-2">
                    <AccentSwatch color="#7a1c24" label="Oxblood" active={settings.accent === "oxblood"} onClick={() => update({ accent: "oxblood" })} />
                    <AccentSwatch color="#0f62fe" label="Carbon blue" active={settings.accent === "blue"} onClick={() => update({ accent: "blue" })} />
                    <AccentSwatch color="#007d79" label="Teal" active={settings.accent === "teal"} onClick={() => update({ accent: "teal" })} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </nav>

        {/* Keyed on settings so chart options built from chartColors() in useMemo
            are rebuilt when theme/accent/density tokens change. */}
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

function Segmented({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] text-text-secondary">{label}</div>
      <div role="group" className="flex h-[30px] overflow-hidden rounded-md border border-border-strong">
        {children}
      </div>
    </div>
  );
}

function SegBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex flex-1 items-center justify-center text-[11.5px] ${
        active ? "bg-accent font-bold text-on-accent" : "font-medium text-text-secondary hover:bg-layer-hover"
      }`}
    >
      {children}
    </button>
  );
}

function AccentSwatch({
  color,
  label,
  active,
  onClick,
}: {
  color: string;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      title={label}
      onClick={onClick}
      className={`flex h-7 w-7 items-center justify-center rounded-full border transition-colors ${
        active ? "border-accent" : "border-transparent hover:border-border-strong"
      }`}
    >
      <span className="h-[18px] w-[18px] rounded-full" style={{ background: color }} />
    </button>
  );
}
