import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
    const environment = loadEnv(mode, import.meta.dirname, "");
    const proxyTarget = environment.OMS_CONSOLE_PROXY_TARGET;

    // Inotify does not fire when a Windows editor writes to a path the dev
    // server sees through /mnt/c, so file changes are missed. Set this to fall
    // back to polling; leave it unset for same-filesystem development.
    const pollWatcher = environment.OMS_CONSOLE_WATCH_POLL === "1";

    return {
        plugins: [react(), tailwindcss()],
        server: {
            host: "127.0.0.1",
            port: 5173,
            // Polling across the mount is expensive, so keep the interval
            // coarse: it costs a beat of latency, not a stalled watcher.
            ...(pollWatcher
                ? { watch: { usePolling: true, interval: 1000 } }
                : {}),
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
