"use client";
import { createContext, useCallback, useContext, useEffect, useReducer } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { insforge } from "@/lib/insforge/browser";
import { authReducer, type AuthState, type AuthUser } from "@/lib/auth/authState";

type AuthContextValue = AuthState & {
  signIn: (email: string, password: string) => Promise<{ error?: string }>;
  signOut: () => Promise<void>;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, { status: "loading", user: null });
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { data } = await insforge.auth.getCurrentUser();
        if (cancelled) return;
        const u = data?.user;
        dispatch({ type: "resolved", user: u ? ({ id: u.id, email: u.email } as AuthUser) : null });
      } catch {
        if (!cancelled) dispatch({ type: "resolved", user: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

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
