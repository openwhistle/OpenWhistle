"""OpenWhistle performance tests.

Run manually (NOT in standard CI):
    locust -f tests/perf/locustfile.py --headless \\
           -u 50 -r 5 --run-time 60s \\
           --host http://localhost:4009 \\
           --html tests/perf/report.html

Or via Docker Compose:
    docker compose run --rm app locust ...
"""
from __future__ import annotations

import random
import string

import pyotp
from locust import HttpUser, between, task

DEMO_TOTP_SECRET = "JBSWY3DPEHPK3PXP"
DEMO_ADMIN_USERNAME = "demo"
DEMO_ADMIN_PASSWORD = "demo"

DEMO_CASES = [
    ("OW-DEMO-00001", "demo-pin-received-00001"),
    ("OW-DEMO-00002", "demo-pin-inreview-00002"),
    ("OW-DEMO-00003", "demo-pin-pending-00003"),
    ("OW-DEMO-00004", "demo-pin-closed-00004"),
]


def _random_string(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))  # noqa: S311


class WhistleblowerUser(HttpUser):
    """Simulates a whistleblower checking their report status."""

    wait_time = between(1, 3)

    @task(3)
    def check_status_page(self) -> None:
        self.client.get("/status", name="/status (GET)")

    @task(2)
    def check_report_status(self) -> None:
        case_number, pin = random.choice(DEMO_CASES)  # noqa: S311
        self.client.post(
            "/status",
            data={"case_number": case_number, "pin": pin},
            name="/status (POST valid)",
        )

    @task(1)
    def check_wrong_credentials(self) -> None:
        self.client.post(
            "/status",
            data={"case_number": "OW-INVALID-99999", "pin": "wrong-pin"},
            name="/status (POST invalid)",
        )

    @task(1)
    def load_submit_form(self) -> None:
        self.client.get("/submit", name="/submit (GET)")

    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")


class AdminUser(HttpUser):
    """Simulates an admin user browsing the dashboard."""

    wait_time = between(2, 5)

    def on_start(self) -> None:
        """Authenticate via the two-step login flow."""
        # Step 1: credentials
        self.client.post(
            "/admin/login",
            data={
                "username": DEMO_ADMIN_USERNAME,
                "password": DEMO_ADMIN_PASSWORD,
            },
            allow_redirects=False,
            name="/admin/login (credentials)",
        )
        # Step 2: TOTP
        self.client.post(
            "/admin/login/mfa",
            data={"totp_code": pyotp.TOTP(DEMO_TOTP_SECRET).now()},
            allow_redirects=True,
            name="/admin/login/mfa",
        )

    @task(5)
    def view_dashboard(self) -> None:
        self.client.get("/admin/dashboard", name="/admin/dashboard")

    @task(2)
    def view_report_detail(self) -> None:
        # This simulates the realistic flow of looking at the dashboard
        self.client.get("/admin/dashboard", name="/admin/dashboard (for report)")

    @task(1)
    def view_audit_log(self) -> None:
        self.client.get("/admin/audit-log", name="/admin/audit-log")

    @task(1)
    def view_stats(self) -> None:
        self.client.get("/admin/stats", name="/admin/stats")

    @task(1)
    def view_categories(self) -> None:
        self.client.get("/admin/categories", name="/admin/categories")


class StatusChecker(HttpUser):
    """High-frequency status page checker — simulates many concurrent passive users."""

    wait_time = between(0.5, 1.5)

    @task
    def load_status_page(self) -> None:
        self.client.get("/status", name="/status (load test)")
