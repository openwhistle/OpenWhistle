"""No key shipped in this repository may be accepted as a real one.

The Quick Start compose file hard-coded a 48-character SECRET_KEY, and the
placeholders in .env.example (32 characters) and ansible/vault.yml.example
(43) passed the 32-character check: an install that skipped the edit ran with
a key anyone can read here.
"""

import re
from pathlib import Path

import yaml

from app.config import _MIN_SECRET_KEY_LEN

ROOT = Path(__file__).parents[1]
KEYS = ("SECRET_KEY", "ENCRYPTION_KEY")


def test_quick_start_compose_takes_its_keys_from_dotenv() -> None:
    app = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["app"]
    assert {"path": ".env", "required": False} in app["env_file"]
    assert not set(KEYS) & set(app["environment"]), app["environment"]


def test_no_example_key_passes_the_length_check() -> None:
    found = []
    sources = {
        ".env.example": r"^({k})=(.*)$",
        "README.md": r"^({k})=(.*)$",
        "docs/de/blog/interne-meldestelle-einrichten.html": r"^({k})=(.*)$",
        "docs/en/docs/index.html": r"({k})</span>=([^\n<]*)",
    }
    for path, pattern in sources.items():
        text = (ROOT / path).read_text()
        for key in KEYS:
            for name, value in re.findall(pattern.format(k=key), text, re.M):
                found.append(name)
                assert len(value.strip()) < _MIN_SECRET_KEY_LEN, (path, name, value)
    assert "SECRET_KEY" in found, "no example SECRET_KEY found — the check reaches nothing"

    vault = yaml.safe_load((ROOT / "ansible/vault.yml.example").read_text())
    secrets = {k: v for k, v in vault.items() if "key" in k or "password" in k}
    assert secrets and not any(secrets.values()), secrets


def test_the_ansible_role_refuses_a_short_secret_key() -> None:
    tasks = (ROOT / "ansible/roles/openwhistle/tasks/main.yml").read_text()
    assert f"openwhistle_secret_key | length >= {_MIN_SECRET_KEY_LEN}" in tasks
