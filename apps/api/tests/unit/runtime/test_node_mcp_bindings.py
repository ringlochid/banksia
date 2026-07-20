from __future__ import annotations

import pytest
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry


def test_managed_binding_registry_keeps_plaintext_out_of_binding_state() -> None:
    registry = DispatchMcpBindingRegistry()

    issued = registry.issue_binding(
        task_id="task.binding-secret",
        dispatch_id="dispatch.binding-secret",
        provider_start_revision=3,
        exposure_ceiling=("get_current_context", "list_files"),
    )

    assert issued.credential
    assert issued.credential.encode("utf-8") != issued.binding.credential_digest
    assert issued.credential not in repr(issued.binding)
    assert issued.binding.provider_start_revision == 3
    assert registry.authenticate(issued.credential) == issued.binding
    assert registry.authenticate(f"{issued.credential}-wrong") is None


def test_managed_binding_registry_rejects_negative_provider_start_revision() -> None:
    registry = DispatchMcpBindingRegistry()

    with pytest.raises(ValueError, match="provider_start_revision must be nonnegative"):
        registry.issue_binding(
            task_id="task.binding-invalid-generation",
            dispatch_id="dispatch.binding-invalid-generation",
            provider_start_revision=-1,
            exposure_ceiling=("get_current_context",),
        )


def test_managed_binding_registry_revokes_one_dispatch_or_every_binding() -> None:
    registry = DispatchMcpBindingRegistry()
    first = registry.issue_binding(
        task_id="task.binding-a",
        dispatch_id="dispatch.binding-a",
        provider_start_revision=0,
        exposure_ceiling=("get_current_context",),
    )
    first_retry = registry.issue_binding(
        task_id="task.binding-a",
        dispatch_id="dispatch.binding-a",
        provider_start_revision=1,
        exposure_ceiling=("get_current_context",),
    )
    second = registry.issue_binding(
        task_id="task.binding-b",
        dispatch_id="dispatch.binding-b",
        provider_start_revision=0,
        exposure_ceiling=("list_files",),
    )

    assert first.credential != first_retry.credential
    assert registry.revoke_binding(first.binding) is True
    assert registry.revoke_binding(first.binding) is False
    assert registry.authenticate(first.credential) is None
    assert registry.authenticate(first_retry.credential) == first_retry.binding

    assert registry.revoke_dispatch("dispatch.binding-a") == 1
    assert registry.authenticate(first_retry.credential) is None
    assert registry.authenticate(second.credential) == second.binding

    assert registry.revoke_all() == 1
    assert registry.revoke_all() == 0
    assert registry.authenticate(second.credential) is None


def test_managed_binding_authentication_compares_every_stored_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = DispatchMcpBindingRegistry()
    issued_bindings = [
        registry.issue_binding(
            task_id=f"task.binding-{index}",
            dispatch_id=f"dispatch.binding-{index}",
            provider_start_revision=index,
            exposure_ceiling=("get_current_context",),
        )
        for index in range(3)
    ]

    from autoclaw.runtime.node_mcp import bindings as binding_module

    original_compare_digest = binding_module.hmac.compare_digest
    compared_digests: list[tuple[bytes, bytes]] = []

    def record_comparison(stored_digest: bytes, presented_digest: bytes) -> bool:
        compared_digests.append((stored_digest, presented_digest))
        return original_compare_digest(stored_digest, presented_digest)

    monkeypatch.setattr(binding_module.hmac, "compare_digest", record_comparison)

    assert registry.authenticate(issued_bindings[1].credential) == issued_bindings[1].binding
    assert len(compared_digests) == len(issued_bindings)


def test_managed_binding_revocation_removes_historical_authentication_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = DispatchMcpBindingRegistry()
    revoked_bindings = []
    for provider_start_revision in range(16):
        issued = registry.issue_binding(
            task_id="task.binding-retries",
            dispatch_id="dispatch.binding-retries",
            provider_start_revision=provider_start_revision,
            exposure_ceiling=("get_current_context",),
        )
        revoked_bindings.append(issued)
        assert registry.revoke_binding(issued.binding) is True

    active = registry.issue_binding(
        task_id="task.binding-retries",
        dispatch_id="dispatch.binding-retries",
        provider_start_revision=len(revoked_bindings),
        exposure_ceiling=("get_current_context",),
    )

    from autoclaw.runtime.node_mcp import bindings as binding_module

    original_compare_digest = binding_module.hmac.compare_digest
    compared_digests: list[tuple[bytes, bytes]] = []

    def record_comparison(stored_digest: bytes, presented_digest: bytes) -> bool:
        compared_digests.append((stored_digest, presented_digest))
        return original_compare_digest(stored_digest, presented_digest)

    monkeypatch.setattr(binding_module.hmac, "compare_digest", record_comparison)

    assert registry.authenticate(active.credential) == active.binding
    assert len(compared_digests) == 1

    for revoked in revoked_bindings:
        compared_digests.clear()
        assert registry.authenticate(revoked.credential) is None
        assert len(compared_digests) == 1
