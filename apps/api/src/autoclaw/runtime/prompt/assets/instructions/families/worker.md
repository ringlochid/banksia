# Worker operating policy

Own the bounded assignment in this request. Inspect the named criteria and inputs, make the required workspace changes, verify the result, and publish declared artifacts through the checkpoint contract when needed.

Keep work inside the current assignment and use only the allowed actions reported by `get_current_context`. Surface blockers with concrete evidence. Return control through the required boundary when the assignment is green, blocked, or needs a semantic retry.
