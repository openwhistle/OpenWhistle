"""Every deployment path ships the app's own defaults.

A default restated in the Helm chart, the Ansible role, the production
Compose file or .env.example is a copy nothing updates: BRAND_PRIMARY_COLOR
stayed #0f4c81 in three of them after config.py moved to #0c7253.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from app.config import Settings

ROOT = Path(__file__).parents[1]
# Set per deployment on purpose; the app default is only a fallback.
_PER_DEPLOYMENT = {"APP_PUBLIC_URL"}


def _norm(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _app_default(key: str) -> str | None:
    field = Settings.model_fields.get(key.lower())
    if field is None or field.is_required():
        return None
    return None if field.default is None else _norm(field.default)


def _chart() -> dict[str, str]:
    values = yaml.safe_load((ROOT / "charts/openwhistle/values.yaml").read_text())
    text = (ROOT / "charts/openwhistle/templates/configmap.yaml").read_text()
    out = {}
    for key, path in re.findall(r"^\s+([A-Z0-9_]+): \{\{ \.Values\.([\w.]+) \| quote \}\}", text, re.M):
        node = values
        for part in path.split("."):
            node = node[part]
        out[key] = node
    return out


def _ansible() -> dict[str, str]:
    defaults = yaml.safe_load((ROOT / "ansible/roles/openwhistle/defaults/main.yml").read_text())
    text = (ROOT / "ansible/roles/openwhistle/templates/env.j2").read_text()
    return {
        key: defaults[var]
        for key, var in re.findall(r"^([A-Z0-9_]+)=\"?\{\{ (\w+)", text, re.M)
        if var in defaults
    }


def _compose() -> dict[str, str]:
    text = (ROOT / "docker-compose.prod.yml").read_text()
    return dict(re.findall(r'^      ([A-Z0-9_]+): "\$\{\1:-([^}]*)\}"', text, re.M))


def _env_example() -> dict[str, str]:
    text = (ROOT / ".env.example").read_text()
    return dict(re.findall(r"^([A-Z0-9_]+)=(.+)$", text, re.M))


@pytest.mark.parametrize("source", [_chart, _ansible, _compose, _env_example])
def test_restated_defaults_match_config_py(source: Callable[[], dict[str, str]]) -> None:
    found = source()
    assert found, f"{source.__name__} matched nothing — the check reaches nothing"
    drift = {
        key: (_norm(value), _app_default(key))
        for key, value in found.items()
        if key not in _PER_DEPLOYMENT and _app_default(key) is not None
        and _norm(value) not in ("", _app_default(key))
    }
    assert not drift, f"{source.__name__}: shipped value vs config.py default: {drift}"
