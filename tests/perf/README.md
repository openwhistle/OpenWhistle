# Performance Tests

OpenWhistle performance baseline using [Locust](https://locust.io/).

## Running

### Prerequisites

Install performance test dependencies:

```bash
pip install ".[perf]"
```

### Against local Docker Compose

```bash
# Start the stack
docker compose up -d

# Run the test (60 seconds, 50 users, ramp up 5/s)
locust -f tests/perf/locustfile.py \
       --headless \
       -u 50 -r 5 \
       --run-time 60s \
       --host http://localhost:4009 \
       --html tests/perf/report.html

# View the HTML report
open tests/perf/report.html
```

### Locust web UI

```bash
locust -f tests/perf/locustfile.py --host http://localhost:4009
# Open http://localhost:8089
```

## Target Thresholds (v1.1.0 baseline)

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `GET /status` | < 50 ms | < 200 ms | < 500 ms |
| `POST /status` | < 80 ms | < 300 ms | < 800 ms |
| `GET /submit` | < 50 ms | < 200 ms | < 500 ms |
| `GET /admin/dashboard` | < 100 ms | < 400 ms | < 1000 ms |
| `GET /health` | < 10 ms | < 50 ms | < 100 ms |

## User Classes

- **WhistleblowerUser** (50% of load): status checks + report submission flow
- **AdminUser** (30% of load): dashboard, report detail, audit log
- **StatusChecker** (20% of load): high-frequency status page hits
