# The security feed: `openwhistle.net/security.json`

The update check (`UPDATE_CHECK_ENABLED`, on by default since 2.5.0) fetches one static file a day and nothing
else. It used to call `api.github.com`; one file we host instead means one host to name in the privacy text, a
vhost that logs nothing, and no GitHub rate limit per installation.

| | Where |
| --- | --- |
| Reader (validates, caches, matches) | `app/services/version_check.py` |
| Generator (website build, from GitHub) | `scripts/security_feed.py` in openwhistle/website |
| Served | `https://openwhistle.net/security.json`, `application/json`, `access_log off` |

## Schema 1

```json
{
  "schema": 1,
  "latest": {
    "version": "2.4.2",
    "url": "https://github.com/openwhistle/OpenWhistle/releases/tag/v2.4.2",
    "published_at": "2026-11-01T10:00:00Z"
  },
  "advisories": [
    {
      "id": "GHSA-xxxx-xxxx-xxxx",
      "cve_ids": ["CVE-2026-0001"],
      "summary": "One line, as the advisory's title",
      "severity": "high",
      "affected": ">= 1.4.0, < 2.4.2",
      "fixed": "2.4.2",
      "url": "https://github.com/openwhistle/OpenWhistle/security/advisories/GHSA-xxxx-xxxx-xxxx"
    }
  ]
}
```

| Field | Rule | The app on a violation |
| --- | --- | --- |
| `schema` | exactly `1` | ignores the whole file, keeps its cache |
| `latest.version` | `X.Y.Z` (up to four parts, optional `v`) | keeps the cached release |
| `latest.url`, `advisories[].url` | `https://` | drops the link |
| `advisories` | a list; the app reads the first 100 | not a list: keeps the cached advisories |
| `id` | `[A-Za-z0-9-]{1,64}` | drops the advisory |
| `summary` | non-empty string; the app cuts it at 300 characters | drops the advisory |
| `affected` | GitHub range syntax: comma-separated `<`, `<=`, `>`, `>=`, `=` or bare versions | drops the advisory |
| `fixed` | a version, or empty while no release fixes it | drops the advisory |
| `severity` | `low`, `medium`, `high`, `critical` | shows none |
| `cve_ids` | `CVE-YYYY-NNNN…`, at most 10 | drops the bad ones |

The generator fails the website build on anything the app would drop: a broken feed is never published.

## Publishing an advisory

The feed is rebuilt with the website (push to its `main`, the weekly run, or `workflow_dispatch`). After
publishing a GitHub security advisory, run the website workflow by hand so installations hear within a day,
not a week.

The app matches `affected` against its own version when a page is rendered, so an upgrade clears the notice
before the next fetch.
