import type { Metadata } from "next";
import { Suspense } from "react";

import { BuilderView } from "@/components/builder/BuilderView";

export const metadata: Metadata = {
  title: "Builder · Investintell Cockpit",
};

export default function BuilderPage() {
  // BuilderView reads ?portfolio=<id> via useSearchParams, which the App
  // Router requires to sit under a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <BuilderView />
    </Suspense>
  );
}
