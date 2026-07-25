import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { RunsPlaceholderPage } from "../features/runs/RunsPlaceholderPage";
import { WorkflowStudioPage } from "../features/workflow-studio/WorkflowStudioPage";
import { WorkflowLibraryPage } from "../features/workflows/WorkflowLibraryPage";
import { workflowApi } from "./api";

export const router = createBrowserRouter([
    {
        path: "/",
        element: <AppShell />,
        children: [
            { index: true, element: <Navigate replace to="/workflows" /> },
            {
                path: "workflows",
                element: <WorkflowLibraryPage api={workflowApi} />,
            },
            {
                path: "workflows/:workflowId",
                element: <WorkflowStudioPage api={workflowApi} />,
            },
            { path: "runs", element: <RunsPlaceholderPage /> },
        ],
    },
]);
