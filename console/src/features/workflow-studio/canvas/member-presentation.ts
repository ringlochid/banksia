import type { NormalizedMember } from "../../../api/types";

export function memberTitle(member: NormalizedMember): string {
    return member.title?.trim() || "Untitled teammate";
}

/**
 * The provider a Member runs on, or null when it uses the installation
 * default. Cards omit the default rather than repeating "Installation default"
 * on every Member — that told the reader nothing and crowded the card.
 */
export function providerSummary(member: NormalizedMember): string | null {
    const provider = member.provider;
    if (provider === undefined || provider === null) {
        return null;
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
