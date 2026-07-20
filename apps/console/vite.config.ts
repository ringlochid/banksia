import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

const API_PATH_PATTERN =
    "^/(runtime|control|definitions|authoring|tasks|healthz|readyz|console)(/|$)";

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, import.meta.dirname, "");
    // loadEnv types values as string, but absent keys are undefined at runtime.
    const proxyTarget = env.AUTOCLAW_CONSOLE_PROXY_TARGET as string | undefined;

    return {
        plugins: [react(), tailwindcss()],
        server: {
            host: "127.0.0.1",
            port: 5173,
            proxy: proxyTarget === undefined ? undefined : apiProxy(proxyTarget),
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

/**
 * Same-origin API forwarding for sandboxed browsers that block cross-origin
 * XHR. HTML navigations bypass the proxy so SPA routes such as /tasks and
 * /definitions keep serving index.html.
 */
function apiProxy(target: string): Record<string, ProxyOptions> {
    return {
        [API_PATH_PATTERN]: {
            target,
            changeOrigin: true,
            bypass: (req) => {
                const accept = req.headers.accept ?? "";
                return accept.includes("text/html") ? "/index.html" : undefined;
            },
        },
    };
}
