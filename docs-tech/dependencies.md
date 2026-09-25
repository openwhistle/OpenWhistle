# Dependencies

Reference: how versions are pinned and who moves them.

| What | Pinned in | Moved by |
| --- | --- | --- |
| Python packages | `pyproject.toml` floors + `uv.lock` (exact) | Renovate (pep621 + uv lock), weekly lock maintenance |
| Python runtime | `Dockerfile`, every `setup-python`, `requires-python` | Renovate group "Python runtime", never auto-merged |
| uv | `Dockerfile` (`COPY --from=ghcr.io/astral-sh/uv`), every workflow | Renovate group "uv" |
| PostgreSQL, Redis, nginx | both compose files, the Ansible template, compose written inline in workflows | Renovate groups; PostgreSQL majors never auto-merged (dump and restore) |
| GitHub Actions | workflows, pinned to commit digests | Renovate |
| axe-core | `tests/e2e/conftest.py` | Renovate custom manager |

Patch, pin and digest updates merge themselves once the required checks pass.
They use GitHub's native auto-merge, so the repository setting "Allow
auto-merge" must stay on: with it off, the first pin PR sat green and unmerged.
Branch protection still decides — auto-merge only fires once the required
checks pass.
Minor and major updates, the Python runtime, and security-relevant libraries
(crypto, JWT, bcrypt, TOTP, FastAPI/Starlette, multipart, the attachment
parsers pypdf and Pillow, python-ldap) always wait for a person.

LDAP uses python-ldap, a wrapper around the maintained OpenLDAP client
library. It replaced ldap3 in v1.6.0: ldap3 has had no release since 2021.
python-ldap builds from source against `libldap`/`libsasl` headers, so it and
boto3 are optional extras (`ldap`, `s3`): the image and CI install both.

## Guards

- `tests/test_renovate.py`: every custom manager reaches a tracked file and
  every `matchStrings` entry matches something there. A dead pattern is
  otherwise silent.
- `tests/test_build_pins.py`: uv, Python, PostgreSQL and Redis carry one version
  across all files.
- `tests/test_renovate.py::test_no_managed_file_is_ignored`: `ignorePaths` is
  explicit. The `config:recommended` preset ignores `tests/`, which hid the
  axe-core pin on Renovate's first run while every other check was green.
- CI: `uv lock --check`.

## Writing a version down somewhere new

Add it to `renovate.json` and to `tests/test_build_pins.py` in the same change.
A pin no tool knows about falls behind without anyone noticing.

## Setup (once)

The Renovate GitHub App must be installed on the `openwhistle` organisation with
access to this repository. After its first run, switch off GitHub's "Dependabot
security updates" (Settings → Code security) so a vulnerability produces one
pull request, not two; keep "Dependabot alerts" on — Renovate reads them.
