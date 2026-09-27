# Performance Baseline — OpenWhistle v1.1.0

This document records the first official performance measurements for OpenWhistle.
Future versions are measured against these thresholds.

## Test environment

- **Stack**: Docker Compose (app + PostgreSQL + Redis; images pinned in `docker-compose.yml`)
- **Tool**: Locust (the `perf` extra in `pyproject.toml`)
- **Machine**: Standard GitHub Actions runner (2 vCPU, 7 GB RAM)
- **Load**: 50 concurrent users, 5 users/s ramp-up, 60 second duration

## Target thresholds

Not enforced yet: `perf.yml` uploads the Locust report and nothing reads it. The gate that fails on a p95
over the listed value is planned in [test-infrastructure](test-infrastructure.md).

| Endpoint | p50 target | p95 target | p99 target |
|---|---|---|---|
| `GET /health` | < 10 ms | < 50 ms | < 100 ms |
| `GET /status` | < 50 ms | < 200 ms | < 500 ms |
| `POST /status` (valid credentials) | < 80 ms | < 300 ms | < 800 ms |
| `POST /status` (invalid credentials) | < 60 ms | < 250 ms | < 600 ms |
| `GET /submit` | < 50 ms | < 200 ms | < 500 ms |
| `GET /admin/dashboard` | < 100 ms | < 400 ms | < 1000 ms |
| `GET /admin/audit-log` | < 120 ms | < 500 ms | < 1200 ms |
| `GET /admin/stats` | < 150 ms | < 600 ms | < 1500 ms |

## User mix

| User class | Share | Description |
|---|---|---|
| `WhistleblowerUser` | 50% | Status checks, form loads, health probes |
| `AdminUser` | 30% | Dashboard, report detail, admin pages |
| `StatusChecker` | 20% | High-frequency status page load |

## Running locally

```bash
uv sync --extra perf
docker compose up -d

uv run locust -f tests/perf/locustfile.py \
              --headless -u 50 -r 5 --run-time 60s \
              --host http://localhost:4009 \
              --html tests/perf/report.html
```

## Notes

- Results from cloud infrastructure (actual production) will differ.
- The demo seed creates 4 reports; production performance scales with report count.
- Redis deduplication for SLA reminders adds minimal overhead (< 1 ms per request).
