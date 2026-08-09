from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai_codex import (
    CodexRpcError,
    InvalidParamsError,
    TransportClosedError,
)
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import (
    GetAccountResponse,
    TurnCompletedNotification,
)
from openai_codex.models import JsonObject

from banksia.integrations.codex.isolation import (
    CodexIsolationError,
    CodexServerRequestHandler,
    CodexTaskThreadStartResponse,
    build_codex_client,
    build_codex_task_config,
    deny_codex_task_server_request,
    read_codex_ambient_state,
    require_codex_task_thread_isolation,
    validate_codex_task_extensions,
)
from banksia.providers import ManagedExtensionMode, ManagedSandboxMode, ProviderKind
from banksia.runtime.contracts.provider_resolution import CodexProviderRoute
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderExtensionInventory,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderSteerOutcome,
    ProviderStopOutcome,
)

_THREAD_START_METHOD = "thread/start"

type _CodexClientFactory = Callable[[CodexServerRequestHandler], CodexClient]


@dataclass(frozen=True, slots=True)
class _StartedTurn:
    thread_id: str
    turn_id: str
    extension_inventory: ProviderExtensionInventory


@dataclass(slots=True)
class _CodexExecution:
    client: CodexClient
    thread_id: str
    turn_id: str
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CodexAdapter:
    """One isolated Codex app-server process and turn per accepted Dispatch."""

    kind = ProviderKind.CODEX

    def __init__(self, *, codex_factory: _CodexClientFactory | None = None) -> None:
        self._codex_factory = codex_factory
        self._executions: dict[str, _CodexExecution] = {}
        self._consumer_tasks: set[asyncio.Task[None]] = set()
        self._starting_dispatches: set[str] = set()
        self._lock = asyncio.Lock()
        self._is_active = False

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        route, connection = _validate_codex_request(request)
        effort = _resolve_effort(route.effort_override)
        workspace = _resolve_workspace(request.working_directory)
        assert request.sandbox_mode is not None

        await self._reserve_start(request.dispatch_id)
        client: CodexClient | None = None
        accepted = False
        try:
            client = self._build_task_client(request.extension_mode)
            started = await self._start_client_turn(
                client,
                request=request,
                route=route,
                connection=connection,
                effort=effort,
                workspace=workspace,
            )
            async with self._lock:
                if not self._is_active:
                    raise _definite_error(ProviderStartErrorCode.UNAVAILABLE)
                consumer = asyncio.create_task(
                    self._consume_turn(
                        request.dispatch_id,
                        client,
                        started,
                    ),
                    name=f"codex-turn-{request.dispatch_id}",
                )
                self._starting_dispatches.discard(request.dispatch_id)
                self._executions[request.dispatch_id] = _CodexExecution(
                    client=client,
                    thread_id=started.thread_id,
                    turn_id=started.turn_id,
                )
                self._consumer_tasks.add(consumer)
                accepted = True
        except asyncio.CancelledError:
            raise
        except ProviderStartError:
            raise
        except (InvalidParamsError, ValueError) as exc:
            raise _definite_error(ProviderStartErrorCode.CONFIGURATION) from exc
        except (CodexRpcError, TransportClosedError, TimeoutError, OSError) as exc:
            raise _definite_error(ProviderStartErrorCode.CONNECTION) from exc
        except Exception as exc:
            raise _definite_error(ProviderStartErrorCode.UNAVAILABLE) from exc
        finally:
            if not accepted:
                if client is not None:
                    await _close_client(client)
                await self._release_start_reservation(request.dispatch_id)
        return ProviderStartAccepted(extension_inventory=started.extension_inventory)

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        async with self._lock:
            execution = self._executions.get(dispatch_id)
            is_starting = dispatch_id in self._starting_dispatches
        if execution is None:
            return ProviderStopOutcome.FAILED if is_starting else ProviderStopOutcome.NOT_RUNNING

        async with execution.operation_lock:
            try:
                await asyncio.to_thread(
                    execution.client.turn_interrupt,
                    execution.thread_id,
                    execution.turn_id,
                )
                await _close_client(execution.client)
            except Exception:
                return ProviderStopOutcome.FAILED

        async with self._lock:
            if self._executions.get(dispatch_id) is execution:
                self._executions.pop(dispatch_id, None)
        return ProviderStopOutcome.STOPPED

    async def can_steer(self, dispatch_id: str) -> bool:
        async with self._lock:
            return dispatch_id in self._executions

    async def steer(self, dispatch_id: str, message: str) -> ProviderSteerOutcome:
        async with self._lock:
            execution = self._executions.get(dispatch_id)
        if execution is None:
            return ProviderSteerOutcome.NOT_RUNNING

        async with execution.operation_lock:
            async with self._lock:
                if self._executions.get(dispatch_id) is not execution:
                    return ProviderSteerOutcome.NOT_RUNNING
            try:
                await asyncio.to_thread(
                    execution.client.turn_steer,
                    execution.thread_id,
                    execution.turn_id,
                    message,
                )
            except InvalidParamsError:
                return ProviderSteerOutcome.NOT_RUNNING
            except (CodexRpcError, TransportClosedError, TimeoutError, OSError):
                return ProviderSteerOutcome.UNCERTAIN
            except Exception:
                return ProviderSteerOutcome.UNCERTAIN
        return ProviderSteerOutcome.DELIVERED

    async def read_availability(self) -> ProviderCheckResult:
        async with self._lock:
            if not self._is_active:
                return _unavailable_check("codex_check_failed")
        client: CodexClient | None = None
        try:
            client = self._build_isolated_client()
            account = await asyncio.to_thread(_read_codex_account, client)
        except Exception:
            return _unavailable_check("codex_check_failed")
        finally:
            if client is not None:
                await _close_client(client)

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

    async def _start_client_turn(
        self,
        client: CodexClient,
        *,
        request: DispatchStartRequest,
        route: CodexProviderRoute,
        connection: ManagedNodeMcpConnection,
        effort: str | None,
        workspace: Path,
    ) -> _StartedTurn:
        worker = asyncio.create_task(
            asyncio.to_thread(
                _start_codex_turn,
                client,
                request,
                route,
                connection,
                effort,
                workspace,
            )
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await _close_client(client)
            await _drain_task(worker)
            raise

    async def _reserve_start(self, dispatch_id: str) -> None:
        async with self._lock:
            if not self._is_active:
                raise _definite_error(ProviderStartErrorCode.UNAVAILABLE)
            if dispatch_id in self._starting_dispatches or dispatch_id in self._executions:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    code=ProviderStartErrorCode.UNCERTAIN,
                )
            self._starting_dispatches.add(dispatch_id)

    def _build_task_client(self, extension_mode: ManagedExtensionMode | None) -> CodexClient:
        assert extension_mode is not None
        if self._codex_factory is not None:
            return self._codex_factory(deny_codex_task_server_request)
        return build_codex_client(
            deny_codex_task_server_request,
            extension_mode=extension_mode,
        )

    def _build_isolated_client(self) -> CodexClient:
        if self._codex_factory is not None:
            return self._codex_factory(deny_codex_task_server_request)
        return build_codex_client(deny_codex_task_server_request)

    async def _release_start_reservation(self, dispatch_id: str) -> None:
        async with self._lock:
            self._starting_dispatches.discard(dispatch_id)

    async def _consume_turn(
        self,
        dispatch_id: str,
        client: CodexClient,
        started: _StartedTurn,
    ) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.to_thread(_wait_for_terminal_turn, client, started.turn_id)
        except BaseException:
            pass
        finally:
            async with self._lock:
                execution = self._executions.get(dispatch_id)
            if execution is not None and execution.client is client:
                async with execution.operation_lock:
                    await _close_client(client)
                async with self._lock:
                    if self._executions.get(dispatch_id) is execution:
                        self._executions.pop(dispatch_id, None)
            else:
                await _close_client(client)
            async with self._lock:
                if current_task is not None:
                    self._consumer_tasks.discard(current_task)

    async def _cleanup(self) -> None:
        async with self._lock:
            executions = tuple(self._executions.values())
            consumers = tuple(self._consumer_tasks)
            self._executions.clear()
            self._consumer_tasks.clear()
            self._starting_dispatches.clear()

        if executions:
            await asyncio.gather(
                *(_close_client(execution.client) for execution in executions),
                return_exceptions=True,
            )
        for consumer in consumers:
            consumer.cancel()
        if consumers:
            await asyncio.gather(*consumers, return_exceptions=True)


