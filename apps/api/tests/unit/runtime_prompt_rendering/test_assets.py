from __future__ import annotations

from autoclaw.runtime.contracts.prompt import PromptFamily, PromptInstructionGuidance
from autoclaw.runtime.prompt import (
    INSTRUCTION_ASSETS,
    InstructionAsset,
    instruction_asset_path,
    instruction_assets_for_family,
    load_instruction_asset,
    render_request_instructions,
)


def test_exactly_five_instruction_assets_are_packaged() -> None:
    assert tuple(instruction_asset_path(asset).as_posix() for asset in INSTRUCTION_ASSETS) == (
        "instructions/shared/authority.md",
        "instructions/shared/context-access.md",
        "instructions/shared/control-transfer.md",
        "instructions/families/worker.md",
        "instructions/families/parent-root.md",
    )
    assert all(load_instruction_asset(asset).strip() for asset in INSTRUCTION_ASSETS)


def test_family_assets_follow_shared_then_family_order() -> None:
    assert instruction_assets_for_family(PromptFamily.WORKER) == (
        InstructionAsset.AUTHORITY,
        InstructionAsset.CONTEXT_ACCESS,
        InstructionAsset.CONTROL_TRANSFER,
        InstructionAsset.WORKER,
    )
    assert (
        instruction_assets_for_family(PromptFamily.PARENT_ROOT)[-1] == InstructionAsset.PARENT_ROOT
    )


def test_worker_asset_does_not_teach_parent_root_operations() -> None:
    worker = load_instruction_asset(InstructionAsset.WORKER)

    assert "assign_child" not in worker
    assert "add_child" not in worker
    assert "update_child" not in worker
    assert "remove_child" not in worker


def test_context_asset_teaches_task_relative_readback_recovery() -> None:
    context_access = load_instruction_asset(InstructionAsset.CONTEXT_ACCESS)

    assert "task-relative logical paths" in context_access
    assert "read_file(path=checkpoint_to_resume_from)" in context_access
    assert "support projection is missing or unreadable" in context_access
    assert "read_file(path=readback_refs.input)" in context_access


def test_parent_root_asset_teaches_structural_operations() -> None:
    parent_root = load_instruction_asset(InstructionAsset.PARENT_ROOT)

    assert "assign_child" in parent_root
    assert "add_child" in parent_root
    assert "update_child" in parent_root
    assert "remove_child" in parent_root


def test_resolved_guidance_follows_the_family_asset() -> None:
    rendered = render_request_instructions(
        family=PromptFamily.WORKER,
        guidance=PromptInstructionGuidance(
            workflow=("WORKFLOW MARKER",),
            role=("ROLE MARKER",),
            node=("NODE MARKER",),
            policy=("POLICY MARKER",),
        ),
    )

    assert rendered.index("# Worker operating policy") < rendered.index("# Workflow guidance")
    assert rendered.index("WORKFLOW MARKER") < rendered.index("ROLE MARKER")
    assert rendered.index("ROLE MARKER") < rendered.index("NODE MARKER")
    assert rendered.index("NODE MARKER") < rendered.index("POLICY MARKER")
