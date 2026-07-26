import type { components } from "../../api/generated/openapi";
import { requestProductApi, type ControllerResponse } from "../../api/client";

export type OperatorAnswerQuestionSetAction =
    components["schemas"]["OperatorAnswerQuestionSetAction"];
export type OperatorAssistantQuestionSetEntry =
    components["schemas"]["OperatorAssistantQuestionSetEntry"];
export type OperatorConversationAction =
    components["schemas"]["OperatorConversationAction"];
export type OperatorConversationEntry =
    components["schemas"]["OperatorConversationEntry"];
export type OperatorConversationPage =
    components["schemas"]["OperatorConversationPage"];
export type OperatorConversationSummary =
    components["schemas"]["OperatorConversationSummary"];
export type OperatorConversationView =
    components["schemas"]["OperatorConversationView"];
export type OperatorQuestion = components["schemas"]["OperatorQuestion"];
export type OperatorQuestionAnswer =
    components["schemas"]["OperatorQuestionAnswer"];
export type OperatorStatusResponse =
    components["schemas"]["OperatorStatusResponse"];
export type OperatorUserQuestionAnswersEntry =
    components["schemas"]["OperatorUserQuestionAnswersEntry"];

export interface OperatorApi {
    getStatus(): Promise<ControllerResponse<OperatorStatusResponse>>;
    listConversations(): Promise<ControllerResponse<OperatorConversationPage>>;
    createConversation(
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>>;
    getConversation(
        conversationId: string,
    ): Promise<ControllerResponse<OperatorConversationView>>;
    sendMessage(
        href: string,
        text: string,
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>>;
    answerQuestions(
        href: string,
        answers: OperatorQuestionAnswer[],
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>>;
}

export class OperatorApiClient implements OperatorApi {
    public constructor(private readonly apiRoot = "/api") {}

    public getStatus(): Promise<ControllerResponse<OperatorStatusResponse>> {
        return requestProductApi(this.apiRoot, "/operator/status");
    }

    public listConversations(): Promise<
        ControllerResponse<OperatorConversationPage>
    > {
        return requestProductApi(this.apiRoot, "/operator/conversations");
    }

    public createConversation(
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>> {
        return requestProductApi(
            this.apiRoot,
            "/operator/conversations",
            jsonPost({}, idempotencyKey),
        );
    }

    public getConversation(
        conversationId: string,
    ): Promise<ControllerResponse<OperatorConversationView>> {
        return requestProductApi(
            this.apiRoot,
            `/operator/conversations/${encodeURIComponent(conversationId)}`,
        );
    }

    public sendMessage(
        href: string,
        text: string,
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>> {
        return requestProductApi(
            this.apiRoot,
            href,
            jsonPost({ text }, idempotencyKey),
        );
    }

    public answerQuestions(
        href: string,
        answers: OperatorQuestionAnswer[],
        idempotencyKey: string,
    ): Promise<ControllerResponse<OperatorConversationView>> {
        return requestProductApi(
            this.apiRoot,
            href,
            jsonPost({ answers }, idempotencyKey),
        );
    }
}

function jsonPost(body: unknown, idempotencyKey: string): RequestInit {
    return {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(body),
    };
}
