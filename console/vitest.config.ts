import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react()],
    test: {
        environment: "jsdom",
        setupFiles: ["./vitest.setup.ts"],
        include: ["tests/unit/**/*.test.ts", "tests/component/**/*.test.tsx"],
        restoreMocks: true,
    },
});
