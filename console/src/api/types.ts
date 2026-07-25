import type { components } from "./generated/openapi";

export type AddMemberOperation = components["schemas"]["AddMemberOperation"];
export type CreateWorkflowDraftRequest =
    components["schemas"]["CreateWorkflowDraftRequest"];
export type DraftOperation =
    | components["schemas"]["UpdateWorkflowOperation"]
    | AddMemberOperation
    | components["schemas"]["UpdateMemberOperation"]
    | components["schemas"]["RemoveMemberOperation"];
export type MemberCapabilities = components["schemas"]["MemberCapabilities"];
export type MemberPatch = components["schemas"]["MemberPatch"];
export type NormalizedMember = components["schemas"]["NormalizedMember"];
export type NormalizedWorkflow = components["schemas"]["NormalizedWorkflow"];
export type ProviderSandbox = components["schemas"]["ProviderSandbox"];
export type ProviderSelection =
    | components["schemas"]["CodexProviderSelection"]
    | components["schemas"]["ClaudeProviderSelection"]
    | components["schemas"]["OpenClawProviderSelection"];
export type WorkflowAuthoringOptions =
    components["schemas"]["WorkflowAuthoringOptions"];
export type WorkflowDraftDiscardResult =
    components["schemas"]["WorkflowDraftDiscardResult"];
export type WorkflowDraftMutationResult =
    components["schemas"]["WorkflowDraftMutationResult"];
export type WorkflowDraftOpenResult =
    components["schemas"]["WorkflowDraftOpenResult"];
export type WorkflowDraftReadback =
    components["schemas"]["WorkflowDraftReadback"];
export type WorkflowDraftValidationResult =
    components["schemas"]["WorkflowDraftValidationResult"];
export type WorkflowGetResponse = components["schemas"]["WorkflowGetResponse"];
export type WorkflowPublishedReadback =
    components["schemas"]["WorkflowPublishedReadback"];
export type WorkflowSearchItem = components["schemas"]["WorkflowSearchItem"];
export type WorkflowSearchResponse =
    components["schemas"]["WorkflowSearchResponse"];
export type WorkflowStaleDraftResponse =
    components["schemas"]["WorkflowStaleDraftResponse"];
export type WorkflowValidationIssue =
    components["schemas"]["WorkflowValidationIssue"];
