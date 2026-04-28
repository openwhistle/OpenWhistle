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
    app_version: str = "1.1.0"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"

    # LDAP / Active Directory login (optional)
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_port: int = 389
    ldap_use_ssl: bool = False
    ldap_bind_dn: str = ""           # service account DN for the initial bind
    ldap_bind_password: str = ""
    ldap_base_dn: str = ""           # search base, e.g. "ou=users,dc=example,dc=com"
    ldap_user_filter: str = "(uid={username})"  # {username} is replaced at runtime
    ldap_attr_username: str = "uid"
    ldap_attr_email: str = "mail"

    # Attachment storage backend
    storage_backend: str = "db"          # "db" or "s3"
    s3_endpoint_url: str = ""            # leave blank for AWS S3; set for MinIO / Hetzner / etc.
    s3_bucket_name: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    s3_prefix: str = "attachments/"

    # SLA reminders (background scheduler)
    reminder_enabled: bool = False
    reminder_ack_warn_days: int = 2     # warn N days before the 7-day ack deadline
    reminder_feedback_warn_days: int = 30  # warn N days before the 3-month feedback deadline

    # Submission mode
    submission_mode_enabled: bool = True

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
    notify_webhook_type: str = "generic"  # "generic", "slack", or "teams"

    # Data-retention policy (GDPR Art. 5 storage limitation)
    retention_enabled: bool = False
    retention_days: int = 1095  # 3 years — HinSchG §12 Abs. 3 minimum

    # Multi-tenancy
    multi_tenancy_enabled: bool = False
    default_org_slug: str = "default"


settings = Settings()  # type: ignore[call-arg]
