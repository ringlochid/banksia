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
    managed_extension_modes: ["inherit", "isolated"],
    human_request_kinds: ["input", "direction", "approval", "review"],
    command_run_values: ["allow"],
    default_provider: {
        kind: "codex",
        model: "gpt-default",
        effort: "high",
        sandbox: { mode: "read_only", network: "deny" },
        extension_mode: "inherit",
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

        const description = screen.getByLabelText("Purpose");
        expect(description).toHaveAttribute("aria-invalid", "true");
        expect(description).toHaveAccessibleDescription(
            /Describe when this team should be used/,
        );
        expect(screen.getByLabelText(/^Shared note/)).toBeVisible();
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
        const provider = screen.getByRole("combobox", { name: "Provider" });
        expect(provider).toHaveTextContent("Installation default");
        expect(screen.getByText(/Nothing is allowed by default/)).toBeVisible();
        expect(screen.getByText(/Default: Codex · gpt-default/)).toBeVisible();

        await user.click(provider);
        await user.click(screen.getByRole("option", { name: /^Codex/ }));
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

    it("keeps a rejected capability beside the affected choices", async () => {
        const user = userEvent.setup();
        const member = workflowFixture().lead;

        render(
            <MemberForm
                disabled={false}
                issues={[
                    {
                        source: "controller",
                        path: "patch.capabilities.human_request",
                        message: "This capability is not available.",
                        target: {
                            kind: "member",
                            memberId: member.id,
                            field: "capabilities",
                        },
                    },
                ]}
                member={member}
                onEdit={vi.fn()}
                onRetryOptions={vi.fn()}
                options={readyOptions}
                workflow={workflowFixture()}
            />,
        );

        await user.click(screen.getByText("Provider and access"));
        const capabilities = screen.getByRole("group", {
            name: "Allowed actions",
        });
        expect(capabilities).toHaveAttribute("aria-invalid", "true");
        expect(capabilities).toHaveAccessibleDescription(
            "This capability is not available.",
        );
    });

    it("omits null capability defaults when another action is enabled", async () => {
        const user = userEvent.setup();
        const onEdit = vi.fn();
        const member = {
            ...workflowFixture().lead,
            capabilities: {
                human_request: ["input"],
                command_run: null,
            },
        } as unknown as ReturnType<typeof workflowFixture>["lead"];

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

        await user.click(screen.getByText("Provider and access"));
        await user.click(
            screen.getByLabelText(
                "Allow this teammate to ask you for direction",
            ),
        );
        expect(onEdit).toHaveBeenCalledWith({
            capabilities: { human_request: ["input", "direction"] },
        });
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
        expect(screen.getByText("Loading choices")).toBeVisible();
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
                name: "Try again",
            }),
        );
        expect(retry).toHaveBeenCalledOnce();
        expect(
            screen.getByRole("combobox", { name: "Provider" }),
        ).toHaveTextContent("OpenClaw");
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
        ).toHaveTextContent("Provider default");
        expect(
            screen.getByRole("combobox", { name: /^Skills and MCP/ }),
        ).toHaveTextContent("Provider default");
        expect(
            screen.getByText(
                /Default: Codex · gpt-default · High effort · Read Only · Network deny · Provider Skills and MCP/,
            ),
        ).toBeVisible();
    });

    it("treats null managed-provider defaults from controller readback as omitted", async () => {
        const user = userEvent.setup();
        const onEdit = vi.fn();
        const member = {
            ...workflowFixture().lead,
            provider: {
                kind: "codex",
                model: null,
                effort: null,
                sandbox: null,
            },
        } as unknown as ReturnType<typeof workflowFixture>["lead"];

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

        await user.click(screen.getByText("Provider and access"));
        expect(
            screen.getByRole("combobox", { name: /^Reasoning effort/ }),
        ).toHaveTextContent("Provider default");
        expect(
            screen.getByRole("combobox", { name: /^Sandbox and network/ }),
        ).toHaveTextContent("Provider default");

        await user.click(
            screen.getByRole("combobox", { name: /^Reasoning effort/ }),
        );
        await user.click(screen.getByRole("option", { name: "High" }));
        expect(onEdit).toHaveBeenCalledWith({
            provider: { kind: "codex", effort: "high" },
        });

        await user.click(
            screen.getByRole("combobox", { name: /^Skills and MCP/ }),
        );
        await user.click(screen.getByRole("option", { name: "Banksia only" }));
        expect(onEdit).toHaveBeenCalledWith({
            provider: { kind: "codex", extension_mode: "isolated" },
        });
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
