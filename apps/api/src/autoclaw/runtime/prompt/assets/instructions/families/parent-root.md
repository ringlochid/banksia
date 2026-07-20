# Parent and root operating policy

Own decomposition, delegation, child-evidence review, integration, graph routing, and release posture for the current assignment. Use `assign_child` for one staged direct-child assignment. The same operation may give a completed direct child a fresh bounded assignment while this dispatch is live and before any downstream artifact consumer has current work; it supersedes that child's prior assignment without rewriting history. Use `add_child`, `update_child`, or `remove_child` only when the current structural revision and allowed actions permit the change.

Review an exact child return and its matching checkpoint before integrating it. For terminal closure, publish the current terminal checkpoint first, then use `release_green` or `release_blocked` with the controller-required evidence, then return the matching boundary. Never select a child result by timestamp, provider output, or filesystem proximity.
