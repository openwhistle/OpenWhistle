# Local review: checking every page in Chrome

How-to: an agent (the Claude-in-Chrome extension) needs to visually check every
page before a release, and must be able to sign in by itself — a human never
types credentials into a browser for this. Reference:
`/var/home/jpy/projects/easywall/docs-tech/local-review.md`'s "Enter the demo"
button, the same idea applied here.

## Starting it

```bash
podman compose -f docker-compose.e2e.yml up -d --build
```

(`docker compose` works the same way if that is what is installed.) The stack
serves the app at **<http://localhost:4009>** over plain HTTP — no TLS, so
there is no certificate interstitial to click through (unlike a production
deployment, where `docker-compose.prod.yml`'s bundled nginx always serves
HTTPS). `DEMO_MODE=true` seeds the demo admin and four example reports;
`LOCAL_REVIEW_LOGIN=true` is what puts the one-click button on the page.

## Signing in

Open `/admin/login` and click **Enter the local review**. One POST, CSRF-protected,
no form fields — it signs in as the seeded demo admin (`demo`) with a full
session, password and MFA already satisfied. Every admin page is reachable
from there. The button only exists when `LOCAL_REVIEW_LOGIN=true`; with it
unset (or `false`, the default everywhere else) the route itself is 404 — it
does not exist, not merely hidden.

Each sign-in through the button writes an audit log entry
(`auth.local_review_login`), same as any other admin login, so a real access
review is never missing them.

## The page matrix

Every public and admin HTML page, plus the marketing/documentation site under
`docs/`. `tests/test_local_review.py` fails if the app grows an `/admin` or
public HTML route, or `docs/` grows an HTML page, that is missing from this
list.

### The app (served by the e2e stack, port 4009)

| Page | Notes |
|---|---|
| `/` | Public landing page. |
| `/submit` | Whistleblower submission wizard — walk every step, both submission modes. |
| `/status` | Whistleblower status/PIN lookup — use a seeded demo case (`OW-DEMO-00001` / `demo-pin-received-00001`). |
| `/setup` | First-run admin setup wizard. Redirects straight to `/admin/login` in this stack, because `DEMO_MODE` seeding already completed setup — review it against a **second, non-demo** instance (`DEMO_MODE=false`, no `LOCAL_REVIEW_LOGIN`, fresh database) instead. |
| `/admin/login` | The login page itself, with and without the local-review button. |
| `/admin/mfa/setup` | TOTP enrolment screen — reachable via a fresh (non-seeded) account's first login, same caveat as `/setup`. |
| `/admin/dashboard` | Filters, search, status pills, the case list. |
| `/admin/reports/{report_id}` | One representative report detail page (any seeded `OW-DEMO-000xx`) — exercise the identity-reveal form, internal notes, status change, and the four-eyes deletion flow. |
| `/admin/users` | User management. |
| `/admin/organisations` | Only rendered with `MULTI_TENANCY_ENABLED=true`. |
| `/admin/categories` | Category management. |
| `/admin/locations` | Location management. |
| `/admin/retention` | Retention policy settings. |
| `/admin/stats` | Statistics dashboard. |
| `/admin/system` | System info page. |
| `/admin/telephone-channel` | HinSchG §16 compliance checklist page. |
| `/admin/audit-log` | Audit log, with its action filter. |

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
| The admin login rate limiter | `MAX_LOGIN_ATTEMPTS` failed attempts within `LOGIN_LOCKOUT_MINUTES` locks a username — but the local-review button bypasses the password/MFA path entirely, so clicking it repeatedly across a review sweep never trips this. It is still there for the *regular* username/password + TOTP form (the demo-credentials autofill on the same page), so a sweep that logs in that way instead can still trip it; restarting the stack is the only reset (the counter lives in Redis, cleared with `-v`). |
| `/setup` and `/admin/mfa/setup` redirect away | `DEMO_MODE` seeding completes setup and enrols the demo admin's TOTP before either page is ever requested, so both redirect to `/admin/login` in this stack. Review them against a second, non-demo instance. |
| Serving `docs/` from the wrong directory | See "The website" above — `docs/`-relative links assume the server root is `docs/` itself, matching how GitHub Pages roots the site there via `docs/CNAME`. |
| A stack kept up across two review sessions | The four seeded demo reports (`OW-DEMO-00001`..`00004`) are always the same rows — nothing accumulates, so this one has no gotcha, unlike a counting assertion in an automated test. |

## Tearing down

```bash
podman compose -f docker-compose.e2e.yml down -v
```

The `-v` matters: `docker-compose.e2e.yml` declares no volumes of its own, but
the official `postgres` image's Dockerfile does (`/var/lib/postgresql/data`),
so without `-v` that anonymous volume survives and the next `up` does not
start from a clean seed.
