from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncTurnHandle,
    CodexConfig,
    CodexRpcError,
    InvalidParamsError,
    Sandbox,
    TransportClosedError,
)
from openai_codex.generated.v2_all import ReasoningEffort
from openai_codex.models import JsonObject

from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.platform.provider_environment import provider_subprocess_environment_overrides
from autoclaw.runtime.contracts.provider_resolution import CodexProviderRoute
from autoclaw.runtime.providers.contracts import (
    MANAGED_NODE_MCP_SERVER_NAME,
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderStopOutcome,
)


@dataclass(slots=True)
class _CodexExecution:
    turn: AsyncTurnHandle
    consumer: asyncio.Task[None]


class CodexAdapter:
    """Narrow Codex app-server adapter for one accepted turn per dispatch."""

    kind = ProviderKind.CODEX

    def __init__(self, *, codex_factory: Callable[[], AsyncCodex] | None = None) -> None:
        self._codex_factory = codex_factory or _build_codex
        self._codex: AsyncCodex | None = None
        self._executions: dict[str, _CodexExecution] = {}
        self._consumer_tasks: set[asyncio.Task[None]] = set()
        self._starting_dispatches: set[str] = set()
        self._lock = asyncio.Lock()
        self._is_active = False

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        route, connection = _validate_codex_request(request)
        instructions = _decode_request_lane(request.instructions)
        dispatch_input = _decode_request_lane(request.input)
        effort = _resolve_effort(route.effort_override)
        sandbox = _resolve_sandbox(request.provider_native_access, request.network_access)
        thread_config = _build_thread_config(connection, request.network_access, sandbox)

        await self._reserve_start(request.dispatch_id)
        try:
            codex = await self._get_codex()
            thread = await codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                config=thread_config,
                cwd=str(request.working_directory),
                developer_instructions=instructions,
                ephemeral=True,
                model=route.model_override,
                sandbox=sandbox,
            )
            try:
                turn = await thread.turn(dispatch_input, effort=effort)
            except (TransportClosedError, TimeoutError, OSError) as exc:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    code=ProviderStartErrorCode.UNCERTAIN,
                ) from exc
            except (InvalidParamsError, CodexRpcError) as exc:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                    code=ProviderStartErrorCode.REJECTED,
                ) from exc
            except Exception as exc:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    code=ProviderStartErrorCode.UNCERTAIN,
                ) from exc
        except ProviderStartError:
            await self._release_start_reservation(request.dispatch_id)
            raise
        except (InvalidParamsError, ValueError) as exc:
            await self._release_start_reservation(request.dispatch_id)
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONFIGURATION,
            ) from exc
        except (CodexRpcError, TransportClosedError, TimeoutError, OSError) as exc:
            await self._release_start_reservation(request.dispatch_id)
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONNECTION,
            ) from exc
        except Exception as exc:
            await self._release_start_reservation(request.dispatch_id)
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.UNAVAILABLE,
            ) from exc
        async with self._lock:
            consumer = asyncio.create_task(
                self._consume_turn(request.dispatch_id, turn),
                name=f"codex-turn-{request.dispatch_id}",
            )
            execution = _CodexExecution(turn=turn, consumer=consumer)
            self._starting_dispatches.discard(request.dispatch_id)
            self._executions[request.dispatch_id] = execution
            self._consumer_tasks.add(consumer)
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        async with self._lock:
            execution = self._executions.get(dispatch_id)
            is_starting = dispatch_id in self._starting_dispatches
        if execution is None:
            return ProviderStopOutcome.FAILED if is_starting else ProviderStopOutcome.NOT_RUNNING

        try:
            await execution.turn.interrupt()
        except Exception:
            return ProviderStopOutcome.FAILED

        async with self._lock:
            if self._executions.get(dispatch_id) is execution:
                self._executions.pop(dispatch_id, None)
        return ProviderStopOutcome.STOPPED

    async def read_availability(self) -> ProviderCheckResult:
        try:
            account = await (await self._get_codex()).account()
        except Exception:
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code="codex_check_failed",
            )
        if account.account is None and account.requires_openai_auth:
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code="codex_authentication_required",
                authentication=ProviderCheckAxisStatus.FAILED,
            )
        account_type = getattr(getattr(account.account, "root", None), "type", None)
        if account_type == "apiKey":
            authentication_method = ProviderAuthenticationMethod.API_KEY
        elif account_type == "chatgpt":
            authentication_method = ProviderAuthenticationMethod.SUBSCRIPTION
        else:
            authentication_method = None
        authentication = (
            ProviderCheckAxisStatus.PASSED
            if authentication_method is not None
            else ProviderCheckAxisStatus.NOT_CHECKED
        )
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="codex_available",
            authentication=authentication,
            authentication_method=authentication_method,
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        if self._is_active:
            raise RuntimeError("Codex adapter lifespan is already active")
        self._is_active = True
        try:
            yield
        finally:
            self._is_active = False
            await self._cleanup()

    async def _get_codex(self) -> AsyncCodex:
        async with self._lock:
            if not self._is_active:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                    code=ProviderStartErrorCode.UNAVAILABLE,
                )
            if self._codex is None:
                self._codex = self._codex_factory()
            return self._codex

    async def _reserve_start(self, dispatch_id: str) -> None:
        async with self._lock:
            if dispatch_id in self._starting_dispatches or dispatch_id in self._executions:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    code=ProviderStartErrorCode.UNCERTAIN,
                )
            self._starting_dispatches.add(dispatch_id)

    async def _release_start_reservation(self, dispatch_id: str) -> None:
        async with self._lock:
            self._starting_dispatches.discard(dispatch_id)

    async def _consume_turn(self, dispatch_id: str, turn: AsyncTurnHandle) -> None:
        current_task = asyncio.current_task()
        try:
            await turn.run()
        except BaseException:
            pass
        finally:
            async with self._lock:
                execution = self._executions.get(dispatch_id)
                if execution is not None and execution.turn is turn:
                    self._executions.pop(dispatch_id, None)
                if current_task is not None:
                    self._consumer_tasks.discard(current_task)

    async def _cleanup(self) -> None:
        async with self._lock:
            consumers = tuple(self._consumer_tasks)
            codex = self._codex
            self._executions.clear()
            self._consumer_tasks.clear()
            self._starting_dispatches.clear()
            self._codex = None

        for consumer in consumers:
            consumer.cancel()
        try:
            if codex is not None:
                await codex.close()
        finally:
            if consumers:
                await asyncio.gather(*consumers, return_exceptions=True)


