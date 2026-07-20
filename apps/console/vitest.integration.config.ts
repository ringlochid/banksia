import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react(), tailwindcss()],
    test: {
        environment: "jsdom",
        include: ["tests/integration/**/*.{test,spec}.{ts,tsx}"],
        setupFiles: ["./vitest.setup.ts"],
    },
});
