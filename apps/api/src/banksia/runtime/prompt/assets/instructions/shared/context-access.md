# Context access

Begin by calling `get_current_context` once for coherent current controller truth. Use its allowed actions, capabilities, live workflow neighborhood, and logical refs rather than inferring currentness from provider history or nearby files. Its readback refs are task-relative logical paths. When `checkpoint_to_resume_from` is non-null, call `read_file(path=checkpoint_to_resume_from)` before acting. If that support projection is missing or unreadable, or the optional current fields are null, call `read_file(path=readback_refs.input)` for the complete dispatch-start trigger and resume detail.

Use `list_files` for a bounded one-level logical listing and `read_file` for bounded UTF-8 reads. Paths are task-relative and begin with `workspace`, `outputs`, `tmp`, or `_runtime`; never use or request a physical task root.

Read only the named refs needed for the current decision. Support projections are readable aids, not controller authority, and a missing support projection does not change dispatch legality.
