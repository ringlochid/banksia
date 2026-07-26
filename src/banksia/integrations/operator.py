from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar, cast

from openai_codex import AsyncCodex, CodexConfig

from banksia.config import OperatorProvider, Settings
from banksia.integrations.claude.native_identity import read_claude_invocation_readiness
from banksia.integrations.claude.operator import (
    ClaudeOperatorTurnRunner,
    resolve_claude_operator_effort,
)
from banksia.integrations.codex.operator import (
    CodexOperatorTurnRunner,
    resolve_codex_operator_effort,
)
from banksia.operator.provider import (
    OperatorProviderUnavailableError,
    OperatorRunnerStatus,
    OperatorTurnOutcome,
    OperatorTurnRequest,
    OperatorTurnRunner,
    UnavailableOperatorTurnRunner,
)
from banksia.operator.tools import OperatorTool
from banksia.platform.provider_environment import provider_subprocess_environment_overrides

_OPERATOR_READINESS_TIMEOUT_SECONDS = 10.0
_PROVIDER_OPTION_CHARACTER_LIMIT = 255
_AsyncResult = TypeVar("_AsyncResult")


@dataclass(frozen=True, slots=True)
class _AuthenticationReadiness:
    is_authenticated: bool
    code: str


@dataclass(frozen=True, slots=True)
class _AsyncOutcome[ResultT]:
    result: ResultT | None = None
    error: BaseException | None = None


class ConfiguredOperatorTurnRunner:
    """Own readiness and exact delegation for one configured Operator provider."""

    def __init__(
        self,
        *,
        settings: Settings,
        system_prompt: str,
        tools: Sequence[OperatorTool],
    ) -> None:
        self._settings = settings
        self._system_prompt = system_prompt
        self._tools = tuple(tools)
        self._is_active = False
        self._runner: OperatorTurnRunner = _initial_runner(settings)
        self._active_turns: set[asyncio.Task[object]] = set()

    @property
    def status(self) -> OperatorRunnerStatus:
        return self._runner.status

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        if not self._is_active:
            raise OperatorProviderUnavailableError(
                "Operator turns are unavailable outside the Banksia application lifespan"
            )
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("Operator turn execution requires an asyncio task")
        runner = self._runner
        self._active_turns.add(current_task)
        try:
            return await runner.execute_turn(request)
        finally:
            self._active_turns.discard(current_task)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[ConfiguredOperatorTurnRunner]:
        if self._is_active:
            raise RuntimeError("Operator runner lifespan is already active")
        self._is_active = True
        try:
            if _selected_provider_is_enabled(self._settings):
                self._runner = await self._activate_selected_provider()
            yield self
        finally:
            self._is_active = False
            self._runner = _initial_runner(self._settings)
            await self._cancel_active_turns()

    async def _cancel_active_turns(self) -> None:
        current_task = asyncio.current_task()
        active_turns = tuple(
            task for task in self._active_turns if task is not current_task and not task.done()
        )
        for task in active_turns:
            task.cancel()
        if active_turns:
            await _await_owned_operation(_settle_tasks(active_turns))
        for task in active_turns:
            self._active_turns.discard(task)

    async def _activate_selected_provider(self) -> OperatorTurnRunner:
        provider = self._settings.operator.provider
        if provider is None:
            return _unconfigured_runner(self._settings)
        overlength_fields = _overlength_provider_options(self._settings)
        if overlength_fields:
            label = " and ".join(overlength_fields)
            verb = "exceeds" if len(overlength_fields) == 1 else "exceed"
            return _unavailable_runner(
                self._settings,
                explanation=(
                    f"The configured {provider.value.title()} Operator {label} "
                    f"{verb} the {_PROVIDER_OPTION_CHARACTER_LIMIT}-character limit."
                ),
                setup_action=(
                    f"Set the Operator or {provider.value.title()} {label} to at most "
                    f"{_PROVIDER_OPTION_CHARACTER_LIMIT} characters in "
                    f"`{self._settings.config_path}`, then restart Banksia."
                ),
            )
        try:
            match provider:
                case OperatorProvider.CLAUDE:
                    return await self._activate_claude()
                case OperatorProvider.CODEX:
                    return await self._activate_codex()
        except Exception:
            return _unavailable_runner(
                self._settings,
                explanation=(
                    f"Banksia could not verify the configured {provider.value.title()} "
                    "Operator provider."
                ),
                setup_action=(
                    f"Run `banksia providers check {provider.value}`, then restart Banksia."
                ),
            )

    async def _activate_claude(self) -> OperatorTurnRunner:
        status = _available_status(self._settings)
        try:
            resolve_claude_operator_effort(status.effort)
        except OperatorProviderUnavailableError:
            return _unavailable_runner(
                self._settings,
                explanation="The configured Claude Operator effort is not supported.",
                setup_action=(
                    "Set the Operator or Claude effort to `low`, `medium`, `high`, "
                    f"`xhigh`, or `max` in `{self._settings.config_path}`, then restart Banksia."
                ),
            )
        readiness = await _await_owned_operation(
            asyncio.to_thread(read_claude_invocation_readiness)
        )
        if not readiness.is_available:
            return _authentication_unavailable_runner(
                self._settings,
                code=readiness.code,
            )
        working_directory = self._settings.data_dir / "operator" / "claude"
        working_directory.mkdir(parents=True, exist_ok=True)
        return ClaudeOperatorTurnRunner(
            system_prompt=self._system_prompt,
            tools=self._tools,
            status=status,
            working_directory=working_directory,
        )

    async def _activate_codex(self) -> OperatorTurnRunner:
        status = _available_status(self._settings)
        try:
            resolve_codex_operator_effort(status.effort)
        except OperatorProviderUnavailableError:
            return _unavailable_runner(
                self._settings,
                explanation="The configured Codex Operator effort is not supported.",
                setup_action=(
                    "Set the Operator or Codex effort to `none`, `minimal`, `low`, "
                    f"`medium`, `high`, `xhigh`, `max`, or `ultra` in "
                    f"`{self._settings.config_path}`, then restart Banksia."
                ),
            )
        authentication = await _read_codex_authentication()
        if not authentication.is_authenticated:
            return _authentication_unavailable_runner(
                self._settings,
                code=authentication.code,
            )
        return CodexOperatorTurnRunner(
            system_prompt=self._system_prompt,
            tools=self._tools,
            status=status,
        )


