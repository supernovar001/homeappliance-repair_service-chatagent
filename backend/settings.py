# -*- coding: utf-8 -*-
"""환경변수 설정. 값은 .env 또는 Railway 변수에서 읽습니다."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _database_url(raw):
    # Railway는 postgresql:// 형식으로 줍니다. SQLAlchemy가 psycopg3 드라이버를 쓰도록 바꿉니다.
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


def _emails(raw):
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


@dataclass(frozen=True)
class Settings:
    base_url: str = field(default_factory=lambda: os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"))
    database_url: str = field(default_factory=lambda: _database_url(os.getenv("DATABASE_URL", "postgresql://washcare:washcare@localhost:5433/washcare")))
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_SECRET", ""))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", ""))
    admin_emails: frozenset = field(default_factory=lambda: _emails(os.getenv("ADMIN_EMAILS", "")))
    # 개발 중 Vite(5173)에서 오는 요청을 허용할 출처. 쉼표로 여러 개를 줄 수 있습니다.
    extra_origins: tuple = field(default_factory=lambda: tuple(o.strip().rstrip("/") for o in os.getenv("EXTRA_ORIGINS", "").split(",") if o.strip()))
    session_days: int = field(default_factory=lambda: int(os.getenv("SESSION_DAYS", "14")))
    retention_days: int = field(default_factory=lambda: int(os.getenv("RETENTION_DAYS", "90")))
    max_concurrent_consults: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_CONSULTS", "2")))
    job_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("JOB_TIMEOUT_SECONDS", "240")))
    rate_limit_count: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_COUNT", "20")))
    rate_limit_minutes: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_MINUTES", "10")))

    @property
    def cookie_secure(self):
        return self.base_url.startswith("https://")

    @property
    def allowed_origins(self):
        parts = urlsplit(self.base_url)
        return {f"{parts.scheme}://{parts.netloc}", *self.extra_origins}


settings = Settings()
