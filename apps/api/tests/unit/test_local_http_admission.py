from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from autoclaw.config import Settings
from autoclaw.interfaces.http.dependencies import read_control_actor_ref
from autoclaw.interfaces.http.local_admission import add_local_control_plane_middleware
from fastapi import FastAPI, Response, status
from httpx import ASGITransport, AsyncClient
from httpx import Response as HttpxResponse

_API_ORIGIN = "http://127.0.0.1:18125"
_ALLOWED_DEVELOPMENT_ORIGIN = "http://localhost:5173"


def _assert_local_admission_failure(response: HttpxResponse, *, status_code: int) -> None:
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/json"
    failure = response.json()
    assert set(failure) == {
        "ok",
        "code",
        "summary",
        "retryable",
        "field_path",
        "suggested_next_step",
    }
    assert failure["ok"] is False
    assert failure["code"] == "local_admission_denied"
    assert failure["retryable"] is False
    assert failure["field_path"] is None
    assert isinstance(failure["summary"], str) and failure["summary"]
    assert isinstance(failure["suggested_next_step"], str)


async def test_local_operator_actor_provenance_is_stable() -> None:
    assert await read_control_actor_ref() == "local_operator"


def _create_probe_app() -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    admitted_methods: list[str] = []

    @app.api_route("/probe", methods=["GET", "POST"])
    async def probe() -> Response:
        admitted_methods.append("admitted")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    add_local_control_plane_middleware(
        app,
        Settings(
            api_host="127.0.0.1",
            api_port=18125,
            console_origins=[_ALLOWED_DEVELOPMENT_ORIGIN],
        ),
    )
    return app, admitted_methods


@asynccontextmanager
async def _client(
    app: FastAPI,
    *,
    client_host: str | None = "127.0.0.1",
) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(
        app=app,
        client=None if client_host is None else (client_host, 43125),  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=transport, base_url=_API_ORIGIN) as client:
        yield client


@pytest.mark.parametrize(
    "host_header",
    ["127.0.0.1:18125", "localhost:18125", "[::1]:18125"],
)
async def test_local_admission_accepts_exact_loopback_authorities(host_header: str) -> None:
    app, admitted_methods = _create_probe_app()

    async with _client(app) as client:
        response = await client.get("/probe", headers={"Host": host_header})

    assert response.status_code == 204
    assert admitted_methods == ["admitted"]


@pytest.mark.parametrize(
    "host_header",
    [
        "127.0.0.1",
        "127.0.0.1:18126",
        "[::1]",
        "attacker.example:18125",
        "user@127.0.0.1:18125",
        "127.0.0.1:+18125",
        "127.0.0.1: 18125",
        "[::1%25lo0]:18125",
        "[::1]]:18125",
    ],
)
async def test_local_admission_rejects_unapproved_or_inexact_host(
    host_header: str,
) -> None:
    app, admitted_methods = _create_probe_app()

    async with _client(app) as client:
        response = await client.get("/probe", headers={"Host": host_header})

    _assert_local_admission_failure(response, status_code=400)
    assert admitted_methods == []


async def test_local_admission_rejects_a_non_loopback_peer_before_route_work() -> None:
    app, admitted_methods = _create_probe_app()

    async with _client(app, client_host="198.51.100.12") as client:
        response = await client.get("/probe")

    _assert_local_admission_failure(response, status_code=403)
    assert admitted_methods == []


async def test_local_admission_allows_missing_peer_information() -> None:
    app, admitted_methods = _create_probe_app()

    async with _client(app, client_host=None) as client:
        response = await client.get("/probe")

    assert response.status_code == 204
    assert admitted_methods == ["admitted"]


async def test_unsafe_request_origin_is_exact_and_missing_origin_remains_local_cli_safe() -> None:
    app, admitted_methods = _create_probe_app()

    async with _client(app) as client:
        missing_origin = await client.post("/probe")
        allowed_origin = await client.post(
            "/probe",
            headers={"Origin": _ALLOWED_DEVELOPMENT_ORIGIN},
        )
        disallowed_origin = await client.post(
            "/probe",
            headers={"Origin": "https://attacker.example"},
        )

    assert missing_origin.status_code == 204
    assert allowed_origin.status_code == 204
    assert allowed_origin.headers["access-control-allow-origin"] == _ALLOWED_DEVELOPMENT_ORIGIN
    assert "access-control-allow-credentials" not in allowed_origin.headers
    _assert_local_admission_failure(disallowed_origin, status_code=403)
    assert admitted_methods == ["admitted", "admitted"]


async def test_development_cors_accepts_only_enumerated_origin_method_and_headers() -> None:
    app, admitted_methods = _create_probe_app()
    preflight_headers = {
        "Access-Control-Request-Headers": "content-type,last-event-id",
        "Access-Control-Request-Method": "POST",
        "Origin": _ALLOWED_DEVELOPMENT_ORIGIN,
    }

    async with _client(app) as client:
        allowed = await client.options("/probe", headers=preflight_headers)
        rejected = await client.options(
            "/probe",
            headers={**preflight_headers, "Origin": "http://attacker.example"},
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == _ALLOWED_DEVELOPMENT_ORIGIN
    assert "access-control-allow-credentials" not in allowed.headers
    _assert_local_admission_failure(rejected, status_code=400)
    assert admitted_methods == []
