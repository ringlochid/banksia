import { defineConfig, devices } from "@playwright/test";

const baseURL = "http://127.0.0.1:18126";

export default defineConfig({
    fullyParallel: false,
    reporter: "list",
    testDir: "./tests/e2e/real-backend",
    timeout: 60_000,
    workers: 1,
    use: {
        baseURL,
        trace: "on-first-retry",
    },
    webServer: {
        command:
            "../../.venv/bin/python ../../scripts/testing/run_console_real_backend.py --port 18126",
        gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
        reuseExistingServer: false,
        stderr: "pipe",
        stdout: "ignore",
        timeout: 60_000,
        url: `${baseURL}/healthz`,
    },
    projects: [
        {
            name: "chromium-real-backend",
            use: { ...devices["Desktop Chrome"] },
        },
    ],
});
