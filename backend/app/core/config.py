from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "production"] = "dev"
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias=AliasChoices("DATABASE_URL", "DATABASE_PATH"),
    )
    session_secret: str = Field(
        default="development-only-change-me",
        validation_alias=AliasChoices("APP_SECRET_KEY", "SESSION_SECRET"),
    )
    session_cookie_name: str = "boyan_session"
    cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("SESSION_SECURE", "COOKIE_SECURE"),
    )
    session_samesite: Literal["lax", "strict"] = "lax"
    csrf_secret: str = "development-only-change-me"
    storage_backend: Literal["local", "oss"] = "local"
    local_storage_root: str = "D:/boyan-data/attachments"
    local_temp_root: str = "D:/boyan-data/temp"
    upload_max_image_bytes: int = 10 * 1024 * 1024
    upload_max_pdf_bytes: int = 20 * 1024 * 1024
    upload_max_office_bytes: int = 20 * 1024 * 1024
    upload_staged_ttl_hours: int = 24
    file_local_retention_days: int = 30
    pii_encryption_key: str = Field(
        default="", validation_alias=AliasChoices("PII_ENCRYPTION_KEY", "DATA_ENCRYPTION_KEY")
    )
    pii_blind_index_key: str = ""
    log_level: str = "INFO"
    backup_local_dir: str = "./backups"
    import_max_bytes: int = 10 * 1024 * 1024
    import_max_rows: int = 2000

    @property
    def sqlite_database_url(self) -> str:
        if self.database_url.startswith("sqlite:"):
            return self.database_url
        return f"sqlite:///{self.database_url}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.storage_backend == "oss":
        raise RuntimeError("OSS后端尚未实现；请设置 STORAGE_BACKEND=local")
    storage_root = Path(settings.local_storage_root).expanduser()
    temp_root = Path(settings.local_temp_root).expanduser()
    if storage_root == storage_root.anchor or temp_root == temp_root.anchor:
        raise RuntimeError("LOCAL_STORAGE_ROOT 和 LOCAL_TEMP_ROOT 不能是磁盘根目录")
    if settings.app_env == "production":
        if (
            len(settings.session_secret) < 32
            or settings.session_secret == "development-only-change-me"
        ):
            raise RuntimeError("SESSION_SECRET must be a unique secret of at least 32 characters")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production")
        if len(settings.csrf_secret) < 32 or settings.csrf_secret == "development-only-change-me":
            raise RuntimeError("CSRF_SECRET must be a unique secret of at least 32 characters")
        if not settings.pii_encryption_key:
            raise RuntimeError("PII_ENCRYPTION_KEY is required in production")
        if not settings.sqlite_database_url.startswith("sqlite:"):
            raise RuntimeError("DATABASE_URL must use SQLite during the first deployment phase")
    return settings
