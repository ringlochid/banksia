import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
    testDir: "./tests/e2e",
    testIgnore: "**/real-backend/**",
    outputDir: "../tmp/codex/execution/wp-10/console-b-evidence/playwright",
    fullyParallel: true,
    reporter: "list",
    use: {
        baseURL: "http://127.0.0.1:5173",
        trace: "on-first-retry",
    },
    webServer: {
        command: "npm run dev",
        reuseExistingServer: !process.env.CI,
        url: "http://127.0.0.1:5173/workflows",
    },
    projects: [
        {
            name: "chromium",
            use: { ...devices["Desktop Chrome"] },
        },
        {
            name: "mobile-chrome",
            use: { ...devices["Pixel 7"] },
        },
    ],
});
