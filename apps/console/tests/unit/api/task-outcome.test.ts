import { describe, expect, it } from "vitest";

import { taskOutcome } from "../../../src/api/task-outcome";

describe("taskOutcome", () => {
    it("renders completed green as Completed", () => {
        expect(taskOutcome("completed", "green")).toEqual({
            isBlocked: false,
            isTerminal: true,
            label: "Completed",
            tone: "success",
        });
    });

    it("renders completed blocked as Blocked with a danger tone", () => {
        expect(taskOutcome("completed", "blocked")).toEqual({
            isBlocked: true,
            isTerminal: true,
            label: "Blocked",
            tone: "danger",
        });
    });

    it("keeps completed without an outcome as Completed for older controllers", () => {
        expect(taskOutcome("completed", null).label).toBe("Completed");
        expect(taskOutcome("completed", undefined).label).toBe("Completed");
    });

    it("maps non-terminal lifecycles without consulting the outcome", () => {
        expect(taskOutcome("running", null)).toMatchObject({ label: "Running", tone: "active" });
        expect(taskOutcome("paused", null)).toMatchObject({ label: "Paused", tone: "warning" });
        expect(taskOutcome("pending", null)).toMatchObject({ label: "Pending", tone: "neutral" });
        expect(taskOutcome("cancelled", null)).toMatchObject({
            label: "Cancelled",
            tone: "neutral",
        });
    });
});