def _start_codex_turn(
    client: CodexClient,
    request: DispatchStartRequest,
    route: CodexProviderRoute,
    connection: ManagedNodeMcpConnection,
    effort: str | None,
    workspace: Path,
) -> _StartedTurn:
    try:
        thread_id, extension_inventory = _start_codex_thread(
            client,
            request=request,
            route=route,
            connection=connection,
            workspace=workspace,
        )
    except ProviderStartError:
        raise
    except (CodexIsolationError, InvalidParamsError, ValueError) as exc:
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION) from exc
    except (TransportClosedError, TimeoutError, OSError) as exc:
        raise _definite_error(ProviderStartErrorCode.CONNECTION) from exc
    except CodexRpcError as exc:
        raise _definite_error(ProviderStartErrorCode.UNAVAILABLE) from exc
    except Exception as exc:
        raise _definite_error(ProviderStartErrorCode.UNAVAILABLE) from exc

    turn_params: JsonObject = {"approvalPolicy": "never"}
    if effort is not None:
        turn_params["effort"] = effort
    try:
        turn = client.turn_start(thread_id, request.input, turn_params)
    except (InvalidParamsError, CodexRpcError) as exc:
        raise _definite_error(ProviderStartErrorCode.REJECTED) from exc
    except (TransportClosedError, TimeoutError, OSError) as exc:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
            code=ProviderStartErrorCode.UNCERTAIN,
        ) from exc
    except Exception as exc:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
            code=ProviderStartErrorCode.UNCERTAIN,
        ) from exc
    return _StartedTurn(
        thread_id=thread_id,
        turn_id=turn.turn.id,
        extension_inventory=extension_inventory,
    )


