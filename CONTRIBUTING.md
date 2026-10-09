# Contributing to OpenWhistle

Open an issue before a pull request, so the change is agreed before it is built.

## Development

| Step | Command |
| --- | --- |
| Install | `uv sync --extra dev` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` (CI runs `ruff format --check .`) |
| Types | `uv run mypy --strict app` |
| Spelling | `uvx codespell` |
| Workflows | `uvx zizmor --offline .github/workflows` (zero findings) |
| Markdown | `npx --yes markdownlint-cli2 <files>` (rules in `.markdownlint.json`, lines ≤ 120) |
| Tests | `uv run pytest` against a real PostgreSQL and Redis, as CI does |

Coverage below 90 % fails the run (`--cov-fail-under=90` in `pyproject.toml`). A new feature brings its
tests. Dependencies are locked in `uv.lock`: after editing `pyproject.toml`, run `uv lock` and commit both.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(admin): …`, `fix(csrf): …`,
`docs(tech): …`. Code, comments and documentation are English only.

## AI-assisted contributions

Welcome, if they say so. An issue or pull request written by an AI agent begins with:

```markdown
> [!WARNING]
> AI-generated
```

`AGENTS.md` and the templates ask agents for it; `.github/workflows/ai-disclosure.yml` labels what carries it
`ai-generated`. The label is a signal for review, not a block: a bot that ignores instructions is not caught.

## Documentation

There are two kinds, and they are kept apart on purpose.

| | For | Where |
| --- | --- | --- |
| **User documentation** | whoever runs OpenWhistle | `docs/`, published as openwhistle.net |
| **Technical documentation** | whoever maintains this repository | `docs-tech/` and `CLAUDE.md`, **never** published |

`docs/` holds the sources; `scripts/build_site.py` builds them, and nothing outside `docs/` reaches the site.

| What | Where |
| --- | --- |
| A page | `docs/<lang>/…` (`.md` for new pages) |
| Strings | `docs/_data/i18n/` |
| Navigation | `docs/_data/nav.yml` |

Build: `uv run --group site python scripts/build_site.py` (output in `_site/`).

An inline script needs its hash in both CSP lines of `website/nginx.conf` (the test names it). No personal data in
the repository or the image: see [`docs-tech/website-image.md`](docs-tech/website-image.md).
`test_the_technical_docs_are_not_published` holds that boundary. A page in doubt: would a stranger running
OpenWhistle need it? Yes → `docs/`. Only the next maintainer → `docs-tech/`.

### User pages: maximum information, minimum text

Reach for a diagram before a paragraph, a table before a list of sentences, and a screenshot before a
description of a screen. A thorough page nobody finishes is worth less than a short one that gets read.

| Rule | Held by |
| --- | --- |
| No sentence over 30 words, average under 18 per page | `tests/test_docs_prose.py` |
| Every page of the interface is named in the docs | `tests/test_every_page_is_documented.py` |
| Every setting has one row in `docs/_data/config.yml` | `tests/test_config_documented.py` |

The prose rules cover every page the site builds from a source of its own; generated pages (changelog,
configuration) and the 404 are left out. Code, tables and headings are not counted; inline code is one word. German
abbreviations (`z. B.`, `d. h.`, `bzw.`, `Abs.`) and dates (`2. Juli`) do not end a sentence.

**Diagrams** are draw.io sources in `docs/_diagrams/` (German pages: `<name>.de.drawio`) and
`docs-tech/_diagrams/`, rendered by `scripts/render_diagrams.py` to committed `-light.svg` and `-dark.svg`.
Rules and roles: `docs-tech/diagrams.md`.

**Screenshots are documentation.** They live in `docs/img/screens/<name>-light.png` and `-dark.png`,
are taken by `scripts/take_screenshots.py`, and are re-taken in the change that alters the interface. A stale
screenshot describes an interface that no longer exists.

### Technical pages: the rule and the incident behind it

Without the incident, a rule gets optimised away at the next rewrite. Never write a dependency version number
there: nothing updates it, and the file holding the pin is one link away. OpenWhistle's own release numbers in
an incident history are fine.

### A fix carries its documentation

A change that renames a setting, a label or a behaviour updates, in the same commit:

- all five locales in `app/locales/` (`en`, `de`, `fr`, `es`, `pt-br`), checked against
  [`docs-tech/i18n-review.md`](docs-tech/i18n-review.md);
- `docs/_data/config.yml` and the docs page that explains the setting (`docs/en/docs/<page>/index.html`),
  `README.md` and `docker-compose.prod.yml`;
- the Helm chart (`charts/openwhistle/`) and `ansible/roles/openwhistle/templates/env.j2`.

Otherwise the next audit finds the mismatch the change created.
