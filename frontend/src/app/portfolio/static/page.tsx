import type { Metadata } from "next";

import { StaticPortfolioView } from "@/components/portfolio/StaticPortfolioView";

export const metadata: Metadata = {
  title: "Static Portfolio Analysis · Investintell Cockpit",
};

export default function StaticPortfolioPage() {
  return <StaticPortfolioView />;
}
