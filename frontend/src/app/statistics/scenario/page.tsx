import type { Metadata } from "next";

import { ScenarioView } from "@/components/statistics/ScenarioView";

export const metadata: Metadata = {
  title: "Scenario — Investintell Light",
};

export default function ScenarioPage() {
  return <ScenarioView />;
}
