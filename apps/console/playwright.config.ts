import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
    testDir: "./tests/e2e",
    testIgnore: "**/real-backend/**",
    fullyParallel: true,
    reporter: "list",
    use: {
        baseURL: "http://127.0.0.1:5173",
        trace: "on-first-retry",
    },
    webServer: {
        command: "npm run dev -- --host 127.0.0.1",
        reuseExistingServer: !process.env.CI,
        url: "http://127.0.0.1:5173",
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