def _start_codex_thread(
    client: CodexClient,
    *,
    request: DispatchStartRequest,
    route: CodexProviderRoute,
    connection: ManagedNodeMcpConnection,
    workspace: Path,
) -> tuple[str, ProviderExtensionInventory]:
    client.start()
    client.initialize()
    ambient = read_codex_ambient_state(client, workspace)
    assert request.sandbox_mode is not None
    assert request.extension_mode is not None
    config = build_codex_task_config(
        ambient,
        connection=connection,
        extension_mode=request.extension_mode,
        network_access=request.network_access,
        sandbox_mode=request.sandbox_mode,
        workspace=workspace,
    )
    params: JsonObject = {
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "allowProviderModelFallback": False,
        "config": config,
        "cwd": str(workspace),
        "developerInstructions": request.instructions,
        "ephemeral": True,
        "personality": "none",
        "runtimeWorkspaceRoots": [str(workspace)],
        "sandbox": _sandbox_value(request.sandbox_mode),
        "selectedCapabilityRoots": [],
    }
    if route.model_override is not None:
        params["model"] = route.model_override
    response = client.request(
        _THREAD_START_METHOD,
        params,
        response_model=CodexTaskThreadStartResponse,
    )
    require_codex_task_thread_isolation(
        response,
        expected_model=route.model_override,
        network_access=request.network_access,
        sandbox_mode=request.sandbox_mode,
        workspace=workspace,
    )
    thread_id = response.thread.id
    extension_inventory = validate_codex_task_extensions(
        client,
        ambient=ambient,
        enabled_tools=connection.enabled_tools,
        extension_mode=request.extension_mode,
        thread_id=thread_id,
    )
    return thread_id, extension_inventory


def _read_codex_account(client: CodexClient) -> GetAccountResponse:
    client.start()
    client.initialize()
    return client.account_read()


def _wait_for_terminal_turn(client: CodexClient, turn_id: str) -> None:
    try:
        while True:
            notification = client.next_turn_notification(turn_id)
            payload = notification.payload
            if isinstance(payload, TurnCompletedNotification) and payload.turn.id == turn_id:
                return
    finally:
        try:
            client.unregister_turn_notifications(turn_id)
        except Exception:
            pass


def _validate_codex_request(
    request: DispatchStartRequest,
) -> tuple[CodexProviderRoute, ManagedNodeMcpConnection]:
    if not isinstance(request.provider_route, CodexProviderRoute):
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION)
    if request.managed_node_mcp is None:
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION)
    return request.provider_route, request.managed_node_mcp


def _resolve_workspace(path: Path) -> Path:
    try:
        workspace = path.resolve(strict=True)
    except OSError as exc:
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION) from exc
    if not workspace.is_dir():
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION)
    return workspace


def _resolve_effort(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        raise _definite_error(ProviderStartErrorCode.CONFIGURATION)
    return value


def _sandbox_value(sandbox_mode: ManagedSandboxMode) -> str:
    return {
        ManagedSandboxMode.READ_ONLY: "read-only",
        ManagedSandboxMode.WORKSPACE_WRITE: "workspace-write",
        ManagedSandboxMode.FULL_ACCESS: "danger-full-access",
    }[sandbox_mode]


def _definite_error(code: ProviderStartErrorCode) -> ProviderStartError:
    return ProviderStartError(
        kind=ProviderStartFailureKind.DEFINITE_FAILURE,
        code=code,
    )


def _unavailable_check(code: str) -> ProviderCheckResult:
    return ProviderCheckResult(
        kind=ProviderKind.CODEX,
        status=ProviderCheckStatus.UNAVAILABLE,
        code=code,
    )


async def _close_client(client: CodexClient) -> None:
    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass


async def _drain_task(task: asyncio.Task[Any]) -> None:
    try:
        await asyncio.shield(task)
    except BaseException:
        pass


__all__ = ["CodexAdapter"]
