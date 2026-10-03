"""Settings come from environment only. Secrets are never defaulted or logged.

Oracle connectivity - choose ONE driver:
  * ODBC   (existing CityKart pattern): ORACLE_ODBC_DSN=<Windows ODBC DSN name>
            optionally ORACLE_USER / ORACLE_PASSWORD if the DSN does not store them,
            or ORACLE_ODBC_CONNECTION_STRING=<full pyodbc connection string>.
  * oracledb thin: ORACLE_DSN=host:1521/service + ORACLE_USER + ORACLE_PASSWORD.
ORACLE_DRIVER=odbc|oracledb forces a choice; by default ODBC is used when an ODBC setting exists."""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    oracle_driver: str | None = None            # odbc | oracledb
    oracle_dsn: str | None = None               # oracledb: host:port/service
    oracle_user: str | None = None
    oracle_password: SecretStr | None = None
    oracle_odbc_dsn: str | None = None          # ODBC data source name
    oracle_odbc_connection_string: SecretStr | None = None
    database_url: str | None = None

    @property
    def resolved_driver(self) -> str | None:
        if self.oracle_driver:
            return self.oracle_driver.lower()
        if self.oracle_odbc_dsn or self.oracle_odbc_connection_string:
            return "odbc"
        if self.oracle_dsn:
            return "oracledb"
        return None

    @property
    def oracle_configured(self) -> bool:
        d = self.resolved_driver
        if d == "odbc":
            return bool(self.oracle_odbc_dsn or self.oracle_odbc_connection_string)
        if d == "oracledb":
            return bool(self.oracle_dsn and self.oracle_user and self.oracle_password)
        return False

    def secret_values(self) -> list[str]:
        vals = [self.oracle_user, self.oracle_dsn, self.oracle_odbc_dsn]
        for s in (self.oracle_password, self.oracle_odbc_connection_string):
            if s:
                vals.append(s.get_secret_value())
        return [v for v in vals if v]
