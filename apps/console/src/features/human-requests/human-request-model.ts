import type { components } from "../../api/generated/openapi";

type HumanRequestItem = components["schemas"]["HumanRequestItem"];
type HumanRequestRead = components["schemas"]["HumanRequestRead"];
type HumanRequestResolveRequest = components["schemas"]["HumanRequestResolveRequest"];
type JsonValue = components["schemas"]["JsonValue"];
type PendingHumanRequest = components["schemas"]["PendingHumanRequest"];

export type StructuredFieldType = "boolean" | "integer" | "number" | "string";

export interface HumanRequestQueueItem {
    readonly assignmentId: string;
    readonly attemptId: string;
    readonly dueAt: string | null;
    readonly flowId: string;
    readonly itemCount: number;
    readonly kind: components["schemas"]["HumanRequestKind"];
    readonly openedAt: string;
    readonly requestId: string;
    readonly sourceDispatchId: string;
    readonly status: components["schemas"]["HumanRequestStatus"];
    readonly summary: string;
}

export interface HumanRequestItemDraft {
    readonly responseFields: Readonly<Partial<Record<string, string>>>;
    readonly responseJson: string;
    readonly selectedOption: string | null;
}

export interface HumanRequestDraft {
    readonly items: Readonly<Record<string, HumanRequestItemDraft>>;
}

export interface StructuredSchemaField {
    readonly name: string;
    readonly required: boolean;
    readonly title: string;
    readonly type: StructuredFieldType;
}

export interface StructuredSchemaModel {
    readonly fields: readonly StructuredSchemaField[];
    readonly mode: "fields" | "json";
}

export interface HumanRequestValidationError {
    readonly itemId: string;
    readonly message: string;
}

export interface HumanRequestResolveBuildResult {
    readonly errors: readonly HumanRequestValidationError[];
    readonly request: HumanRequestResolveRequest | null;
}

export function mapHumanRequestQueueItem(read: HumanRequestRead): HumanRequestQueueItem {
    const { request } = read;
    return {
        assignmentId: request.assignment_id,
        attemptId: request.attempt_id,
        dueAt: request.timeout?.due_at ?? null,
        flowId: request.flow_id,
        itemCount: request.items.length,
        kind: request.kind,
        openedAt: request.opened_at,
        requestId: request.request_id,
        sourceDispatchId: request.source_dispatch_id,
        status: request.status,
        summary: request.summary,
    };
}

export function createDraftForRequest(request: PendingHumanRequest): HumanRequestDraft {
    return {
        items: Object.fromEntries(request.items.map((item) => [item.id, createDraftForItem(item)])),
    };
}

export function buildResolveRequest(
    request: PendingHumanRequest,
    draft: HumanRequestDraft | undefined,
): HumanRequestResolveBuildResult {
    const errors: HumanRequestValidationError[] = [];
    const itemResponses: Record<string, JsonValue> = {};

    for (const item of request.items) {
        const itemDraft = draft?.items[item.id] ?? createDraftForItem(item);
        const options = item.options ?? null;

        if (options !== null) {
            const selectedOption = itemDraft.selectedOption;
            if (selectedOption === null) {
                errors.push({
                    itemId: item.id,
                    message: "Choose one response option for this item.",
                });
                continue;
            }
            if (!options.some((option) => option.id === selectedOption)) {
                errors.push({
                    itemId: item.id,
                    message: "Selected option is not available for this request item.",
                });
                continue;
            }

            itemResponses[item.id] = selectedOption;
            continue;
        }

        const response = readSchemaResponse(item, itemDraft, errors);
        if (response.ok) {
            itemResponses[item.id] = response.value;
        }
    }

    if (errors.length > 0) {
        return { errors, request: null };
    }

    return {
        errors: [],
        request: {
            item_responses: itemResponses,
        },
    };
}

export function getStructuredSchemaModel(item: HumanRequestItem): StructuredSchemaModel | null {
    const schema = item.response_schema;
    if (!isRecord(schema)) {
        return null;
    }

    const properties = isRecord(schema.properties) ? schema.properties : null;
    if (schema.type !== "object" || properties === null) {
        return { fields: [], mode: "json" };
    }

    const propertyEntries = Object.entries(properties);
    if (propertyEntries.length === 0) {
        return { fields: [], mode: "json" };
    }

    const requiredFields = Array.isArray(schema.required)
        ? new Set(schema.required.filter((value): value is string => typeof value === "string"))
        : new Set<string>();
    const fields: StructuredSchemaField[] = [];
    for (const [name, propertySchema] of propertyEntries) {
        if (!isRecord(propertySchema) || !isSupportedFieldType(propertySchema.type)) {
            return { fields: [], mode: "json" };
        }
        fields.push({
            name,
            required: requiredFields.has(name),
            title:
                typeof propertySchema.title === "string"
                    ? propertySchema.title
                    : labelFromName(name),
            type: propertySchema.type,
        });
    }

    return { fields, mode: "fields" };
}

