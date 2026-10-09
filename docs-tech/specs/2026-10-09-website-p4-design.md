# Website P4: container

Type: explanation + scope. Source: the brainstorming session of 2026-10-09. It refines P4 of
`2026-10-01-website-redesign-design.md` (sections Architecture and deploy; Security, performance, accessibility;
Guards) and takes the P4 row of the P3 plan's hand-off table. Every decision below was taken with the maintainer.

## Outcome

The site exists as a signed container image that serves it exactly as the redesign spec describes: its own
security headers, a CSP without `'unsafe-inline'`, 301s for every old URL, and a log with no IP address. Tests prove
each of these against the running container. Nothing is deployed: GitHub Pages keeps serving `openwhistle.net` until
P5.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| P4-1 | P4 ends at a published image and its tests; rollout, the Semaphore trigger, checks from outside and DNS are P5 | Maintainer's choice |
| P4-2 | One PR for all of P4 | As P3 |
| P4-3 | CSP hashes are written by hand in `website/nginx.conf`; a test compares them with every inline script of every built page | A changed inline script is a security change and shows in the diff; the failing test names the right hash |
| P4-4 | The redirect map is generated at build from `docs/_data/redirects.yml` | Data that grows with every rename; the redesign spec already says "`redirects.yml` → nginx map" |
| P4-5 | Multi-stage `website/Dockerfile`: Python builds `_site/`, `nginx-unprivileged` serves it; both bases pinned by digest | `docker build` alone reproduces the image; no build artefact travels between CI jobs |
| P4-6 | Published to GHCR only, signed with cosign, with SBOM and provenance | Same chain as the app image; the site is not a product for others, so no Docker Hub or quay |
| P4-7 | `Cache-Control: no-cache` with ETag on every response | File names carry no hash and the fonts are re-subset whenever the text changes; an unchanged file costs a 304 |
| P4-8 | `style-src 'self'` with no hash | The built site has no inline style and no `style=` attribute (checked 2026-10-09); the redesign spec's critical-CSS hash is not needed |
| P4-9 | `error_log stderr emerg` | nginx error lines carry `client: <IP>`; at `emerg` only start-up failures are written |
| P4-10 | The image is rebuilt monthly | `security.txt` expires about 335 days after the build that wrote it, as on Pages today |

## Image

```text
website/Dockerfile
  stage 1  python:3.14-alpine@sha256:…     uv sync --group site; build_site.py → /out/site
                                            + a .gz beside every html, css, js, svg, xml, txt and json
                                            + /out/redirects.map from docs/_data/redirects.yml
  stage 2  nginxinc/nginx-unprivileged:alpine@sha256:…
           /usr/share/nginx/html ← /out/site;  /etc/nginx/conf.d/ ← website/nginx.conf, redirects.map
           user 101, port 8080, read-only root filesystem with tmpfs for /tmp
```

- Workflow `website-image.yml`:
  - Triggers: a push to `main` touching `docs/**`, `website/**`, `scripts/build_site.py`, `CHANGELOG.md`,
    `pyproject.toml` or `uv.lock`; monthly; `workflow_dispatch`.
  - Steps: build, run the container tests (below), Trivy, push `ghcr.io/openwhistle/website:latest` and
    `:sha-<short>`, then cosign keyless signing.
  - Pull requests build and test but never push.
- `docs/_legacy/` stays: Pages still serves those three files until P5. nginx answers them with 301.

## nginx (`website/nginx.conf`)

