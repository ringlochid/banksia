import type { components } from "../../api/generated/openapi";
import {
    browserEventSourceFactory,
    requestProductApi,
    resolveProductApiUrl,
    type ControllerResponse,
    type ProductEventSource,
    type ProductEventSourceFactory,
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
export type MemberSteerReceipt = components["schemas"]["MemberSteerReceipt"];
export type ProductAction = components["schemas"]["ProductAction"];
export type TaskControlReceipt = components["schemas"]["TaskControlReceipt"];
export type TaskActivity = components["schemas"]["TaskActivity"];
export type TaskActivityPage = components["schemas"]["TaskActivityPage"];
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
        cursor?: string | null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>>;
    startRun(
        request: TaskStartRequest,
    ): Promise<ControllerResponse<TaskStartReceipt>>;
    getRun(
        taskId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskView>>;
    getRunActivities(
        taskId: string,
        cursor?: string | null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskActivityPage>>;
    openRunActivityStream(
        taskId: string,
        cursor?: string | null,
    ): ProductEventSource;
    controlRun(
        taskId: string,
        actionId: string,
        confirmed: boolean,
    ): Promise<ControllerResponse<TaskControlReceipt>>;
    steerMember(
        taskId: string,
        memberId: string,
        actionId: string,
        message: string,
    ): Promise<ControllerResponse<MemberSteerReceipt>>;
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
    public constructor(
        private readonly apiRoot = "/api",
        private readonly eventSourceFactory: ProductEventSourceFactory = browserEventSourceFactory,
    ) {}

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
        return requestProductApi(
            this.apiRoot,
            `/tasks${querySuffix(parameters)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public searchWorkflows(
        cursor: string | null = null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<WorkflowSearchResponse>> {
        const parameters = new URLSearchParams();
        if (cursor !== null) {
            parameters.set("cursor", cursor);
        }
        return requestProductApi(
            this.apiRoot,
            `/workflows${querySuffix(parameters)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public startRun(
        request: TaskStartRequest,
    ): Promise<ControllerResponse<TaskStartReceipt>> {
        return requestProductApi(
            this.apiRoot,
            "/tasks",
            jsonRequest("POST", request),
        );
    }

    public getRun(
        taskId: string,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskView>> {
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}`,
            signal === undefined ? {} : { signal },
        );
    }

    public getRunActivities(
        taskId: string,
        cursor: string | null = null,
        signal?: AbortSignal,
    ): Promise<ControllerResponse<TaskActivityPage>> {
        const parameters = new URLSearchParams({ limit: "200" });
        if (cursor !== null) {
            parameters.set("cursor", cursor);
        }
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}/activities?${parameters.toString()}`,
            signal === undefined ? {} : { signal },
        );
    }

    public openRunActivityStream(
        taskId: string,
        cursor: string | null = null,
    ): ProductEventSource {
        const parameters = new URLSearchParams();
        if (cursor !== null) {
            parameters.set("cursor", cursor);
        }
        const path = `/tasks/${encodeURIComponent(taskId)}/activities/stream${querySuffix(parameters)}`;
        return this.eventSourceFactory(
            resolveProductApiUrl(this.apiRoot, path),
        );
    }

    public controlRun(
        taskId: string,
        actionId: string,
        confirmed: boolean,
    ): Promise<ControllerResponse<TaskControlReceipt>> {
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}/controls/${encodeURIComponent(actionId)}`,
            jsonRequest("POST", { confirmed }),
        );
    }

    public steerMember(
        taskId: string,
        memberId: string,
        actionId: string,
        message: string,
    ): Promise<ControllerResponse<MemberSteerReceipt>> {
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}/members/${encodeURIComponent(memberId)}/steers`,
            jsonRequest("POST", { action_id: actionId, message }),
        );
    }

    public respondToHumanRequest(
        taskId: string,
        requestId: string,
        actionId: string,
        input: HumanRequestResponseInput,
    ): Promise<ControllerResponse<HumanRequestResponseReceipt>> {
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}/human-requests/${encodeURIComponent(requestId)}/responses`,
            jsonRequest("POST", { action_id: actionId, input }),
        );
    }

    public cancelCommandRun(
        taskId: string,
        commandId: string,
        actionId: string,
    ): Promise<ControllerResponse<CommandRunCancelReceipt>> {
        return requestProductApi(
            this.apiRoot,
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
        return requestProductApi(
            this.apiRoot,
            `/tasks/${encodeURIComponent(taskId)}/command-runs/${encodeURIComponent(commandId)}/output?${parameters.toString()}`,
            signal === undefined ? {} : { signal },
        );
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
