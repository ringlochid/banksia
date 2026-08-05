import { load } from "js-yaml";
import { describe, expect, it } from "vitest";

import type { NormalizedWorkflow } from "../../src/api/types";
import { renderWorkflowYaml } from "../../src/features/workflow-studio/workflow-export";

describe("Workflow YAML export", () => {
    it("renders the complete current Workflow without nulls or YAML references", () => {
        const sharedChild = {
            id: "member-reviewer",
            title: "Reviewer",
            description: null,
        };
        const workflow: NormalizedWorkflow = {
            kind: "workflow",
            id: "current-draft",
            description: "The current visible purpose.",
            note: null,
            lead: {
                id: "member-lead",
                title: "Lead",
                children: [sharedChild, sharedChild],
            },
        };

        const rendered = renderWorkflowYaml(workflow);

        expect(load(rendered)).toEqual({
            kind: "workflow",
            id: "current-draft",
            description: "The current visible purpose.",
            lead: {
                id: "member-lead",
                title: "Lead",
                children: [
                    { id: "member-reviewer", title: "Reviewer" },
                    { id: "member-reviewer", title: "Reviewer" },
                ],
            },
        });
        expect(rendered).not.toMatch(/(?:^|\s)[&*][^\s]+/m);
        expect(rendered.endsWith("\n")).toBe(true);
    });
});
