import type { components } from "../../api/generated/openapi";

type DefinitionDraftKind = components["schemas"]["DefinitionKind"];

export function starterBodyForKind(
    kind: DefinitionDraftKind,
    key: string,
    description: string,
): string {
    const draftDescription = description.trim() || `Draft ${kind} ${key}.`;
    if (kind === "policy") {
        return [
            yamlField("kind", "policy"),
            yamlField("id", key),
            yamlField("title", draftDescription),
            yamlField("description", draftDescription),
            yamlField("instruction", "Keep the assigned work bounded to this policy."),
            "applies_to:",
            `    - ${yamlScalar("worker")}`,
            "capabilities:",
            yamlField("provider_native_access", "full", 4),
            yamlField("network_access", "allow", 4),
            "    human_request:",
            yamlField("mode", "deny", 8),
            "        allowed_kinds: []",
            yamlField("command_run", "deny", 4),
            "",
        ].join("\n");
    }
    if (kind === "workflow") {
        return [
            yamlField("kind", "workflow"),
            yamlField("id", key),
            yamlField("description", draftDescription),
            "root:",
            yamlField("node_key", "root", 4),
            yamlField("kind", "root", 4),
            yamlField("role_id", "root_planning_lead", 4),
            yamlField("policy_id", "standard-root", 4),
            "    provider:",
            yamlField("kind", "codex", 8),
            yamlField("description", draftDescription, 4),
            yamlField("instruction", "Plan the requested work and close when complete.", 4),
            "",
        ].join("\n");
    }
    return [
        yamlField("kind", "role"),
        yamlField("id", key),
        yamlField("title", draftDescription),
        yamlField("description", draftDescription),
        yamlField("instruction", "Work inside the assigned scope and report concise results."),
        "allowed_node_kinds:",
        `    - ${yamlScalar("worker")}`,
        "",
    ].join("\n");
}

function yamlField(field: string, value: string, indentation = 0): string {
    return `${" ".repeat(indentation)}${field}: ${yamlScalar(value)}`;
}

function yamlScalar(value: string): string {
    return JSON.stringify(value);
}
