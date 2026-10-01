---
title: HinSchG duties and what OpenWhistle covers | OpenWhistle
description: HinSchG duties and what OpenWhistle covers
translation_key: hinschg-reference
noindex: true
css:
- fonts
- docs
js:
- site
---
<main id="main-content" class="docs-content docs-standalone">

# HinSchG duties and what OpenWhistle covers

Reference for whoever runs an internal reporting office with OpenWhistle. It is a summary, not legal advice.
The binding text is at <https://www.gesetze-im-internet.de/hinschg/> (in force since 2 July 2023). The EU
directive behind it is [2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937).

## Who must run a reporting office

| Section | Rule |
| --- | --- |
| § 12 Abs. 1 | Employers set up at least one internal reporting office. Municipalities follow their state law. |
| § 12 Abs. 2 | The duty applies from 50 employees. |
| § 12 Abs. 3 | Some financial-sector firms need one at any size, for example banks and insurers. |
| § 12 Abs. 4 | The office must have the powers to examine reports and take follow-up measures. |

## Duty by duty

| Section | Duty | OpenWhistle | The organisation |
| --- | --- | --- | --- |
| § 8 | Keep the identity of the reporter and of named persons confidential | No IP address is stored; access by role; confidential identity shown only with an audited reason | Who may see reports, and their training |
| § 9 | Exceptions to confidentiality, e.g. criminal proceedings or the reporter's written consent | Identity reveals are audited | Deciding each exception |
| § 10 | Processing personal data as far as the office's tasks need it | Only the fields a report needs | Record of processing, data-protection notice |
| § 11 Abs. 1 | Document every report | Every report and message is stored, encrypted | — |
| § 11 Abs. 2 | Record a telephone report only with consent; otherwise write a summary | Telephone guide on `/admin/telephone-channel` | Running the telephone channel |
| § 11 Abs. 5 | Delete the documentation three years after the procedure ends | Retention settings on `/admin/retention` | Keeping it longer only where a law requires it |
| § 16 Abs. 1 | Channels for employees; anonymous reports should be processed | Anonymous and confidential submission | Who else may report |
| § 16 Abs. 2 | Only the responsible persons access reports | Roles and per-organisation scope | Assigning the roles |
| § 16 Abs. 3 | Reports orally and in text form; a personal meeting on request | The text channel | The oral channel and meetings |
| § 17 Abs. 1 Nr. 1 | Confirm receipt within seven days | 7-day deadline on every case | Confirming in time |
| § 17 Abs. 1 Nr. 3 | Stay in contact with the reporter | Two-way messages via case number and PIN | Answering |
| § 17 Abs. 2 | Feedback within three months of the confirmation | 3-month deadline on every case | The feedback itself |

## Deadlines

| Event | Deadline | Section |
| --- | --- | --- |
| Confirmation of receipt | 7 days after the report | § 17 Abs. 1 Nr. 1 |
| Feedback to the reporter | 3 months after the confirmation | § 17 Abs. 2 |
| Deletion of the documentation | 3 years after the procedure ends | § 11 Abs. 5 |

## GDPR alongside the HinSchG

| Requirement | Article | OpenWhistle |
| --- | --- | --- |
| Data minimisation | Art. 5(1)(c) | No IP logging, no fields a report does not need |
| Privacy by design | Art. 25 | Self-hosted; no third-party requests from the reporter's pages |
| Lawful basis | Art. 6(1)(c) | The legal duty of § 12 HinSchG, with § 10 HinSchG |
| Erasure | Art. 17 | Reports can be deleted for good; § 11 Abs. 5 sets the regular deadline |
| Security of processing | Art. 32 | Encryption at rest and TLS in transit |
| Breach notification | Art. 33 | Organisational: 72 hours to the authority |

Fonts, styles and scripts are served by the instance itself. A German court (LG München I, January 2022)
held that loading Google Fonts without consent breached the GDPR, because it sends the visitor's address
to a third party.

</main>
