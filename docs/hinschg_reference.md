# HinSchG — Key Paragraphs Reference

> **Official source:** <https://www.gesetze-im-internet.de/hinschg/>
> **EU Directive:** <https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937>
> **In force:** 2 July 2023

This document summarizes the paragraphs most relevant to OpenWhistle development.
For legally binding text, always consult the official source above.

---

## §8 Confidentiality (Vertraulichkeit)

The identity of the whistleblower **must be kept confidential** at all times. Information that directly or
indirectly allows identification of the whistleblower may only be disclosed:

- With the explicit consent of the whistleblower, or
- When required by law (e.g., criminal prosecution requires it)

**Implementation implication:** No IP addresses, no browser fingerprints, no metadata that could identify
the whistleblower must be stored anywhere. The system must be designed so that even the system operator
cannot identify the whistleblower without their cooperation.

---

## §12 Obligation to Establish Internal Reporting Channels

Companies with **50 or more employees** and all public authorities must establish internal reporting channels.

The reporting channel must:

- Allow reports in writing or verbally (or both)
- Guarantee the confidentiality of the whistleblower's identity
- Be accessible to employees of the organization

**Implementation implication:** OpenWhistle provides the technical reporting channel. The organization
deploying it must ensure it meets the organizational requirements.

---

## §16 Internal Reporting Office (Interne Meldestelle)

### §16 Abs. 1 — Operation

The internal reporting office must be operated by:

- An internal employee designated for this purpose, or
- A third party (e.g., an external provider)

Multiple organizations may share a single reporting channel.

### §16 Abs. 3 — Secure Channel

Reports must be receivable via a **secure channel** that ensures confidentiality. The whistleblower must be
identifiable by the reporting office (via their case reference) to enable follow-up, but
**not identifiable to anyone else**.

### §16 Abs. 7 — Oral Reports

If the whistleblower requests an oral report, the reporting office must provide the opportunity
(telephone, video conference). A record must be made and provided to the whistleblower for approval.

**Implementation implication:** The PIN + case number system satisfies the "identifiable by reporting
office" requirement while maintaining full anonymity. The written-form digital submission satisfies the
written reporting requirement.

---

## §17 Follow-Up by the Internal Reporting Office (Rückmeldungen)

This is the most critical paragraph for bidirectional communication.

### §17 Abs. 1 — Acknowledgement of Receipt

The reporting office must **acknowledge receipt within 7 days** of receiving the report.

Exception: The 7-day deadline may be waived only if:

- The whistleblower explicitly requests no acknowledgement, AND
- Sending an acknowledgement would compromise the whistleblower's anonymity

**Implementation implication:**

- System must track `submitted_at` and `acknowledged_at` timestamps
- Dashboard must show a warning when the 7-day SLA is approaching or exceeded
- Acknowledgement is either automatic (on submission) or manual (admin action)

### §17 Abs. 2 — Feedback within 3 Months

The reporting office must provide **feedback within 3 months** of the acknowledgement. The feedback must include:

- What measures have been taken or are planned
- The reasons for those measures (or why no measures will be taken)

**Implementation implication:**

- System must track `feedback_due_at` (= `acknowledged_at` + 90 days)
- Dashboard must show a "3-month SLA" warning
- The admin must be able to send a feedback message to the whistleblower

### §17 Abs. 3 — Communication Channel

The follow-up communication must be done via the **same secure channel** through which the report was
submitted. This means the whistleblower must be able to receive messages back through the OpenWhistle
interface.

**Implementation implication:**

- Bidirectional thread (WhistleblowerMessage table) is required by law
- The whistleblower must be able to read admin replies using their PIN + case number
- The whistleblower must also be able to send follow-up messages

---

## §26 Data Protection (Datenschutz)

### §26 Abs. 1 — Legal Basis

The processing of personal data in connection with internal reporting channels is lawful under DSGVO
Art. 6(1)(c) (legal obligation) and Art. 6(1)(e) (public interest task), as far as required for
compliance with HinSchG.

### §26 Abs. 2 — Confidentiality of Third Parties

If a report contains information about third parties (e.g., the person being reported), their identity
must also be treated confidentially until the report has been investigated to a sufficient degree.

### §26 Abs. 3 — Data Retention

Personal data must be **deleted after 3 years** following the completion of a case, unless:

- Longer retention is required for ongoing proceedings
- The whistleblower consents to longer retention

**Implementation implication:**

- Reports must have a `closed_at` timestamp
- A scheduled cleanup job (or at minimum, a manual delete function) must be available
- The system must support hard deletion of reports and all associated messages

---

## DSGVO Requirements for Whistleblower Systems

| Requirement | Article | Implementation |
|---|---|---|
| Data minimization | Art. 5(1)(c) | No IP logging, no unnecessary fields |
| Privacy by design | Art. 25 | Self-hosted, anonymized from the start |
| Lawful basis | Art. 6(1)(c) | HinSchG §26 provides the legal basis |
| Right to erasure | Art. 17 | Reports must be hard-deletable |
| Security of processing | Art. 32 | Encryption at rest and in transit |
| Data breach notification | Art. 33 | 72-hour notification requirement (organizational) |
| No international transfer | Art. 44ff | Self-hosted, data stays on-premises |

### External Resources and DSGVO

Loading resources from external CDNs (Google Fonts, Cloudflare CDN, etc.) causes the user's IP address to
be transmitted to a third party. A German court (LG München, January 2022) ruled that loading Google
Fonts without explicit consent violates DSGVO Art. 6(1)(a).

**For OpenWhistle:** All fonts, CSS, and JavaScript must be self-hosted. No external CDN calls permitted.

---

## SLA Summary Table

| Event | Deadline | Source |
|---|---|---|
| Acknowledgement of receipt | 7 days after `submitted_at` | §17 Abs. 1 |
| Feedback to whistleblower | 3 months after `acknowledged_at` | §17 Abs. 2 |
| Data deletion after case closure | 3 years after `closed_at` | §26 Abs. 3 |