def build_operator_turn_runner(
    *,
    settings: Settings,
    system_prompt: str,
    tools: Sequence[OperatorTool],
) -> ConfiguredOperatorTurnRunner:
    return ConfiguredOperatorTurnRunner(
        settings=settings,
        system_prompt=system_prompt,
        tools=tools,
    )


async def _read_codex_authentication() -> _AuthenticationReadiness:
    """Read native Codex account availability and close the short-lived client."""

    try:
        client = AsyncCodex(
            CodexConfig(env=provider_subprocess_environment_overrides()),
        )
    except Exception:
        return _AuthenticationReadiness(False, "codex_check_failed")

    account = None
    failed = False
    try:
        account = await asyncio.wait_for(
            client.account(),
            timeout=_OPERATOR_READINESS_TIMEOUT_SECONDS,
        )
    except Exception:
        failed = True
    finally:
        try:
            await _await_owned_operation(
                asyncio.wait_for(
                    client.close(),
                    timeout=_OPERATOR_READINESS_TIMEOUT_SECONDS,
                )
            )
        except Exception:
            failed = True

    if failed or account is None:
        return _AuthenticationReadiness(False, "codex_check_failed")
    if account.account is None and account.requires_openai_auth:
        return _AuthenticationReadiness(False, "codex_authentication_required")
    return _AuthenticationReadiness(True, "codex_available")


def _initial_runner(settings: Settings) -> OperatorTurnRunner:
    provider = settings.operator.provider
    if provider is None:
        return _unconfigured_runner(settings)
    if not _selected_provider_is_enabled(settings):
        return _unavailable_runner(
            settings,
            explanation=f"The configured {provider.value.title()} Operator provider is disabled.",
            setup_action=(
                f"Run `banksia providers configure {provider.value}`, then restart Banksia."
            ),
        )
    return _unavailable_runner(
        settings,
        explanation="Operator readiness will be checked when Banksia starts.",
        setup_action=f"Run `banksia providers check {provider.value}` if startup cannot verify it.",
    )


