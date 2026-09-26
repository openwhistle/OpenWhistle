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


def test_no_tracked_file_holds_a_machine_local_path() -> None:
    """A session scratchpad path (user, session id) once reached a public plan."""
    files = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True,  # noqa: S607
    ).stdout.decode().split("\0")
    local = re.compile(r"/tmp/claude-\d+/|/var/home/\w+|/home/jpy\b")  # noqa: S108
    offenders = [
        name for name in files
        if name and name != "tests/test_v160_ops.py" and (ROOT / name).is_file()
        and local.search((ROOT / name).read_bytes().decode("utf-8", "ignore"))
    ]
    assert not offenders, offenders


_PROCESS_NOTE = re.compile(
    r"fix[ -]rounds?\b|\bround[ -]\d\b|\bruling\b|\breviewers?\b|\bre-review|\btask[ -]x?\d"
    r"|chrome[ -](?:review|check) finding",
    re.IGNORECASE,
)
_SHIPPED = re.compile(r"(?:app|nginx|ansible|charts|docs)/|docker-compose[^/]*\.yml$|Dockerfile$")


def test_shipped_files_explain_the_code_not_the_review_history() -> None:
    """What ships or is published says why the code is like this; "fix round 2"
    or "Task 17" points at review notes the reader of the image or site does
    not have."""
    files = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True,  # noqa: S607
    ).stdout.decode().split("\0")
    offenders = [
        f"{name}: {m.group(0)}"
        for name in files
        if _SHIPPED.match(name) and (ROOT / name).is_file()
        for m in [_PROCESS_NOTE.search((ROOT / name).read_bytes().decode("utf-8", "ignore"))]
        if m
    ]
    assert not offenders, offenders


def test_the_image_ships_exactly_the_font_files_the_app_css_uses() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    copied = set(re.findall(r"docs/fonts/([\w.-]+\.woff2)", dockerfile))
    css = "".join(p.read_text() for p in (ROOT / "app/static/css").glob("*.css"))
    assert copied == set(re.findall(r"([\w.-]+\.woff2)", css))


def test_local_tooling_and_maintainer_docs_stay_out_of_the_build_context() -> None:
    ignored = (ROOT / ".dockerignore").read_text().split()
    for path in (".serena", ".superpowers", ".claude", "docs-tech"):
        assert path in ignored, path
    assert ".serena/" in (ROOT / ".gitignore").read_text().split()
