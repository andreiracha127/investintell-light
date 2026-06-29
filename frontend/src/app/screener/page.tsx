import type { Metadata } from "next";
import { Suspense } from "react";

import { ScreenerView } from "@/components/screener/ScreenerView";

export const metadata: Metadata = {
  title: "Screener · Investintell Cockpit",
};

export default function ScreenerPage() {
  // Suspense boundary: ScreenerView reads `useSearchParams` (?tab=).
  return (
    <Suspense fallback={null}>
      <ScreenerView />
    </Suspense>
  );
}
