"""Configuración. Se lee de variables de entorno y del archivo .env (ver .env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    database_url: str = ""
    run_migrations: bool = True

    jwt_key: str = ""
    jwt_issuer: str = "DeploymentHub"
    jwt_audience: str = "DeploymentHub"
    jwt_expiration_minutes: int = 60

    cors_allowed_origins: str = "http://localhost:5173,https://localhost:5173"

    seed_admin_email: str = ""
    seed_admin_password: str = ""

    krud_issuer: str = ""
    krud_private_jwk: str = ""
    krud_audience: str = "velo-krud"
    krud_lifetime_seconds: int = 60

    email_host: str = ""
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = ""
    # Alternativa a SMTP para hostings que lo bloquean (Render free): un webhook HTTPS (p. ej. Google Apps Script).
    email_webhook_url: str = ""
    email_webhook_secret: str = ""

    notifications_enabled: bool = True
    notifications_public_url: str = ""
    notifications_grouping_seconds: int = Field(default=5)

    application_name: str = "DeploymentHub"
    application_version: str = "2.0"

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() == "development"

    @property
    def sqlalchemy_url(self) -> str:
        """Normaliza la URL al driver psycopg 3 (los proveedores entregan postgres:// o postgresql://)."""
        url = self.database_url.strip()
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.email_host.strip()) and bool(self.email_from.strip())

    @property
    def webhook_configured(self) -> bool:
        return bool(self.email_webhook_url.strip())

    @property
    def krud_enabled(self) -> bool:
        return bool(self.krud_private_jwk.strip()) and bool(self.krud_issuer.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_required(settings: Settings) -> None:
    """La API no arranca con valores sin completar: con una clave de ejemplo cualquiera podría firmar sesiones."""
    missing: list[str] = []
    if not settings.database_url.strip():
        missing.append("DATABASE_URL")
    for name, value in settings.model_dump().items():
        if isinstance(value, str) and value.strip().upper().startswith("COMPLETAR"):
            missing.append(name.upper())
    if missing:
        raise RuntimeError(
            "Faltan valores de configuración: " + ", ".join(sorted(set(missing))) +
            ". Defínelos como variables de entorno o en el archivo .env (ver .env.example)."
        )
    if len(settings.jwt_key.encode("utf-8")) < 32:
        raise RuntimeError(
            "JWT_KEY debe tener al menos 32 bytes. Genera una con: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
