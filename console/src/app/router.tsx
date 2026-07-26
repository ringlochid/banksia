import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import {
    RunApiClient,
    RunListPage,
    RunStudioPage,
    StartRunPage,
} from "../features/runs";
import { WorkflowStudioPage } from "../features/workflow-studio/WorkflowStudioPage";
import { WorkflowLibraryPage } from "../features/workflows/WorkflowLibraryPage";
import { workflowApi } from "./api";

const runApi = new RunApiClient();

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
            { path: "runs", element: <RunListPage api={runApi} /> },
            { path: "runs/new", element: <StartRunPage api={runApi} /> },
            {
                path: "runs/:taskId",
                element: <RunStudioPage api={runApi} />,
            },
        ],
    },
]);
