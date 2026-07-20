import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { PageFrame } from "../../components/layout";
import { DefinitionDetailPanel } from "./DefinitionDetailPanel";
import { DefinitionListPanel, DefinitionsHeaderControls } from "./DefinitionListPanel";
import { useDefinitionsController } from "./definition-controller";

export function DefinitionsPage() {
    const controller = useDefinitionsController();

    return (
        <PageFrame
            actions={
                <div className="flex flex-wrap items-center gap-2">
                    <DefinitionsNavLink to="/definitions/editor">
                        Definition Editor
                    </DefinitionsNavLink>
                    <DefinitionsNavLink to="/task-start">Task Start</DefinitionsNavLink>
                </div>
            }
            eyebrow="Authoring"
            headerContent={<DefinitionsHeaderControls controller={controller} />}
            title="Definitions"
        >
            <div className="grid min-w-0 gap-3 border-t border-outline-soft pt-3 xl:grid-cols-[minmax(22rem,0.78fr)_minmax(0,1.12fr)]">
                <section
                    aria-labelledby="definitions-list-heading"
                    className="min-w-0 overflow-hidden rounded-card border border-outline-soft bg-surface-low"
                >
                    <DefinitionListPanel controller={controller} />
                </section>
                <section
                    aria-labelledby="definitions-detail-heading"
                    className="min-w-0 rounded-card border border-outline-soft bg-surface-low"
                >
                    <DefinitionDetailPanel controller={controller} />
                </section>
            </div>
        </PageFrame>
    );
}

function DefinitionsNavLink({ children, to }: { readonly children: string; readonly to: string }) {
    return (
        <Link
            className="inline-flex h-control items-center justify-center gap-2 rounded-control border border-outline bg-surface-low px-3 text-utility font-semibold text-foreground transition-colors hover:border-primary/45 hover:text-primary-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            to={to}
        >
            <span className="min-w-0 truncate">{children}</span>
            <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
        </Link>
    );
}
