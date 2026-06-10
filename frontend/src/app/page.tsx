export default function Home() {
  return (
    <div className="flex items-center justify-center min-h-full px-6 py-10">
      <div className="bg-surface-2 border border-border rounded-xl px-12 py-10 max-w-[480px] w-full text-center">
        <h1 className="text-2xl font-bold text-text-primary mb-2 tracking-tight">
          Investintell Light
        </h1>

        <p className="text-sm text-text-secondary mb-8">
          Stock &amp; portfolio analysis — design token preview
        </p>

        {/* Design token demo: financial semantics + tabular-nums */}
        <div className="flex justify-center gap-8">
          <div>
            <div className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-1">
              Gain
            </div>
            <span className="tabular-nums text-[22px] font-bold text-gain">
              +12.47%
            </span>
          </div>

          <div>
            <div className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-1">
              Loss
            </div>
            <span className="tabular-nums text-[22px] font-bold text-loss">
              -3.81%
            </span>
          </div>

          <div>
            <div className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-1">
              Flat
            </div>
            <span className="tabular-nums text-[22px] font-bold text-neutral-value">
              0.00%
            </span>
          </div>
        </div>

        {/* Accent strip */}
        <div className="mt-8 p-3 bg-surface-3 rounded-lg border border-border">
          <span className="text-xs text-accent font-medium">
            Graphite theme · dark-first · Tailwind 4 @theme tokens
          </span>
        </div>
      </div>
    </div>
  );
}
