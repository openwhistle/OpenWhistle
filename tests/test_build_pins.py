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


def _clamav_block(path: str) -> str:
    text = (ROOT / path).read_text()
    match = re.search(r"^  clamav:\n.*?(?=^volumes:)", text, re.M | re.S)
    assert match, f"{path}: no clamav service block found"
    return match.group(0)


def test_clamav_service_is_identical_and_hardened_in_both_compose_files() -> None:
    """docker-compose.prod.yml and the Ansible-rendered compose template must
    offer the same optional, profile-gated, hardened clamav service — one
    drifting out of sync with the other is exactly the kind of gap that goes
    unnoticed until a deploy differs from the other."""
    blocks = {path: _clamav_block(path) for path in COMPOSE_FILES}
    a, b = blocks.values()
    assert a == b, f"clamav service blocks differ between {list(blocks)}"

    block = a
    for needle in (
        'profiles: ["clamav"]',
        "read_only: true",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "clamdcheck.sh",
        "clamav_data:/var/lib/clamav",
    ):
        assert needle in block, f"clamav service lacks {needle!r}"
    assert re.search(r"image: clamav/clamav:[0-9.]+@sha256:[0-9a-f]{64}", block), \
        "clamav image is not pinned by digest"

    networks = re.search(r"networks:\n((?:\s+- \S+\n)+)", block)
    assert networks, "clamav service has no networks: block"
    joined = {line.strip("- \n") for line in networks.group(1).splitlines()}
    assert joined == {"internal", "clamav-egress"}, (
        f"clamav must share only 'internal' with app plus its own egress "
        f"network for freshclam — never 'proxy' (nginx's network): {joined}"
    )


def test_every_workflow_action_is_pinned_by_commit_sha() -> None:
    """Every `uses: owner/repo@...` in every workflow must pin a full 40-hex
    commit SHA, with a `# vX...` comment recording the human-readable
    version — never a floating tag/branch (`@v4`, `@main`), which a
    compromised upstream tag could silently repoint. `docker/*-action`,
    `actions/*`, and third-party actions (e.g. `aquasecurity/trivy-action`,
    `DavidAnson/markdownlint-cli2-action`) are all covered; a local action
    (`uses: ./...`) is not a remote pin and is exempt."""
    pattern = re.compile(r"^(\s*-?\s*)?uses:\s*(\S+)\s*(#.*)?$", re.M)
    unpinned: dict[str, list[str]] = {}
    refs: list[str] = []
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text()
        for _prefix, ref, comment in pattern.findall(text):
            refs.append(ref)
            if ref.startswith("./") or ref.startswith("docker://"):
                continue  # local/inline action, nothing to pin by SHA
            bad = []
            if not re.search(r"@[0-9a-f]{40}$", ref):
                bad.append(f"{ref!r} is not pinned to a 40-hex commit SHA")
            elif not re.fullmatch(r"#\s*v[\w.]+\s*", comment):
                bad.append(f"{ref!r} has no '# vX' version comment")
            if bad:
                unpinned.setdefault(wf.name, []).extend(bad)
    assert refs, "no `uses:` line found — the check reaches nothing"
    assert unpinned == {}, unpinned
    # The Node date-only formatter test fails in CI without it.
    assert any(r.startswith("actions/setup-node@") for r in refs)


def test_no_bare_pip_install_in_any_workflow() -> None:
    """A `pip install` (or `uv pip install`) line in a workflow must be
    pinned, not a floating "whatever's latest today" install that bypasses
    uv.lock — the same pinning discipline
    test_every_workflow_action_is_pinned_by_commit_sha enforces for actions.
    Allowed without a version pin: `-r <file>` (a requirements file that was
    itself generated from the lock, e.g. `uv export --frozen`) and `-e .`
    (installing this project from the checkout, which has no separate
    version to pin). Every other package argument must carry `==<version>`.
    """
    pattern = re.compile(r"\bpip install\b(.*)$", re.M)
    bad: dict[str, list[str]] = {}
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in pattern.findall(wf.read_text()):
            if re.search(r"(^|\s)-r\s+\S+", line) or re.search(r"(^|\s)-e\s+\S+", line):
                continue  # requirements file or local editable install
            for token in line.split():
                if token.startswith("-"):
                    continue
                if "==" not in token:
                    bad.setdefault(wf.name, []).append(
                        f"unpinned package {token!r} in 'pip install{line}'"
                    )
    assert bad == {}, bad


def test_security_workflow_audits_dependencies_and_the_image() -> None:
    wf = (ROOT / ".github/workflows/security.yml").read_text()
    needles = (
        "pull_request:", "schedule:", "pip-audit", "aquasecurity/trivy-action@", "--all-extras",
    )
    for needle in needles:
        assert needle in wf, needle
    pinned = re.search(r"aquasecurity/trivy-action@[0-9a-f]{40}", wf)
    assert pinned, "trivy action not pinned by digest"

