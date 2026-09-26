import logging
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A v3 onion address is 56 base32 characters (RFC 4648, lowercase a-z2-7).
_ONION_LOCATION_RE = re.compile(r"^https?://[a-z2-7]{56}\.onion$", re.IGNORECASE)

# Minimum SECRET_KEY / ENCRYPTION_KEY length. SECRET_KEY signs admin JWTs;
# ENCRYPTION_KEY (falling back to SECRET_KEY when unset) is the root of all
# at-rest encryption — so a weak key collapses the platform's core protection.
_MIN_SECRET_KEY_LEN = 32

# Minimum SETUP_TOKEN length, when one is configured. Long enough that it
# cannot be brute-forced over the /setup form's request budget.
_MIN_SETUP_TOKEN_LEN = 32


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

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        if len(v) < _MIN_SECRET_KEY_LEN:
            raise ValueError(
                f"SECRET_KEY must be at least {_MIN_SECRET_KEY_LEN} characters "
                "(it is the root key for admin authentication and confidential-"
                "identity encryption). Generate one with e.g. "
                "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`."
            )
        return v

    # Root of all at-rest encryption. Empty = SECRET_KEY (pre-v2.0.0 behaviour,
    # warned at startup). Old keys go in ENCRYPTION_KEY_PREVIOUS (comma-separated,
    # no spaces) until scripts/rotate_encryption_key.py has re-encrypted everything.
    encryption_key: str = ""
    encryption_key_previous: str = ""

    @field_validator("encryption_key")
    @classmethod
    def _validate_encryption_key(cls, v: str) -> str:
        if v and len(v) < _MIN_SECRET_KEY_LEN:
            raise ValueError(f"ENCRYPTION_KEY must be at least {_MIN_SECRET_KEY_LEN} characters.")
        return v

    @field_validator("encryption_key_previous")
    @classmethod
    def _validate_encryption_key_previous(cls, v: str) -> str:
        # A key containing a comma is split into fragments; each is refused here.
        if any(len(k) < _MIN_SECRET_KEY_LEN for k in v.split(",") if k):
            raise ValueError(
                f"Every ENCRYPTION_KEY_PREVIOUS entry must be at least {_MIN_SECRET_KEY_LEN} "
                "characters (comma-separated, no spaces; keys cannot contain commas)."
            )
        return v

    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Absolute admin session lifetime, counted from login and never extended by
    # "stay signed in": after this a fresh password + TOTP login is required.
    session_max_hours: int = Field(default=12, ge=1)

    # Whistleblower rate limiting (Redis-based, no IP tracking)
    max_access_attempts: int = 5
    access_lockout_minutes: int = 15

    # Admin rate limiting
    max_login_attempts: int = 10
    login_lockout_minutes: int = 30

    # Password-spraying detection: failed admin password attempts counted
    # instance-wide (no username, no IP). Crossing the threshold within the
    # window sends one alert through the notification channels and writes an
    # audit log entry. 0 disables it.
    admin_failed_login_alert_threshold: int = 50
    admin_failed_login_alert_window_minutes: int = Field(default=15, ge=1)

    # Demo mode
    demo_mode: bool = False

    # Local review only: /admin/login shows a one-click button that signs in as
    # the seeded demo admin with no password or MFA check, so an agent (e.g. the
    # Claude-in-Chrome extension) can review every admin page without a human
    # typing credentials. Requires demo_mode=true (enforced below) — never set
    # this against a real database. See docs-tech/local-review.md.
    local_review_login: bool = False

    # Cookie security — set to false when the app is served over plain HTTP
    # (e.g. local network without TLS). Always keep true behind HTTPS.
    secure_cookies: bool = True

    # First-run setup: whoever opens /setup must also know this token. Empty =
    # a random one is created at startup and logged once at WARNING.
    setup_token: str = ""

    @field_validator("setup_token")
    @classmethod
    def _validate_setup_token(cls, v: str) -> str:
        # Empty means "unset" — this is also what docker-compose.prod.yml's
        # SETUP_TOKEN:-}" interpolates to when the operator never set it —
        # and a random token is generated instead. Anything else must be a
        # real token: no bare whitespace, no length short enough to guess.
        if not v:
            return v
        v = v.strip()
        if not v or len(v) < _MIN_SETUP_TOKEN_LEN:
            raise ValueError(
                f"SETUP_TOKEN must be at least {_MIN_SETUP_TOKEN_LEN} characters (or unset, "
                "to let the app generate one). Generate one with e.g. "
                "`python -c 'import secrets; print(secrets.token_urlsafe(24))'`."
            )
        return v

    # Application
    app_name: str = "OpenWhistle"
    app_version: str = "2.0.0"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"

    # LDAP / Active Directory login (optional)
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_port: int = 389
    ldap_use_ssl: bool = False
    ldap_start_tls: bool = False     # upgrade a plain connection (port 389) before any bind
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

    # New draft attachments are refused while Redis uses more than this share
    # of its maxmemory (no effect when Redis has no maxmemory set).
    draft_redis_memory_percent: int = 80

    # OIDC (optional)
    oidc_enabled: bool = False
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_server_metadata_url: str = ""
    oidc_redirect_uri: str = ""

    # Branding (optional — companies can override defaults)
    brand_primary_color: str = "#0c7253"
    brand_logo_url: str = ""

    # Public base URL used in notification links
    app_public_url: str = "http://localhost"

    # Tor onion address for reporters on a monitored network, e.g.
    # http://<56 base32 chars>.onion — Tor Browser offers it to visitors and the
    # submit page shows it. Empty disables both. See docs/docs.html
    # "Offering an onion address" for how to run the hidden service.
    onion_location: str = ""

    @field_validator("onion_location")
    @classmethod
    def _validate_onion_location(cls, v: str) -> str:
        v = v.strip()
        if v and not _ONION_LOCATION_RE.match(v):
            raise ValueError(
                "ONION_LOCATION must be empty or http(s)://<56-character-onion-address>.onion "
                "with no path or query string, e.g. http://" + "a" * 56 + ".onion."
            )
        return v

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

    # New-report / whistleblower-message notices are sent as one digest every N
    # minutes, so their timing cannot be matched to who was at their desk.
    # 0 sends each one immediately.
    notification_batch_minutes: int = 1440

    # Data-retention policy (GDPR Art. 5 storage limitation)
    retention_enabled: bool = True
    retention_days: int = 1095  # 3 years — HinSchG §11 Abs. 5 deletion deadline

    # Multi-tenancy
    multi_tenancy_enabled: bool = False
    default_org_slug: str = "default"

    # Update check — opt-in check against the GitHub Releases API. Default OFF to
    # preserve the "no external calls" posture and support air-gapped installs.
    # When enabled, a daily background job caches the latest release in Redis and
    # the admin System page surfaces it; no instance data is ever sent to GitHub.
    update_check_enabled: bool = False

    # Virus scan of uploads through clamd (INSTREAM). Empty = off. When set, an
    # upload is refused if clamd cannot be reached: nothing is stored unscanned.
    clamav_host: str = ""
    clamav_port: int = 3310
    clamav_timeout_seconds: int = Field(default=30, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _ignore_removed_settings(cls, data: Any) -> Any:
        # Removed in 2.0.0. A .env file that still sets it is warned about, not
        # refused (pydantic-settings rejects unknown .env keys).
        if isinstance(data, dict) and data.pop("brand_secondary_color", None) is not None:
            logging.getLogger(__name__).warning(
                "BRAND_SECONDARY_COLOR was removed in 2.0.0 and is ignored; delete it."
            )
        return data

    @model_validator(mode="after")
    def _validate_local_review_login(self) -> Settings:
        if self.local_review_login and not self.demo_mode:
            raise ValueError(
                "LOCAL_REVIEW_LOGIN requires DEMO_MODE=true: it signs in as the seeded "
                "demo admin with no password or MFA check, so it must never be reachable "
                "against a real database. Refusing to start."
            )
        # DEMO_MODE alone is not enough: the public demo runs with it. A local review
        # stack is plain HTTP on a loopback URL; anything else is a reachable server.
        host = (urlsplit(self.app_public_url).hostname or "").lower()
        if self.local_review_login and (
            host not in {"localhost", "127.0.0.1", "::1"} or self.secure_cookies
        ):
            raise ValueError(
                "LOCAL_REVIEW_LOGIN requires a loopback APP_PUBLIC_URL and "
                "SECURE_COOKIES=false: it is for a review stack on this machine only. "
                "Refusing to start."
            )
        return self


settings = Settings()  # type: ignore[call-arg]
