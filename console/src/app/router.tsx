import { createBrowserRouter, Navigate } from "react-router";

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
import { RouteErrorPage } from "./RouteErrorPage";

const runApi = new RunApiClient();
const routeError = <RouteErrorPage />;

export const router = createBrowserRouter([
    {
        path: "/",
        element: <AppShell />,
        errorElement: routeError,
        children: [
            { index: true, element: <Navigate replace to="/workflows" /> },
            {
                path: "workflows",
                element: <WorkflowLibraryPage api={workflowApi} />,
                errorElement: routeError,
            },
            {
                path: "workflows/:workflowId",
                element: <WorkflowStudioPage api={workflowApi} />,
                errorElement: routeError,
            },
            {
                path: "runs",
                element: <RunListPage api={runApi} />,
                errorElement: routeError,
            },
            {
                path: "runs/new",
                element: <StartRunPage api={runApi} />,
                errorElement: routeError,
            },
            {
                path: "runs/:taskId",
                element: <RunStudioPage api={runApi} />,
                errorElement: routeError,
            },
        ],
    },
]);
