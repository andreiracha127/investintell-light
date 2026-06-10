import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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
            <aside
              style={{
                width: "220px",
                flexShrink: 0,
                backgroundColor: "var(--color-surface-1)",
                borderRight: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              {/* Product name */}
              <div
                style={{
                  padding: "20px 16px 16px",
                  borderBottom: "1px solid var(--color-border)",
                }}
              >
                <span
                  style={{
                    fontSize: "15px",
                    fontWeight: 600,
                    color: "var(--color-accent)",
                    letterSpacing: "-0.01em",
                  }}
                >
                  Investintell Light
                </span>
              </div>

              {/* Navigation */}
              <nav
                style={{
                  flex: 1,
                  overflowY: "auto",
                  padding: "12px 8px",
                }}
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
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              {/* Header bar */}
              <header
                style={{
                  height: "52px",
                  flexShrink: 0,
                  backgroundColor: "var(--color-surface-1)",
                  borderBottom: "1px solid var(--color-border)",
                  display: "flex",
                  alignItems: "center",
                  padding: "0 20px",
                }}
              >
                <input
                  type="text"
                  placeholder="Search ticker…"
                  disabled
                  style={{
                    width: "240px",
                    height: "32px",
                    padding: "0 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--color-border)",
                    backgroundColor: "var(--color-surface-2)",
                    color: "var(--color-text-muted)",
                    fontSize: "13px",
                    cursor: "not-allowed",
                    outline: "none",
                  }}
                />
              </header>

              {/* Page content */}
              <main
                style={{
                  flex: 1,
                  overflowY: "auto",
                  backgroundColor: "var(--color-surface-0)",
                }}
              >
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
    <div style={{ marginBottom: "20px" }}>
      <div
        style={{
          fontSize: "10px",
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--color-text-muted)",
          padding: "0 8px",
          marginBottom: "4px",
        }}
      >
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
    <a
      href={href}
      style={{
        display: "block",
        padding: "6px 8px",
        borderRadius: "5px",
        fontSize: "13px",
        color: "var(--color-text-secondary)",
        textDecoration: "none",
      }}
    >
      {children}
    </a>
  );
}
