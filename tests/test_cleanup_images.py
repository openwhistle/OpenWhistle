"""The weekly registry cleanup must never delete a manifest a release tag uses.

skopeo deletes by digest, so deleting an old ``sha-`` tag on Quay deleted
every tag on the same digest: 1.3.1, 1.4.0 and 1.5.0 answered 404 afterwards.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def _quay_step() -> dict:
    wf = yaml.safe_load((ROOT / ".github/workflows/cleanup-images.yml").read_text())
    (step,) = [s for s in wf["jobs"]["cleanup-registries"]["steps"] if "Quay" in s["name"]]
    return step


def _doomed(tags: list[dict], keep: int) -> list[str]:
    jq = shutil.which("jq")
    if jq is None:
        pytest.fail("jq is required: the workflow runs this filter with it")
    out = subprocess.run(  # noqa: S603
        [jq, "-r", "--argjson", "keep", str(keep), _quay_step()["env"]["QUAY_DOOMED_DIGESTS"]],
        input=json.dumps(tags),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.split()


def _tag(name: str, digest: str, ts: int) -> dict:
    return {"name": name, "manifest_digest": f"sha256:{digest}", "start_ts": ts}


def test_a_digest_shared_with_a_release_tag_is_never_deleted() -> None:
    tags = [
        _tag("sha-new", "n", 30),
        _tag("edge", "n", 30),
        _tag("sha-rel", "r", 20),  # the release commit's sha- tag
        _tag("1.5.0", "r", 20),
        _tag("sha-old", "o", 10),
        _tag("sha-twin", "k", 5),  # older than KEEP, but shares a kept digest
        _tag("sha-kept", "k", 25),
    ]
    assert _doomed(tags, keep=2) == ["sha256:o"]


def test_the_step_deletes_the_selected_digests_not_tags() -> None:
    run = _quay_step()["run"]
    assert "QUAY_DOOMED_DIGESTS" in run
    assert "openwhistle@${digest}" in run
    assert "openwhistle:${tag}" not in run


@pytest.mark.parametrize("registry", ["Docker Hub", "Quay"])
def test_a_delete_the_registry_refuses_fails_the_cleanup(tmp_path: Path, registry: str) -> None:
    """A refused delete printed one line to stderr and the step stayed green: nobody
    learns that old images are piling up, or that the token lost its rights."""
    wf = yaml.safe_load((ROOT / ".github/workflows/cleanup-images.yml").read_text())
    (step,) = [s for s in wf["jobs"]["cleanup-registries"]["steps"] if registry in s["name"]]
    tags = [_tag(f"sha-{i:07x}", f"{i:064x}", 1000 + i) for i in range(12)]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listing = {
        "Quay": {"tags": tags, "has_additional": False},
        "Docker Hub": {"results": [{"name": t["name"]} for t in tags], "next": None},
    }
    (tmp_path / "listing.json").write_text(json.dumps(listing[registry]))
    # Every listing answers; every DELETE (curl -X DELETE, skopeo delete) is refused.
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\ncase "$*" in *DELETE*) exit 22;; *login*) echo \'{{"token":"t"}}\';; '
        f"*) cat {tmp_path}/listing.json;; esac\n"
    )
    (bin_dir / "skopeo").write_text("#!/bin/sh\nexit 1\n")
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        **dict.fromkeys(
            (
                "QUAY_USERNAME",
                "QUAY_TOKEN",
                "QUAY_NAMESPACE",
                "DOCKERHUB_USERNAME",
                "DOCKERHUB_TOKEN",
            ),
            "x",
        ),
        **{k: str(v) for k, v in (step.get("env") or {}).items() if "${{" not in str(v)},
    }
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", step["run"]],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Failed to delete" in result.stderr, result.stdout + result.stderr
    assert result.returncode != 0
