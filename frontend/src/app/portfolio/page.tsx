import type { Metadata } from "next";

import { PortfolioOverviewView } from "@/components/portfolio/PortfolioOverviewView";

export const metadata: Metadata = {
  title: "Portfolio Overview — Investintell Light",
};

export default function PortfolioOverviewPage() {
  return <PortfolioOverviewView />;
}
