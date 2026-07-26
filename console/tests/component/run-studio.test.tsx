import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { RunListPage } from "../../src/features/runs/RunListPage";
import { RunStudioPage } from "../../src/features/runs/RunStudioPage";
import { StartRunPage } from "../../src/features/runs/StartRunPage";
import {
    commandOutputFixture,
    humanResponseReceiptFixture,
    response,
    runApiStub,
    taskFixture,
    taskSearchFixture,
    taskStartReceiptFixture,
    workflowSearchFixture,
} from "../fixtures/runs";

describe("temporary Run Studio", () => {
    it("renders a scan-friendly semantic Run list without runtime language", async () => {
        const api = runApiStub({
            searchRuns: () => Promise.resolve(response(taskSearchFixture())),
        });

        render(
            <MemoryRouter>
                <RunListPage api={api} />
            </MemoryRouter>,
        );

        expect(screen.getByRole("status")).toHaveTextContent("Loading Runs");
        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(screen.getByText("Needs your attention")).toBeVisible();
        expect(
            screen.getByRole("link", {
                name: "Open Run: Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(
            screen.queryByText(/dispatch|attempt|boundary|wave/i),
        ).toBeNull();
    });

    it("starts from one exact prompt with optional workspace file references", async () => {
        const startRun = vi.fn(() =>
            Promise.resolve(response(taskStartReceiptFixture(), 202)),
        );
        const api = runApiStub({
            searchWorkflows: () =>
                Promise.resolve(response(workflowSearchFixture())),
            startRun,
        });
        const user = userEvent.setup();

        render(
            <MemoryRouter initialEntries={["/runs/new"]}>
                <Routes>
                    <Route
                        element={<StartRunPage api={api} />}
                        path="/runs/new"
                    />
                    <Route
                        element={<p>Accepted Run opened</p>}
                        path="/runs/:taskId"
                    />
                </Routes>
            </MemoryRouter>,
        );

        await screen.findByLabelText("Workflow");
        await user.type(
            screen.getByLabelText("What should the team accomplish?"),
            "Review the release and recommend one.",
        );
        await user.click(screen.getByText("Advanced"));
        await user.type(
            screen.getByLabelText(/^Workspace/),
            "/workspace/project",
        );
        await user.click(screen.getByRole("button", { name: "Add file" }));
        await user.type(
            screen.getByLabelText("File 1 path"),
            "docs/release-brief.md",
        );
        await user.type(
            screen.getByLabelText(/^Why should the team open it/),
            "Release constraints.",
        );
        await user.click(screen.getByRole("button", { name: "Start run" }));

        expect(await screen.findByText("Accepted Run opened")).toBeVisible();
        expect(startRun).toHaveBeenCalledWith({
            workflow: "reviewed-delivery",
            prompt: "Review the release and recommend one.",
            workspace: "/workspace/project",
            files: [
                {
                    path: "docs/release-brief.md",
                    description: "Release constraints.",
                },
            ],
        });
    });

    it("answers a Human Request and opens bounded Action output from controller truth", async () => {
        const getRun = vi.fn(() => Promise.resolve(response(taskFixture())));
        const respondToHumanRequest = vi.fn(() =>
            Promise.resolve(response(humanResponseReceiptFixture())),
        );
        const api = runApiStub({
            getRun,
            respondToHumanRequest,
            getCommandOutput: () =>
                Promise.resolve(response(commandOutputFixture())),
        });
        const user = userEvent.setup();

        renderRun(api);

        expect(
            await screen.findByRole("heading", {
                name: "Compare the release candidates and recommend one.",
            }),
        ).toBeVisible();
        expect(
            screen.getByRole("heading", { name: "Needs your attention" }),
        ).toBeVisible();
        await user.click(screen.getByRole("radio", { name: /Reliability/ }));
        await user.click(
            screen.getByRole("button", { name: "Submit response" }),
        );

        expect(await screen.findByText("Response received")).toBeVisible();
        expect(respondToHumanRequest).toHaveBeenCalledWith(
            "t_7m4k2d9x",
            "request-one",
            "answer-request",
            {
                kind: "answer",
                item_responses: {
                    priority: {
                        kind: "option",
                        option_id: "reliability",
                    },
                },
            },
        );
        await waitFor(() => expect(getRun).toHaveBeenCalledTimes(2));

        await user.click(screen.getByRole("button", { name: "View output" }));
        const dialog = await screen.findByRole("dialog", {
            name: "Output: Run the release verification suite",
        });
        expect(
            within(dialog).getByLabelText("Command output"),
        ).toHaveTextContent("all focused checks passed");
        expect(
            within(dialog).getByText(
                "The output is incomplete. Only observed content is shown.",
            ),
        ).toBeVisible();
        expect(document.body).not.toHaveTextContent("c_q3m8y1ka");
    });
});

function renderRun(api: Parameters<typeof RunStudioPage>[0]["api"]) {
    return render(
        <MemoryRouter initialEntries={["/runs/t_7m4k2d9x"]}>
            <Routes>
                <Route
                    element={<RunStudioPage api={api} />}
                    path="/runs/:taskId"
                />
            </Routes>
        </MemoryRouter>,
    );
}
