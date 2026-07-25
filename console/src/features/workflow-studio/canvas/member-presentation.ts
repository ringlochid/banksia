import type { NormalizedMember } from "../../../api/types";

export function memberTitle(member: NormalizedMember): string {
    return member.title?.trim() || "Untitled teammate";
}

export function providerSummary(member: NormalizedMember): string {
    const provider = member.provider;
    if (provider === undefined || provider === null) {
        return "Installation default";
    }
    const name =
        provider.kind === "openclaw"
            ? "OpenClaw"
            : provider.kind.charAt(0).toUpperCase() + provider.kind.slice(1);
    if (
        (provider.kind === "codex" || provider.kind === "claude") &&
        provider.model
    ) {
        return `${name} · ${provider.model}`;
    }
    return name;
}
