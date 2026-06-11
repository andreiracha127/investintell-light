import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/shell/AppShell";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Investintell Cockpit",
  description: "Stock and portfolio analysis",
};

/**
 * Applies persisted theme/accent/density to <html> before first paint so the
 * cockpit never flashes the default scheme. Mirrors AppShell's readSettings.
 */
const SETTINGS_SCRIPT = `(function(){try{var s=JSON.parse(localStorage.getItem("ix-cockpit-settings")||"{}");var e=document.documentElement;e.dataset.theme=s.theme==="dark"?"dark":"light";e.dataset.accent=s.accent==="blue"||s.accent==="teal"?s.accent:"oxblood";e.dataset.density=s.density==="comfortable"?"comfortable":"compact";}catch(_){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="light"
      data-accent="oxblood"
      data-density="compact"
      suppressHydrationWarning
    >
      <body className={`${geistMono.variable} antialiased`}>
        <script dangerouslySetInnerHTML={{ __html: SETTINGS_SCRIPT }} />
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
