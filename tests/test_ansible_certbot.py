"""The Ansible role can obtain and renew its certificate.

nginx refused to start without the certificate it serves, yet the role
started the stack (systemd.yml) before certbot.yml; and the standalone
authenticator needs :80, which the running nginx container holds, so every
`certbot renew` failed and the certificate expired after 90 days.
"""

import os
import stat
import subprocess
from pathlib import Path

import jinja2
import pytest
import yaml

ROLE = Path(__file__).parents[1] / "ansible/roles/openwhistle"


def _tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def test_the_certificate_is_obtained_before_the_stack_starts() -> None:
    order = [
        t["ansible.builtin.import_tasks"]
        for t in _tasks("main.yml")
        if "ansible.builtin.import_tasks" in t
    ]
    assert order.index("certbot.yml") < order.index("systemd.yml"), order


def _hook_task() -> dict:
    (task,) = [t for t in _tasks("certbot.yml") if "renewal-hooks/{{ item.dir }}" in str(t)]
    return task


def _hook_paths() -> dict[str, str]:
    task = _hook_task()
    dest = task["ansible.builtin.copy"]["dest"]
    return {i["action"]: jinja2.Template(dest).render(item=i) for i in task["loop"]}


def test_every_certbot_run_stops_the_stack_and_starts_it_again() -> None:
    paths = _hook_paths()
    assert paths == {
        "stop": "/etc/letsencrypt/renewal-hooks/pre/stop-openwhistle.sh",
        "start": "/etc/letsencrypt/renewal-hooks/post/start-openwhistle.sh",
    }
    (issue,) = [t for t in _tasks("certbot.yml") if "certbot certonly" in str(t)]
    cmd = issue["ansible.builtin.command"]["cmd"]
    assert f"--pre-hook {paths['stop']}" in cmd
    assert f"--post-hook {paths['start']}" in cmd


@pytest.mark.parametrize(("installed", "expected"), [(True, "stop openwhistle"), (False, "")])
def test_the_hook_skips_a_unit_that_is_not_installed_yet(
    tmp_path: Path,
    installed: bool,
    expected: str,
) -> None:
    task = _hook_task()
    script = jinja2.Template(task["ansible.builtin.copy"]["content"]).render(item=task["loop"][0])
    log = tmp_path / "log"
    stub = tmp_path / "systemctl"
    stub.write_text(
        f'#!/bin/sh\n[ "$1" = cat ] && exit {0 if installed else 1}\necho "$@" >> {log}\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run(["sh", "-c", script], env=env, check=True)  # noqa: S603, S607
    assert (log.read_text().strip() if log.exists() else "") == expected


def test_no_task_or_handler_names_a_host_nginx() -> None:
    text = "".join(p.read_text() for p in (ROLE / "tasks").glob("*.yml"))
    text += (ROLE / "handlers/main.yml").read_text()
    assert "python3-certbot-nginx" not in text
    assert "name: nginx" not in text


def test_the_post_hook_removes_the_visitor_addresses_certbot_logged(tmp_path: Path) -> None:
    """certbot --standalone holds :80 during a renewal and its acme server logs each
    request with the client address at DEBUG, which certbot's log file keeps (measured
    with acme 5.8: 'acme.standalone:::ffff:127.0.0.1 - - "GET / HTTP/1.1" 200 -')."""
    task = _hook_task()
    (start,) = [i for i in task["loop"] if i["action"] == "start"]
    script = jinja2.Template(task["ansible.builtin.copy"]["content"]).render(item=start)
    assert script.startswith("#!/bin/sh\n")
    log = tmp_path / "letsencrypt.log"
    log.write_text(
        "2026-10-13 03:12:01,100:DEBUG:certbot._internal.main:certbot version: 2.11.0\n"
        '2026-10-13 03:12:02,200:DEBUG:acme.standalone:203.0.113.7 - - "GET / HTTP/1.1" 404 -\n'
        "2026-10-13 03:12:03,300:INFO:certbot._internal.renewal:Renewal succeeded\n"
    )
    script = script.replace("/var/log/letsencrypt/letsencrypt.log", str(log))
    stub = tmp_path / "systemctl"
    stub.write_text("#!/bin/sh\nexit 1\n")  # no unit: the hook stops after the scrub
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run(["sh", "-c", script], env=env, check=True)  # noqa: S603, S607
    assert "203.0.113.7" not in log.read_text()
    assert "Renewal succeeded" in log.read_text()
