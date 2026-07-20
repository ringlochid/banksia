import { describe, expect, it } from "vitest";

import { starterBodyForKind } from "../../../src/features/definition-editor/definition-editor-template";

describe("definition editor starter templates", () => {
    it.each(["role", "policy", "workflow"] as const)(
        "emits JSON-compatible YAML scalars for %s drafts",
        (kind) => {
            const key = `quoted-${kind}`;
            const description = 'Scope: preserve # markers, "quotes", and\nnew lines.';
            const body = starterBodyForKind(kind, key, description);
            const parsedScalars = parseGeneratedYamlScalars(body);

            expect(parsedScalars.get("id")).toContain(key);
            expect(parsedScalars.get("description")).toContain(description);
            expect(body).not.toContain(`id: ${key}`);
            expect(body.split("\n")).not.toContain("new lines.");
        },
    );
});

function parseGeneratedYamlScalars(body: string): Map<string, string[]> {
    const valuesByField = new Map<string, string[]>();

    for (const line of body.split("\n")) {
        const trimmedLine = line.trim();
        if (trimmedLine.length === 0 || trimmedLine.endsWith(":")) {
            continue;
        }

        if (trimmedLine.startsWith("- ")) {
            expect(JSON.parse(trimmedLine.slice(2))).toBeTypeOf("string");
            continue;
        }

        const separatorIndex = trimmedLine.indexOf(": ");
        expect(separatorIndex).toBeGreaterThan(0);
        const field = trimmedLine.slice(0, separatorIndex);
        const encodedValue = trimmedLine.slice(separatorIndex + 2);
        if (encodedValue === "[]") {
            expect(JSON.parse(encodedValue)).toEqual([]);
            continue;
        }

        const value = JSON.parse(encodedValue) as unknown;
        expect(value).toBeTypeOf("string");
        const fieldValues = valuesByField.get(field) ?? [];
        fieldValues.push(String(value));
        valuesByField.set(field, fieldValues);
    }

    return valuesByField;
}
