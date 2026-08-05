import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { StartRunPage } from "../../src/features/runs/StartRunPage";
import { response, runApiStub, workflowSearchFixture } from "../fixtures/runs";

describe("Start Run", () => {
    it("loads every Workflow page before choosing a published Workflow", async () => {
        const published = workflowSearchFixture().items[0];
        if (published === undefined) {
            throw new Error("Expected published Workflow fixture");
        }
        const searchWorkflows = vi.fn((cursor: string | null = null) =>
            Promise.resolve(
                response(
                    cursor === null
                        ? {
                              items: [
                                  {
                                      ...published,
                                      workflow_id: "draft-only",
                                      state: "draft" as const,
                                      published_revision_no: null,
                                      available_actions: [
                                          "edit" as const,
                                          "remove" as const,
                                      ],
                                  },
                                  published,
                              ],
                              next_cursor: "page-two",
                          }
                        : {
                              items: [
                                  {
                                      ...published,
                                      workflow_id: "later-published",
                                  },
                              ],
                              next_cursor: null,
                          },
                ),
            ),
        );
        const api = runApiStub({ searchWorkflows });
        const user = userEvent.setup();

        render(
            <MemoryRouter
                initialEntries={["/runs/new?workflow=later-published"]}
            >
                <Routes>
                    <Route
                        element={<StartRunPage api={api} />}
                        path="/runs/new"
                    />
                </Routes>
            </MemoryRouter>,
        );

        const picker = await screen.findByRole("combobox", {
            name: "Workflow",
        });
        expect(
            screen.getByRole("heading", { level: 1, name: "Start a run" }),
        ).toBeVisible();
        expect(picker).toHaveTextContent("later-published");
        expect(
            screen.queryByText("No published Workflows"),
        ).not.toBeInTheDocument();
        await user.click(picker);
        const search = screen.getByRole("searchbox", {
            name: "Search Workflows",
        });
        expect(
            screen.getByRole("option", { name: /later-published/ }),
        ).toBeVisible();
        expect(
            screen.queryByRole("option", { name: /draft-only/ }),
        ).not.toBeInTheDocument();
        await user.type(search, "production-feature");
        expect(
            screen.getByRole("option", { name: /production-feature-delivery/ }),
        ).toBeVisible();
        expect(
            screen.queryByRole("option", { name: /later-published/ }),
        ).not.toBeInTheDocument();
        await user.click(
            screen.getByRole("option", { name: /production-feature-delivery/ }),
        );
        expect(picker).toHaveTextContent("production-feature-delivery");
        expect(searchWorkflows.mock.calls.map(([cursor]) => cursor)).toEqual([
            null,
            "page-two",
        ]);
    });
});
