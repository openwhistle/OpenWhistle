# Scanning the image locally

How-to for the maintainer: run the CI image gate on your machine. Same scanner,
same pin, same policy as `security.yml` and `docker-publish.yml`.

| Where | Image scanned | When |
| --- | --- | --- |
| `security.yml` job `image` | a fresh build of the commit | every PR, Mondays, every publish |
| `security.yml` job `published` | `:latest` and `:edge` (the demo), amd64 and arm64 | Mondays |
| `docker-publish.yml` job `build` | the digest just pushed, per platform | before `merge` tags it |

## Scan

From the repository root (`.grype.yaml` holds the reviewed exceptions):

```bash
GRYPE=docker.io/anchore/grype@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea  # v0.121.0, as in the workflows
podman run --rm -v "$PWD/.grype.yaml:/policy.yaml:ro,Z" "$GRYPE" \
  registry:ghcr.io/openwhistle/openwhistle:latest \
  --config /policy.yaml --only-fixed --fail-on negligible
echo "exit $?"   # 0 = clean, 2 = a fixable finding
```

A local build: `podman save -o /tmp/ow.tar <image>`, mount it with
`-v /tmp/ow.tar:/img.tar:ro,Z` and scan `docker-archive:/img.tar`.

Drop `--only-fixed --fail-on negligible` to see the unfixable findings too
(BusyBox's CVE-2025-60876 has no fix in any Alpine release; `apk del busybox`
is refused because `alpine-baselayout` and `ca-certificates` depend on it).

## A finding

| Finding | Fix |
| --- | --- |
| Alpine package (`apk`) | Rebuild: the final stage runs `apk upgrade`. Published images stay stale until the next release, which is what the Monday `published` job reports. |
| Python package | Update `uv.lock` (`uv lock --upgrade-package <name>`). |
| Python itself (`binary`) | Wait for the `python:3.15-alpine` digest Renovate brings; if the fix exists only in a newer line, add an entry to `.grype.yaml`. |

An entry in `.grype.yaml` names the CVE, the package **and its version**, and a
reason (`tests/test_image_scan.py` enforces all three). The version pin makes it
expire: once the package moves, the new version is judged without the
exception.

## Why grype, not Trivy

v2.2.1 shipped zlib `1.3.2-r0` six days after `-r1` fixed CVE-2026-85091. Trivy
rated it MEDIUM and the old gate passed only CRITICAL and HIGH; grype rates it
High and does not filter by severity. Trivy also does not match the Python
binary. Trivy still runs, for secrets only, so no second vulnerability verdict
can disagree with grype in silence.
