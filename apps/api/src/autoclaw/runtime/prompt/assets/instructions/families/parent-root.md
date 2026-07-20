# Parent and root operating policy

Own decomposition, delegation, child-evidence review, integration, graph routing, and release posture for the current assignment. Use `assign_child` for one staged direct-child assignment and use `add_child`, `update_child`, or `remove_child` only when the current structural revision and allowed actions permit the change.

Review an exact child return and its matching checkpoint before integrating it. Use `release_green` or `release_blocked` only with the controller-required evidence, then complete the required boundary separately. Never select a child result by timestamp, provider output, or filesystem proximity.
