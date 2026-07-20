# Watchdog And Provider Recovery

Status: Reference

> **V2 supersession notice:** This page remains V1 provider-recovery routing. V2 recovery, the six-call control retry policy, and the two-restart budget are owned by [Runtime lifecycle and watchdog](../../v2/architecture/runtime-lifecycle-and-watchdog.md); provider events no longer affect watchdog truth.

## Purpose

This page routes provider-specific recovery questions to the live v1 watchdog, observability, and OpenClaw transport owner pages.

## Core Reminder

Provider transport recovery is not assignment truth. Watchdog reads controller/DB truth first, classifies delivery/liveness incidents on one dispatch path, and treats `_runtime/dispatch/<dispatch_id>/` files as observability projections only.

Foreground control owns the initial `launching`, `abort_requested`, `ambiguous`, and fenced decisions. Watchdog inspects those persisted facts later; it does not replace the first-pass inactivity proof needed for safe redispatch.

## Canonical Recovery Actions

Automatic recovery chooses only:

- `redispatch_same_attempt`
- `escalate`

Rules:

- `redispatch_same_attempt` keeps the same assignment and same attempt
- `escalate` stops automatic redispatch and returns control to higher-owner or operator handling
- any retained `same_session_continue` detail is compatibility debt only and not the live redispatch model; delete it when cleanup reaches the prompt and transport residue
- delivery, continuity, watchdog, and provider-event refs stay in the shared `support_runtime_file_ref` family and remain observability/operator-only

## Go Deeper

- [Watchdog and recovery contract](watchdog-and-recovery-contract.md)
- [Runtime observability and boundary log](runtime-observability-and-boundary-log.md)
- [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md)
- [OpenClaw worker and gateway contract](openclaw-worker-and-gateway-contract.md)
