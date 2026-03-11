"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ModelSEED API configuration.

    All settings can be overridden via environment variables prefixed with MODELSEED_.
    Example: MODELSEED_DEBUG=true, MODELSEED_WORKSPACE_URL=https://...
    """

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = ["*"]

    # PATRIC Workspace Service
    workspace_url: str = "https://p3.theseed.org/services/Workspace"

    # Shock file storage
    shock_url: str = "https://p3.theseed.org/services/shock_api"

    # Authentication endpoints (for reference/validation, not used directly by API)
    rast_auth_url: str = "https://p3.theseed.org/Sessions/Login"
    patric_auth_url: str = "https://user.patricbrc.org/authenticate"

    # Workspace paths
    public_media_path: str = "/chenry/public/modelsupport/media"
    public_plants_path: str = "/plantseed/plantseed/"

    # Local data paths (override via .env or MODELSEED_ env vars)
    modelseed_db_path: str = ""
    templates_path: str = ""
    cb_annotation_ontology_api_path: str = ""

    # Job scripts (subprocess fallback for local dev)
    job_scripts_dir: str = "src/job_scripts"
    job_store_dir: str = "/tmp/modelseed-jobs"

    # Celery (bioseed scheduler)
    celery_broker_url: str = "redis://bioseed_redis:6379/10"
    celery_result_backend: str = "redis://bioseed_redis:6379/10"
    use_celery: bool = False  # Set True in production to use bioseed scheduler

    # Timeouts
    workspace_timeout: int = 1800  # 30 minutes (matching existing client)

    model_config = {"env_prefix": "MODELSEED_", "env_file": ".env"}


settings = Settings()
