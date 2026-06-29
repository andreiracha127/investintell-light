import type { Metadata } from "next";

import { MacroRegimeView } from "@/components/macro/MacroRegimeView";

export const metadata: Metadata = {
  title: "Market Regime · Investintell Cockpit",
};

export default function MacroRegimePage() {
  return <MacroRegimeView />;
}
