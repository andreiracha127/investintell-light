import type { Metadata } from "next";

import { FundsView } from "@/components/funds/FundsView";

export const metadata: Metadata = {
  title: "Funds — Investintell Light",
};

export default function FundsPage() {
  return <FundsView />;
}
