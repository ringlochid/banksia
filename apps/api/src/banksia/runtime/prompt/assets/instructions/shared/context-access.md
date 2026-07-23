# Context access

Begin by calling `get_current_context` once for coherent current controller truth. Use its allowed actions, capabilities, live workflow neighborhood, Assignment files, and exact trigger rather than inferring currentness from provider history or nearby files. Its readback refs are task-relative logical paths. If the optional current fields are null or the request readback is needed for exact continuation detail, call `read_file(path=readback_refs.input)`.

Use `list_files` for a bounded one-level logical listing and `read_file` for bounded UTF-8 reads. Paths are task-relative and begin with `workspace`, `outputs`, `tmp`, or `_runtime`; never use or request a physical task root.

Read only the named refs needed for the current decision. Support projections are readable aids, not controller authority, and a missing support projection does not change dispatch legality.
