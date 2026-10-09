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


def test_the_image_is_signed_with_sbom_and_provenance_for_the_amd64_target() -> None:
    steps = JOBS["publish"]["steps"]
    build = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action@"))
    assert build["with"]["file"] == "website/Dockerfile"
    assert build["with"]["platforms"] == "linux/amd64"
    assert not any("setup-qemu-action" in s.get("uses", "") for s in steps)
    assert build["with"]["provenance"] is True and build["with"]["sbom"] is True
    assert build["with"]["push"] is True
    run = "\n".join(s.get("run", "") for s in steps)
    assert "cosign sign --yes" in run and "cosign verify" in run
    assert '--certificate-identity "${IDENTITY}"' in run
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in run
    env = next(s["env"] for s in steps if s.get("name") == "Sign and verify")
    assert env["IDENTITY"].endswith("/.github/workflows/website-image.yml@refs/heads/main")
    assert all("docker.io" not in str(s) and "quay.io" not in str(s) for s in steps)


def test_publishes_run_one_at_a_time_in_order() -> None:
    assert "concurrency" not in JOBS["publish"], "job level orders by test end, not push order"
    assert WF["concurrency"] == {
        "group": "website-image-${{ github.ref }}",
        "cancel-in-progress": False,
    }


def test_a_version_bump_rebuilds_the_image() -> None:
    """The footer shows app_version from app/config.py."""
    assert "app/config.py" in WF[True]["push"]["paths"]


def test_the_browser_tests_cannot_skip_in_the_website_job() -> None:
    step = next(
        s for s in JOBS["test"]["steps"] if s.get("name") == "Browser tests against the container"
    )
    assert step["env"] == {"WEBSITE_URL": "http://127.0.0.1:8080", "WEBSITE_REQUIRED": "1"}


def test_the_browser_suite_fails_instead_of_skipping_when_required() -> None:
    # Read as text: importing the module needs Playwright, which the unit job lacks.
    suite = (Path(__file__).parent / "e2e/test_site_container.py").read_text()
    assert 'require_url(BASE, os.environ.get("WEBSITE_REQUIRED", ""))' in suite
