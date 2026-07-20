import { describe, expect, it } from "vitest";

import {
    formatBudgetSpec,
    mapDefinitionDetail,
} from "../../../src/features/definitions/definition-model";
import {
    createPolicyDefinitionDetail,
    createWorkflowDefinitionDetail,
} from "../../fixtures/definitions";

describe("formatBudgetSpec", () => {
    it("renders absent budgets as unbounded", () => {
        expect(formatBudgetSpec(null)).toBe("No controller budget limit");
        expect(formatBudgetSpec({})).toBe("No controller budget limit");
    });

    it("renders only configured child-assignment budgets", () => {
        expect(formatBudgetSpec({ child_assignment_limit: 1 })).toBe("1 child assignment");
        expect(formatBudgetSpec({ child_assignment_limit: 4 })).toBe("4 child assignments");
    });

    it("renders only configured retry budgets", () => {
        expect(formatBudgetSpec({ retry_limit: 1 })).toBe("1 retry");
        expect(formatBudgetSpec({ retry_limit: 2 })).toBe("2 retries");
    });
});

describe("definition detail mapping", () => {
    it("keeps authored policy capabilities distinct from omission defaults", () => {
        const authored = mapDefinitionDetail("policy", createPolicyDefinitionDetail());
        const defaults = mapDefinitionDetail(
            "policy",
            createPolicyDefinitionDetail("standard-parent-planning"),
        );

        expect(authored.kind).toBe("policy");
        if (authored.kind !== "policy" || defaults.kind !== "policy") {
            throw new Error("Expected policy detail fixtures");
        }
        expect(authored.capabilities).toMatchObject({
            commandRun: { basis: null, value: "deny" },
            humanRequest: { basis: null, mode: "allow" },
            networkAccess: { basis: "authored", value: "deny" },
            providerNativeAccess: { basis: "authored", value: "restricted" },
        });
        expect(defaults.capabilities).toMatchObject({
            networkAccess: { basis: "omitted_default", value: "allow" },
            providerNativeAccess: { basis: "omitted_default", value: "full" },
        });
    });

    it("preserves strict authored workflow provider objects and omission", () => {
        const detail = mapDefinitionDetail(
            "workflow",
            createWorkflowDefinitionDetail("bounded-change"),
        );

        expect(detail.kind).toBe("workflow");
        if (detail.kind !== "workflow") {
            throw new Error("Expected workflow detail fixture");
        }
        expect(detail.root.providerKind).toBe("openclaw");
        expect(detail.firstLevelNodes[0]?.providerKind).toBe("codex");
    });
});
