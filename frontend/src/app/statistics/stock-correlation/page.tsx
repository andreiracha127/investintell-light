import type { Metadata } from "next";

import { StockCorrelationView } from "@/components/statistics/StockCorrelationView";

export const metadata: Metadata = {
  title: "Stock Correlation · Investintell Cockpit",
};

export default function StockCorrelationPage() {
  return <StockCorrelationView />;
}
