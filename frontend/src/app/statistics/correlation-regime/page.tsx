import type { Metadata } from "next";

import { CorrelationRegimeView } from "@/components/statistics/CorrelationRegimeView";

export const metadata: Metadata = {
  title: "Correlation Regime — Investintell Light",
};

export default function CorrelationRegimePage() {
  return <CorrelationRegimeView />;
}
