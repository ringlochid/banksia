export type ClassValue = false | null | string | undefined;

export function classNames(...values: readonly ClassValue[]): string {
    return values
        .filter((value): value is string => typeof value === "string" && value.length > 0)
        .join(" ");
}
