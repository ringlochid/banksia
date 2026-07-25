import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
    const environment = loadEnv(mode, import.meta.dirname, "");
    const proxyTarget = environment.BANKSIA_CONSOLE_PROXY_TARGET;

    return {
        plugins: [react(), tailwindcss()],
        server: {
            host: "127.0.0.1",
            port: 5173,
            proxy:
                proxyTarget === undefined || proxyTarget === ""
                    ? undefined
                    : {
                          "/api": {
                              target: proxyTarget,
                              changeOrigin: true,
                          },
                      },
        },
        preview: {
            host: "127.0.0.1",
            port: 4173,
        },
        build: {
            outDir: "dist",
            sourcemap: false,
        },
    };
});
