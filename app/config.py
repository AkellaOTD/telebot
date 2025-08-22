from pydantic_settings import BaseSettings
from pydantic import AnyUrl, Field
from typing import List

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMINS: List[int] = Field(default_factory=list)
    ADMIN_GROUP_ID: int
    ADMIN_LOG_CHANNEL_ID: int

    USE_WEBHOOK: bool = False
    WEBHOOK_BASE: str | None = None
    WEBHOOK_SECRET: str | None = None
    PORT: int = 8080

    DATABASE_URL: AnyUrl = "sqlite+aiosqlite:///./data/bot.db"  # type: ignore

    MAX_PHOTOS: int = 20
    BAD_WORDS: List[str] = Field(default_factory=list)
    PHASH_HAMMING_THRESHOLD: int = 6
    RATE_LIMIT_PER_MINUTE: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

settings = Settings()
