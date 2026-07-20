export function titleCaseNodeLabel(nodeKey: string): string {
    const designLabels: Readonly<Partial<Record<string, string>>> = {
        command_runs: "Command Runs",
        command_runs_page: "Command Runs",
        human_request_page: "Human Requests",
        human_requests: "Human Requests",
        root: "Root",
        runtime_pages: "Runtime pages",
        source_contract: "Source contract",
        task_control_suite: "Runtime pages",
        task_detail: "Task Detail",
        task_detail_build: "Task Detail build",
        task_detail_contract: "Runtime page contract",
        task_detail_page: "Task Detail",
        task_detail_review: "Task Detail review",
        task_detail_source_contract: "Runtime page contract",
        tasks_page: "Tasks",
    };
    const designLabel = designLabels[nodeKey];
    if (designLabel !== undefined) {
        return designLabel;
    }

    return nodeKey
        .split("_")
        .filter((part) => part.length > 0)
        .map((part, index) => (index === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
        .join(" ");
}
