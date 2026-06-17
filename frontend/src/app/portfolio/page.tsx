import type { Metadata } from "next";
import { Suspense } from "react";

import { PortfolioOverviewView } from "@/components/portfolio/PortfolioOverviewView";

export const metadata: Metadata = {
  title: "Portfolio Overview — Investintell Light",
};

export default function PortfolioOverviewPage() {
  return (
    <Suspense fallback={null}>
      <PortfolioOverviewView />
    </Suspense>
  );
}
