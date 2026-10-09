# Website P5: move

Type: explanation + scope. Source: the session of 2026-10-09; the maintainer approved publishing the site and every
step it needs ("selbständig weiter arbeiten bis zur Veröffentlichung der Website ohne Rückfragen"). It refines P5 of
`2026-10-01-website-redesign-design.md` and takes the "Handed to P5" table of `2026-10-09-website-p4-design.md`.

## Outcome

`openwhistle.net` is served by `ghcr.io/openwhistle/website` on root01xvp behind the host nginx. GitHub Pages is
switched off. The repository and the image hold no personal data of the maintainer: the imprint's and the privacy
policy's name and c/o address come from wdk-ansible's vault at runtime.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| P5-1 | Done in P4 (rulings R16, R17): the legal pages include the operator's address by SSI from wdk-ansible's read-only mount; `pages.yml` is gone, so Pages keeps its last deployment until DNS moves | Global rule: no personal data in a public repo or image (maintainer, 2026-10-09) |
| P5-2 | This PR merges and its image is deployed **before** DNS moves | Visitors of the container must read a privacy policy that describes the container, not GitHub Pages |
| P5-3 | The privacy policy names the own server (Hetzner Online GmbH, Art. 28 GDPR), the counter's four log fields and their retention (journald 30 days; archive per P3-6), instead of GitHub Pages | Plan W4; the policy describes exactly this setup |
| P5-4 | `--redirect-stubs`, `write_stubs()` and `docs/_legacy/` go; nginx answers every old URL with 301 | The stubs only existed for Pages |
| P5-5 | The HSTS preload submission is not part of P5 | `mta-sts`, `autoconfig`, `autodiscover` must first answer over HTTPS; the submission is hard to undo |
| P5-6 | Rollout is wdk-ansible's: digest pin, Renovate, template 22; vhost proxy-only with `access_log off`; DNS last, after the vhost is verified against the live container | Infra session, 2026-10-09 |

## Guards

| Guard | Catches |
| --- | --- |
| The privacy policy names Hetzner and the four log fields, not GitHub Pages | a policy describing the old hosting |
| No `pages.yml`, no stub writer, no `_legacy/` | Pages machinery coming back |

## Steps outside the repository (in order)

1. P4 merged; its digest went to wdk-ansible. P5 merges → a new digest; wdk-ansible deploys that one.
2. wdk-ansible deploys container, mount and vhost; the openwhistle session checks headers, imprint, redirects and the
   log through the vhost (Host header against root01xvp) before DNS.
3. DNS moves (apex A/AAAA, www; Pages A records deleted).
4. Checks from outside: headers, `/impressum/`, `/.well-known/security.txt`, an old URL's 301, `/` language choice.
5. GitHub Pages unpublished.