def _build_codex() -> AsyncCodex:
    return AsyncCodex(
        CodexConfig(env=provider_subprocess_environment_overrides()),
    )


def _validate_codex_request(
    request: DispatchStartRequest,
) -> tuple[CodexProviderRoute, ManagedNodeMcpConnection]:
    if not isinstance(request.provider_route, CodexProviderRoute):
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        )
    if request.managed_node_mcp is None:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        )
    return request.provider_route, request.managed_node_mcp


def _decode_request_lane(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        ) from exc


def _resolve_effort(value: str | None) -> ReasoningEffort | None:
    if value is None:
        return None
    try:
        return ReasoningEffort(value)
    except ValueError as exc:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        ) from exc


def _resolve_sandbox(
    native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
) -> Sandbox:
    if native_access is ProviderNativeAccess.DENIED or (
        native_access is ProviderNativeAccess.FULL and network_access is NetworkAccess.DENY
    ):
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.UNSUPPORTED,
        )
    if native_access is ProviderNativeAccess.RESTRICTED:
        return Sandbox.workspace_write
    return Sandbox.full_access


def _build_thread_config(
    connection: ManagedNodeMcpConnection,
    network_access: NetworkAccess,
    sandbox: Sandbox,
) -> JsonObject:
    config: JsonObject = {
        "mcp_servers": {
            MANAGED_NODE_MCP_SERVER_NAME: {
                "url": connection.url,
                "http_headers": {"Authorization": connection.authorization_header},
                "enabled_tools": list(connection.enabled_tools),
                "required": True,
            }
        }
    }
    if sandbox is Sandbox.workspace_write:
        config["sandbox_workspace_write"] = {
            "network_access": network_access is NetworkAccess.ALLOW
        }
    return config


__all__ = ["CodexAdapter"]