export function isRequestEditable(read: HumanRequestRead): boolean {
    return read.request.status === "open" && read.resolution == null;
}

export function labelFromKind(kind: components["schemas"]["HumanRequestKind"]): string {
    switch (kind) {
        case "approval":
            return "Approval";
        case "direction":
            return "Direction";
        case "input":
            return "Input";
        case "review":
            return "Review";
    }
}

function createDraftForItem(item: HumanRequestItem): HumanRequestItemDraft {
    const schemaModel = getStructuredSchemaModel(item);
    return {
        responseFields: Object.fromEntries(
            (schemaModel?.fields ?? []).map((field) => [field.name, ""]),
        ),
        responseJson: initialJsonResponse(item),
        selectedOption: null,
    };
}

function initialJsonResponse(item: HumanRequestItem): string {
    if (item.options != null || item.response_schema == null) {
        return "";
    }
    return item.response_schema.type === "object" ? "{}" : "";
}

function readSchemaResponse(
    item: HumanRequestItem,
    itemDraft: HumanRequestItemDraft,
    errors: HumanRequestValidationError[],
): { readonly ok: true; readonly value: JsonValue } | { readonly ok: false } {
    const schemaModel = getStructuredSchemaModel(item);
    if (schemaModel === null) {
        errors.push({
            itemId: item.id,
            message: "This request item is missing its response contract.",
        });
        return { ok: false };
    }

    if (schemaModel.mode === "json") {
        return readJsonResponse(item.id, itemDraft.responseJson, errors);
    }

    const response: Record<string, JsonValue> = {};
    let isValid = true;
    for (const field of schemaModel.fields) {
        const rawValue = (itemDraft.responseFields[field.name] ?? "").trim();
        if (rawValue.length === 0) {
            if (field.required) {
                errors.push({
                    itemId: item.id,
                    message: `${field.title} is required.`,
                });
                isValid = false;
            }
            continue;
        }

        const parsedValue = parseStructuredFieldValue(field, rawValue);
        if (parsedValue.ok) {
            response[field.name] = parsedValue.value;
            continue;
        }

        errors.push({
            itemId: item.id,
            message: parsedValue.message,
        });
        isValid = false;
    }

    return isValid ? { ok: true, value: response } : { ok: false };
}

function readJsonResponse(
    itemId: string,
    rawJson: string,
    errors: HumanRequestValidationError[],
): { readonly ok: true; readonly value: JsonValue } | { readonly ok: false } {
    const trimmedJson = rawJson.trim();
    if (trimmedJson.length === 0) {
        errors.push({
            itemId,
            message: "Provide a JSON response for this item.",
        });
        return { ok: false };
    }

    try {
        return { ok: true, value: JSON.parse(trimmedJson) };
    } catch {
        errors.push({
            itemId,
            message: "Response must be valid JSON.",
        });
        return { ok: false };
    }
}

function parseStructuredFieldValue(
    field: StructuredSchemaField,
    rawValue: string,
):
    | { readonly ok: true; readonly value: boolean | number | string }
    | { readonly ok: false; readonly message: string } {
    switch (field.type) {
        case "boolean":
            if (rawValue === "true") {
                return { ok: true, value: true };
            }
            if (rawValue === "false") {
                return { ok: true, value: false };
            }
            return { ok: false, message: `${field.title} must be true or false.` };
        case "integer": {
            const numberValue = Number(rawValue);
            if (Number.isInteger(numberValue)) {
                return { ok: true, value: numberValue };
            }
            return { ok: false, message: `${field.title} must be an integer.` };
        }
        case "number": {
            const numberValue = Number(rawValue);
            if (Number.isFinite(numberValue)) {
                return { ok: true, value: numberValue };
            }
            return { ok: false, message: `${field.title} must be a number.` };
        }
        case "string":
            return { ok: true, value: rawValue };
    }
}

function labelFromName(name: string): string {
    return name
        .split("_")
        .filter((part) => part.length > 0)
        .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
        .join(" ");
}

function isSupportedFieldType(value: unknown): value is StructuredFieldType {
    return value === "boolean" || value === "integer" || value === "number" || value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
