from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://openwhistle:openwhistle@localhost:5432/openwhistle"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security — no default; must be set in environment
    secret_key: str

    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Whistleblower rate limiting (Redis-based, no IP tracking)
    max_access_attempts: int = 5
    access_lockout_minutes: int = 15

    # Admin rate limiting
    max_login_attempts: int = 10
    login_lockout_minutes: int = 30

    # Demo mode
    demo_mode: bool = False

    # Application
    app_name: str = "OpenWhistle"
    app_version: str = "0.1.0"

    # OIDC (optional)
    oidc_enabled: bool = False
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_server_metadata_url: str = ""
    oidc_redirect_uri: str = ""

    # Branding (optional — companies can override defaults)
    brand_primary_color: str = "#0f4c81"
    brand_secondary_color: str = "#b07230"
    brand_logo_url: str = ""

    # Public base URL used in notification links
    app_public_url: str = "http://localhost"

    # Email notifications (SMTP)
    notify_email_enabled: bool = False
    notify_email_to: str = ""          # comma-separated list of recipients
    notify_email_from: str = "openwhistle@localhost"
    notify_smtp_host: str = "localhost"
    notify_smtp_port: int = 587
    notify_smtp_user: str = ""
    notify_smtp_password: str = ""
    notify_smtp_tls: bool = True       # STARTTLS
    notify_smtp_ssl: bool = False      # SMTPS (port 465)

    # Webhook notifications (HTTP POST)
    notify_webhook_enabled: bool = False
    notify_webhook_url: str = ""
    notify_webhook_secret: str = ""    # HMAC-SHA256 signing secret (optional)


settings = Settings()  # type: ignore[call-arg]
