import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// E2E runs against the built UI served by the real backend (one process serves
// API + UI on one port). Network-free: no remote importers are exercised.
const port = Number(process.env.PV_E2E_PORT || 8765);
const dataDir = path.join(os.tmpdir(), "promptvault-e2e-data");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1, // tests share one server and clean up after themselves
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["list"], ["junit", { outputFile: "e2e-results/junit.xml" }]]
    : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "retain-on-failure",
    permissions: ["clipboard-read", "clipboard-write"],
  },
  webServer: {
    command: "uv run --no-sync promptvault serve --host localhost --port 8765",
    cwd: "../backend",
    url: `http://localhost:${port}/api/v1/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      PV_DATA_DIR: dataDir,
      PV_SEED_ON_START: "false",
      PV_HOST: "localhost",
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
