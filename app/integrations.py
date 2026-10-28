import httpx

from app.config import settings


async def deliver(resource: str, payload: dict) -> dict:
    if not settings.sync_target_url:
        raise RuntimeError("SYNC_TARGET_URL is not configured")

    headers = {"Content-Type": "application/json"}
    if settings.sync_target_token:
        headers["Authorization"] = f"Bearer {settings.sync_target_token}"

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(
            f"{settings.sync_target_url.rstrip('/')}/{resource}",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
    return {"status": "delivered", "http_status": response.status_code}
