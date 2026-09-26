# Planned test-infrastructure work

Maintainer-only work from the v1.1.0 test-quality review, checked against the tree. It
changes no behaviour a user sees, so it is not on the public roadmap (`docs/roadmap.html`).

| Item | Now | Change |
| --- | --- | --- |
| Firefox smoke test | Only Chromium runs E2E | A second `pytest-playwright` job in `e2e.yml` runs login, submission, status and session expiry against Firefox |
| Reply tests isolated from the demo seed | `test_admin_reply_appears_in_thread` mutates `OW-DEMO-00002` | Create a throwaway report first, as `test_four_eyes_deletion.py` does |
| No silent skips | `tests/e2e/` calls `pytest.skip` when demo data is missing | Fail instead: a broken demo seed must fail the run |
| Performance regression gate | `perf.yml` uploads the Locust CSV; nothing reads it | A post-run script fails the workflow when p95 exceeds `docs-tech/performance-baseline.md` |
| Full wizard flow in `WhistleblowerUser` | `tests/perf/locustfile.py` issues simplified requests | A full 6-step submission session, Redis session reads included |
| OpenAPI contract | `tests/test_openapi_contract.py` tests routes directly (`openapi_url` is off in production) | A fixture with a second client that enables OpenAPI for the test app only, asserting every expected `operationId` |
