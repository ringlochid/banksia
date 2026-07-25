import { ApiNetworkError, ApiResponseError } from "../../../api/client";
import type { DraftOperation } from "../../../api/types";
import type {
    StudioRecovery,
    StudioSaveState,
    StudioStructuralSelectionBasis,
    StudioValidationIssue,
} from "./contracts";
import { operationValidationTarget } from "./validation";

export type DraftFailure =
    | {
          readonly kind: "conflict";
          readonly message: string;
          readonly current: NonNullable<
              ReturnType<ApiResponseError["staleDraft"]>
          >["detail"]["current"];
          readonly selectionBasis: StudioStructuralSelectionBasis | null;
      }
    | {
          readonly kind: "recoverable";
          readonly recovery: Exclude<StudioRecovery, null>;
          readonly save: StudioSaveState;
          readonly fieldIssue: StudioValidationIssue | null;
      };

export function mapDraftFailure(
    error: unknown,
    fallback: string,
    requestedRecovery: Exclude<StudioRecovery, null>,
    operation?: DraftOperation,
): DraftFailure {
    if (error instanceof ApiResponseError) {
        const stale = error.staleDraft();
        if (stale !== null) {
            return {
                kind: "conflict",
                message: stale.detail.message,
                current: stale.detail.current,
                selectionBasis: structuralSelectionBasis(requestedRecovery),
            };
        }
    }
    return {
        kind: "recoverable",
        recovery:
            error instanceof ApiResponseError && error.status === 428
                ? reloadRecovery(requestedRecovery)
                : requestedRecovery,
        save:
            error instanceof ApiNetworkError
                ? { kind: "offline", message: error.message }
                : {
                      kind: "failed",
                      message: draftErrorMessage(error, fallback),
                  },
        fieldIssue:
            error instanceof ApiResponseError
                ? operationFieldIssue(error, operation)
                : null,
    };
}

function reloadRecovery(
    requestedRecovery: Exclude<StudioRecovery, null>,
): Exclude<StudioRecovery, null> {
    const selectionBasis = structuralSelectionBasis(requestedRecovery);
    return selectionBasis === null
        ? { kind: "reload_current" }
        : { kind: "reload_current", selectionBasis };
}

function structuralSelectionBasis(
    recovery: Exclude<StudioRecovery, null>,
): StudioStructuralSelectionBasis | null {
    return "selectionBasis" in recovery
        ? (recovery.selectionBasis ?? null)
        : null;
}

export function draftErrorMessage(error: unknown, fallback: string): string {
    return error instanceof Error && error.message !== ""
        ? error.message
        : fallback;
}

function operationFieldIssue(
    error: ApiResponseError,
    operation: DraftOperation | undefined,
): StudioValidationIssue | null {
    const fieldPath = operationFailureFieldPath(error.body);
    if (fieldPath === null) {
        return null;
    }
    const target =
        operation === undefined
            ? null
            : operationValidationTarget(operation, fieldPath);
    return {
        source: "controller",
        path: fieldPath,
        message: error.message,
        ...(target === null ? {} : { target }),
    };
}

function operationFailureFieldPath(body: unknown): string | null {
    if (typeof body !== "object" || body === null || !("field_path" in body)) {
        return null;
    }
    const fieldPath = body.field_path;
    return typeof fieldPath === "string" && fieldPath !== "" ? fieldPath : null;
}
