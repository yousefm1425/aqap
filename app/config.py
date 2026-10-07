from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AQAP_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql://aqap:aqap@localhost:5432/aqap"

    # المصادقة: HS256 للتطوير، أو JWKS لمزوّد الدخول الموحّد في الإنتاج
    jwt_secret: str = "change-me-in-production"
    jwt_audience: str = "aqap"
    jwt_issuer: str | None = None
    jwks_url: str | None = None

    # تخزين الشواهد
    storage_backend: Literal["minio", "local"] = "minio"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "aqap-evidence"
    local_storage_dir: str = "./_storage"

    official_template: str | None = None   # مسار ملف نموذج العمل الرسمي (.xlsb) للتصدير

    max_upload_mb: int = 50
    download_url_ttl_seconds: int = 300
    allowed_extensions: set[str] = {
        ".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt",
        ".png", ".jpg", ".jpeg", ".webp", ".csv", ".txt", ".zip", ".mp4",
    }


settings = Settings()
