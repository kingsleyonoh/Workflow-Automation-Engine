"""Environment configuration loader using pydantic-settings.

Loads all environment variables with sensible defaults for local development.
Values can be overridden via .env file or environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    env: str = "development"
    log_level: str = "info"

    # Tenant Management
    self_registration_enabled: bool = True
    default_tenant_name: str = "Default"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows"
    test_database_url: str = (
        "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows_test"
    )
    redis_url: str = "redis://localhost:6380"

    # Execution
    max_steps_per_workflow: int = 50
    max_concurrent_steps: int = 10
    execution_timeout_seconds: int = 300
    http_step_timeout: int = 30
    max_response_body_size: int = 1_048_576
    max_sub_workflow_depth: int = 3

    # Webhooks
    max_payload_size: int = 1_048_576
    webhook_replay_enabled: bool = True

    # Scheduler
    cron_timezone: str = "UTC"
    max_cron_workflows: int = 50

    # Workers
    arq_concurrency: int = 10
    arq_max_jobs: int = 100

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.env == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.env == "production"

    @property
    def is_testing(self) -> bool:
        """Check if running in test mode."""
        return self.env == "testing"


settings = Settings()
