from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from autoclaw.config import OpenClawGatewayAuthMode, OpenClawSettings, Settings, get_settings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.openclaw.gateway.cli_transport import (
    OpenClawGatewayCliError,
    OpenClawGatewayFailureCode,
    call_openclaw_gateway,
)
from autoclaw.runtime.contracts.provider_resolution import OpenClawProviderRoute
from autoclaw.runtime.providers.contracts import (
    DispatchStartRequest,
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


@dataclass(frozen=True, slots=True)
class _OpenClawRunHandle:
    gateway_profile: str
    session_key: str
    run_id: str


class OpenClawGatewayAdapter:
    """Narrow experimental start/stop adapter over the user-owned Gateway CLI."""

    kind = ProviderKind.OPENCLAW

    def __init__(self, *, config: OpenClawSettings) -> None:
        self.config = config
        self._run_handles: dict[str, _OpenClawRunHandle] = {}
        self._is_in_lifespan = False

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        if self._is_in_lifespan:
            raise RuntimeError("OpenClaw adapter lifespan cannot be re-entered")
        self._is_in_lifespan = True
        try:
            yield
        finally:
            await asyncio.gather(
                *(self.stop(dispatch_id) for dispatch_id in tuple(self._run_handles)),
                return_exceptions=True,
            )
            self._run_handles.clear()
            self._is_in_lifespan = False

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        route = request.provider_route
        if not isinstance(route, OpenClawProviderRoute):
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONFIGURATION,
            )
        try:
            instructions = request.instructions.decode("utf-8")
            input_text = request.input.decode("utf-8")
        except UnicodeDecodeError:
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONFIGURATION,
            ) from None

        session_key = f"autoclaw-{uuid4().hex}"
        idempotency_key = (
            f"autoclaw:{request.dispatch_id}:provider-start:{request.provider_start_revision}"
        )
        try:
            response = await call_openclaw_gateway(
                executable=self.config.cli_path,
                profile=route.gateway_profile,
                gateway_url=self.config.gateway_url,
                gateway_auth_mode=self.config.gateway_auth_mode,
                method="agent",
                params={
                    "sessionKey": session_key,
                    "message": input_text,
                    "extraSystemPrompt": instructions,
                    "idempotencyKey": idempotency_key,
                },
                working_directory=request.working_directory,
            )
        except OpenClawGatewayCliError as exc:
            raise _build_provider_start_error(exc) from None

        status = response.get("status")
        run_id = response.get("runId")
        if status not in {"accepted", "in_flight"} or not isinstance(run_id, str) or not run_id:
            raise ProviderStartError(
                kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                code=ProviderStartErrorCode.UNCERTAIN,
            )
        self._run_handles[request.dispatch_id] = _OpenClawRunHandle(
            gateway_profile=route.gateway_profile,
            session_key=session_key,
            run_id=run_id,
        )
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        run_handle = self._run_handles.pop(dispatch_id, None)
        if run_handle is None:
            return ProviderStopOutcome.NOT_RUNNING
        try:
            response = await call_openclaw_gateway(
                executable=self.config.cli_path,
                profile=run_handle.gateway_profile,
                gateway_url=self.config.gateway_url,
                gateway_auth_mode=self.config.gateway_auth_mode,
                method="sessions.abort",
                params={
                    "key": run_handle.session_key,
                    "runId": run_handle.run_id,
                },
            )
        except OpenClawGatewayCliError:
            return ProviderStopOutcome.FAILED

        if response.get("ok") is not True:
            return ProviderStopOutcome.FAILED
        if response.get("status") == "no-active-run":
            return ProviderStopOutcome.NOT_RUNNING
        if response.get("status") == "aborted":
            return ProviderStopOutcome.STOPPED
        return ProviderStopOutcome.FAILED

    async def read_availability(self) -> ProviderCheckResult:
        authentication_method = (
            ProviderAuthenticationMethod.TOKEN
            if self.config.gateway_auth_mode is OpenClawGatewayAuthMode.TOKEN
            else ProviderAuthenticationMethod.PASSWORD
        )
        try:
            response = await call_openclaw_gateway(
                executable=self.config.cli_path,
                profile=self.config.gateway_profile,
                gateway_url=self.config.gateway_url,
                gateway_auth_mode=self.config.gateway_auth_mode,
                method="health",
                params={},
            )
        except OpenClawGatewayCliError as exc:
            authentication = ProviderCheckAxisStatus.NOT_CHECKED
            reachability = ProviderCheckAxisStatus.NOT_CHECKED
            if exc.code is OpenClawGatewayFailureCode.AUTHENTICATION_FAILED:
                authentication = ProviderCheckAxisStatus.FAILED
            elif exc.code in {
                OpenClawGatewayFailureCode.UNREACHABLE,
                OpenClawGatewayFailureCode.TIMEOUT,
            }:
                reachability = ProviderCheckAxisStatus.FAILED
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code=exc.code.value,
                authentication=authentication,
                authentication_method=authentication_method,
                reachability=reachability,
            )
        if response.get("ok") is not True:
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code=OpenClawGatewayFailureCode.REJECTED.value,
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=authentication_method,
                reachability=ProviderCheckAxisStatus.PASSED,
            )
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.LIMITED,
            code="openclaw_experimental",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=authentication_method,
            reachability=ProviderCheckAxisStatus.PASSED,
        )


def build_openclaw_gateway_adapter(settings: Settings | None = None) -> OpenClawGatewayAdapter:
    loaded = settings or get_settings()
    return OpenClawGatewayAdapter(config=loaded.openclaw)


def _build_provider_start_error(exc: OpenClawGatewayCliError) -> ProviderStartError:
    kind = ProviderStartFailureKind.DEFINITE_FAILURE
    if exc.is_acceptance_uncertain:
        kind = ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE
    code = {
        OpenClawGatewayFailureCode.NOT_INSTALLED: ProviderStartErrorCode.UNAVAILABLE,
        OpenClawGatewayFailureCode.PROCESS_LAUNCH_FAILED: ProviderStartErrorCode.UNAVAILABLE,
        OpenClawGatewayFailureCode.AUTHENTICATION_FAILED: ProviderStartErrorCode.AUTHENTICATION,
        OpenClawGatewayFailureCode.UNREACHABLE: ProviderStartErrorCode.CONNECTION,
        OpenClawGatewayFailureCode.REJECTED: ProviderStartErrorCode.REJECTED,
        OpenClawGatewayFailureCode.TIMEOUT: ProviderStartErrorCode.TIMEOUT,
        OpenClawGatewayFailureCode.INVALID_RESPONSE: ProviderStartErrorCode.UNCERTAIN,
        OpenClawGatewayFailureCode.CALL_FAILED: ProviderStartErrorCode.UNCERTAIN,
    }[exc.code]
    return ProviderStartError(kind=kind, code=code)


__all__ = [
    "OpenClawGatewayAdapter",
    "build_openclaw_gateway_adapter",
]
