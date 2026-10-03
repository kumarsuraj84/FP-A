"""Settings come from environment only. Secrets are never defaulted or logged."""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    oracle_dsn: str | None = None
    oracle_user: str | None = None
    oracle_password: SecretStr | None = None
    database_url: str | None = None

    @property
    def oracle_configured(self) -> bool:
        return bool(self.oracle_dsn and self.oracle_user and self.oracle_password)
