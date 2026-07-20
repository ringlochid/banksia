import { PageFrame } from "./PageFrame";
import {
    CodeBlock,
    Disclosure,
    ListRow,
    PropertyGrid,
    StatePanel,
    StatusChip,
    Surface,
} from "../ui";

export interface RouteScaffoldProps {
    readonly backingSurfaces: readonly string[];
    readonly eyebrow: string;
    readonly title: string;
}

export function RouteScaffold({ backingSurfaces, eyebrow, title }: RouteScaffoldProps) {
    return (
        <PageFrame
            actions={<StatusChip tone="neutral">Page slice pending</StatusChip>}
            eyebrow={eyebrow}
            title={title}
        >
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
                <Surface label="Route" title="Foundation state">
                    <div className="space-y-4">
                        <StatePanel
                            summary="The shared shell, layout, and primitives are available here before the page-owned API workflow lands."
                            title="Reserved for page implementation"
                            tone="empty"
                        />
                        <PropertyGrid
                            items={[
                                {
                                    label: "Route",
                                    value: title,
                                },
                                {
                                    label: "Surface",
                                    value: eyebrow,
                                },
                                {
                                    label: "Claim",
                                    value: "No page workflow release",
                                },
                            ]}
                        />
                        <Disclosure label="Boundary" open title="Scope guard">
                            <p className="text-compact text-muted">
                                This scaffold may expose shared shell and primitive states only.
                                API-backed page behavior belongs to a later reviewed page slice.
                            </p>
                        </Disclosure>
                    </div>
                </Surface>
                <Surface label="Contract" title="Backing surfaces">
                    <div className="space-y-3">
                        {backingSurfaces.map((surface) => (
                            <ListRow
                                description={<CodeBlock>{surface}</CodeBlock>}
                                key={surface}
                                title="Controller route"
                            />
                        ))}
                    </div>
                </Surface>
            </div>
        </PageFrame>
    );
}
