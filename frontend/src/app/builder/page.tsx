import type { Metadata } from "next";

import { BuilderView } from "@/components/builder/BuilderView";

export const metadata: Metadata = {
  title: "Builder — Investintell Light",
};

export default function BuilderPage() {
  return <BuilderView />;
}
