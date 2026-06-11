import type { Metadata } from "next";

import { CorrelationView } from "@/components/statistics/CorrelationView";

export const metadata: Metadata = {
  title: "Correlation — Investintell Light",
};

export default function CorrelationPage() {
  return <CorrelationView />;
}
