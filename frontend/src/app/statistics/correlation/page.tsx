import type { Metadata } from "next";

import { CorrelationView } from "@/components/statistics/CorrelationView";

export const metadata: Metadata = {
  title: "Correlation · Investintell Cockpit",
};

export default function CorrelationPage() {
  return <CorrelationView />;
}
