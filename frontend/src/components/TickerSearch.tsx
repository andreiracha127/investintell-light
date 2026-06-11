"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Header search: type a ticker + Enter to navigate to /stocks/{TICKER}. */
export function TickerSearch() {
  const router = useRouter();
  const [value, setValue] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const ticker = value.trim().toUpperCase();
        if (!ticker) return;
        router.push(`/stocks/${encodeURIComponent(ticker)}`);
        setValue("");
      }}
    >
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Search ticker…"
        aria-label="Search ticker"
        autoComplete="off"
        spellCheck={false}
        className="w-[240px] h-8 px-3 rounded-[6px] border border-border bg-surface-2 text-text-primary placeholder:text-text-muted text-[13px] outline-none focus:border-accent-muted transition-colors uppercase"
      />
    </form>
  );
}
