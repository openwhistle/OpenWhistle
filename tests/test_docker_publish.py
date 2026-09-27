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


def _merge_step() -> dict:
    wf = yaml.safe_load((ROOT / ".github/workflows/docker-publish.yml").read_text())
    (step,) = [s for s in wf["jobs"]["merge"]["steps"] if "verify" in s.get("name", "")]
    return step


def _run(tmp_path: Path, *, bad: str = "none", ref: str = "refs/heads/main",
         dockerhub: str = "t") -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("cosign", "#!/bin/bash\n")):
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
    }
    return subprocess.run(
        ["bash", "-c", _merge_step()["run"]], cwd=digests, env=env,
        capture_output=True, text=True, check=False,
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
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_REF_NAME": ref,
           "GITHUB_OUTPUT": str(out), "GITHUB_SERVER_URL": "x", "GITHUB_REPOSITORY": "y"}
    subprocess.run(["bash", "-c", step["run"]], env=env, check=True)
    return dict(line.split("=") for line in out.read_text().split())


@pytest.mark.parametrize(("ref", "latest", "major", "minor"), [
    ("v2.0.1", "true", "true", "true"),
    ("v2.0.0", "false", "false", "false"),   # re-publishing an older patch
    ("v1.10.0", "false", "true", "true"),    # highest 1.x, sorted as a version
    ("v1.3.1", "false", "false", "true"),
    ("v2.1.0-rc1", "false", "false", "false"),
    ("main", "false", "false", "false"),
])
def test_floating_tags_move_only_to_the_highest_stable_release(
    tmp_path: Path, ref: str, latest: str, major: str, minor: str,
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
