"""The Helm chart rolls its pods on a changed value and accepts real uploads.

`helm template` showed an identical Deployment after a config change (so
`helm upgrade` restarted nothing), `replicas: 1` rendered next to an HPA,
no body-size annotation (ingress-nginx refuses bodies over 1m), and
`postgresql.*` / `redis.*` values that no template read.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
CHART = ROOT / "charts/openwhistle"
VALUES = yaml.safe_load((CHART / "values.yaml").read_text())


def _templates() -> str:
    return "".join(p.read_text() for p in (CHART / "templates").iterdir())


def test_every_top_level_value_is_read_by_a_template() -> None:
    text = _templates()
    dead = [k for k in VALUES if not re.search(rf"\.Values\.{k}\b", text)]
    assert not dead, dead


def test_the_ingress_accepts_what_the_bundled_nginx_accepts() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    size = re.search(r"client_max_body_size (\w+);", conf).group(1)  # type: ignore[union-attr]
    annotations = VALUES["ingress"]["annotations"]
    assert annotations["nginx.ingress.kubernetes.io/proxy-body-size"] == size


def test_the_deployment_template_carries_both_guards() -> None:
    """The same checks as the helm-rendered tests below, for runners without helm."""
    deploy = (CHART / "templates/deployment.yaml").read_text()
    for name in ("configmap", "secret"):
        include = rf'include \(print \$\.Template\.BasePath "/{name}\.yaml"\) \.'
        assert re.search(rf"checksum/\w+: \{{\{{ {include} \| sha256sum \}}\}}", deploy), name
    assert re.search(r"if not \.Values\.autoscaling\.enabled \}\}\n.*\n\s*replicas:", deploy)


def _render(*sets: str) -> dict:
    args = ["--set", "secrets.secretKey=" + "x" * 40, "--set", "secrets.databaseUrl=d",
            "--set", "secrets.redisUrl=r"]
    for s in sets:
        args += ["--set", s]
    out = subprocess.run(  # noqa: S603
        ["helm", "template", "ow", str(CHART), "--show-only", "templates/deployment.yaml", *args],  # noqa: S607
        capture_output=True, text=True, check=True,
    )
    return yaml.safe_load(out.stdout)


@pytest.mark.skipif(shutil.which("helm") is None, reason="needs helm")
def test_a_changed_value_changes_the_pod_template() -> None:
    base = _render()["spec"]["template"]
    for change in ("config.appName=Other", "secrets.setupToken=" + "t" * 40):
        assert _render(change)["spec"]["template"] != base, change


@pytest.mark.skipif(shutil.which("helm") is None, reason="needs helm")
def test_replicas_are_left_to_the_hpa_when_it_is_on() -> None:
    assert _render()["spec"]["replicas"] == VALUES["replicaCount"]
    assert "replicas" not in _render("autoscaling.enabled=true")["spec"]
