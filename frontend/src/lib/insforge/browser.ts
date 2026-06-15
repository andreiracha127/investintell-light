"use client";
import { createBrowserClient } from "@insforge/sdk/ssr";

/** Singleton InsForge browser client. Reads the insforge_access_token cookie
 *  and refreshes through /api/auth/refresh when needed. */
export const insforge = createBrowserClient();