def _unconfigured_runner(settings: Settings) -> OperatorTurnRunner:
    return UnavailableOperatorTurnRunner(
        OperatorRunnerStatus(
            availability="unconfigured",
            configured_provider=None,
            explanation="Operator is not configured with a provider.",
            setup_action=(
                f'Add `[operator]` with `provider = "claude"` or `provider = "codex"` '
                f"to `{settings.config_path}`; run `banksia providers configure <provider>` "
                "and `banksia providers check <provider>` for that provider "
                "(`banksia providers login <provider>` if prompted), then restart Banksia."
            ),
        )
    )


def _selected_provider_is_enabled(settings: Settings) -> bool:
    match settings.operator.provider:
        case OperatorProvider.CLAUDE:
            return settings.claude.enabled
        case OperatorProvider.CODEX:
            return settings.codex.enabled
        case None:
            return False


def _available_status(settings: Settings) -> OperatorRunnerStatus:
    provider = settings.operator.provider
    if provider is None:
        raise RuntimeError("an available Operator status requires a provider")
    model, effort = _resolved_provider_options(settings)
    if _overlength_provider_options(settings):
        raise ValueError("Operator provider model and effort must not exceed 255 characters")
    return OperatorRunnerStatus(
        availability="available",
        configured_provider=provider.value,
        explanation=f"Operator is ready with {provider.value.title()}.",
        model=model,
        effort=effort,
    )


def _authentication_unavailable_runner(
    settings: Settings,
    *,
    code: str,
) -> OperatorTurnRunner:
    provider = settings.operator.provider
    if provider is None:
        return UnavailableOperatorTurnRunner()
    if code.endswith("_authentication_required"):
        return _unavailable_runner(
            settings,
            explanation=(
                f"The configured {provider.value.title()} Operator provider is not authenticated."
            ),
            setup_action=(f"Run `banksia providers login {provider.value}`, then restart Banksia."),
        )
    return _unavailable_runner(
        settings,
        explanation=(
            f"Banksia could not verify the configured {provider.value.title()} Operator provider."
        ),
        setup_action=f"Run `banksia providers check {provider.value}`, then restart Banksia.",
    )


def _unavailable_runner(
    settings: Settings,
    *,
    explanation: str,
    setup_action: str,
) -> OperatorTurnRunner:
    provider = settings.operator.provider
    model, effort = _resolved_provider_options(settings)
    return UnavailableOperatorTurnRunner(
        OperatorRunnerStatus(
            availability="unavailable",
            configured_provider=provider.value if provider is not None else None,
            explanation=explanation,
            setup_action=setup_action,
            model=model,
            effort=effort,
        )
    )


def _resolved_provider_options(settings: Settings) -> tuple[str | None, str | None]:
    match settings.operator.provider:
        case OperatorProvider.CLAUDE:
            provider_model = settings.claude.model
            provider_effort = settings.claude.effort
        case OperatorProvider.CODEX:
            provider_model = settings.codex.model
            provider_effort = settings.codex.effort
        case None:
            return None, None
    return (
        settings.operator.model or provider_model or None,
        settings.operator.effort or provider_effort or None,
    )


def _overlength_provider_options(settings: Settings) -> tuple[str, ...]:
    model, effort = _resolved_provider_options(settings)
    return tuple(
        field
        for field, value in (("model", model), ("effort", effort))
        if value is not None and len(value) > _PROVIDER_OPTION_CHARACTER_LIMIT
    )


async def _capture_async_outcome(
    operation: Awaitable[_AsyncResult],
) -> _AsyncOutcome[_AsyncResult]:
    try:
        return _AsyncOutcome(result=await operation)
    except BaseException as exc:
        return _AsyncOutcome(error=exc)


async def _await_owned_operation(operation: Awaitable[_AsyncResult]) -> _AsyncResult:
    """Defer owner cancellation until one bounded child operation has settled."""

    operation_task = asyncio.create_task(_capture_async_outcome(operation))
    pending_cancellation: asyncio.CancelledError | None = None
    while not operation_task.done():
        try:
            await asyncio.shield(operation_task)
        except asyncio.CancelledError as exc:
            pending_cancellation = pending_cancellation or exc
    outcome = operation_task.result()
    if pending_cancellation is not None:
        raise pending_cancellation
    if outcome.error is not None:
        raise outcome.error
    return cast(_AsyncResult, outcome.result)


async def _settle_tasks(tasks: tuple[asyncio.Task[object], ...]) -> None:
    await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "ConfiguredOperatorTurnRunner",
    "build_operator_turn_runner",
]