| Area | Rule |
| --- | --- |
| Server | `listen 8080`, `server_tokens off`, `absolute_redirect off` (behind the host nginx, a relative `Location` keeps https and the host) |
| Headers, every response | `Content-Security-Policy: default-src 'none'; script-src 'self' 'sha256-<theme>'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests`, `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()` |
| `/en/docs/` | The same, with `script-src` adding the docs-anchor and menu-close hashes and `'wasm-unsafe-eval'` (Pagefind) |
| `/` and `/index.html` | 302 to `/de/` when `Accept-Language` starts with `de`, else to `/en/`; `Vary: Accept-Language`; no cookie |
| Redirects | `map $uri $moved { include redirects.map; }` → 301 |
| Not found | `error_page 404 /404.html` |
| Compression | `gzip_static on`; no on-the-fly gzip |
| Types | `application/wasm` for `.wasm`; `.pagefind` and `.pf_*` as `application/octet-stream`; `security.txt` as `text/plain; charset=utf-8` |
| Access log | `log_format counter '$time_iso8601 $uri $status $ref_host'`, where `$ref_host` is the host of `$http_referer` via `map`, else `-`. No `$remote_addr`, no `X-Forwarded-For`, no user agent, no query |
| Error log | `error_log stderr emerg` (P4-9) |

`scripts/site_stats.py` reads `counter` lines from stdin or `journalctl` and prints requests per path and per
referrer host. It is used from P5 on.

## Tests and guards

Every guard goes through `scripts/mutation_audit.py` and must go RED.

| Level | Proves | Runs |
| --- | --- | --- |
| Unit, no Docker | The CSP hashes equal the SHA-256 of every inline script of every built page, per location. No inline script exists outside `/en/docs/` except the theme script. `redirects.map` has every `redirects.yml` entry and every URL of `tests/data/sitemap-2026-10-01.txt` resolves. `log_format` holds none of `$remote_addr`, `$http_x_forwarded_for`, `$http_user_agent` or `$request`. `error_log` is `emerg`. Every text file has its `.gz` | pytest, every PR |
| Container | `nginx -t`; the headers per path; every 301; the 302 for `de` and for `en`; 404 page and status; `security.txt` type; the `.gz` variant with `Accept-Encoding: gzip`; the process is not root; **no log line carries an IP**, also with `X-Forwarded-For` set | `website-image.yml` and a PR job: build, `docker run`, pytest against it |
| Browser, Playwright against the container | All 70 pages raise no `securitypolicyviolation`; docs search works under the real CSP; per page: first view ≤ 100 KB transferred, LCP < 1.5 s under mobile throttling, CLS 0, no request to another host | same job |
| Chrome check | Every page at Full HD, dark first, served by the container, so with the real CSP | before the PR |

The existing site e2e tests keep running against the fast Python server; only the new job tests the container.

## Documentation

- `docs-tech/website-image.md`: build, run and check the image locally (how-to).
- `README.md`: one sentence on how the site is served.
- This spec's "Handed to P5" section is the brief for the wdk-ansible session.

## Handed to P5

| Owner | Input |
| --- | --- |
| wdk-ansible | `host_specific/tasks/openwhistle-website.yml` on root01xvp (pattern `momo.yml`): `ghcr.io/openwhistle/website` pinned by digest in `docker_images.yml`, loopback port, read-only root filesystem, entry in `hc_expected_images`, not part of `demo.yml` |
| wdk-ansible | :443 vhost `openwhistle.net www.openwhistle.net`: proxy only, `access_log off;`, `error_log /dev/null;`, the four inherited host-level headers removed; deployed and verified before DNS moves |
| wdk-ansible | DNS, `mta-sts`/`autoconfig`/`autodiscover` over HTTPS before the HSTS preload submission, Search Console TXT (redesign spec § Constraints owned by wdk-ansible) |
| openwhistle | Semaphore trigger after the image push (token in `gh secret`); checks from outside; privacy policy and `tests/test_legal_pages.py` switch from GitHub Pages to the own server; `docs/_legacy/`, `--redirect-stubs` and `pages.yml` removed |

## Out of P4

Rollout, DNS, the Semaphore trigger and the privacy-policy switch (P5). Brotli (redesign spec: stock nginx lacks it).
Fingerprinted asset names (P4-7 makes them unnecessary).
