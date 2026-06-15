"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Form, InlineNotification, PasswordInput, Stack, TextInput } from "@carbon/react";
import { useAuth } from "@/lib/auth/context";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    <div className="ix-carbon-scope flex min-h-screen items-center justify-center bg-surface-0 px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-6 flex items-baseline gap-2">
          <span className="font-serif text-[22px] font-bold tracking-[-0.01em] text-text-primary">Investintell</span>
          <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">Cockpit</span>
        </div>
        <Form onSubmit={onSubmit}>
          <Stack gap={6}>
            {error && (
              <InlineNotification kind="error" title="Sign in failed" subtitle={error} lowContrast hideCloseButton />
            )}
            <TextInput
              id="email" type="email" labelText="Email" autoComplete="email" required
              value={email} onChange={(e) => setEmail(e.target.value)}
            />
            <PasswordInput
              id="password" labelText="Password" autoComplete="current-password" required
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
            <Button type="submit" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</Button>
          </Stack>
        </Form>
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
