"""Every image CI builds or publishes is scanned, and a fixable finding fails it.

v2.2.1 (2026-10-12) shipped zlib 1.3.2-r0 six days after Alpine fixed a High CVE in
-r1: the final stage never upgraded the base digest's packages, and Trivy rated the
CVE MEDIUM, under its CRITICAL,HIGH cut-off. grype rated it High; nothing ran grype.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
GRYPE = re.compile(r"docker://anchore/grype:v[\d.]+@sha256:[0-9a-f]{64}")


def _jobs(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]


def _grype_steps(job: dict) -> list[dict]:
    return [s for s in job["steps"] if s.get("uses", "").startswith("docker://anchore/grype")]


def test_final_stage_upgrades_its_alpine_packages() -> None:
    final = (ROOT / "Dockerfile").read_text().split("AS final", 1)[1]
    assert re.search(r"RUN apk upgrade --no-cache\b", final), "keeps the base digest's packages"


def test_ci_builds_the_final_stage_without_cache() -> None:
    """A cached `RUN apk upgrade` layer is reused until the base digest moves."""
    builds = {
        "security.yml": _jobs("security.yml")["image"]["steps"],
        "docker-publish.yml": _jobs("docker-publish.yml")["build"]["steps"],
    }
    for wf, steps in builds.items():
        (build,) = [s for s in steps if s.get("uses", "").startswith("docker/build-push-action@")]
        assert build["with"].get("no-cache-filters") == "final", wf


def test_every_grype_gate_fails_on_any_fixable_finding_with_the_reviewed_exceptions() -> None:
    gates = {
        "security.yml:image": _jobs("security.yml")["image"],
        "security.yml:published": _jobs("security.yml")["published"],
        "docker-publish.yml:build": _jobs("docker-publish.yml")["build"],
    }
    pins = set()
    for where, job in gates.items():
        (step,) = _grype_steps(job)
        args = step["with"]["args"].split()
        for flag in ("--only-fixed", "--config .grype.yaml", "--fail-on negligible"):
            assert flag in " ".join(args), f"{where}: {flag} missing"
        assert GRYPE.fullmatch(step["uses"]), f"{where}: grype is not pinned by digest"
        pins.add(step["uses"])
    assert len(pins) == 1, f"grype pins disagree: {pins}"


def test_the_scan_runs_on_pull_requests_every_week_and_for_every_publish() -> None:
    triggers = yaml.safe_load((WORKFLOWS / "security.yml").read_text())[True]
    assert {"pull_request", "schedule", "workflow_call"} <= set(triggers)
    assert _jobs("docker-publish.yml")["build"]["needs"].count("security") == 1


def test_publish_scans_the_digest_it_pushed_before_anything_is_tagged() -> None:
    steps = _jobs("docker-publish.yml")["build"]["steps"]
    (scan,) = _grype_steps({"steps": steps})
    assert "@${{ steps.build.outputs.digest }}" in scan["with"]["args"]
    assert "--platform ${{ matrix.platform }}" in scan["with"]["args"]
    ids = [s.get("id") for s in steps]
    assert steps.index(scan) > ids.index("build"), "scan runs before the push"
    assert _jobs("docker-publish.yml")["merge"]["needs"] == "build"


def test_every_published_tag_and_platform_is_scanned_every_week() -> None:
    """Only ``:latest`` for the runner's amd64 was rescanned: the arm64 image and
    ``:edge``, which the demo runs, went unscanned between pushes."""
    job = _jobs("security.yml")["published"]
    (step,) = _grype_steps(job)
    matrix = job["strategy"]["matrix"]
    assert set(matrix["tag"]) == {"latest", "edge"}
    assert set(matrix["platform"]) == {"linux/amd64", "linux/arm64"}
    image = "registry:ghcr.io/openwhistle/openwhistle:${{ matrix.tag }}"
    assert step["with"]["args"].startswith(f"{image} --platform ${{{{ matrix.platform }}}} ")


def test_the_local_scan_recipe_uses_the_workflows_grype() -> None:
    """docs-tech/image-scan.md said "v0.120.1, as in the workflows" after Renovate had
    moved every workflow to v0.121.0."""
    import re

    (step,) = _grype_steps(_jobs("security.yml")["published"])
    version, digest = re.fullmatch(
        r"docker://anchore/grype:(v[\d.]+)@(sha256:\w+)", step["uses"]
    ).groups()
    doc = (Path(__file__).parents[1] / "docs-tech/image-scan.md").read_text()
    assert f"docker.io/anchore/grype@{digest}  # {version}, as in the workflows" in doc


def test_trivy_scans_secrets_only_so_no_second_vulnerability_verdict_disagrees() -> None:
    steps = _jobs("security.yml")["image"]["steps"]
    (trivy,) = [s for s in steps if s.get("uses", "").startswith("aquasecurity/")]
    assert trivy["with"]["scanners"] == "secret"
    assert trivy["with"]["exit-code"] == "1"


def test_every_scan_exception_names_a_version_and_a_reason() -> None:
    """An entry pinned to a version expires when the package moves."""
    entries = yaml.safe_load((ROOT / ".grype.yaml").read_text())["ignore"]
    assert entries, "no exception: delete .grype.yaml's ignore list instead"
    for entry in entries:
        assert re.fullmatch(r"CVE-\d{4}-\d+|GHSA-[\w-]+", entry["vulnerability"]), entry
        assert entry["package"]["name"] and entry["package"]["version"], entry
        assert len(entry.get("reason", "")) > 40, entry
