export default function Home() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100%",
        padding: "40px 24px",
      }}
    >
      <div
        style={{
          backgroundColor: "var(--color-surface-2)",
          border: "1px solid var(--color-border)",
          borderRadius: "12px",
          padding: "40px 48px",
          maxWidth: "480px",
          width: "100%",
          textAlign: "center",
        }}
      >
        <h1
          style={{
            fontSize: "24px",
            fontWeight: 700,
            color: "var(--color-text-primary)",
            marginBottom: "8px",
            letterSpacing: "-0.02em",
          }}
        >
          Investintell Light
        </h1>

        <p
          style={{
            fontSize: "14px",
            color: "var(--color-text-secondary)",
            marginBottom: "32px",
          }}
        >
          Stock &amp; portfolio analysis — design token preview
        </p>

        {/* Design token demo: financial semantics + tabular-nums */}
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: "32px",
          }}
        >
          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: "var(--color-text-muted)",
                marginBottom: "4px",
              }}
            >
              Gain
            </div>
            <span
              className="tabular-nums"
              style={{
                fontSize: "22px",
                fontWeight: 700,
                color: "var(--color-gain)",
              }}
            >
              +12.47%
            </span>
          </div>

          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: "var(--color-text-muted)",
                marginBottom: "4px",
              }}
            >
              Loss
            </div>
            <span
              className="tabular-nums"
              style={{
                fontSize: "22px",
                fontWeight: 700,
                color: "var(--color-loss)",
              }}
            >
              -3.81%
            </span>
          </div>

          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: "var(--color-text-muted)",
                marginBottom: "4px",
              }}
            >
              Flat
            </div>
            <span
              className="tabular-nums"
              style={{
                fontSize: "22px",
                fontWeight: 700,
                color: "var(--color-neutral-value)",
              }}
            >
              0.00%
            </span>
          </div>
        </div>

        {/* Accent strip */}
        <div
          style={{
            marginTop: "32px",
            padding: "12px",
            backgroundColor: "var(--color-surface-3)",
            borderRadius: "8px",
            border: "1px solid var(--color-border)",
          }}
        >
          <span
            style={{
              fontSize: "12px",
              color: "var(--color-accent)",
              fontWeight: 500,
            }}
          >
            Graphite theme · dark-first · Tailwind 4 @theme tokens
          </span>
        </div>
      </div>
    </div>
  );
}
