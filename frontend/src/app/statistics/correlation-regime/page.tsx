import type { Metadata } from "next";

import { CorrelationRegimeView } from "@/components/statistics/CorrelationRegimeView";

export const metadata: Metadata = {
  title: "Correlation Regime · Investintell Cockpit",
};

export default function CorrelationRegimePage() {
  return <CorrelationRegimeView />;
}
