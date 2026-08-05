import { dump } from "js-yaml";

import type { NormalizedWorkflow } from "../../api/types";

const YAML_MIME_TYPE = "application/yaml;charset=utf-8";

export function renderWorkflowYaml(workflow: NormalizedWorkflow): string {
    const payload = JSON.parse(
        JSON.stringify(workflow, (_key, value: unknown) =>
            value === null ? undefined : value,
        ),
    ) as object;
    const rendered = dump(payload, {
        lineWidth: -1,
        noRefs: true,
        sortKeys: false,
    });
    return rendered.endsWith("\n") ? rendered : `${rendered}\n`;
}

export function downloadWorkflowYaml(workflow: NormalizedWorkflow): void {
    const blobUrl = URL.createObjectURL(
        new Blob([renderWorkflowYaml(workflow)], { type: YAML_MIME_TYPE }),
    );
    const link = document.createElement("a");
    link.download = `${workflow.id}.yaml`;
    link.href = blobUrl;
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
}
