import type { components } from "../../api/generated/openapi";
import {
    ApiNetworkError,
    ApiResponseError,
    type ControllerResponse,
} from "../../api/client";

export type CommandRunCancelReceipt =
    components["schemas"]["CommandRunCancelReceipt"];
export type CommandRunOutputPage =
    components["schemas"]["CommandRunOutputPage"];
export type CommandRunView = components["schemas"]["CommandRunView"];
export type FileReference = components["schemas"]["FileReference"];
export type HumanRequestItemAnswer =
    components["schemas"]["HumanRequestItemAnswer"];
export type HumanRequestResponseInput =
    components["schemas"]["HumanRequestResponseInput"];
export type HumanRequestResponseReceipt =
    components["schemas"]["HumanRequestResponseReceipt"];
export type HumanRequestView = components["schemas"]["HumanRequestView"];
export type ProductAction = components["schemas"]["ProductAction"];
export type TaskControlReceipt = components["schemas"]["TaskControlReceipt"];
export type TaskActivity = components["schemas"]["TaskActivity"];
export type TaskMemberView = components["schemas"]["TaskMemberView"];
export type TaskPlanView = components["schemas"]["TaskPlanView"];
export type TaskResultView = components["schemas"]["TaskResultView"];
export type TaskSearchResponse = components["schemas"]["TaskSearchResponse"];
export type TaskStartReceipt = components["schemas"]["TaskStartReceipt"];
export type TaskStartRequest = components["schemas"]["TaskStartRequest"];
export type TaskView = components["schemas"]["TaskView"];
export type WorkflowSearchItem = components["schemas"]["WorkflowSearchItem"];
export type WorkflowSearchResponse =
    components["schemas"]["WorkflowSearchResponse"];

export interface RunApi {
    searchRuns(
        query?: string,
        cursor?: string | null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskSearchResponse>>;
    searchWorkflows(
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>>;
    startRun(
        request: TaskStartRequest,
    ): Promise<ControllerResponse<TaskStartReceipt>>;
    getRun(
        taskId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskView>>;
    controlRun(
        taskId: string,
        actionId: string,
        confirmed: boolean,
    ): Promise<ControllerResponse<TaskControlReceipt>>;
    respondToHumanRequest(
        taskId: string,
        requestId: string,
        actionId: string,
        input: HumanRequestResponseInput,
    ): Promise<ControllerResponse<HumanRequestResponseReceipt>>;
    cancelCommandRun(
        taskId: string,
        commandId: string,
        actionId: string,
    ): Promise<ControllerResponse<CommandRunCancelReceipt>>;
    getCommandOutput(
        taskId: string,
        commandId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<CommandRunOutputPage>>;
}

export class RunApiClient implements RunApi {
    public constructor(private readonly apiRoot = "/api") {}

    public searchRuns(
        query = "",
        cursor: string | null = null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskSearchResponse>> {
        const parameters = new URLSearchParams();
        if (query !== "") {
            parameters.set("q", query);
        }
        if (cursor !== null) {
            parameters.set("cursor", cursor);
        }
        return this.request(
            `/tasks${querySuffix(parameters)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public searchWorkflows(
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>> {
        return this.request(
            "/workflows",
            signal === undefined ? {} : { signal },
        );
    }

    public startRun(
        request: TaskStartRequest,
    ): Promise<ControllerResponse<TaskStartReceipt>> {
        return this.request("/tasks", jsonRequest("POST", request));
    }

    public getRun(
        taskId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskView>> {
        return this.request(
            `/tasks/${encodeURIComponent(taskId)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public controlRun(
        taskId: string,
        actionId: string,
        confirmed: boolean,
    ): Promise<ControllerResponse<TaskControlReceipt>> {
        return this.request(
            `/tasks/${encodeURIComponent(taskId)}/controls/${encodeURIComponent(actionId)}`,
            jsonRequest("POST", { confirmed }),
        );
    }

    public respondToHumanRequest(
        taskId: string,
        requestId: string,
        actionId: string,
        input: HumanRequestResponseInput,
    ): Promise<ControllerResponse<HumanRequestResponseReceipt>> {
        return this.request(
            `/tasks/${encodeURIComponent(taskId)}/human-requests/${encodeURIComponent(requestId)}/responses`,
            jsonRequest("POST", { action_id: actionId, input }),
        );
    }

    public cancelCommandRun(
        taskId: string,
        commandId: string,
        actionId: string,
    ): Promise<ControllerResponse<CommandRunCancelReceipt>> {
        return this.request(
            `/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(commandId)}/cancel`,
            jsonRequest("POST", {
                action_id: actionId,
                confirmed: true,
            }),
        );
    }

    public getCommandOutput(
        taskId: string,
        commandId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<CommandRunOutputPage>> {
        const parameters = new URLSearchParams({ limit: "4096" });
        return this.request(
            `/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(commandId)}/output?${parameters.toString()}`,
            signal === undefined ? {} : { signal },
        );
    }

    private async request<T>(
        path: string,
        init: RequestInit = {},
    ): Promise<ControllerResponse<T>> {
        let response: Response;
        try {
            response = await fetch(`${this.apiRoot}${path}`, {
                ...init,
                headers: {
                    Accept: "application/json",
                    ...init.headers,
                },
            });
        } catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") {
                throw error;
            }
            throw new ApiNetworkError(error);
        }
        const body = await responseBody(response);
        if (!response.ok) {
            throw new ApiResponseError(response.status, unwrapDetail(body));
        }
        return {
            body: body as T,
            etag: response.headers.get("ETag"),
            status: response.status,
        };
    }
}

function querySuffix(parameters: URLSearchParams): string {
    return parameters.size === 0 ? "" : `?${parameters.toString()}`;
}

function jsonRequest(method: string, body: unknown): RequestInit {
    return {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    };
}

async function responseBody(response: Response): Promise<unknown> {
    if (response.status === 204) {
        return null;
    }
    const text = await response.text();
    if (text === "") {
        return null;
    }
    try {
        return JSON.parse(text) as unknown;
    } catch {
        return text;
    }
}

function unwrapDetail(body: unknown): unknown {
    if (typeof body === "object" && body !== null && "detail" in body) {
        return body.detail;
    }
    return body;
}
