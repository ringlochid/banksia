import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react(), tailwindcss()],
    test: {
        environment: "jsdom",
        include: [
            "tests/unit/**/*.{test,spec}.{ts,tsx}",
            "tests/component/**/*.{test,spec}.{ts,tsx}",
        ],
        setupFiles: ["./vitest.setup.ts"],
    },
});
