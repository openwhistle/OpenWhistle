"""website-image.yml publishes only what its own test job passed, only from main, signed."""

from pathlib import Path

import yaml

WF = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/website-image.yml").read_text())
JOBS = WF["jobs"]


def test_publish_waits_for_the_tests_and_never_runs_for_a_pull_request() -> None:
    publish = JOBS["publish"]
    assert publish["needs"] == "test" or publish["needs"] == ["test"]
    assert publish["if"] == "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'"


def test_only_publish_may_write_packages_and_sign() -> None:
    assert JOBS["test"]["permissions"] == {"contents": "read"}
    assert JOBS["publish"]["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
    }


def test_the_image_is_signed_with_sbom_and_provenance_for_both_architectures() -> None:
    steps = JOBS["publish"]["steps"]
    build = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action@"))
    assert build["with"]["file"] == "website/Dockerfile"
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert build["with"]["provenance"] is True and build["with"]["sbom"] is True
    assert build["with"]["push"] is True
    run = "\n".join(s.get("run", "") for s in steps)
    assert "cosign sign --yes" in run and "cosign verify" in run
    assert '--certificate-identity "${IDENTITY}"' in run
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in run
    env = next(s["env"] for s in steps if s.get("name") == "Sign and verify")
    assert env["IDENTITY"].endswith("/.github/workflows/website-image.yml@refs/heads/main")
    assert all("docker.io" not in str(s) and "quay.io" not in str(s) for s in steps)
