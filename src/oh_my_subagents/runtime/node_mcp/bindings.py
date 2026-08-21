from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock


class DispatchMcpBindingState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class DispatchMcpBinding:
    credential_digest: bytes = field(repr=False)
    task_id: str
    dispatch_id: str
    provider_start_revision: int
    exposure_ceiling: frozenset[str]
    lifecycle_state: DispatchMcpBindingState = DispatchMcpBindingState.ACTIVE

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be nonempty")
        if not self.dispatch_id:
            raise ValueError("dispatch_id must be nonempty")
        if self.provider_start_revision < 0:
            raise ValueError("provider_start_revision must be nonnegative")
        if not self.exposure_ceiling:
            raise ValueError("exposure_ceiling must contain at least one operation")
        if any(not operation_name for operation_name in self.exposure_ceiling):
            raise ValueError("exposure_ceiling operation names must be nonempty")


@dataclass(frozen=True, slots=True)
class IssuedDispatchMcpBinding:
    binding: DispatchMcpBinding
    credential: str = field(repr=False)


class DispatchMcpBindingRegistry:
    """Process-local authentication registry for managed Node MCP calls."""

    def __init__(self) -> None:
        self._bindings_by_digest: dict[bytes, DispatchMcpBinding] = {}
        self._lock = RLock()

    def issue_binding(
        self,
        *,
        task_id: str,
        dispatch_id: str,
        provider_start_revision: int,
        exposure_ceiling: Iterable[str],
    ) -> IssuedDispatchMcpBinding:
        normalized_ceiling = frozenset(exposure_ceiling)

        with self._lock:
            credential, credential_digest = self._generate_unique_credential()
            binding = DispatchMcpBinding(
                credential_digest=credential_digest,
                task_id=task_id,
                dispatch_id=dispatch_id,
                provider_start_revision=provider_start_revision,
                exposure_ceiling=normalized_ceiling,
            )
            self._bindings_by_digest[credential_digest] = binding

        return IssuedDispatchMcpBinding(binding=binding, credential=credential)

    def authenticate(self, credential: str) -> DispatchMcpBinding | None:
        if not credential:
            return None
        presented_digest = _credential_digest(credential)

        with self._lock:
            matching_binding: DispatchMcpBinding | None = None
            for stored_digest, binding in self._bindings_by_digest.items():
                is_match = hmac.compare_digest(stored_digest, presented_digest)
                if is_match:
                    matching_binding = binding

            if (
                matching_binding is None
                or matching_binding.lifecycle_state is not DispatchMcpBindingState.ACTIVE
            ):
                return None
            return matching_binding

    def is_active(self, binding: DispatchMcpBinding) -> bool:
        with self._lock:
            current_binding = self._bindings_by_digest.get(binding.credential_digest)
            return (
                current_binding is not None
                and current_binding.lifecycle_state is DispatchMcpBindingState.ACTIVE
            )

    def revoke_binding(self, binding: DispatchMcpBinding) -> bool:
        with self._lock:
            return self._bindings_by_digest.pop(binding.credential_digest, None) is not None

    def revoke_dispatch(self, dispatch_id: str) -> int:
        revoked_count = 0
        with self._lock:
            for credential_digest, binding in tuple(self._bindings_by_digest.items()):
                if binding.dispatch_id != dispatch_id:
                    continue
                del self._bindings_by_digest[credential_digest]
                revoked_count += 1
        return revoked_count

    def revoke_all(self) -> int:
        with self._lock:
            revoked_count = len(self._bindings_by_digest)
            self._bindings_by_digest.clear()
            return revoked_count

    def _generate_unique_credential(self) -> tuple[str, bytes]:
        while True:
            credential = secrets.token_urlsafe(32)
            credential_digest = _credential_digest(credential)
            if credential_digest not in self._bindings_by_digest:
                return credential, credential_digest


def _credential_digest(credential: str) -> bytes:
    return hashlib.sha256(credential.encode("utf-8")).digest()


__all__ = [
    "DispatchMcpBinding",
    "DispatchMcpBindingRegistry",
    "DispatchMcpBindingState",
    "IssuedDispatchMcpBinding",
]
