# Data Processing Agreement (DPA) Template

**GDPR Art. 28 — Controller–Processor Agreement**

**Version**: 1.0.0
**Classification**: Template — Seek legal advice before use in production

---

## Parties

**Controller**: [Your Organisation Name], [Address], ("Controller")

**Processor**: [Hosting Provider / IT Service Provider], [Address], ("Processor")

---

## 1. Subject Matter and Duration

The Processor processes personal data on behalf of the Controller for the purpose
of operating the OpenWhistle whistleblowing platform, as described in Annex 1.

The duration of this agreement is tied to the service agreement between the parties.

---

## 2. Nature and Purpose of Processing

The Processor hosts and operates the OpenWhistle application, which:

- Receives and stores whistleblowing reports submitted by the Controller's
  employees or third parties.
- Stores report content encrypted at rest (AES-256 envelope encryption).
- Provides an administrative interface for the Controller's staff to review
  and process reports.
- Deletes reports automatically after the configured retention period
  (minimum 1095 days, satisfying HinSchG §12 Abs. 3).

---

## 3. Type of Personal Data and Categories of Data Subjects

**Categories of data subjects**: Employees and third parties who submit reports.

**Types of personal data**:

- Report descriptions and messages (potentially containing personal data about
  third parties named in the report)
- Confidential whistleblower identity (name, contact information) — only when
  the whistleblower selects confidential mode
- Anonymous session tokens and case numbers (no personal identifiers)

**Special category data**: Reports may incidentally contain data revealing racial
or ethnic origin, health data, or data concerning criminal convictions (Art. 9/10
GDPR). The Controller bears responsibility for handling such data lawfully.

---

## 4. Obligations of the Processor

The Processor agrees to:

1. Process personal data only on documented instructions from the Controller.
2. Ensure persons authorised to process the data have committed to confidentiality.
3. Implement appropriate technical and organisational measures (Art. 32 GDPR),
   including those listed in Annex 2.
4. Not engage sub-processors without prior written authorisation from the Controller
   (see Annex 3 for authorised sub-processors).
5. Assist the Controller in responding to data subject rights requests.
6. Assist the Controller with security obligations (Art. 32–36 GDPR).
7. At the Controller's choice, delete or return all personal data after the end
   of the service provision, and delete existing copies.
8. Make available all information necessary to demonstrate compliance and allow
   for audits.

---

## 5. Obligations of the Controller

The Controller agrees to:

1. Inform the Processor of any restrictions or specifications for data processing.
2. Ensure that data subjects have been informed about the processing.
3. Verify the technical and organisational measures of the Processor before
   processing begins and regularly during the term of the agreement.

---

## 6. Sub-Processors

Authorised sub-processors are listed in Annex 3. The Processor must inform the
Controller of any intended changes to this list and give the Controller the
opportunity to object.

---

## 7. Security Measures (Annex 2)

The Processor implements the following technical and organisational measures:

| Category | Measure |
|----------|---------|
| Pseudonymisation / encryption | Report content encrypted at rest (AES-256 envelope encryption); TLS 1.2+ in transit |
| Access control | Role-based access (superadmin / admin / case manager); mandatory TOTP MFA |
| Anonymity | No IP addresses logged at any layer |
| Data minimisation | Anonymous submissions require no personal data |
| Availability | Regular PostgreSQL backups with point-in-time recovery |
| Audit | Immutable audit log of all admin actions |
| Deletion | Automatic deletion after retention period; 4-eyes deletion for manual removal |
| Patch management | Dependencies scanned by GitHub Dependabot; OS patching per Processor's policy |

---

## 8. Data Breach Notification

The Processor will notify the Controller without undue delay (and in any case
within [72 hours]) after becoming aware of a personal data breach affecting
data processed under this agreement.

---

## 9. Governing Law

This agreement is governed by the laws of [Germany / your jurisdiction].

---

## Annex 1: Description of Processing

| Field | Value |
|-------|-------|
| Purpose | Internal whistleblowing system (HinSchG compliance) |
| Platform | OpenWhistle (open source, self-hosted) |
| Data location | [Datacenter location, e.g. Germany — Hetzner Falkenstein] |
| Retention period | [1095 days / 3 years] after case closure |

---

## Annex 3: Authorised Sub-Processors

| Sub-Processor | Location | Purpose |
|--------------|----------|---------|
| [e.g. Hetzner Online GmbH] | Germany | Server hosting |
| [e.g. Let's Encrypt / ISRG] | USA | TLS certificate issuance |

---

*This document is a template. It does not constitute legal advice. Consult a
qualified data protection lawyer before using this template in a production
environment.*
