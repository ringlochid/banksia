import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { initializeConsoleConfig } from "./app/config";
import { router } from "./app/router";
import "./styles/tailwind.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
    throw new Error("AutoClaw console root element was not found");
}

const consoleRootElement = rootElement;

async function startConsole(): Promise<void> {
    await initializeConsoleConfig();

    if (import.meta.env.DEV && import.meta.env.VITE_AUTOCLAW_MOCK_API === "true") {
        const { enableMockApi } = await import("./mocks/browser");
        await enableMockApi();
    }

    createRoot(consoleRootElement).render(
        <StrictMode>
            <RouterProvider router={router} />
        </StrictMode>,
    );
}

void startConsole();
