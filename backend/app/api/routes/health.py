import httpx
from fastapi import APIRouter, Response, status

from app.container import container
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.app_env,
        "providers": {
            "realtime": settings.realtime_provider,
            "asr": settings.asr_provider,
            "llm": settings.llm_provider,
            "tts": settings.tts_provider,
            "avatar": settings.avatar_provider,
        },
        "activeSessions": container.sessions.active_count,
    }


def _missing_realtime_settings() -> list[str]:
    settings = get_settings()
    provider = settings.realtime_provider.strip().lower()
    if provider == "doubao":
        values = {
            "DOUBAO_APP_ID": settings.doubao_app_id,
            "DOUBAO_ACCESS_KEY": settings.doubao_access_key,
            "DOUBAO_RESOURCE_ID": settings.doubao_resource_id,
            "DOUBAO_APP_KEY": settings.doubao_app_key,
        }
    elif provider == "bailian":
        values = {"BAILIAN_API_KEY": settings.bailian_api_key}
    else:
        return [f"unsupported realtime provider: {settings.realtime_provider}"]
    return [name for name, value in values.items() if not value.strip()]


async def _livetalking_ready() -> tuple[bool, str | None]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.livetalking_base_url.rstrip('/')}/")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return False, str(exc)
    return True, None


@router.get("/ready")
async def ready(response: Response) -> dict:
    missing = _missing_realtime_settings()
    avatar_ready, avatar_error = await _livetalking_ready()
    ready_now = not missing and avatar_ready
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready_now else "not_ready",
        "realtimeConfigured": not missing,
        "missingSettings": missing,
        "livetalking": {
            "ready": avatar_ready,
            "error": avatar_error,
        },
        "activeSessions": container.sessions.active_count,
    }
