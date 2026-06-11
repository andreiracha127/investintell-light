/**
 * Shared presentational bits for the Statistics tool pages — pure markup,
 * no hooks, no data fetching.
 */

export const INPUT_CLASS =
  "px-3 py-1.5 rounded-[6px] bg-surface-1 border border-border text-[13px] " +
  "text-text-primary placeholder:text-text-muted focus:border-accent-muted focus:outline-none";

export const LABEL_CLASS =
  "flex items-center gap-2 text-[12px] text-text-secondary";

/** Primary submit button shared by all four tool forms. */
export function RunButton({
  pending,
  disabled,
  onClick,
}: {
  pending: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || pending}
      className="ml-auto px-5 py-1.5 rounded-[7px] bg-accent text-surface-0 text-sm font-semibold hover:bg-accent-strong transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      {pending ? "Running…" : "Run"}
    </button>
  );
}

/** Fail-loud error panel: renders the backend `detail` verbatim. */
export function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="bg-surface-2 border border-loss rounded-xl px-5 py-4"
    >
      <h2 className="text-sm font-semibold text-loss mb-1">{title}</h2>
      <p className="text-[13px] text-text-secondary break-words whitespace-pre-wrap">
        {message}
      </p>
    </div>
  );
}
