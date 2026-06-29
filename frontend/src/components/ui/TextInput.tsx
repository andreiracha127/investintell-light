"use client";

import { forwardRef } from "react";

/**
 * Shared text input — single source of truth for field styling across the
 * Investintell Cockpit. Variants:
 *   - "underline": bottom rule only, accent on focus (Carbon tile field).
 *   - "boxed":     full hairline border, accent bottom rule on focus (forms).
 *
 * Replaces the ad-hoc fieldClass strings duplicated in login, portfolio, and
 * screener. Density-aware via --ix-* tokens where relevant.
 */
const BASE =
  "bg-field text-text-primary placeholder:text-text-muted outline-none " +
  "transition-[background,box-shadow,border-color] focus:border-accent " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const VARIANT_UNDERLINE =
  "border-0 border-b border-border-strong focus:border-b-2";
const VARIANT_BOXED =
  "border border-border-strong focus:border-b-2";

export type TextInputVariant = "underline" | "boxed";

export interface TextInputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  variant?: TextInputVariant;
  invalid?: boolean;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  function TextInput(
    { variant = "underline", invalid = false, className = "", ...props },
    ref,
  ) {
    const variantClass =
      variant === "boxed" ? VARIANT_BOXED : VARIANT_UNDERLINE;
    const invalidClass = invalid
      ? "border-loss focus:border-loss"
      : "";
    return (
      <input
        ref={ref}
        className={`${BASE} ${variantClass} ${invalidClass} ${className}`}
        {...props}
      />
    );
  },
);
