import path from "node:path";
import { defineConfig } from "vitest/config";

// Pure-logic tests only (node environment, no jsdom) — see
// docs/adr/0001-start-sh-is-the-test-gate.md and .scratch/frontend-test-infra.
// Add a jsdom environment per-file (`// @vitest-environment jsdom`) if and
// when component tests arrive.
export default defineConfig({
  test: {
    include: ["**/*.test.ts"],
    environment: "node",
  },
  resolve: {
    // Mirror tsconfig's `"@/*": ["./*"]`.
    alias: { "@": path.resolve(__dirname) },
  },
});
