import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemberForm } from "../../src/features/workflow-studio/forms/MemberForm";
import { WorkflowForm } from "../../src/features/workflow-studio/forms/WorkflowForm";
import type { WorkflowAuthoringOptions } from "../../src/api/types";
import { workflowFixture } from "../fixtures/workflows";

const options: WorkflowAuthoringOptions = {
    workflow_fields: ["description", "note"],
    member_fields: [
        "title",
        "description",
        "instruction",
        "provider",
        "capabilities",
    ],
    provider_kinds: ["codex", "claude", "openclaw"],
    codex_efforts: ["low", "medium", "high"],
    claude_efforts: ["low", "medium", "high", "max"],
    managed_sandbox_options: [
        { mode: "read_only", network: "deny" },
        { mode: "workspace_write", network: "deny" },
    ],
    human_request_kinds: ["input", "direction", "approval", "review"],
    command_run_values: ["allow"],
    default_provider: {
        kind: "codex",
        model: "gpt-default",
        effort: "high",
        sandbox: { mode: "read_only", network: "deny" },
    },
};
const readyOptions = { kind: "ready" as const, options };

describe("Workflow authoring forms", () => {
    it("connects Workflow validation to the editable field", () => {
        const workflow = workflowFixture("");

        render(
            <WorkflowForm
                disabled={false}
                issues={[
                    {
                        source: "console",
                        path: "$.description",
                        message: "Describe when this team should be used.",
                    },
                ]}
                onEdit={vi.fn()}
                workflow={workflow}
            />,
        );

        const description = screen.getByLabelText("Use this team when…");
        expect(description).toHaveAttribute("aria-invalid", "true");
        expect(description).toHaveAccessibleDescription(
            /Describe when this team should be used/,
        );
        expect(
            screen.getByText("Shared note").closest("details"),
        ).not.toHaveAttribute("open");
    });

    it("keeps provider and default-deny capabilities reachable by disclosure", async () => {
        const user = userEvent.setup();
        const onEdit = vi.fn();
        const member = workflowFixture().lead;

        render(
            <MemberForm
                disabled={false}
                issues={[]}
                member={member}
                onEdit={onEdit}
                onRetryOptions={vi.fn()}
                options={readyOptions}
                workflow={workflowFixture()}
            />,
        );

        expect(screen.queryByLabelText("Provider")).not.toBeVisible();
        await user.click(screen.getByText("Provider and access"));
        expect(screen.getByLabelText("Provider")).toHaveValue("default");
        expect(screen.getByText(/Nothing is allowed by default/)).toBeVisible();
        expect(
            screen.getByText(/Installation default: Codex · gpt-default/),
        ).toBeVisible();

        await user.selectOptions(screen.getByLabelText("Provider"), "codex");
        expect(onEdit).toHaveBeenCalledWith({ provider: { kind: "codex" } });
        await user.click(
            screen.getByLabelText(
                "Allow this teammate to ask you for approval",
            ),
        );
        expect(onEdit).toHaveBeenCalledWith({
            capabilities: { human_request: ["approval"] },
        });
    });

    it("connects stable Member validation paths to the selected form", () => {
        const member = workflowFixture().lead;

        render(
            <MemberForm
                disabled={false}
                issues={[
                    {
                        source: "console",
                        path: `$.members.${member.id}.title`,
                        message: "Name must be 16,384 characters or fewer.",
                    },
                ]}
                member={member}
                onEdit={vi.fn()}
                onRetryOptions={vi.fn()}
                options={readyOptions}
                workflow={workflowFixture()}
            />,
        );

        const name = screen.getByRole("textbox", { name: /^Name/ });
        expect(name).toHaveAttribute("aria-invalid", "true");
        expect(name).toHaveAccessibleDescription(
            /Name must be 16,384 characters or fewer/,
        );
    });

    it("distinguishes loading from options failure and offers a real retry", async () => {
        const user = userEvent.setup();
        const retry = vi.fn();
        const member = {
            ...workflowFixture().lead,
            provider: { kind: "openclaw" as const },
        };

        const { rerender } = render(
            <MemberForm
                disabled={false}
                issues={[]}
                member={member}
                onEdit={vi.fn()}
                onRetryOptions={retry}
                options={{ kind: "loading" }}
                workflow={workflowFixture()}
            />,
        );

        await user.click(screen.getByText("Provider and access"));
        expect(
            screen.getByText(/Loading provider and access choices/i),
        ).toBeVisible();
        expect(
            screen.queryByText(/choices could not be loaded/i),
        ).not.toBeInTheDocument();
        expect(screen.getByLabelText("Provider")).toBeDisabled();

        rerender(
            <MemberForm
                disabled={false}
                issues={[]}
                member={member}
                onEdit={vi.fn()}
                onRetryOptions={retry}
                options={{
                    kind: "error",
                    message: "Choices could not be loaded.",
                }}
                workflow={workflowFixture()}
            />,
        );
        await user.click(
            screen.getByRole("button", {
                name: "Try loading choices again",
            }),
        );
        expect(retry).toHaveBeenCalledOnce();
        expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
        expect(
            screen.getByRole("option", { name: "OpenClaw" }),
        ).toBeInTheDocument();
        expect(screen.getByText(/OpenClaw owns its sandbox/)).toBeVisible();
        expect(
            screen.queryByLabelText(
                "Allow this teammate to ask you for approval",
            ),
        ).toBeNull();
        expect(
            screen.queryByLabelText(
                "Allow this teammate to run a managed command",
            ),
        ).toBeNull();
    });

    it("explains the managed-provider sandbox default accurately", async () => {
        const user = userEvent.setup();
        const member = {
            ...workflowFixture().lead,
            provider: { kind: "codex" as const },
        };

        render(
            <MemberForm
                disabled={false}
                issues={[]}
                member={member}
                onEdit={vi.fn()}
                onRetryOptions={vi.fn()}
                options={readyOptions}
                workflow={workflowFixture()}
            />,
        );

        await user.click(screen.getByText("Provider and access"));
        expect(
            screen.getByRole("combobox", { name: /^Sandbox and network/ }),
        ).toHaveValue("");
        expect(
            screen.getByRole("option", {
                name: "Full access · network allow (default)",
            }),
        ).toBeVisible();
    });

    it("routes colliding Member IDs and provider model paths exactly", async () => {
        const user = userEvent.setup();
        const base = workflowFixture();
        const workflow = {
            ...base,
            lead: {
                ...base.lead,
                id: "review",
                provider: { kind: "codex" as const },
                children: [
                    {
                        id: "review-lead",
                        title: "Review lead",
                    },
                ],
            },
        };

        render(
            <MemberForm
                disabled={false}
                issues={[
                    {
                        source: "controller",
                        path: "$.members.review-lead.title",
                        message: "The other Member has a name problem.",
                    },
                    {
                        source: "controller",
                        path: "$.members.review.title",
                        message: "This Member has a name problem.",
                    },
                    {
                        source: "controller",
                        path: "$.lead.provider.model",
                        message: "This model is not available.",
                    },
                ]}
                member={workflow.lead}
                onEdit={vi.fn()}
                onRetryOptions={vi.fn()}
                options={readyOptions}
                workflow={workflow}
            />,
        );

        const name = screen.getByRole("textbox", { name: /^Name/ });
        expect(name).toHaveAccessibleDescription(
            /This Member has a name problem/,
        );
        expect(name).not.toHaveAccessibleDescription(
            /other Member has a name problem/,
        );

        await user.click(screen.getByText("Provider and access"));
        const model = screen.getByRole("textbox", { name: /^Model/ });
        expect(model).toHaveAttribute("aria-invalid", "true");
        expect(model).toHaveAccessibleDescription(
            /This model is not available/,
        );
    });
});
