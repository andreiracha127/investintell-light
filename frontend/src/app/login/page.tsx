"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, View, ViewOff } from "@carbon/icons-react";
import { useAuth } from "@/lib/auth/context";
import { TextInput } from "@/components/ui/TextInput";

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

  return (
    <div
      className="ix-carbon-scope relative flex min-h-screen items-center justify-center bg-surface-0 px-4"
    >
      <div className="w-full max-w-[396px] border border-border bg-surface-1 px-10 pb-10 pt-11">
        {/* Brand */}
        <div className="mb-[30px] flex items-center gap-2">
          <span className="h-3.5 w-3.5 flex-none bg-accent" aria-hidden />
          <span className="font-serif text-[21px] font-bold text-text-primary">Investintell</span>
          <span className="text-[9.5px] font-bold uppercase tracking-[0.16em] text-accent">Cockpit</span>
        </div>

        <h1 className="mb-7 font-serif text-[24px] font-bold text-text-primary">Sign in</h1>

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
          <TextInput
            id="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@firm.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-11 w-full mb-[22px] px-3.5 text-[13.5px] placeholder:text-placeholder focus:bg-field focus:shadow-[inset_0_-1px_0_0_var(--color-accent)]"
          />

          <label htmlFor="password" className="mb-1.5 block text-[11px] font-semibold tracking-[0.02em] text-text-secondary">
            Password
          </label>
          <div className="relative mb-2.5">
            <TextInput
              id="password"
              type={showPassword ? "text" : "password"}
              required
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-11 w-full pl-3.5 pr-11 text-[13.5px] placeholder:text-placeholder focus:bg-field focus:shadow-[inset_0_-1px_0_0_var(--color-accent)]"
            />
            <button
              type="button"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-2 top-0 flex h-11 w-[34px] items-center justify-center text-text-muted transition-colors hover:text-text-primary"
            >
              {showPassword ? <ViewOff size={17} aria-hidden /> : <View size={17} aria-hidden />}
            </button>
          </div>

          {/* Spacing reserved for a future "Forgot password?" flow.
              The dead placeholder link was removed to avoid promising a
              feature that does not exist yet. */}
          <div className="mb-[26px]" aria-hidden />

          <button
            type="submit"
            disabled={submitting}
            className="flex h-12 w-full items-center justify-between bg-accent px-[18px] text-[14px] font-bold tracking-[0.01em] text-on-accent transition hover:bg-accent-muted active:bg-accent-pressed disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span>{submitting ? "Signing in…" : "Sign in"}</span>
            <ArrowRight size={16} aria-hidden />
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
