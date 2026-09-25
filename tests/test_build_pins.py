"""Build tool pins that live in several files must agree."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_uv_version_is_the_same_in_the_image_and_every_workflow() -> None:
    image = re.search(r"ghcr\.io/astral-sh/uv:([0-9.]+)", (ROOT / "Dockerfile").read_text())
    assert image, "Dockerfile no longer copies uv from ghcr.io/astral-sh/uv"
    pins = {
        wf.name: re.findall(r"uv==([0-9.]+)", wf.read_text())
        for wf in (ROOT / ".github" / "workflows").glob("*.yml")
    }
    stale = {name: found for name, found in pins.items() if set(found) - {image.group(1)}}
    assert not stale, f"uv pins differ from the Dockerfile's {image.group(1)}: {stale}"
    assert any(pins.values()), "no workflow pins uv — the check reaches nothing"


def _all(pattern: str, *globs: str) -> set[str]:
    return {
        m for g in globs for f in ROOT.glob(g) for m in re.findall(pattern, f.read_text())
    }


def test_python_version_is_the_same_everywhere() -> None:
    found = _all(r"python:(\d+\.\d+)-alpine", "Dockerfile")
    found |= _all(r'python-version: "(\d+\.\d+)"', ".github/workflows/*.yml")
    found |= _all(r'requires-python = ">=(\d+\.\d+)"', "pyproject.toml")
    assert len(found) == 1, f"Python versions disagree: {found}"


def test_postgres_and_redis_majors_are_the_same_everywhere() -> None:
    places = ("docker-compose*.yml", ".github/workflows/*.yml",
              "ansible/roles/openwhistle/templates/*.j2")
    for image in ("postgres", "redis"):
        found = _all(rf"image: {image}:([0-9a-z.\-]+)", *places)
        assert len(found) == 1, f"{image} tags disagree: {found}"


def _final_stage() -> str:
    return (ROOT / "Dockerfile").read_text().split("AS final", 1)[1]


def test_base_images_are_pinned_by_digest() -> None:
    images = re.findall(r"^FROM (\S+)", (ROOT / "Dockerfile").read_text(), re.M)
    assert images, "no FROM line"
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", f) for f in images), images


def test_runtime_image_has_no_curl_and_a_python_healthcheck() -> None:
    final = _final_stage()
    assert "curl" not in final
    assert re.search(r"HEALTHCHECK .*\n?.*python", final)


COMPOSE_FILES = (
    "docker-compose.prod.yml",
    "ansible/roles/openwhistle/templates/docker-compose.yml.j2",
)


def test_compose_app_is_read_only_without_capabilities() -> None:
    for path in COMPOSE_FILES:
        app = (ROOT / path).read_text().split("\n  nginx:", 1)[0]
        for needle in ("read_only: true", "- /tmp", "cap_drop:", "- ALL", "no-new-privileges:true"):
            assert needle in app, f"{path}: app service lacks {needle!r}"


def test_prod_compose_pins_the_image_version() -> None:
    text = (ROOT / "docker-compose.prod.yml").read_text()
    assert "openwhistle:latest" not in text
    assert re.search(r"openwhistle:\$\{OPENWHISTLE_VERSION:-\d+\.\d+\.\d+\}", text)


def test_helm_container_security_context() -> None:
    deploy = (ROOT / "charts/openwhistle/templates/deployment.yaml").read_text()
    for needle in ("readOnlyRootFilesystem: true", "allowPrivilegeEscalation: false", "- ALL"):
        assert needle in deploy


def test_ansible_directory_is_kept_out_of_the_build_context() -> None:
    lines = (ROOT / ".dockerignore").read_text().split()
    assert "ansible" in lines


def test_compose_host_bind_mounts_carry_the_selinux_label() -> None:
    """Every host-path bind mount (not a named volume, not tmpfs) needs :z so it
    is readable under SELinux — a no-op on hosts that don't enforce it."""
    pattern = re.compile(r"^\s*- (\.{1,2}/\S+|/\S+):(/\S+):(\S+)\s*$", re.M)
    found = False
    for path in COMPOSE_FILES:
        text = (ROOT / path).read_text()
        for host, _container, opts in pattern.findall(text):
            found = True
            assert "z" in opts.split(","), f"{path}: {host} bind mount lacks :z ({opts!r})"
    assert found, "no bind mount matched — the check reaches nothing"


def test_security_workflow_audits_dependencies_and_the_image() -> None:
    wf = (ROOT / ".github/workflows/security.yml").read_text()
    needles = (
        "pull_request:", "schedule:", "pip-audit", "aquasecurity/trivy-action@", "--all-extras",
    )
    for needle in needles:
        assert needle in wf, needle
    pinned = re.search(r"aquasecurity/trivy-action@[0-9a-f]{40}", wf)
    assert pinned, "trivy action not pinned by digest"
