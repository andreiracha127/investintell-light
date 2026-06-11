"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Header search: type a ticker + Enter to navigate to /stocks/{TICKER}. */
export function TickerSearch() {
  const router = useRouter();
  const [value, setValue] = useState("");

  return (
    <form
      className="relative min-w-0 flex-1"
      style={{ maxWidth: 380 }}
      onSubmit={(event) => {
        event.preventDefault();
        const ticker = value.trim().toUpperCase();
        if (!ticker) return;
        router.push(`/stocks/${encodeURIComponent(ticker)}`);
        setValue("");
      }}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
      >
        <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M11 11l4 4" stroke="currentColor" strokeWidth="1.4" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Search ticker…"
        aria-label="Search ticker"
        autoComplete="off"
        spellCheck={false}
        className="h-9 w-full border-0 border-b border-border-strong bg-field pl-[34px] pr-3 text-[13px] uppercase text-text-primary outline-none placeholder:text-text-muted focus:border-b-2 focus:border-accent"
      />
    </form>
  );
}
