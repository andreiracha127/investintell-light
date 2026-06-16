import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

const config = {
  plugins: [react()],
  oxc: false,
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    // Pure-logic suites run in the default `node` environment; React component
    // tests opt into jsdom per-file via `// @vitest-environment jsdom`.
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["./vitest.setup.ts"],
  },
};

export default defineConfig(config as unknown as Parameters<typeof defineConfig>[0]);
