from __future__ import annotations

from xml.etree import ElementTree

from oh_my_subagents.product_identity import OMS_IDENTITY
from oh_my_subagents.runtime.contracts.prompt import DispatchRequestRenderInput
from oh_my_subagents.runtime.prompt.asset_catalog import (
    InstructionAsset,
    instruction_assets_for_request,
    load_instruction_asset,
)

_ASSET_TAGS = {
    InstructionAsset.CORE: "controller_core",
    InstructionAsset.WORKSPACE_AND_FILES: "workspace_and_files",
    InstructionAsset.CHECKPOINT: "checkpoint_contract",
    InstructionAsset.TASK_LEAD: "task_lead",
    InstructionAsset.MANAGER: "manager",
    InstructionAsset.CONTRIBUTOR: "contributor",
    InstructionAsset.HUMAN_REQUEST: "human_request_guidance",
    InstructionAsset.COMMAND_RUN: "command_run_guidance",
    InstructionAsset.CONTINUATION: "continuation_guidance",
}


def render_request_instructions(request: DispatchRequestRenderInput) -> str:
    root = ElementTree.Element(OMS_IDENTITY.system_prompt_root)
    for asset in instruction_assets_for_request(request.dynamic_input):
        element = ElementTree.SubElement(root, _ASSET_TAGS[asset])
        element.text = load_instruction_asset(asset).rstrip("\r\n")
    if request.member_instruction is not None and request.member_instruction.strip():
        element = ElementTree.SubElement(
            root,
            "member_instruction",
            {"source": "workflow", "format": "markdown"},
        )
        element.text = request.member_instruction
    if request.workflow_note is not None and request.workflow_note.strip():
        element = ElementTree.SubElement(
            root,
            "workflow_note",
            {"source": "workflow", "format": "markdown"},
        )
        element.text = request.workflow_note
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


__all__ = ["render_request_instructions"]
