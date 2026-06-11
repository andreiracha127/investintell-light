import type { Metadata } from "next";

import { BetaView } from "@/components/statistics/BetaView";

export const metadata: Metadata = {
  title: "Beta — Investintell Light",
};

export default function BetaPage() {
  return <BetaView />;
}
