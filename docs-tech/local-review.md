# Local review: checking every page in Chrome

How-to: an agent (the Claude-in-Chrome extension) needs to visually check every
page before a release, and must be able to sign in by itself — a human never
types credentials into a browser for this. Reference:
[easywall's own `local-review.md`](https://github.com/jp1337/easywall/blob/main/docs-tech/local-review.md)'s
"Enter the demo" button — the same idea applied here.

## Two stacks, not one

`docker-compose.e2e.yml` is also CI's own E2E file (`.github/workflows/e2e.yml`).
The one-click button never lives there: `LOCAL_REVIEW_LOGIN` on that file would
put a second `<button>` in front of the E2E suite's own login helper, which
clicks the *first* `button.btn-primary[type='submit']` it finds — so it would
click the local-review button by accident and every E2E admin test would
silently sign in as someone who never typed a password.

Instead, `docker-compose.review.yml` is a review-only override:

```bash
podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml up -d --build
```

It adds `LOCAL_REVIEW_LOGIN=true` and rebinds the app's published port to
`127.0.0.1:4009` (loopback only — the plain file publishes on every interface,
fine for CI's throwaway runner, not fine for a maintainer's LAN-reachable
machine). The button also gets its own `id` (`local-review-login-btn`) and a
non-primary class (`btn-secondary`, not `btn-primary`), so even pointing the
E2E suite at the review stack by mistake would not make its selectors match
it.

`docker compose` works the same way if that is what is installed.

## Why the flag alone is not the only gate

`LOCAL_REVIEW_LOGIN` requires `DEMO_MODE=true` (the app refuses to start
otherwise) — but `DEMO_MODE` is also what the public demo runs with, and
nothing except a test *stops* a hand-added `LOCAL_REVIEW_LOGIN=true` in that
host's `.env` from passing the validator. So both the route and the button
check a second, independent condition, `_local_review_reachable()` in
`app/api/auth.py`: no header only a reverse proxy adds
(`X-Forwarded-Proto`/`-For`, `X-Real-IP`, `Forwarded`, `Via` — nginx and every
ingress controller always set `X-Forwarded-Proto` in front of this app, and a
client cannot strip a header the proxy adds after it) **and** the `Host` the
request addressed is a loopback name (`localhost`, `127.0.0.1`, `[::1]`, with
or without a port).

A client-*address* check does not work here: the app's `uvicorn` runs without
`--proxy-headers` (see `Dockerfile`), so a browser on the same machine,
reaching the container through podman/docker's NAT, shows up as the
container's gateway IP — never as `127.0.0.1`. Either half of the header/Host
check alone can be spoofed (a stray client header; nginx's default server
echoing back whatever `Host` it was given); together they hold, and the
loopback-only port binding above is a third, independent layer.

Fails either check → 404, same as the flag being off. This also means: on
the public demo host, even a hand-edited `LOCAL_REVIEW_LOGIN=true` gets no
button and no route, because every real request to `demo.openwhistle.net`
arrives through nginx with `X-Forwarded-Proto` set and a `Host` that is not
loopback.

## Signing in

Open `/admin/login` and click **Enter the local review**. One POST,
CSRF-protected, no form fields — it signs in as the seeded demo admin
(`demo`) with a full session, password and MFA already satisfied. Every
admin page is reachable from there.

With the flag off, unreachable (a proxy header present, or a non-loopback
`Host`), or the demo admin deactivated, the route answers 404 or redirects to
`/admin/login` — never a session, never an audit row for a login that did not
happen. `GET`/`HEAD /admin/local-review-login` also answer 404 (not the 405 a
path with only a `POST` handler would otherwise give, which would reveal the
path exists).

Each successful sign-in writes an audit log entry (`auth.local_review_login`),
same as any other admin login, so a real access review is never missing them.
Not separately rate-limited: the reachability check above already confines it
to a loopback request with no proxy in front of it.

## The setup stack: what the button cannot show

`/setup`, `/admin/mfa/setup` (a fresh account's first login) and
`/admin/organisations` (needs `MULTI_TENANCY_ENABLED=true`) are never
reachable through the button — its whole existence assumes setup is already
done and MFA already enrolled, and the review stack does not turn on
multi-tenancy. Bring up a second, independent instance for these, as a compose
profile so it costs nothing when not needed:

```bash
podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml --profile setup up -d --build app-setup
```

`app-setup` has its own database and Redis (`db-setup`/`redis-setup`, no
volumes — same as the main stack, a plain `down` already clears them),
`DEMO_MODE=false`, no `LOCAL_REVIEW_LOGIN`, `SECURE_COOKIES=false` (plain
HTTP), and `MULTI_TENANCY_ENABLED=true`, at **<http://localhost:4010>**. Walk:

1. `/setup` — the wizard, using `SETUP_TOKEN=review-setup-token-not-for-production`
   (pinned in `docker-compose.review.yml`, a test value that exists only in
   that file — never a real secret).
2. `/admin/login` — the login page an operator *without* `LOCAL_REVIEW_LOGIN`
   actually sees: no button.
3. Sign in with the admin account the wizard just created. First login lands
   on `/admin/mfa/setup` — viewing the QR/enrolment page is enough, nobody has
   to finish enrolling it.
4. `/admin/organisations` — reachable now that multi-tenancy is on.

Tear down with `podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml --profile setup down -v`.

## The page matrix

Every public and admin page the app itself renders, every page template under
`app/templates` (`tests/test_local_review.py` fails if either grows a route or
a template missing from this table — parsed from the table rows only, and
checked against a floor so an empty walk cannot pass by accident), plus the
marketing/documentation site under `docs/`.

### The app

| Page | Template | Notes |
|---|---|---|
| `/` | — | Redirects to `/setup` or `/submit`; no template of its own. |
| `/submit` | `submit.html` | Whistleblower submission wizard — walk every step, both submission modes. |
| — (finishing the wizard) | `submit_success.html` | The PIN screen. Complete a submission on `/submit` to reach it. |
| — (a concurrent double-submit) | `submit_pending.html` | "Still processing" page for a second submit of the same draft. Hard to force by hand reliably — throttle the network in devtools and click Submit twice quickly; `tests/test_submit_prg.py` exercises it directly if a manual attempt does not land. |
| `/status` | `status.html` | Whistleblower status/PIN lookup — use a seeded demo case (`OW-DEMO-00001` / `demo-pin-received-00001`); also check the signed-in state after a lookup succeeds. |
| `/setup` | `wizard/setup.html` | Setup stack only (see above) — the plain/review stack's `DEMO_MODE` seeding has already completed setup, so this redirects to `/admin/login` there. |
| `/admin/login` | `login.html` | With the button (review stack) and without it (setup stack). |
| — (login with `demo`/`demo`, then no code) | `login_mfa.html` | The TOTP verify screen. The one-click button skips straight past it — use the login form's own demo-credentials autofill instead (local test credentials from the seed) and stop before entering `000000`. |
| `/admin/mfa/setup` | `login_mfa_setup.html` | Setup stack only — a fresh account's first login. |
| — (a 422) | `error.html` | Open devtools on any admin page and run `fetch('/admin/login/mfa',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'csrf_token='+document.cookie.match(/ow_csrf=([^;]+)/)[1]})` — no `temp_token` field triggers the 422 validation page. |
| `/admin/dashboard` | `admin/dashboard.html` | Filters, search, status pills, the case list. |
| `/admin/reports/{report_id}` | `admin/report.html` | One representative report detail page (any seeded `OW-DEMO-000xx`) — exercise the identity-reveal form, internal notes, status change, and the four-eyes deletion flow. |
| `/admin/users` | `admin/users.html` | User management. |
| `/admin/organisations` | `admin/organisations.html` | Setup stack only — needs `MULTI_TENANCY_ENABLED=true`. |
| `/admin/categories` | `admin/categories.html` | Category management. |
| `/admin/locations` | `admin/locations.html` | Location management. |
| `/admin/retention` | `admin/retention.html` | Retention policy settings. |
| `/admin/stats` | `admin/stats.html` | Statistics dashboard. |
| `/admin/system` | `admin/system.html` | System info page. |
| `/admin/telephone-channel` | `admin/telephone_channel.html` | HinSchG §16 compliance checklist page. |
| `/admin/audit-log` | `admin/audit_log.html` | Audit log, with its action filter. |

Excluded from the template floor, by name, with why: `base.html` (layout, no
route renders it standalone) and every partial starting with `_`
(`_field.html`, `_icons.html`, `admin/_audit.html`, `admin/_layout.html` —
included by another template, never rendered on their own).

### The website (`docs/`, static — GitHub Pages)

Serve it from inside the directory, so `docs/`-relative links resolve the way
they do once GitHub Pages roots the site at `docs/` via the `docs/CNAME` file
(`openwhistle.net`):

```bash
python3 -m http.server -d docs 8000
```

Serving from the repository root instead breaks every `../`-relative link on
`docs/de/index.html` and `docs/blog/*.html` (they resolve against `docs/`, not
against the repo root), and every root-absolute link (`/docs.html`,
`/roadmap.html`) 404s because there is no `docs/docs.html` at the server root.

| Page | Notes |
|---|---|
| `docs/index.html` | Landing page, English. |
| `docs/de/index.html` | Landing page, German — the longest strings; check nothing overflows or truncates. |
| `docs/docs.html` | Full documentation — long page, check the anchor nav and the "Current version" line. |
| `docs/roadmap.html` | Roadmap. |
| `docs/blog/index.html` | Blog index. |
| `docs/blog/hinschg-compliance-leitfaden.html` | Article. |
| `docs/blog/interne-meldestelle-einrichten.html` | Article. |
| `docs/blog/was-ist-neu-in-1-6.html` | Article. |
| `docs/blog/whistleblower-software-vergleich.html` | Article. |

## What to check, on every page

- **Both themes**: light and dark (`prefers-color-scheme`, or the in-page
  toggle where there is one — exercise the toggle itself, not just the OS
  preference).
- **Both widths**: 1440px (desktop) and 390px (phone) — no sideways scroll.
- **Both languages**: `en` and `de` (`?lang=de` or the language switcher) — German
  strings are the longest and are what breaks a layout first.
- **Console**: no error, and specifically no CSP violation
  (`Refused to ... because it violates the following Content Security Policy
  directive`) — this app runs a strict CSP with no `unsafe-inline`.
- **Interactive paths**, not just the resting state: the setup/submission
  wizard's steps, the identity-reveal form, the dashboard's filters, a theme
  toggle, a language switch.

Fix every finding before the release PR — nothing here is carried forward.

## Traps

| Trap | What happens |
|---|---|
| The admin login rate limiter | `MAX_LOGIN_ATTEMPTS` failed attempts within `LOGIN_LOCKOUT_MINUTES` locks a username. The one-click button never touches this limiter — it has no password or code to get wrong. The regular username/password + TOTP form (the demo-credentials autofill on the same page) still goes through it, so a sweep that signs in that way instead can trip it. |
| `/setup` and `/admin/mfa/setup` redirect away on the plain/review stack | `DEMO_MODE` seeding completes setup and enrols the demo admin's TOTP before either page is ever requested. Use the setup stack (above) for both. |
| Serving `docs/` from the wrong directory | `docs/`-relative links assume the server root is `docs/` itself, matching how GitHub Pages roots the site there via `docs/CNAME`. |
| A stack kept up across two review sessions | The four seeded demo reports (`OW-DEMO-00001`..`00004`) are always the same rows — nothing accumulates, so this one has no gotcha, unlike a counting assertion in an automated test. |

## Tearing down

```bash
podman compose -f docker-compose.e2e.yml -f docker-compose.review.yml down -v
```

Neither this file nor `docker-compose.e2e.yml` declares a named volume, so
every `db`/`redis` container gets a fresh anonymous one on `up`, regardless
of `-v` — a plain `down` (no `-v`) does not delete the previous one, only
orphans it on disk (checked directly: `podman volume ls`/`inspect` after a
plain `down` still lists it). So `-v` is not what gives the next `up` a
clean slate — that already happens either way — it only matters for not
leaving an orphaned volume behind on every cycle.
