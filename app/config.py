import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "data/sync.db")
    api_key: str = os.getenv("API_KEY", "dev-change-me")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    sync_target_url: str = os.getenv("SYNC_TARGET_URL", "")
    sync_target_token: str = os.getenv("SYNC_TARGET_TOKEN", "")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))


settings = Settings()
