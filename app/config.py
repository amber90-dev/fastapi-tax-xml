from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    database_url: str = "postgresql+psycopg2://tax:tax@localhost:5432/tax"
    # Illustrative rules only -- not real tax law. Kept in config so they can change per year.
    income_tax_rate: Decimal = Decimal("0.15")
    taxpayer_credit_cents: int = 3_084_000
    flat_rate_expense_share: Decimal = Decimal("0.60")
    flat_rate_expense_cap_cents: int = 120_000_000


settings = Settings()
