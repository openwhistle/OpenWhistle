# The website image

How-to: build, run and check `ghcr.io/openwhistle/website` (openwhistle.net as an nginx container).
Why it is built this way: `docs-tech/specs/2026-10-09-website-p4-design.md`.

## Build and run

Build from a **full clone**. A linked git worktree fails: `build_site.py` runs git (sitemap `lastmod`)
and sees a `.git` pointer file.

```bash
docker build -f website/Dockerfile -t openwhistle-website:local .
docker run --rm --name ow-website --read-only --tmpfs /tmp -p 8080:8080 openwhistle-website:local
```

| Variant | Change |
| --- | --- |
| podman | `podman` for `docker`; `CONTAINER_CLI=podman` for the tests |
| SELinux host, private mount | `-v "$PWD/private":/usr/share/nginx/private:ro,z` |

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
| Personal data | The maintainer's name and c/o address never enter the repo or the image |
| Address page | wdk-ansible renders `address.html` from ansible-vault and bind-mounts the directory read-only at `/usr/share/nginx/private`; nginx includes it by SSI through the internal location `/_private/` |
| `/healthz` | Answers 204, not logged |
| Deploy | As energysharing in wdk-ansible: digest pin in `docker_images.yml`, Renovate PR per new digest, merge runs Semaphore template 22. No token leaves GitHub |
