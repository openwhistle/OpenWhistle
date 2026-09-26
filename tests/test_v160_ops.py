"""v1.6.0 deployment guards: migrations, configuration and the onion header."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.parametrize("direction", [
    ("upgrade", "7d4e2b9c1a05:a1c6e0f4b201"), ("downgrade", "a1c6e0f4b201:7d4e2b9c1a05"),
])
def test_migration_004_refuses_offline_sql(direction: tuple[str, str]) -> None:
    """--sql would emit only the ALTER and leave the TOTP secrets unencrypted."""
    run = subprocess.run(  # noqa: S603
        ["alembic", direction[0], direction[1], "--sql"],  # noqa: S607
        capture_output=True, text=True, check=False,
    )
    assert run.returncode != 0
    assert "must run online" in run.stderr


def test_a_stale_brand_secondary_color_in_env_is_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from app.config import Settings

    env = tmp_path / ".env"
    env.write_text("BRAND_SECONDARY_COLOR=#b07230\n")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings(_env_file=env)  # type: ignore[call-arg]
    assert "BRAND_SECONDARY_COLOR was removed" in caplog.text


ROOT = Path(__file__).parents[1]


def test_the_documented_rollback_downgrades_to_the_last_1_5_revision() -> None:
    """The 1.5.0 image refuses the 1.6 schema: rollback is a downgrade to the
    revision just before 004, run with the 1.6.0 image."""
    mig = (ROOT / "migrations/versions/004_encrypt_totp_secrets.py").read_text()
    before = re.search(r'down_revision: str \| None = "(\w+)"', mig)
    assert before
    for doc in ("docs/docs.html", "CHANGELOG.md"):
        assert f"alembic downgrade {before.group(1)}" in (ROOT / doc).read_text(), doc


def test_the_docs_run_no_module_that_does_not_exist() -> None:
    docs = (ROOT / "docs/docs.html").read_text()
    for module in re.findall(r"python -m ([\w.]+)", docs):
        path = ROOT / module.replace(".", "/")
        assert (path / "__main__.py").exists() or path.with_suffix(".py").exists(), module


async def test_x_ow_onion_is_ignored_without_an_onion_address(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Helm ingress forwards a client-sent X-OW-Onion; with no onion
    listener configured it must not strip HSTS or the Secure cookie flag."""
    from app.config import settings

    monkeypatch.setattr(settings, "onion_location", "")
    resp = await client.get("/status", headers={"X-OW-Onion": "1"})
    assert "strict-transport-security" in resp.headers


def test_the_chart_says_to_clear_x_ow_onion_when_an_onion_address_is_set() -> None:
    for path in ("charts/openwhistle/values.yaml", "docs/docs.html"):
        text = (ROOT / path).read_text()
        assert 'proxy_set_header X-OW-Onion "";' in text.replace("\n            ", " "), path


@pytest.mark.skipif(not shutil.which("helm"), reason="helm not installed")
def test_helm_extra_env_reaches_the_configmap() -> None:
    """Settings without a values.yaml key (SECURE_COOKIES, the lockout
    settings, ...) can still be set on Helm."""
    run = subprocess.run(  # noqa: S603
        ["helm", "template", "t", str(ROOT / "charts/openwhistle"),  # noqa: S607
         "--set", "secrets.existingSecret=x", "--set", "extraEnv.SECURE_COOKIES=false",
         "-s", "templates/configmap.yaml"],
        capture_output=True, text=True, check=True,
    )
    assert 'SECURE_COOKIES: "false"' in run.stdout
