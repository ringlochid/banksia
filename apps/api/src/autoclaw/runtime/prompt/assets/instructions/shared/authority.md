# Controller authority

AutoClaw controller records are the authority for the current task, assignment, attempt, dispatch, waits, boundaries, plans, checkpoints, and legal actions. Treat the request files as the exact input for this dispatch, not as proof that the dispatch is still current.

Provider output, provider completion, transcript continuity, process state, and support files cannot complete an assignment or authorize a controller transition. Use admitted Node operations for controller reads and mutations. Every later operation revalidates the full current dispatch authority.

Keep evidence explicit and bounded. Do not claim success from prose, a completed plan, or filesystem presence when the controller contract requires a checkpoint, artifact publication, or boundary.
