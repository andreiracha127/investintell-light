"use client";

import { useEffect, useRef } from "react";

/**
 * Styled confirm dialog — replaces native window.confirm so destructive
 * confirmations stay inside the Investintell Cockpit visual language.
 *
 * Focus is trapped inside the dialog while open, Escape cancels, and the
 * backdrop click cancels. Mirrors the PortfolioEditDialog chrome.
 */

const OVERLAY_CLASS =
  "fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(0,0,0,0.32)] p-4";

const PANEL_CLASS =
  "w-[420px] max-w-[96vw] border border-border-strong bg-surface-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)]";

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = true,
  pending = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Focus the confirm button on mount.
  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  // Escape cancels.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, pending]);

  // Simple focus trap: keep Tab inside the overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const overlay = document.querySelector("[data-confirm-overlay]");
      if (!overlay) return;
      const focusable = overlay.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      data-confirm-overlay
      onClick={() => {
        if (!pending) onCancel();
      }}
      className={OVERLAY_CLASS}
    >
      <div
        role="alertdialog"
        aria-label={title}
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className={PANEL_CLASS}
      >
        <div className="px-[var(--ix-pad)] py-4">
          <h2 className="ix-title m-0 text-[18px] text-text-primary">{title}</h2>
          <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
            {message}
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-[var(--ix-pad)] py-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={pending}
            className="h-[30px] border border-border-strong bg-field px-4 text-[12px] text-text-secondary transition-colors hover:bg-layer-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={
              destructive
                ? "h-[30px] border border-[var(--color-loss)] bg-[var(--color-loss)] px-4 text-[12px] font-bold text-white transition-[filter] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
                : "h-[30px] border border-accent bg-accent px-4 text-[12px] font-bold text-on-accent disabled:cursor-not-allowed disabled:opacity-40"
            }
          >
            {pending ? "…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
