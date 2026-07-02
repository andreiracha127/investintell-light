"use client";
import { Theme } from "@carbon/react";
import { useEffect, useState } from "react";

/** Drives the Carbon theme from the app's data-theme attribute so Carbon
 *  components match light/dark. light -> g10, dark -> g100. */
export function CarbonThemeBridge({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<"g10" | "g100">(() =>
    typeof document !== "undefined" && document.documentElement.dataset.theme === "dark"
      ? "g100"
      : "g10",
  );
  useEffect(() => {
    const sync = () => setTheme(document.documentElement.dataset.theme === "dark" ? "g100" : "g10");
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return <Theme theme={theme}>{children}</Theme>;
}
