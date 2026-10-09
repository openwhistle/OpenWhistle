# The website image

How-to: build, run and check `ghcr.io/openwhistle/website` (openwhistle.net as an nginx container).
Why it is built this way: `docs-tech/specs/2026-10-09-website-p4-design.md`.

## Build and run

Build from a **full clone**. A linked git worktree fails: `build_site.py` runs git (sitemap `lastmod`)
and sees a `.git` pointer file.

```bash
docker build -f website/Dockerfile -t openwhistle-website:local .
docker run --rm --name ow-website --read-only --tmpfs /tmp -p 8080:8080 \
  -v "$PWD/tests/website/fixtures/private:/usr/share/nginx/private:ro" openwhistle-website:local
```

| Variant | Change |
| --- | --- |
| podman | `podman` for `docker`; `CONTAINER_CLI=podman` for the tests |
| SELinux host | `:ro,z` instead of `:ro` on the mount |

## Check

| What | Command |
| --- | --- |
| Container tests | `WEBSITE_URL=http://127.0.0.1:8080 WEBSITE_CONTAINER=ow-website pytest tests/website -q --no-cov` |
| Browser tests | `WEBSITE_URL=http://127.0.0.1:8080 pytest tests/e2e/test_site_container.py -m e2e --browser chromium -q --no-cov` |
| By eye | every page in Chrome, dark first: `docs-tech/local-review.md` |

## Change

| You change | Do |
| --- | --- |
| An inline script | `tests/test_website_config.py` names the new hash; put it in **both** CSP lines of `website/nginx.conf` |
| A redirect | `docs/_data/redirects.yml` only |
| A font | Variable originals are in `docs/_fonts`; the build subsets them and inlines them as `data:` URIs in `fonts.css`. `docs/fonts/*.woff2` belong to the app image (copied by name): leave them |
| Page views | `journalctl CONTAINER_NAME=openwhistle-website -o cat --since -7d \| python scripts/site_stats.py` |

## Private data and deploy

| Fact | Detail |
| --- | --- |
| Personal data | Neither the repo nor the image holds any. The imprint and both privacy policies carry `<!--# include virtual="/_private/address.html" -->` where the address goes; tests use the fake fixture |
| Address page | wdk-ansible renders `address.html` from ansible-vault and bind-mounts the directory read-only at `/usr/share/nginx/private`; nginx includes it by SSI through the internal location `/_private/` |
| File mode | `address.html` must be readable by UID 101 (`0444`, as wdk-ansible renders it). `/healthz` only checks that it exists: an unreadable file passes it, and the legal pages then embed the 404 page |
| `/healthz` | 204 with the fragment, 503 without; not logged |
| Leak guard | `OW_PRIVATE_STRINGS` (one string per line) arms `test_no_file_in_the_repository_holds_the_real_data`; unset, it skips |
| Deploy | As energysharing in wdk-ansible: digest pin in `docker_images.yml`, Renovate PR per new digest, merge runs Semaphore template 22. No token leaves GitHub |
