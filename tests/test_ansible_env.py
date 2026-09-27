"""The Ansible-rendered .env delivers every value to the container unchanged.

The file is both `env_file` and Compose's interpolation source. Unquoted,
Compose expanded `$`: a password pa$$w0rd$HOME reached the container as
pa$w0rd/home/<user>. A password with `@` or `/` also broke DATABASE_URL.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import jinja2
import pytest
import yaml

from app.config import Settings

ROLE = Path(__file__).parents[1] / "ansible/roles/openwhistle"
NASTY = "p@ss:w/rd$HOME$$x'q\"#1 %"
KEY = "k$HOME" + "x" * 40


def _render(**overrides: object) -> str:
    values = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    values.update(openwhistle_domain="ow.example.com", ansible_date_time={"iso8601": "now"})
    # Ansible renders with trim_blocks; defaults refer to other variables.
    env = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True)  # noqa: S701 — not HTML
    values = {k: env.from_string(v).render(**values) if isinstance(v, str) else v
              for k, v in values.items()}
    values.update(overrides)
    return env.from_string((ROLE / "templates/env.j2").read_text()).render(**values)


def test_every_setting_can_be_set_through_the_role() -> None:
    text = (ROLE / "templates/env.j2").read_text()
    assert "openwhistle_env" in text
    rendered = _render(openwhistle_env={"CLAMAV_HOST": "clamav"})
    assert "\nCLAMAV_HOST='clamav'\n" in rendered
    keys = set(re.findall(r"^#? ?([A-Z0-9_]+)=", text, re.M))
    missing = [n.upper() for n in Settings.model_fields if n.upper() not in keys]
    assert not missing, missing
    # Set by the image; a version written here goes stale.
    assert re.search(r"^# APP_VERSION=\s", text, re.M)


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker compose")
def test_compose_passes_every_value_through_unchanged(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(_render(
        openwhistle_db_password=NASTY, openwhistle_redis_password=NASTY,
        openwhistle_secret_key=KEY, openwhistle_app_name=NASTY,
        openwhistle_env={"SETUP_TOKEN": NASTY},
    ))
    (tmp_path / "compose.yml").write_text(
        "services:\n  app:\n    image: scratch\n    env_file: .env\n"
        '    command: ["${REDIS_PASSWORD}"]\n'
    )
    out = subprocess.run(
        ["docker", "compose", "config", "--format", "json"], cwd=tmp_path,  # noqa: S607
        capture_output=True, text=True, check=True,
    )
    # `config` re-escapes each literal $ as $$ in its output.
    app = json.loads(out.stdout.replace("$$", "$"))["services"]["app"]
    env = app["environment"]
    for name in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "APP_NAME", "SETUP_TOKEN"):
        assert env[name] == NASTY, name
    assert env["SECRET_KEY"] == KEY
    assert app["command"] == [NASTY], "the interpolated ${REDIS_PASSWORD} was changed"
    for url in ("DATABASE_URL", "REDIS_URL"):
        assert unquote(urlsplit(env[url]).password or "") == NASTY, url
