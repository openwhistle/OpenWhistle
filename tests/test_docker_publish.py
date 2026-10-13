"""The publish step's shell runs against stub docker/cosign commands.

The step claims a tag is "verified" only when its index and every platform
manifest behind it can be pulled. A failure inside `for x in $(...)` does not
trip `set -e`, so an uninspectable tag used to print "verified" and pass.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]

DOCKER_STUB = """#!/bin/bash
case "$*" in
  *"inspect --raw $STUB_BAD"*) echo "manifest unknown" >&2; exit 1 ;;
  *"inspect --raw"*) echo '{"manifests":[{"digest":"sha256:child"}]}' ;;
  *"--format"*) echo '{"digest":"sha256:index"}' ;;
esac
"""

# Records every call; `verify` fails for a digest that was never signed, and the first
# STUB_LATE times for a registry that lists a new signature only later (Docker Hub).
COSIGN_STUB = """#!/bin/bash
echo "$*" >> "$COSIGN_LOG"
[[ "$1" == verify && -n "${STUB_UNSIGNED:-}" ]] && exit 1
if [[ "$1" == verify && -n "${STUB_LATE:-}" ]]; then
  n=$(cat "$COSIGN_LOG.late" 2>/dev/null || echo 0)
  echo $((n + 1)) > "$COSIGN_LOG.late"
  (( n < STUB_LATE )) && exit 1
fi
exit 0
"""


def _merge_step() -> dict:
    wf = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())
    (step,) = [s for s in wf["jobs"]["merge"]["steps"] if "verify" in s.get("name", "")]
    return step


def _run(
    tmp_path: Path,
    *,
    bad: str = "none",
    ref: str = "refs/heads/main",
    dockerhub: str = "t",
    unsigned: str = "",
    late: str = "",
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("docker", DOCKER_STUB),
        ("cosign", COSIGN_STUB),
        ("sleep", "#!/bin/bash\n"),
    ):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    digests = tmp_path / "digests"
    digests.mkdir()
    (digests / "abc").touch()
    tags = ["ghcr.io/o/ow:edge", "ghcr.io/o/ow:sha-1", "docker.io/u/ow:edge"]
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GHCR_IMAGE": "ghcr.io/o/ow",
        "DOCKER_METADATA_OUTPUT_JSON": json.dumps({"tags": tags}),
        "DOCKERHUB_TOKEN": dockerhub,
        "QUAY_TOKEN": "",
        "GITHUB_REF": ref,
        "STUB_BAD": bad,
        "STUB_UNSIGNED": unsigned,
        "STUB_LATE": late,
        "COSIGN_LOG": str(tmp_path / "cosign.log"),
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_WORKFLOW_REF": "o/ow/.github/workflows/docker-publish.yml@refs/tags/v9.9.9",
    }
    return subprocess.run(  # noqa: S603
        ["bash", "-c", _merge_step()["run"]],  # noqa: S607
        cwd=digests,
        env=env,  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_tag_is_verified_when_all_are_pullable(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("verified ") == 3


@pytest.mark.parametrize("bad", ["ghcr.io/o/ow:sha-1", "docker.io/u/ow:edge"])
def test_an_uninspectable_tag_fails_the_step(tmp_path: Path, bad: str) -> None:
    result = _run(tmp_path, bad=bad)
    assert result.returncode != 0
    assert f"verified {bad}" not in result.stdout


def _floating(tmp_path: Path, ref: str) -> dict[str, str]:
    wf = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())
    (step,) = [s for s in wf["jobs"]["merge"]["steps"] if s.get("id") == "line"]
    remote = ["v1.3.1", "v1.5.0", "v2.0.0", "v2.0.1", "v2.1.0-rc1", "v1.10.0"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "git"
    stub.write_text("#!/bin/bash\n" + "".join(f"echo 'x\trefs/tags/{t}'\n" for t in remote))
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "out"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_REF_NAME": ref,
        "GITHUB_OUTPUT": str(out),
        "GITHUB_SERVER_URL": "x",
        "GITHUB_REPOSITORY": "y",
    }
    subprocess.run(["bash", "-c", step["run"]], env=env, check=True)  # noqa: S603, S607
    return dict(line.split("=") for line in out.read_text().split())


@pytest.mark.parametrize(
    ("ref", "latest", "major", "minor"),
    [
        ("v2.0.1", "true", "true", "true"),
        ("v2.0.0", "false", "false", "false"),  # re-publishing an older patch
        ("v1.10.0", "false", "true", "true"),  # highest 1.x, sorted as a version
        ("v1.3.1", "false", "false", "true"),
        ("v2.1.0-rc1", "false", "false", "false"),
        ("main", "false", "false", "false"),
    ],
)
def test_floating_tags_move_only_to_the_highest_stable_release(
    tmp_path: Path,
    ref: str,
    latest: str,
    major: str,
    minor: str,
) -> None:
    assert _floating(tmp_path, ref) == {"latest": latest, "major": major, "minor": minor}


def test_metadata_action_takes_floating_tags_only_from_that_step() -> None:
    wf = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())
    (meta,) = [s for s in wf["jobs"]["merge"]["steps"] if s.get("id") == "meta"]
    assert meta["with"]["flavor"] == "latest=false"
    floating = [t for t in meta["with"]["tags"].splitlines() if "{{major}}" in t or "latest" in t]
    assert len(floating) == 3, floating
    for line in floating:
        assert "steps.line.outputs." in line, line


def test_a_release_without_docker_hub_credentials_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, ref="refs/tags/v9.9.9", dockerhub="")
    assert result.returncode != 0
    assert "must reach Docker Hub" in result.stdout


def test_publishing_waits_for_every_check_on_the_same_commit() -> None:
    """Nothing gated the publish: a tag on any commit, or a main commit whose
    pull request was tested against an older main, went straight out."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())["jobs"]
    called = {name: job["uses"] for name, job in jobs.items() if "uses" in job}
    assert set(called.values()) == {
        "$/.github/workflows/ci.yml",
        "$/.github/workflows/e2e.yml",
        "$/.github/workflows/security.yml",
    }
    assert set(jobs["build"]["needs"]) == {*called, "on-main"}
    for path in called.values():
        triggers = yaml.safe_load((ROOT / path.removeprefix("$/")).read_text())[True]  # `on:`
        assert "workflow_call" in triggers, path


