"use client";
import { Theme } from "@carbon/react";
import { useEffect, useState } from "react";

/** Drives the Carbon theme from the app's data-theme attribute so Carbon
 *  components match light/dark. light -> g10, dark -> g100. */
export function CarbonThemeBridge({ children }: { children: React.ReactNode }) {
  // Start from a deterministic "g10" so the server render and the first client
  // render agree (the server has no `document`, so reading it in a lazy
  // initializer would return "g100" for dark sessions and cause a hydration
  // mismatch). The effect below syncs the real theme immediately after mount.
  const [theme, setTheme] = useState<"g10" | "g100">("g10");
  useEffect(() => {
    const sync = () => setTheme(document.documentElement.dataset.theme === "dark" ? "g100" : "g10");
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return <Theme theme={theme}>{children}</Theme>;
}
