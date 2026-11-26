from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_INSECURE_SECRETS = {
    "",
    "change-me",
    "secret",
    "dev-secret",
    "hormozgan-dev-secret-change-in-production",
    "placeholder",
}

KNOWN_SAMPLE_PASSWORDS = {
    "admin123",
    "123456",
    "password",
    "demo1234",
    "Admin@1234",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "هرمزگان بیدار — نسخهٔ ۲"
    app_env: str = "development"  # development | test | production
    database_url: str = "postgresql+asyncpg://hb_app:hb_dev_password@127.0.0.1:5432/hormozgan_bidar"
    database_admin_url: str = "postgresql+asyncpg://hb_admin:hb_dev_password@127.0.0.1:5432/hormozgan_bidar"
    secret_key: str = "local-ephemeral-dev-key-not-for-prod-9f8e7d6c5b4a3210"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    session_idle_minutes: int = 120
    session_absolute_hours: int = 24
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    trusted_proxies: str = "127.0.0.1,::1"

    # Rate limits (shared DB-backed)
    login_rate_limit_max_attempts: int = 8
    login_rate_limit_window_seconds: int = 300
    login_rate_limit_lock_seconds: int = 300

    # Configurable business rules (explicitly separated from fixed decisions)
    auto_score_daily_login: int = 1
    auto_score_timely_action: int = 4
    auto_score_success: int = 5
    sla_hours_urgent: int = 2
    sla_hours_medium: int = 24
    sla_hours_normal: int = 72
    export_max_rows: int = 10000
    reminder_poll_seconds: int = 3
    presence_ttl_seconds: int = 45

    # Seed settings
    demo_seed_enabled: bool = True
    admin_initial_username: str = "admin"
    admin_initial_password: str = ""

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV باید یکی از {allowed} باشد")
        return v

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def trusted_proxies_list(self) -> List[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    def validate_production_safety(self) -> None:
        if self.app_env == "production":
            if not self.cookie_secure:
                raise RuntimeError("در محیط production فعال‌بودن HTTPS و COOKIE_SECURE=true الزامی است.")
            if self.secret_key.strip() in DEFAULT_INSECURE_SECRETS or len(self.secret_key.strip()) < 32:
                raise RuntimeError("در محیط production باید SECRET_KEY امن با طول حداقل ۳۲ کاراکتر تنظیم شود.")
            if self.admin_initial_password and self.admin_initial_password in KNOWN_SAMPLE_PASSWORDS:
                raise RuntimeError("در محیط production استفاده از رمز نمونه برای ادمین مجاز نیست.")
            if self.demo_seed_enabled:
                raise RuntimeError("در محیط production باید DEMO_SEED_ENABLED=false باشد.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
