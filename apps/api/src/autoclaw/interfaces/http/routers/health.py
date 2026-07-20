from fastapi import APIRouter, HTTPException, status

from autoclaw.interfaces.http.contracts.health import HealthResponse
from autoclaw.persistence.session import ping_database

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok", service="autoclaw-api")


@router.get("/readyz", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def readyz() -> HealthResponse:
    try:
        await ping_database()
    except Exception as exc:  # pragma: no cover - readiness degrades without DB
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database_unavailable",
        ) from exc

    return HealthResponse(status="ready", service="autoclaw-api")
