import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Investintell Light",
  description: "Stock and portfolio analysis",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <Providers>
          <div className="flex h-screen overflow-hidden">
            {/* ── Left Sidebar ──────────────────────────────────────────── */}
            <aside className="w-[220px] shrink-0 flex flex-col overflow-hidden bg-surface-1 border-r border-border">
              {/* Product name */}
              <div className="px-4 pt-5 pb-4 border-b border-border">
                <span className="text-[15px] font-semibold tracking-tight text-accent">
                  Investintell Light
                </span>
              </div>

              {/* Navigation */}
              <nav
                aria-label="Primary"
                className="flex-1 overflow-y-auto py-3 px-2"
              >
                <NavGroup label="Stocks">
                  <NavItem href="/stocks/analysis">Stock Analysis</NavItem>
                </NavGroup>

                <NavGroup label="Portfolio">
                  <NavItem href="/portfolio">Overview</NavItem>
                  <NavItem href="/portfolio/static">Static Analysis</NavItem>
                </NavGroup>

                <NavGroup label="Statistics">
                  <NavItem href="/statistics/scenario">Scenario</NavItem>
                  <NavItem href="/statistics/beta">Beta</NavItem>
                  <NavItem href="/statistics/correlation">Correlation</NavItem>
                  <NavItem href="/statistics/stock-correlation">
                    Stock Correlation
                  </NavItem>
                </NavGroup>

                <NavGroup label="Screener">
                  <NavItem href="/screener">Screener</NavItem>
                </NavGroup>
              </nav>
            </aside>

            {/* ── Main area ─────────────────────────────────────────────── */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Header bar */}
              <header className="h-[52px] shrink-0 flex items-center px-5 bg-surface-1 border-b border-border">
                <input
                  type="text"
                  placeholder="Search ticker…"
                  disabled
                  aria-label="Search ticker"
                  className="w-[240px] h-8 px-3 rounded-[6px] border border-border bg-surface-2 text-text-muted text-[13px] cursor-not-allowed outline-none"
                />
              </header>

              {/* Page content */}
              <main className="flex-1 overflow-y-auto bg-surface-0">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}

/* ── Internal nav components ─────────────────────────────────────────────── */

function NavGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5">
      <div className="text-[10px] font-bold tracking-[0.08em] uppercase text-text-muted px-2 mb-1">
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}

function NavItem({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="block px-2 py-1.5 rounded-[5px] text-[13px] text-text-secondary no-underline hover:bg-surface-2 hover:text-text-primary transition-colors"
    >
      {children}
    </Link>
  );
}
