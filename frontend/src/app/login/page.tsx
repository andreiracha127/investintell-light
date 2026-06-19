"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/context";

function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M1 8s2.5-4.5 7-4.5S15 8 15 8s-2.5 4.5-7 4.5S1 8 1 8Z" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="1.9" stroke="currentColor" strokeWidth="1.3" />
      {off && <path d="M2 2l12 12" stroke="currentColor" strokeWidth="1.3" />}
    </svg>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const rawNext = params.get("next") || "/";
  // Prevent post-auth open redirect: only allow same-origin relative paths.
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const { error } = await signIn(email, password);
    setSubmitting(false);
    if (error) { setError(error); return; }
    router.replace(next);
  }

  const fieldClass =
    "h-11 w-full border-0 border-b border-field-underline bg-surface-0 text-[13.5px] text-text-primary outline-none transition-[background,box-shadow,border-color] placeholder:text-placeholder focus:border-accent focus:bg-field focus:shadow-[inset_0_-1px_0_0_var(--color-accent)]";

  return (
    <div
      className="ix-carbon-scope relative flex min-h-screen items-center justify-center px-4"
      style={{
        background:
          "radial-gradient(125% 90% at 50% -8%, var(--color-surface-1) 0%, var(--color-surface-0) 42%, var(--color-gradient-outer) 100%)",
      }}
    >
      <div className="w-full max-w-[396px] border border-border bg-surface-1 px-10 pb-10 pt-11 shadow-[0_1px_1px_rgba(22,22,22,0.04),0_4px_10px_rgba(22,22,22,0.05),0_18px_40px_rgba(22,22,22,0.10)]">
        {/* Brand */}
        <div className="mb-[30px] flex items-center gap-2">
          <span className="h-3.5 w-3.5 flex-none bg-accent" aria-hidden />
          <span className="font-serif text-[21px] font-bold tracking-[-0.01em] text-text-primary">Investintell</span>
          <span className="text-[9.5px] font-bold uppercase tracking-[0.16em] text-accent">Cockpit</span>
        </div>

        <h1 className="mb-7 font-serif text-[24px] font-bold tracking-[-0.01em] text-text-primary">Sign in</h1>

        <form onSubmit={onSubmit} noValidate>
          {error && (
            <div
              role="alert"
              className="mb-5 border-l-2 border-loss bg-loss-muted px-3 py-2 text-[12.5px] leading-snug text-loss"
            >
              <span className="font-semibold">Sign in failed.</span> {error}
            </div>
          )}

          <label htmlFor="email" className="mb-1.5 block text-[11px] font-semibold tracking-[0.02em] text-text-secondary">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@firm.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={`${fieldClass} mb-[22px] px-3.5`}
          />

          <label htmlFor="password" className="mb-1.5 block text-[11px] font-semibold tracking-[0.02em] text-text-secondary">
            Password
          </label>
          <div className="relative mb-2.5">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              required
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={`${fieldClass} pl-3.5 pr-11`}
            />
            <button
              type="button"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-2 top-0 flex h-11 w-[34px] items-center justify-center text-text-muted transition-colors hover:text-text-primary"
            >
              <EyeIcon off={showPassword} />
            </button>
          </div>

          <div className="mb-[26px] flex justify-end">
            <a
              href="#"
              onClick={(e) => e.preventDefault()}
              className="text-[12px] text-text-secondary no-underline transition-colors hover:text-accent"
            >
              Forgot password?
            </a>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="flex h-12 w-full items-center justify-between bg-accent px-[18px] text-[14px] font-bold tracking-[0.01em] text-on-accent transition hover:bg-accent-muted active:bg-accent-pressed disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span>{submitting ? "Signing in…" : "Sign in"}</span>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M3 8h9M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
        </form>
      </div>

      <div className="absolute bottom-[22px] left-0 right-0 text-center text-[11px] text-field-underline">
        Protected workspace · Investintell Cockpit
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
