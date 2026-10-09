"""Every setting is documented, once, and can be set in the shipped Compose file."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.config import Settings
from tests.built_site import page

ROOT = Path(__file__).parents[1]
CONFIG = yaml.safe_load((ROOT / "docs/_data/config.yml").read_text(encoding="utf-8"))
DOCUMENTED = [s["name"] for g in CONFIG["groups"] for s in g["settings"]]

# APP_VERSION is set by the image itself; a Compose default would pin a stale
# version. LOCAL_REVIEW_LOGIN must never reach a deployment: only
# docker-compose.review.yml sets it (tests/test_local_review.py).
_NOT_IN_COMPOSE = {"APP_VERSION", "LOCAL_REVIEW_LOGIN"}


def test_config_yml_lists_every_setting_once_and_nothing_else() -> None:
    settings = {n.upper() for n in Settings.model_fields}
    assert len(DOCUMENTED) == len(set(DOCUMENTED)), [
        n for n in DOCUMENTED if DOCUMENTED.count(n) > 1
    ]
    assert set(DOCUMENTED) == settings, {
        "undocumented": sorted(settings - set(DOCUMENTED)),
        "stale": sorted(set(DOCUMENTED) - settings),
    }


def test_the_configuration_page_shows_every_setting() -> None:
    rows = re.findall(r'<code class="env-key">([A-Z0-9_]+)</code>', page("/en/docs/configuration/"))
    assert sorted(rows) == sorted(DOCUMENTED)


def test_every_group_is_shown_on_the_page_that_explains_it() -> None:
    for group in CONFIG["groups"]:
        if group["id"] == "core":
            continue  # the core settings are the reference itself
        url = group["page"].partition("#")[0]
        rows = re.findall(r'<code class="env-key">([A-Z0-9_]+)</code>', page(url))
        assert {s["name"] for s in group["settings"]} <= set(rows), (group["id"], url)


def test_every_setting_is_in_docker_compose_prod() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    keys = set(re.findall(r"^      ([A-Z0-9_]+): ", compose, re.M))
    missing = [
        n.upper()
        for n in Settings.model_fields
        if n.upper() not in keys and n.upper() not in _NOT_IN_COMPOSE
    ]
    assert not missing, missing
