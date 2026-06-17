"use client";
import { createContext, useCallback, useContext, useEffect, useReducer } from "react";
import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { authReducer, isPublicPath, type AuthState } from "@/lib/auth/authState";
import { resolveAuthIdentity } from "@/lib/auth/token";

type AuthContextValue = AuthState & {
  signIn: (email: string, password: string) => Promise<{ error?: string }>;
  signOut: () => Promise<void>;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, { status: "loading", user: null });
  const queryClient = useQueryClient();
  const pathname = usePathname();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (isPublicPath(pathname)) {
        if (cancelled) return;
        dispatch({ type: "resolved", user: null });
        return;
      }
      // Resolve auth from the same-origin access-token cookie (kept fresh by the
      // SSR middleware), not the cross-site SDK getCurrentUser: the refresh token
      // is an httpOnly cookie on this origin and never travels cross-site to the
      // InsForge host, so that path always 401s and falsely logs the user out.
      const identity = await resolveAuthIdentity();
      if (!cancelled) dispatch({ type: "resolved", user: identity });
    })();
    return () => { cancelled = true; };
  }, [pathname]);

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await fetch("/api/auth/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { error: body.message ?? "Sign in failed" };
    }
    const { user } = await res.json();
    dispatch({ type: "resolved", user: user ? { id: user.id, email: user.email } : null });
    return {};
  }, []);

  const signOut = useCallback(async () => {
    await fetch("/api/auth/sign-out", { method: "POST", credentials: "include" }).catch(() => {});
    queryClient.clear();
    dispatch({ type: "signedOut" });
    if (typeof window !== "undefined") window.location.assign("/login");
  }, [queryClient]);

  return <AuthContext.Provider value={{ ...state, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
