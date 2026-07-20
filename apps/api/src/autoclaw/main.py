from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.config import Environment, Settings, format_loopback_authority, get_settings
from autoclaw.integrations.provider_registry import build_provider_adapter_registry
from autoclaw.interfaces.http.errors import (
    operation_failure_from_http_exception,
    request_validation_failure,
)
from autoclaw.interfaces.http.local_admission import add_local_control_plane_middleware
from autoclaw.interfaces.http.router import api_router
from autoclaw.interfaces.mcp.node.server import create_node_mcp_apps
from autoclaw.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_app,
)
from autoclaw.interfaces.mcp.transport import node_mcp_transport_policy
from autoclaw.interfaces.web_console.router import mount_packaged_web_console
from autoclaw.persistence.session import (
    dispose_db_engine,
    ensure_database_schema,
    get_session_factory,
)
from autoclaw.runtime.boundary import create_boundary_accepted_handler
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.command_run import (
    CommandProcessOwner,
    create_command_run_terminal_handler,
)
from autoclaw.runtime.dispatch.cleanup import (
    cleanup_aged_dispatch_request_directories,
    create_dispatch_binding_cleanup_handler,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.human_request import (
    create_human_request_due_handler,
    create_human_request_opened_handler,
    create_human_request_terminal_handler,
)
from autoclaw.runtime.launch.continuation import create_flow_start_handler
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import (
    NodeOperationExecutor,
    create_watchdog_activity_publisher,
)
from autoclaw.runtime.post_commit import (
    BoundaryAccepted,
    CommandProcessExited,
    CommandRunCancellationRequested,
    CommandRunDue,
    CommandRunPending,
    CommandRunTerminal,
    DeadlineScheduler,
    DispatchCleanupRequested,
    DispatchStartDue,
    FlowStartCommitted,
    HumanRequestDue,
    HumanRequestOpened,
    HumanRequestTerminal,
    RuntimeEffectRouter,
    RuntimeEffectSignal,
    TransientCleanupRequested,
    WatchdogDeadlineChanged,
    WatchdogDue,
)
from autoclaw.runtime.post_commit.bootstrap import audit_startup_runtime_effects
from autoclaw.runtime.projection import SupportProjectionOwner, TransientProjection
from autoclaw.runtime.providers.cleanup import create_provider_dispatch_cleanup_handler
from autoclaw.runtime.providers.registry import ProviderAdapterRegistry
from autoclaw.runtime.providers.starter import DispatchStarter
from autoclaw.runtime.startup_audit import audit_startup_support_projections
from autoclaw.runtime.task_root import cleanup_expired_transient
from autoclaw.runtime.watchdog import (
    create_watchdog_deadline_changed_handler,
    create_watchdog_due_handler,
)

_RUNTIME_STARTUP_ROUTED_SIGNAL_TYPES = (
    FlowStartCommitted,
    BoundaryAccepted,
    HumanRequestOpened,
    HumanRequestTerminal,
    CommandRunPending,
    CommandRunCancellationRequested,
    CommandRunTerminal,
    TransientCleanupRequested,
    WatchdogDeadlineChanged,
    DispatchStartDue,
)


@dataclass(frozen=True, slots=True)
class _ApplicationRuntime:
    binding_registry: DispatchMcpBindingRegistry
    provider_adapter_registry: ProviderAdapterRegistry
    runtime_effect_router: RuntimeEffectRouter
    deadline_scheduler: DeadlineScheduler
    dispatch_opening_dependencies: DispatchOpeningDependencies
    command_process_owner: CommandProcessOwner
    support_projection_owner: SupportProjectionOwner
    node_operation_executor: NodeOperationExecutor
    dispatch_starter: DispatchStarter


def _package_version() -> str:
    try:
        return version("autoclaw")
    except PackageNotFoundError:
        for parent in Path(__file__).resolve().parents:
            pyproject_path = parent / "pyproject.toml"
            if not pyproject_path.is_file():
                continue
            with pyproject_path.open("rb") as handle:
                pyproject = tomllib.load(handle)
            project = pyproject.get("project", {})
            project_version = project.get("version")
            if isinstance(project_version, str):
                return project_version
            break
    return "0.0.0"


def create_app(
    *,
    should_enable_mcp_mounts: bool | None = None,
) -> FastAPI:
    settings = get_settings()
    if should_enable_mcp_mounts is None:
        should_enable_mcp_mounts = settings.env != Environment.TEST

    docs_enabled = settings.env in {Environment.DEVELOPMENT, Environment.TEST}
    app = FastAPI(
        title="AutoClaw API",
        version=_package_version(),
        lifespan=_lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    runtime = _build_application_runtime(settings)
    _register_runtime_effect_routes(
        router=runtime.runtime_effect_router,
        scheduler=runtime.deadline_scheduler,
        command_process_owner=runtime.command_process_owner,
        support_projection_owner=runtime.support_projection_owner,
        dispatch_starter=runtime.dispatch_starter,
        provider_adapter_registry=runtime.provider_adapter_registry,
        binding_registry=runtime.binding_registry,
        dependencies=runtime.dispatch_opening_dependencies,
        settings=settings,
    )
    _store_application_runtime(app, runtime)
    add_local_control_plane_middleware(app, settings)
    _register_exception_handlers(app)
    app.include_router(api_router)
    mount_packaged_web_console(app)
    if should_enable_mcp_mounts:
        _mount_mcp_apps(app, settings=settings, runtime=runtime)
    return app


def _build_application_runtime(settings: Settings) -> _ApplicationRuntime:
    binding_registry = DispatchMcpBindingRegistry()
    provider_adapter_registry = build_provider_adapter_registry(settings)
    runtime_effect_router = RuntimeEffectRouter(session_factory=_runtime_session_context)
    deadline_scheduler = DeadlineScheduler(publish=runtime_effect_router.publish)
    dispatch_opening_dependencies = DispatchOpeningDependencies.create(
        settings=settings,
        available_adapter_kinds=provider_adapter_registry.available_kinds,
        post_commit_publisher=runtime_effect_router,
    )

    def register_command_run_due(signal: CommandRunDue) -> None:
        deadline_scheduler.register(signal)

    command_process_owner = CommandProcessOwner(
        session_factory=_runtime_session_context,
        runtime_effect_publisher=runtime_effect_router,
        register_due=register_command_run_due,
        health=runtime_effect_router.health,
    )
    support_projection_owner = SupportProjectionOwner(
        session_factory=_runtime_session_context,
    )
    node_operation_executor = NodeOperationExecutor(
        publish_activity_signal=create_watchdog_activity_publisher(
            runtime_effect_router,
            inactivity_timeout_seconds=(settings.runtime.watchdog_inactivity_timeout_seconds),
        ),
        runtime_effect_publisher=runtime_effect_router,
        support_projection_publisher=support_projection_owner,
    )
    dispatch_starter = DispatchStarter(
        adapters=provider_adapter_registry,
        binding_registry=binding_registry,
        operation_executor=node_operation_executor,
        scheduler=deadline_scheduler,
        runtime_effect_publisher=runtime_effect_router,
        runtime_settings=settings.runtime,
        session_factory=_runtime_session_context,
        managed_node_mcp_url=_node_mcp_url(settings, path="/_internal/node/mcp"),
        compatibility_node_mcp_url=_node_mcp_url(settings, path="/node/mcp"),
    )
    return _ApplicationRuntime(
        binding_registry=binding_registry,
        provider_adapter_registry=provider_adapter_registry,
        runtime_effect_router=runtime_effect_router,
        deadline_scheduler=deadline_scheduler,
        dispatch_opening_dependencies=dispatch_opening_dependencies,
        command_process_owner=command_process_owner,
        support_projection_owner=support_projection_owner,
        node_operation_executor=node_operation_executor,
        dispatch_starter=dispatch_starter,
    )


def _store_application_runtime(app: FastAPI, runtime: _ApplicationRuntime) -> None:
    app.state.runtime_effect_router = runtime.runtime_effect_router
    app.state.runtime_effect_publisher = runtime.runtime_effect_router
    app.state.deadline_scheduler = runtime.deadline_scheduler
    app.state.command_process_owner = runtime.command_process_owner
    app.state.dispatch_opening_dependencies = runtime.dispatch_opening_dependencies
    app.state.support_projection_owner = runtime.support_projection_owner
    app.state.support_projection_publisher = runtime.support_projection_owner
    app.state.dispatch_mcp_binding_registry = runtime.binding_registry
    app.state.provider_adapter_registry = runtime.provider_adapter_registry
    app.state.node_operation_executor = runtime.node_operation_executor
    app.state.dispatch_starter = runtime.dispatch_starter
    app.state.mcp_lifespan_apps = ()


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        _request: object,
        exc: HTTPException,
    ) -> JSONResponse:
        failure = operation_failure_from_http_exception(exc)
        content = failure.model_dump(mode="json") if failure is not None else {"detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(
        _request: object,
        exc: RequestValidationError,
    ) -> JSONResponse:
        failure = request_validation_failure(exc)
        return JSONResponse(
            status_code=400,
            content=failure.model_dump(mode="json"),
        )


def _mount_mcp_apps(
    app: FastAPI,
    *,
    settings: Settings,
    runtime: _ApplicationRuntime,
) -> None:
    operator_mcp_app = create_operator_mcp_app(
        host=settings.api_host,
        port=settings.api_port,
        allowed_origins=tuple(settings.console_origins),
        effect_publishers=OperatorEffectPublishers(
            runtime_effect_publisher=runtime.runtime_effect_router,
            support_projection_publisher=runtime.support_projection_owner,
            dispatch_opening_dependencies=runtime.dispatch_opening_dependencies,
        ),
    )
    node_mcp_apps = create_node_mcp_apps(
        binding_registry=runtime.binding_registry,
        operation_executor=runtime.node_operation_executor,
        transport_policy=node_mcp_transport_policy(
            host=settings.api_host,
            port=settings.api_port,
            allowed_origins=settings.console_origins,
        ),
    )
    app.state.mcp_lifespan_apps = (
        operator_mcp_app,
        node_mcp_apps.managed,
        node_mcp_apps.compatibility,
    )
    app.mount("/operator", operator_mcp_app)
    app.mount("/_internal/node", node_mcp_apps.managed)
    app.mount("/node", node_mcp_apps.compatibility)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await ensure_database_schema()
        settings = get_settings()
        app.state.dispatch_request_cleanup = await cleanup_aged_dispatch_request_directories(
            session_factory=_runtime_session_context,
            data_boundary=settings.data_dir,
            now=utc_now(),
        )
        runtime_effect_router: RuntimeEffectRouter = app.state.runtime_effect_router
        deadline_scheduler: DeadlineScheduler = app.state.deadline_scheduler
        command_process_owner: CommandProcessOwner = app.state.command_process_owner
        support_projection_owner: SupportProjectionOwner = app.state.support_projection_owner
        provider_adapter_registry: ProviderAdapterRegistry = app.state.provider_adapter_registry
        dispatch_starter: DispatchStarter = app.state.dispatch_starter
        binding_registry: DispatchMcpBindingRegistry = app.state.dispatch_mcp_binding_registry

        async def publish_startup(signal: RuntimeEffectSignal) -> bool:
            if isinstance(signal, DispatchStartDue):
                dispatch_starter.mark_recovered(signal)
            return await runtime_effect_router.publish_startup(signal)

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(provider_adapter_registry.lifespan())
            stack.callback(binding_registry.revoke_all)
            await stack.enter_async_context(command_process_owner)
            await stack.enter_async_context(support_projection_owner)
            await stack.enter_async_context(runtime_effect_router)
            await stack.enter_async_context(deadline_scheduler)
            for mcp_app in getattr(app.state, "mcp_lifespan_apps", ()):
                await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
            app.state.runtime_startup_audit = await audit_startup_runtime_effects(
                session_factory=_runtime_session_context,
                publish=publish_startup,
                routed_signal_types=_RUNTIME_STARTUP_ROUTED_SIGNAL_TYPES,
                watchdog_inactivity_timeout_seconds=(
                    settings.runtime.watchdog_inactivity_timeout_seconds
                ),
            )
            app.state.support_projection_startup_audit = await audit_startup_support_projections(
                session_factory=_runtime_session_context,
                publish=support_projection_owner.publish_startup,
            )
            yield
    finally:
        await dispose_db_engine()


def _register_runtime_effect_routes(
    *,
    router: RuntimeEffectRouter,
    scheduler: DeadlineScheduler,
    command_process_owner: CommandProcessOwner,
    support_projection_owner: SupportProjectionOwner,
    dispatch_starter: DispatchStarter,
    provider_adapter_registry: ProviderAdapterRegistry,
    binding_registry: DispatchMcpBindingRegistry,
    dependencies: DispatchOpeningDependencies,
    settings: Settings,
) -> None:
    human_terminal_handler = create_human_request_terminal_handler(dependencies)
    command_terminal_handler = create_command_run_terminal_handler(dependencies)
    binding_cleanup_handler = create_dispatch_binding_cleanup_handler(binding_registry)
    provider_cleanup_handler = create_provider_dispatch_cleanup_handler(provider_adapter_registry)

    async def handle_transient_cleanup(
        session: AsyncSession,
        signal: TransientCleanupRequested,
    ) -> None:
        if await cleanup_expired_transient(session, signal):
            support_projection_owner.publish(TransientProjection(signal.transient_localization_id))

    async def handle_human_terminal(
        session: AsyncSession,
        signal: HumanRequestTerminal,
    ) -> None:
        scheduler.cancel_source(HumanRequestDue, signal.request_id)
        await human_terminal_handler(session, signal)

    async def handle_command_terminal(
        session: AsyncSession,
        signal: CommandRunTerminal,
    ) -> None:
        scheduler.cancel_source(CommandRunDue, signal.run_id)
        await command_terminal_handler(session, signal)

    async def handle_dispatch_cleanup(
        session: AsyncSession,
        signal: DispatchCleanupRequested,
    ) -> None:
        scheduler.cancel_source(WatchdogDue, signal.dispatch_id)
        await binding_cleanup_handler(session, signal)
        await provider_cleanup_handler(session, signal)

    router.register(FlowStartCommitted, create_flow_start_handler(dependencies))
    router.register(BoundaryAccepted, create_boundary_accepted_handler(dependencies))
    router.register(HumanRequestOpened, create_human_request_opened_handler(scheduler))
    router.register(
        HumanRequestDue,
        create_human_request_due_handler(runtime_effect_publisher=router),
    )
    router.register(HumanRequestTerminal, handle_human_terminal)
    router.register(CommandRunPending, command_process_owner.launch_pending_command)
    router.register(CommandRunDue, command_process_owner.enforce_command_deadline)
    router.register(
        CommandRunCancellationRequested,
        command_process_owner.terminate_cancelled_command,
    )
    router.register(CommandRunTerminal, handle_command_terminal)
    router.register(CommandProcessExited, command_process_owner.record_command_process_exit)
    router.register(DispatchCleanupRequested, handle_dispatch_cleanup)
    router.register(TransientCleanupRequested, handle_transient_cleanup)
    router.register(DispatchStartDue, dispatch_starter.schedule_or_start_dispatch)
    router.register(
        WatchdogDeadlineChanged,
        create_watchdog_deadline_changed_handler(
            scheduler,
            inactivity_timeout_seconds=settings.runtime.watchdog_inactivity_timeout_seconds,
        ),
    )
    router.register(WatchdogDue, create_watchdog_due_handler(dependencies))


def _node_mcp_url(settings: Settings, *, path: str) -> str:
    return f"http://{format_loopback_authority(settings.api_host, settings.api_port)}{path}"


def _runtime_session_context() -> AbstractAsyncContextManager[AsyncSession]:
    return get_session_factory()()


app: FastAPI = create_app()

__all__ = ["app", "create_app"]
