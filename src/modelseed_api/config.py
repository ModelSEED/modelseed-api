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

    # Storage backend: "workspace" (PATRIC) or "local" (filesystem)
    storage_backend: str = "workspace"
    local_data_dir: str = "~/.modelseed/data"

    # PATRIC Workspace Service (only used when storage_backend == "workspace")
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

    # RAST legacy database (optional, leave empty to disable /api/rast/jobs)
    rast_db_host: str = ""
    rast_db_port: int = 3306
    rast_db_user: str = ""
    rast_db_password: str = ""
    rast_db_name: str = "RastProdJobCache"

    # MSSeedSupportServer JSON-RPC URL (used by /api/rast/genome to fetch
    # annotated genomes from RAST jobs). Leave empty to disable that endpoint.
    # DEPRECATED once rast_jobs_dir is configured: the filesystem reader
    # supersedes the MSSS proxy. Kept temporarily as a fallback during the
    # bake period; will be removed in a follow-up PR.
    modelseed_msss_url: str = "https://modelseed.org/services/ms_fba"

    # RAST jobs filesystem directory (used by /api/rast/genome to fetch
    # annotated genomes directly from disk via the FIGV-on-disk format).
    # Leave empty (default) for local/standalone deployments without RAST
    # data on disk; the route handlers return 503 in that case. Production
    # poplar deployment sets this to "/vol/rast-prod/jobs" via .env.
    rast_jobs_dir: str = ""

    # Persistent index file for /api/rast/jobs (job_id -> user metadata).
    # Built at container startup; sub-millisecond reads thereafter. Leave
    # empty to use the default in-container path /tmp/rast_user_index.json.
    rast_index_path: str = ""

    # Timeouts
    workspace_timeout: int = 1800  # 30 minutes (matching existing client)

    model_config = {"env_prefix": "MODELSEED_", "env_file": ".env"}


settings = Settings()
