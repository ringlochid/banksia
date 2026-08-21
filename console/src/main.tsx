import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";

import "./styles/index.css";
import "./components/ui/ui.css";
import "./components/ui/prose.css";
import "./components/layout/shell.css";
import "./features/operator/operator.css";
import "./features/workflows/workflows.css";
import "./features/workflow-studio/studio.css";
import { router } from "./app/router";

const root = document.getElementById("root");
if (root === null) {
    throw new Error("Oh My Subagents Console root element is missing");
}

createRoot(root).render(
    <StrictMode>
        <RouterProvider router={router} />
    </StrictMode>,
);
