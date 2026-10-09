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

There are two kinds, in two repositories.

| | For | Where |
| --- | --- | --- |
| **User documentation** | whoever runs OpenWhistle | [openwhistle/website](https://github.com/openwhistle/website), published as openwhistle.net |
| **Technical documentation** | whoever maintains this repository | `docs-tech/` and `CLAUDE.md`, **never** published |

A page in doubt: would a stranger running OpenWhistle need it? Yes → openwhistle/website. Only the next
maintainer → `docs-tech/`. The website builds from the latest release tag of this repository and fails when its
documentation no longer matches it (settings, case statuses, admin routes, version).

**A user-facing change opens a pull request in openwhistle/website**, linked from this pull request: a setting,
a route, a case status, a label or a screen. Screenshots are taken by `scripts/take_screenshots.py` into a
checkout of the website (`--out`, see [`docs-tech/local-review.md`](docs-tech/local-review.md)) and committed
there, in the change that alters the interface.

**Diagrams** of this repository are draw.io sources in `docs-tech/_diagrams/`, rendered by
`scripts/render_diagrams.py` to committed `-light.svg` and `-dark.svg`. Rules and roles: `docs-tech/diagrams.md`.

### Technical pages: the rule and the incident behind it

Without the incident, a rule gets optimised away at the next rewrite. Never write a dependency version number
there: nothing updates it, and the file holding the pin is one link away. OpenWhistle's own release numbers in
an incident history are fine.

### A fix carries its documentation

A change that renames a setting, a label or a behaviour updates, in the same commit:

- all five locales in `app/locales/` (`en`, `de`, `fr`, `es`, `pt-br`), checked against
  [`docs-tech/i18n-review.md`](docs-tech/i18n-review.md);
- `README.md` and `docker-compose.prod.yml`;
- the Helm chart (`charts/openwhistle/`) and `ansible/roles/openwhistle/templates/env.j2`;
- and, in the linked openwhistle/website pull request, `docs/_data/config.yml` and the page that explains it.

Otherwise the next audit finds the mismatch the change created.
