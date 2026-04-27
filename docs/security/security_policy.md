# OpenWhistle Information Security Policy Template

**Version**: 1.0.0
**Classification**: Template — Adapt for your organisation before use

---

## 1. Purpose and Scope

This document describes the information security policy that applies to the
operation of the OpenWhistle whistleblowing platform. It applies to all
personnel with access to the system, its underlying infrastructure, and the
data it processes.

---

## 2. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| System Owner | Overall accountability for the platform; approves policy changes |
| Superadmin | Manages organisations and platform-level configuration |
| Admin | Manages cases, users, categories; can delete with 4-eyes approval |
| Case Manager | Processes assigned cases; no user management |
| Infrastructure Team | Hosts the platform; manages backups, patching, TLS certificates |
| Data Protection Officer | Reviews data processing; maintains GDPR compliance records |

---

## 3. Data Classification

| Class | Description | Examples |
|-------|-------------|----------|
| **Restricted** | Personally identifying or sensitive report content | Report text, confidential identity, messages |
| **Internal** | Admin-only metadata | Admin notes, audit log, case assignments |
| **Public** | Non-identifying, aggregate | Statistics (no case details) |

All report data is **Restricted** and subject to the controls in section 4.

---

## 4. Technical Security Controls

### 4.1 Encryption at Rest

- All report descriptions and messages are encrypted at-rest using envelope
  encryption (AES-256 via Fernet, per-report DEK wrapped with HKDF-SHA256 MEK).
- The Master Encryption Key (MEK) is derived from `SECRET_KEY` using HKDF-SHA256
  and is **never stored**. It exists only in memory during request processing.
- Per-report Data Encryption Keys (DEKs) are stored encrypted alongside the
  report. Without `SECRET_KEY`, DEKs cannot be decrypted.
- Confidential whistleblower identity (name, contact) is encrypted separately
  with Fernet using a key derived from the platform secret.

### 4.2 Encryption in Transit

- All HTTP traffic must be served over TLS 1.2+. The provided Ansible role and
  Docker Compose configuration include Certbot/Let's Encrypt integration.
- The `SECRET_KEY` environment variable must be passed via a secrets manager or
  Docker/Kubernetes secret — never in a plain-text `.env` file in production.

### 4.3 Authentication and Access Control

- All admin accounts require TOTP multi-factor authentication (no exceptions,
  no bypass). TOTP enrollment is enforced at first login.
- Passwords are hashed with bcrypt (cost factor ≥ 12).
- Login attempts are rate-limited (10 failures → temporary lockout, stored in
  Redis with a configurable TTL).
- Role-based access control (`superadmin` > `admin` > `case_manager`) is
  enforced at the FastAPI dependency layer on every protected endpoint.

### 4.4 Anonymity Preservation

- No IP addresses are logged at any layer (Nginx, application, or database).
  This is a core design constraint — do not add IP logging middleware.
- Whistleblower sessions use a Redis key tied to a random session token.
  The session token is bound to the case number and is invalidated on logout
  or after a configurable TTL.

### 4.5 Data Deletion

- Hard deletion of a report requires approval by two different admin accounts
  (4-eyes principle, HTTP 409 if the same admin confirms).
- All deletion events are recorded in the immutable audit log.
- The data retention scheduler permanently deletes closed reports older than
  `RETENTION_DAYS` days and writes an `report.auto_deleted` audit entry.

---

## 5. Incident Response

1. **Detection** — Monitor the structured JSON logs for authentication failures,
   unexpected 5xx errors, or anomalous access patterns.
2. **Containment** — Rotate `SECRET_KEY` immediately if a breach is suspected.
   Note: rotating `SECRET_KEY` invalidates all existing encrypted DEKs —
   coordinate a data re-encryption operation before rotation in production.
3. **Notification** — If personal data is involved, notify the supervisory
   authority within 72 hours (GDPR Art. 33).
4. **Post-mortem** — Document root cause and remediation in the audit log.

---

## 6. Backup and Recovery

- The PostgreSQL database must be backed up at least daily with point-in-time
  recovery (WAL archiving) enabled.
- Redis contains ephemeral session data only. Redis persistence (`appendonly yes`)
  is optional; sessions will be invalidated on restart without it.
- `SECRET_KEY` must be stored in a separate, offline location. Loss of
  `SECRET_KEY` makes encrypted report content irrecoverable.
- Recovery Time Objective (RTO): define based on your organisation's requirements.
- Recovery Point Objective (RPO): define based on your organisation's requirements.

---

## 7. Patch Management

- Platform container images are published for every release on GHCR, Docker Hub,
  and Quay.io. Apply updates within [define your SLA] of a security release.
- GitHub Dependabot is enabled on the OpenWhistle repository for dependency
  vulnerability scanning.
- Operating system patches must be applied on the host according to your
  organisation's standard patch management policy.

---

## 8. Audit and Review

- The OpenWhistle audit log records all admin actions with timestamps and
  usernames. The log is append-only from the application layer.
- Access to the PostgreSQL database (direct or via admin tools) should be
  restricted and logged at the infrastructure level.
- This policy must be reviewed at least annually and after any significant
  change to the platform or its threat landscape.

---

## 9. Compliance References

| Regulation | Relevant Clause | How OpenWhistle Addresses It |
|-----------|----------------|------------------------------|
| GDPR Art. 5(1)(f) | Integrity and confidentiality | Encryption at rest, access control, audit log |
| GDPR Art. 5(1)(e) | Storage limitation | Data retention scheduler |
| GDPR Art. 17 | Right to erasure | 4-eyes deletion, retention scheduler |
| GDPR Art. 25 | Data protection by design | No IP logging, anonymity-first architecture |
| GDPR Art. 32 | Security of processing | Encryption at rest and in transit, MFA |
| HinSchG §9 | Confidentiality obligation | Role-based access, TOTP MFA |
| HinSchG §12 Abs. 3 | 3-year documentation minimum | Default `RETENTION_DAYS=1095` |
| HinSchG §16 | Telephone channel requirement | Admin guidance at `/admin/telephone-channel` |

---

*This document is a template. Replace bracketed placeholders with your
organisation's specific values before use.*
