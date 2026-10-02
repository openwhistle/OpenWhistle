---
title: OpenWhistle Information Security Policy Template | OpenWhistle
description: OpenWhistle Information Security Policy Template
translation_key: security-policy
noindex: true
css:
- fonts
- docs
js:
- site
---
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
  encryption (Fernet: AES-128-CBC with HMAC-SHA256; a per-report DEK wrapped
  with an HKDF-SHA256 MEK).
- The Master Encryption Key (MEK) is derived from `ENCRYPTION_KEY` (or
  `SECRET_KEY` while that is unset) using HKDF-SHA256 and is **never stored**.
  It exists only in memory during request processing.
- Per-report Data Encryption Keys (DEKs) are stored encrypted alongside the
  report. Without `ENCRYPTION_KEY`, DEKs cannot be decrypted.
- Confidential whistleblower identity (name, contact) is encrypted separately
  with Fernet using a key derived from the same root.

### 4.2 Encryption in Transit

- All HTTP traffic must be served over TLS 1.2+. The Ansible role obtains and
  renews a Let's Encrypt certificate; the Docker Compose stack creates a
  self-signed one (`tls-init`) until you mount your own.
- `SECRET_KEY` and `ENCRYPTION_KEY` must be passed via a secrets manager or
  Docker/Kubernetes secret — never in a plain-text `.env` file in production.

### 4.3 Authentication and Access Control

- All admin accounts require TOTP multi-factor authentication (no exceptions,
  no bypass). TOTP enrollment is enforced at first login.
- Passwords are hashed with bcrypt (cost factor ≥ 12).
- Login attempts are rate-limited (`MAX_LOGIN_ATTEMPTS`, default 10, failures
  lock the username for `LOGIN_LOCKOUT_MINUTES` after the last one; kept in Redis).
- Role-based access control (`superadmin` > `admin` > `case_manager`) is
  enforced at the FastAPI dependency layer on every protected endpoint.

### 4.4 Anonymity Preservation

- No IP addresses are logged at any layer (Nginx, application, or database).
  This is a core design constraint — do not add IP logging middleware.
- Whistleblower sessions use a Redis key tied to a random session token.
  The token names one report and ends on logout, when the report is deleted,
  or two hours after sign-in; viewing the page does not extend it.

### 4.5 Data Deletion

- Hard deletion of a report requires approval by two different admins
  (4-eyes principle, HTTP 409 if the same admin, or an account one of them
  made, confirms). A superadmin can reset another account and act as it.
- Every deletion leaves one audit entry with the case number
  (`report.delete_confirmed`, `report.auto_deleted`); the report's own entries
  are deleted with it.
- The data retention scheduler permanently deletes closed reports older than
  `RETENTION_DAYS` days and writes an `report.auto_deleted` audit entry.

---

## 5. Incident Response

1. **Detection** — Monitor the structured JSON logs for authentication failures,
   unexpected 5xx errors, or anomalous access patterns.
2. **Containment** — Rotate `ENCRYPTION_KEY` if a breach is suspected: set the
   new key, move the old one to `ENCRYPTION_KEY_PREVIOUS`, then run
   `scripts/rotate_encryption_key.py`, which re-wraps every DEK. Rotate
   `SECRET_KEY` too: it signs sessions, so every admin signs in again.
3. **Notification** — If personal data is involved, notify the supervisory
   authority within 72 hours (GDPR Art. 33).
4. **Post-mortem** — Document root cause and remediation in the audit log.

---

## 6. Backup and Recovery

- The PostgreSQL database must be backed up at least daily with point-in-time
  recovery (WAL archiving) enabled.
- Redis contains ephemeral session data only. Redis persistence (`appendonly yes`)
  is optional; sessions will be invalidated on restart without it.
- `ENCRYPTION_KEY` must be stored in a separate, offline location. Its loss
  makes encrypted report content irrecoverable.
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
| HinSchG §8 | Confidentiality obligation | Role-based access, TOTP MFA |
| HinSchG §11 Abs. 5 | Deletion 3 years after the procedure ends | Default `RETENTION_DAYS=1095` |
| HinSchG §16 | Telephone channel requirement | Admin guidance at `/admin/telephone-channel` |

---

*This document is a template. Replace bracketed placeholders with your
organisation's specific values before use.*