@pytest.mark.parametrize(
    ("ref", "on_main", "ok"),
    [
        ("refs/tags/v9.9.9", False, False),
        ("refs/tags/v9.9.9", True, True),
        # Not only tags: a dispatch on a branch published its :sha-<sha> unreviewed.
        ("refs/heads/feature", False, False),
        ("refs/heads/main", True, True),
    ],
)
def test_a_tag_off_main_is_refused(tmp_path: Path, ref: str, on_main: bool, ok: bool) -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())["jobs"]
    (step,) = [s for s in jobs["on-main"]["steps"] if "run" in s]
    stub = tmp_path / "git"
    stub.write_text(f"#!/bin/bash\nexit {0 if on_main else 1}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_REF": ref,
        "GITHUB_REF_NAME": ref.rsplit("/", 1)[-1],
        "GITHUB_SHA": "abc",
    }
    result = subprocess.run(["bash", "-c", step["run"]], env=env, check=False)  # noqa: S603, S607
    assert (result.returncode == 0) is ok


def test_every_signed_digest_is_verified_against_this_workflow_and_ref(tmp_path: Path) -> None:
    """The step signed and then only checked that the tags could be pulled: a digest whose
    signature was missing or came from another workflow still printed "verified"."""
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "cosign.log").read_text().splitlines()
    verifies = [c for c in calls if c.startswith("verify ")]
    assert len(verifies) == 2  # ghcr.io and docker.io
    for call in verifies:
        assert "@sha256:index" in call
        assert (
            "--certificate-identity https://github.com/o/ow/.github/workflows/docker-publish.yml"
            "@refs/tags/v9.9.9 " in call + " "
        )
        assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in call
        assert "identity-regexp" not in call


def test_a_digest_whose_signature_does_not_verify_fails_the_step(tmp_path: Path) -> None:
    result = _run(tmp_path, unsigned="1")
    assert result.returncode != 0
    assert "verified " not in result.stdout


def test_a_signature_the_registry_lists_late_still_verifies(tmp_path: Path) -> None:
    """v2.3.0: Docker Hub listed the signature (an OCI referrer) seconds after `cosign sign`,
    the verify right after it found none, and the release stopped half published."""
    result = _run(tmp_path, late="2")
    assert result.returncode == 0, result.stdout + result.stderr
    verifies = [
        c for c in (tmp_path / "cosign.log").read_text().splitlines() if c.startswith("verify ")
    ]
    assert len(verifies) == 4  # ghcr.io: two misses, then found; docker.io: found
