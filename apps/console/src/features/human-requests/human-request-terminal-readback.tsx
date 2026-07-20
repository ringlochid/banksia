import { CodeBlock, IdRefText, PropertyGrid, Surface, TimestampText } from "../../components/ui";
import type { components } from "../../api/generated/openapi";

type HumanRequestRead = components["schemas"]["HumanRequestRead"];
type HumanRequestResolution = components["schemas"]["HumanRequestResolution"];
type HumanRequestStatus = components["schemas"]["HumanRequestStatus"];

export function TerminalReadback({ read }: { readonly read: HumanRequestRead }) {
    const resolution = read.resolution ?? null;

    return (
        <Surface label="Terminal readback" title={terminalTitle(read.request.status, resolution)}>
            {resolution === null ? (
                <p className="text-compact text-muted">
                    The request is terminal, but the list response did not include resolution
                    detail.
                </p>
            ) : (
                <ResolutionReadback resolution={resolution} />
            )}
        </Surface>
    );
}

function ResolutionReadback({ resolution }: { readonly resolution: HumanRequestResolution }) {
    const itemResponses = Object.entries(resolution.item_responses ?? {});

    return (
        <div className="space-y-4">
            <PropertyGrid
                items={[
                    {
                        label: "Resolution kind",
                        value: resolution.resolution_kind,
                    },
                    {
                        label: "Resolved",
                        value: <TimestampText value={resolution.resolved_at} />,
                    },
                    {
                        label: "Resolved by",
                        value: resolution.resolved_by_actor_ref ?? "Controller",
                    },
                    {
                        label: "Resolution surface",
                        value: resolution.resolved_by_surface,
                    },
                ]}
            />
            <p className="text-compact text-foreground">{resolution.summary}</p>
            {itemResponses.length === 0 ? (
                <p className="text-compact text-muted">
                    No item responses were persisted for this terminal outcome.
                </p>
            ) : (
                <ol className="space-y-2">
                    {itemResponses.map(([itemId, response]) => (
                        <li
                            className="rounded-card border border-outline-soft bg-surface-low p-3"
                            key={itemId}
                        >
                            <IdRefText value={itemId} />
                            <CodeBlock className="mt-3" title="Response">
                                {formatJson(response)}
                            </CodeBlock>
                        </li>
                    ))}
                </ol>
            )}
            {resolution.policy_basis == null ? null : (
                <CodeBlock title="Policy basis">{formatJson(resolution.policy_basis)}</CodeBlock>
            )}
        </div>
    );
}

function terminalTitle(
    status: HumanRequestStatus,
    resolution: HumanRequestResolution | null,
): string {
    if (resolution?.resolution_kind === "answered" || status === "resolved") {
        return "Resolved request";
    }
    if (resolution?.resolution_kind === "timed_out" || status === "timed_out") {
        return "Timed out request";
    }
    if (resolution?.resolution_kind === "cancelled" || status === "cancelled") {
        return "Cancelled request";
    }
    return "Terminal request";
}

function formatJson(value: unknown): string {
    return JSON.stringify(value, null, 2);
}
