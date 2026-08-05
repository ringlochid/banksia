import { RotateCw } from "lucide-react";
import { Link, useRouteError } from "react-router";

import { Button, PageState } from "../components/ui";

export function RouteErrorPage() {
    const error = useRouteError();
    reportRouteError(error);

    return (
        <section className="page">
            <div className="page__body">
                <PageState
                    actions={
                        <>
                            <Button onClick={() => window.location.reload()}>
                                <RotateCw aria-hidden="true" size={16} />
                                Reload
                            </Button>
                            <Link
                                className="ui-button ui-button--quiet"
                                to="/workflows"
                            >
                                Open Workflows
                            </Link>
                        </>
                    }
                    detail="Your data is still in the controller. Reload this page, or return to Workflows."
                    fill
                    kind="error"
                    title="This page stopped working"
                />
            </div>
        </section>
    );
}

function reportRouteError(error: unknown): void {
    if (import.meta.env.DEV) {
        console.error("Banksia route render failed", error);
    }
}
