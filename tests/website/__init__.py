def require_url(base: str, ci: str) -> bool:
    """True when the container tests may run; False skips them. In CI a missing URL is an error."""
    if not base and ci:
        raise RuntimeError(
            "WEBSITE_URL is not set in CI: the container tests would be skipped silently"
        )
    return bool(base)
