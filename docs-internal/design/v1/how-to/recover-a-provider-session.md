# Recover a provider session

Status: Reference

This page describes the intended provider-session recovery path.

## Procedure

1. Confirm that the boundary is session loss, not dependency wait or whole-flow operator pause.
2. Use the provider recovery hook for the current dispatch and current continuity context recorded by controller/DB truth.
3. If recovery succeeds, resume only the same assignment/attempt continuity path the controller already selected; do not invent a new assignment during transport recovery.
4. If recovery fails, escalate through controller/watchdog logic rather than auto-minting a new attempt.
5. Do not redefine assignment or subtree scope during provider-session recovery.

## Use these owner pages

- [OpenClaw session lifecycle](../architecture/openclaw-session-lifecycle.md)
- [OpenClaw continuity and send modes](../architecture/openclaw-continuity-and-send-modes.md)
- [Watchdog and provider recovery](../architecture/watchdog-and-provider-recovery.md)
