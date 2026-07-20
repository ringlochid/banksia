import {
    CheckCircle2,
    ChevronRight,
    ExternalLink,
    Pause,
    Play,
    RefreshCw,
    Trash2,
    X,
} from "lucide-react";
import { useState } from "react";

import { PageFrame } from "../components/layout";
import {
    Button,
    CodeBlock,
    Disclosure,
    FocusedDetailShell,
    FormField,
    IconButton,
    IdRefText,
    ListRow,
    PropertyGrid,
    SegmentedControl,
    StatePanel,
    StatusChip,
    Surface,
    Tabs,
    TimestampText,
} from "../components/ui";

type FixtureDetailView = "overview" | "checkpoint" | "trace";

export function FixtureGalleryPage() {
    const [detailView, setDetailView] = useState<FixtureDetailView>("overview");

    return (
        <PageFrame eyebrow="Internal" title="Fixture Gallery">
            <div className="grid gap-4 xl:grid-cols-2">
                <Surface label="Controls" title="Buttons">
                    <div className="space-y-4">
                        <div className="flex flex-wrap gap-3">
                            <Button icon={<Play className="size-4" />} variant="primary">
                                Primary
                            </Button>
                            <Button icon={<Pause className="size-4" />}>Secondary</Button>
                            <Button icon={<Trash2 className="size-4" />} variant="danger">
                                Danger
                            </Button>
                            <Button variant="ghost">Ghost</Button>
                            <IconButton icon={<RefreshCw className="size-4" />} label="Refresh" />
                        </div>
                        <SegmentedControl
                            label="Definition kind"
                            onChange={() => undefined}
                            options={[
                                { label: "Roles", value: "roles" },
                                { label: "Policies", value: "policies" },
                                { label: "Workflows", value: "workflows" },
                            ]}
                            value="roles"
                        />
                        <Tabs
                            label="Detail views"
                            onChange={setDetailView}
                            tabs={[
                                { label: "Overview", panelId: "overview-panel", value: "overview" },
                                {
                                    label: "Checkpoint",
                                    panelId: "checkpoint-panel",
                                    value: "checkpoint",
                                },
                                { label: "Trace", panelId: "trace-panel", value: "trace" },
                            ]}
                            value={detailView}
                        />
                    </div>
                </Surface>
                <Surface label="State" title="Status chips">
                    <div className="space-y-4">
                        <div className="flex flex-wrap gap-2">
                            <StatusChip tone="active" withDot>
                                running
                            </StatusChip>
                            <StatusChip tone="success" withDot>
                                ready
                            </StatusChip>
                            <StatusChip tone="warning" withDot>
                                waiting
                            </StatusChip>
                            <StatusChip tone="danger" withDot>
                                blocked
                            </StatusChip>
                            <StatusChip>quiet</StatusChip>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2">
                            <StatePanel
                                summary="No rows match the current view."
                                title="No results"
                                tone="empty"
                            />
                            <StatePanel
                                summary="Reread current task truth before retrying."
                                title="Stale action"
                                tone="stale"
                            />
                        </div>
                    </div>
                </Surface>
                <Surface label="Rows" title="List and disclosure">
                    <div className="space-y-3">
                        <ListRow
                            action={
                                <Button icon={<ChevronRight className="size-4" />}>Open</Button>
                            }
                            description="Update shell labels without widening the page slice."
                            meta={
                                <>
                                    <IdRefText value="runtime_copy_refresh" />
                                    <TimestampText value="2026-06-29T15:00:00Z" />
                                </>
                            }
                            selected
                            status={<StatusChip tone="active">running</StatusChip>}
                            title="Refresh runtime route copy"
                        />
                        <Disclosure label="Log" open title="Command output">
                            <CodeBlock title="Latest summary">
                                timeout 120s make console-test
                            </CodeBlock>
                        </Disclosure>
                    </div>
                </Surface>
                <Surface label="Forms" title="Field grammar">
                    <div className="space-y-4">
                        <FormField
                            hint="Stored workflow keys come from controller truth."
                            id="workflow-search"
                            label="Workflow search"
                        >
                            <input
                                className="h-control w-full border border-outline bg-surface-low px-3 text-compact"
                                placeholder="Search workflows"
                                type="search"
                            />
                        </FormField>
                        <PropertyGrid
                            items={[
                                { label: "Kind", value: "workflow" },
                                { label: "Revision", value: "current stored" },
                                {
                                    label: "Ref",
                                    value: <IdRefText value="frontend_console_full_delivery" />,
                                },
                            ]}
                        />
                    </div>
                </Surface>
                <Surface
                    actions={<StatusChip tone="success">green</StatusChip>}
                    className="xl:col-span-2"
                    label="Focused detail"
                    title="Selected context"
                >
                    <FocusedDetailShell
                        actions={
                            <IconButton icon={<X className="size-4" />} label="Close detail" />
                        }
                        label="Inspector"
                        title="Checkpoint"
                    >
                        <div className="grid gap-3 lg:grid-cols-3">
                            {["Overview", "Assignment", "Artifacts"].map((item) => (
                                <div
                                    className="rounded-md border border-outline-soft bg-surface-muted p-3"
                                    key={item}
                                >
                                    <CheckCircle2
                                        aria-hidden="true"
                                        className="mb-3 size-4 text-primary"
                                    />
                                    <p className="font-display text-compact font-semibold">
                                        {item}
                                    </p>
                                    <p className="mt-1 font-mono text-label text-muted">
                                        selected context
                                    </p>
                                </div>
                            ))}
                        </div>
                        <div className="mt-4">
                            <Button icon={<ExternalLink className="size-4" />}>Open sibling</Button>
                        </div>
                    </FocusedDetailShell>
                </Surface>
            </div>
        </PageFrame>
    );
}
