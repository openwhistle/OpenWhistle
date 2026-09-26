"""Every setting is documented and can be set in the shipped Compose file."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).parents[1]

# Set by the image itself; a Compose default would pin a stale version.
_NOT_IN_COMPOSE = {"APP_VERSION"}


def test_every_setting_has_a_row_in_the_docs_env_table() -> None:
    docs = (ROOT / "docs/docs.html").read_text()
    rows = set(re.findall(r'<code class="env-key">([A-Z0-9_]+)</code>', docs))
    missing = [n.upper() for n in Settings.model_fields if n.upper() not in rows]
    assert not missing, missing


def test_every_setting_is_in_docker_compose_prod() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    keys = set(re.findall(r"^      ([A-Z0-9_]+): ", compose, re.M))
    missing = [
        n.upper() for n in Settings.model_fields
        if n.upper() not in keys and n.upper() not in _NOT_IN_COMPOSE
    ]
    assert not missing, missing
