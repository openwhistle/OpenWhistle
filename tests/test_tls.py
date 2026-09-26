"""The bundled nginx always has a certificate and never serves the app over plain HTTP."""

from __future__ import annotations

import importlib.util
import os
import re
import stat
from pathlib import Path

import pytest
from cryptography import x509

ROOT = Path(__file__).parents[1]


def _ensure():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("tls", ROOT / "scripts/ensure_tls_cert.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ensure


def test_self_signed_certificate_is_created_once(tmp_path: Path) -> None:
    ensure = _ensure()
    assert ensure(tmp_path / "none", tmp_path / "tls", "whistle.example.org") == "self-signed"
    cert = x509.load_pem_x509_certificate((tmp_path / "tls/fullchain.pem").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "whistle.example.org" in san.get_values_for_type(x509.DNSName)
    assert ensure(tmp_path / "none", tmp_path / "tls", "whistle.example.org") == "kept"


def test_operator_certificate_wins(tmp_path: Path) -> None:
    ensure = _ensure()
    src = tmp_path / "certs"
    src.mkdir()
    (src / "fullchain.pem").write_text("CERT")
    (src / "privkey.pem").write_text("KEY")
    assert ensure(src, tmp_path / "tls", "x") == "provided"
    assert (tmp_path / "tls/fullchain.pem").read_text() == "CERT"
    mode = stat.S_IMODE((tmp_path / "tls/privkey.pem").stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_a_dangling_certificate_symlink_fails_loudly(tmp_path: Path) -> None:
    """A certbot symlink dangles inside the container; it must not quietly
    turn into a self-signed certificate."""
    src = tmp_path / "certs"
    src.mkdir()
    (src / "fullchain.pem").write_text("CERT")
    (src / "privkey.pem").symlink_to(tmp_path / "live/privkey.pem")
    with pytest.raises(SystemExit, match="privkey.pem.*do not symlink"):
        _ensure()(src, tmp_path / "tls", "x")
    assert not (tmp_path / "tls/fullchain.pem").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_operator_key_fails_loudly(tmp_path: Path) -> None:
    src = tmp_path / "certs"
    src.mkdir()
    (src / "fullchain.pem").write_text("CERT")
    (src / "privkey.pem").write_text("KEY")
    (src / "privkey.pem").chmod(0)
    with pytest.raises(SystemExit, match="privkey.pem: Permission denied.*root-owned 0600"):
        _ensure()(src, tmp_path / "tls", "x")


def test_a_certificate_without_its_key_fails_loudly(tmp_path: Path) -> None:
    src = tmp_path / "certs"
    src.mkdir()
    (src / "fullchain.pem").write_text("CERT")
    with pytest.raises(SystemExit, match="privkey.pem"):
        _ensure()(src, tmp_path / "tls", "x")


def test_nginx_redirects_http_and_strips_ip_headers_on_https() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    plain = next(s for s in servers if "listen 80;" in s)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    onion = next(s for s in servers if "listen 8080;" in s)
    assert "return 301 https://$host$request_uri;" in plain
    assert "proxy_pass" not in plain

    # The IP-strip/proxy-header block lives in one shared snippet (not
    # duplicated per server block) — both the TLS and onion server blocks
    # include it, and the snippet itself carries every header.
    snippet = (ROOT / "nginx/snippets/proxy-headers.conf").read_text()
    for header in (
        "X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP", "True-Client-IP",
    ):
        assert f"proxy_set_header {header}" in snippet
        assert f"proxy_set_header {header}" not in tls, "duplicated instead of included"
        assert f"proxy_set_header {header}" not in onion, "duplicated instead of included"
    assert "include /etc/nginx/snippets/proxy-headers.conf;" in tls
    assert "include /etc/nginx/snippets/proxy-headers.conf;" in onion


def _servers(conf: str) -> list[str]:
    return re.findall(r"\n    server \{.*?\n    \}", conf, re.S)


def test_the_behind_proxy_nginx_differs_from_nginx_conf_only_in_its_listeners() -> None:
    """The plain-HTTP config for an external TLS terminator is a second file;
    everything but its port-80 block must stay identical to nginx.conf."""
    conf = (ROOT / "nginx/nginx.conf").read_text()
    behind = (ROOT / "nginx/nginx.behind-proxy.conf").read_text()

    def preamble(text: str) -> str:
        text = text[text.index("worker_processes"):]
        return text[: text.index("\n    }\n", text.index("upstream openwhistle"))]

    assert preamble(behind) == preamble(conf)
    tls = next(s for s in _servers(conf) if "listen 443 ssl" in s)
    onion = next(s for s in _servers(conf) if "listen 8080;" in s)
    assert onion in _servers(behind)
    assert "listen 443" not in behind
    plain = next(s for s in _servers(behind) if "listen 80;" in s)
    assert "return 301" not in plain
    location = re.search(r"\n        location / \{.*?\n        \}", tls, re.S)
    assert location and location.group(0) in plain
    for snippet in ("proxy-headers.conf", "static-location.conf"):
        assert f"include /etc/nginx/snippets/{snippet};" in plain


def test_the_behind_proxy_override_swaps_the_config_and_drops_443() -> None:
    override = (ROOT / "docker-compose.behind-proxy.yml").read_text()
    assert "./nginx/nginx.behind-proxy.conf:/etc/nginx/nginx.conf:ro" in override
    # !override replaces the port list; a plain list would be merged with 443.
    assert "ports: !override" in override
    assert '"443:443"' not in override


def test_nginx_tls_listener_offers_only_tls_1_2_and_1_3() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    tls = next(
        s for s in re.findall(r"\n    server \{.*?\n    \}", conf, re.S) if "listen 443 ssl" in s
    )
    assert re.findall(r"ssl_protocols ([^;]+);", tls) == ["TLSv1.2 TLSv1.3"]


def test_nginx_static_location_is_a_shared_snippet_too() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    onion = next(s for s in servers if "listen 8080;" in s)
    snippet = (ROOT / "nginx/snippets/static-location.conf").read_text()
    assert "location /static/" in snippet
    # The app sets Cache-Control: no-cache; add_header would append a second,
    # conflicting value rather than replace it.
    directives = re.sub(r"#.*", "", snippet)
    assert "add_header" not in directives and "expires" not in directives
    assert "location /static/" not in tls, "duplicated instead of included"
    assert "location /static/" not in onion, "duplicated instead of included"
    assert "include /etc/nginx/snippets/static-location.conf;" in tls
    assert "include /etc/nginx/snippets/static-location.conf;" in onion


def test_docker_compose_mounts_the_nginx_snippets_directory() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    assert "./nginx/snippets:/etc/nginx/snippets:ro" in compose


def test_onion_listener_has_its_own_higher_budget_rate_limit_zone() -> None:
    """Every onion visitor arrives from 127.0.0.1 (the host's Tor
    daemon), so ow_req (per-IP) would give them all ONE shared bucket by
    coincidence; the onion listener gets its own zone, keyed on a constant
    to make that explicit, with a higher rate/burst than the per-IP zone."""
    conf = (ROOT / "nginx/nginx.conf").read_text()
    assert 'limit_req_zone "onion" zone=ow_req_onion:' in conf
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    onion = next(s for s in servers if "listen 8080;" in s)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    assert "limit_req zone=ow_req_onion" in onion
    assert "limit_req zone=ow_req " in tls  # unchanged, still per-IP
    onion_rate = int(re.search(r"ow_req_onion:\w+ rate=(\d+)r/s", conf).group(1))  # type: ignore[union-attr]
    tls_rate = int(re.search(r"\bow_req:\w+ rate=(\d+)r/s", conf).group(1))  # type: ignore[union-attr]
    assert onion_rate > tls_rate
    onion_burst = int(re.search(r"ow_req_onion burst=(\d+)", onion).group(1))  # type: ignore[union-attr]
    tls_burst = int(re.search(r"ow_req burst=(\d+)", tls).group(1))  # type: ignore[union-attr]
    assert onion_burst > tls_burst


def test_x_ow_onion_is_cleared_by_default_and_set_only_on_the_onion_listener() -> None:
    """The app must never decide "onion"
    from the client-supplied Host, so nginx asserts it instead. The shared
    snippet clears the header for every server block that includes it (so
    the TLS listener can never forget to), and only the onion (8080) block
    sets it back to "1", after its own include — an override, not a merge."""
    snippet = (ROOT / "nginx/snippets/proxy-headers.conf").read_text()
    assert 'proxy_set_header X-OW-Onion "";' in snippet

    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    onion = next(s for s in servers if "listen 8080;" in s)

    assert 'proxy_set_header X-OW-Onion "1";' not in tls
    include_idx = onion.index("include /etc/nginx/snippets/proxy-headers.conf;")
    set_idx = onion.index('proxy_set_header X-OW-Onion "1";')
    assert set_idx > include_idx, "must come AFTER the include to override it, not before"


# ── The Ansible-deployed nginx (the live demo) must clear X-OW-Onion too —
# with ONION_LOCATION set the app trusts that header, so any deployment path
# that never clears it lets a client spoof onion-listener behaviour
# (non-Secure cookies, no HSTS). One source, not a second hand-maintained
# copy of the snippet.


def test_ansible_nginx_template_includes_the_shared_snippets_not_a_second_copy() -> None:
    j2 = (ROOT / "ansible/roles/openwhistle/templates/nginx.conf.j2").read_text()
    for header in (
        "X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP", "True-Client-IP",
        "X-OW-Onion",
    ):
        assert f"proxy_set_header {header}" not in j2, (
            f"{header} hand-retyped into nginx.conf.j2 instead of included from the snippet"
        )
    assert "location /static/" not in j2, "static location hand-retyped instead of included"
    # Both branches (TLS on/off) of the {% if %} must include both snippets.
    assert j2.count("include /etc/nginx/snippets/proxy-headers.conf;") == 2
    assert j2.count("include /etc/nginx/snippets/static-location.conf;") == 2


def test_ansible_deploy_copies_the_real_snippet_files_not_a_retyped_copy() -> None:
    deploy = (ROOT / "ansible/roles/openwhistle/tasks/deploy.yml").read_text()
    assert "nginx/snippets/" in deploy
    assert "openwhistle_deploy_dir }}/nginx/snippets/" in deploy
    # role_path, not playbook_dir: the role must work from any playbook.
    src = re.search(r'src: "\{\{ role_path \}\}/([^"]+)"', deploy)
    assert src, "snippets src is not relative to role_path"
    assert (ROOT / "ansible/roles/openwhistle" / src.group(1)).resolve() == ROOT / "nginx/snippets"


def test_ansible_compose_mounts_the_nginx_snippets_directory() -> None:
    compose = (ROOT / "ansible/roles/openwhistle/templates/docker-compose.yml.j2").read_text()
    assert "./nginx/snippets:/etc/nginx/snippets:ro" in compose


def _render_role_template(name: str) -> str:
    """Render one of the role's templates with defaults/main.yml's own values
    (only the empty, documented-as-required openwhistle_domain is set)."""
    import jinja2
    import yaml

    defaults = yaml.safe_load(
        (ROOT / "ansible/roles/openwhistle/defaults/main.yml").read_text()
    )
    defaults["openwhistle_domain"] = "ow-test.example.com"

    def _bool(v: object) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "yes", "1", "on")

    env = jinja2.Environment()  # noqa: S701 — renders nginx/compose config, not HTML
    env.filters["bool"] = _bool
    return env.from_string(
        (ROOT / "ansible/roles/openwhistle/templates" / name).read_text()
    ).render(**defaults)


def test_ansible_writes_every_nginx_bind_mount_world_readable() -> None:
    """nginx runs with cap_drop ALL, so its root master has no CAP_DAC_OVERRIDE
    and cannot open a 0640 file owned by the deploy user: nginx would not start."""
    import yaml

    compose = yaml.safe_load(_render_role_template("docker-compose.yml.j2"))
    assert "DAC_OVERRIDE" not in compose["services"]["nginx"].get("cap_add", [])
    sources = [
        v.split(":")[0].removeprefix("./").rstrip("/")
        for v in compose["services"]["nginx"]["volumes"]
        if v.startswith("./")
    ]
    assert sources
    tasks = yaml.safe_load((ROOT / "ansible/roles/openwhistle/tasks/deploy.yml").read_text())
    modes = {}
    for task in tasks:
        args = task.get("ansible.builtin.template") or task.get("ansible.builtin.copy") or {}
        dest = args.get("dest", "").removeprefix("{{ openwhistle_deploy_dir }}/").rstrip("/")
        modes[dest] = (args.get("mode"), args.get("directory_mode"))
    for source in sources:
        assert source in modes, f"{source} is mounted into nginx but no task writes it"
        mode, directory_mode = modes[source]
        assert mode == "0644", f"{source} is written {mode}; nginx cannot read it"
        assert directory_mode in (None, "0755"), source


def test_ansible_nginx_template_renders_with_the_roles_own_defaults_and_clears_x_ow_onion() -> None:
    """Fast, no-docker guard for the CI job's own render step: renders
    nginx.conf.j2 with defaults/main.yml's actual values (only overriding the
    empty, documented-as-required openwhistle_domain) and confirms the
    output both includes the snippet and never hand-sets X-OW-Onion itself."""
    rendered = _render_role_template("nginx.conf.j2")

    assert "proxy_set_header X-OW-Onion" not in rendered
    assert rendered.count("include /etc/nginx/snippets/proxy-headers.conf;") == 1
    assert "ow-test.example.com" in rendered


def test_every_public_route_is_rate_limited_in_both_deployments() -> None:
    """POST /submit (and every other public route) is limited by the bundled
    nginx's catch-all location and, on Kubernetes, by the ingress annotations
    at the same rate and burst."""
    import yaml

    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    proxied = [s for s in servers if "proxy_pass" in s]
    assert proxied
    for server in proxied:
        for location in re.findall(r"location [^{]*\{[^}]*\}", server):
            if "proxy_pass" in location:
                assert "limit_req zone=" in location, location
    rate = int(re.search(r"\bow_req:\w+ rate=(\d+)r/s", conf).group(1))  # type: ignore[union-attr]
    burst = int(re.search(r"ow_req burst=(\d+)", conf).group(1))  # type: ignore[union-attr]

    values = yaml.safe_load((ROOT / "charts/openwhistle/values.yaml").read_text())
    annotations = values["ingress"]["annotations"]
    rps = int(annotations["nginx.ingress.kubernetes.io/limit-rps"])
    multiplier = int(annotations["nginx.ingress.kubernetes.io/limit-burst-multiplier"])
    assert (rps, rps * multiplier) == (rate, burst)


def test_the_chart_requires_crit_error_logging_where_the_operator_reads() -> None:
    """Below crit, ingress-nginx logs each rate-limited reporter's IP address."""
    for path in ("values.yaml", "templates/NOTES.txt"):
        text = (ROOT / "charts/openwhistle" / path).read_text()
        assert "REQUIRED" in text and "error-log-level: crit" in text, path
    docs = (ROOT / "docs/docs.html").read_text()
    assert "limit-req-status-code" in docs
    values = (ROOT / "charts/openwhistle/values.yaml").read_text()
    for text in (docs, values):
        # L4: proxy protocol or a local traffic policy; L7: forwarded headers
        # only with the trusted range, or clients spoof X-Forwarded-For.
        for setting in (
            "use-proxy-protocol",
            "externalTrafficPolicy: Local",
            "use-forwarded-headers",
            "proxy-real-ip-cidr",
        ):
            assert setting in text, setting
