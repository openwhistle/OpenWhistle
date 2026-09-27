# The reviewer's first reads

`app/locales/en.json` holds over 700 keys. A reviewer checking `de`, `fr` or `pt-br` against it in order meets
the sentences that matter most somewhere in the middle, tired. This page collects them so they are read first.

**The rule these sentences have to survive translation under:**

> A translator may rephrase freely. A translator may not change what the sentence *claims*.

**What makes a key belong here:** getting it backwards would make a whistleblower or a case handler act
*worse* — trust a channel that identifies them, throw away a PIN that cannot be replaced, miss a legal
deadline, or delete where they meant to close. Button labels and generic errors are not here: a wrong
"Cancel" confuses, it does not expose anyone.

For every row, ask: does the translation assert the same fact, in the same direction, with the same caveat?
`tests/test_i18n_review.py` fails when a key below is renamed or removed from `en.json`.

## Anonymity and what is not recorded

| Key | What it must claim |
| --- | --- |
| `submit.sidebar.short` | Anonymous by default; no IP address is stored |
| `submit.sidebar.g01.desc` | OpenWhistle neither stores nor logs the IP address — **and** the employer may still see the visit |
| `submit.sidebar.g03.desc` | No analytics, tracking or third-party requests; the only cookies are the ones the form needs |
| `submit.step.mode.anonymous.desc` | No name or contact is asked for or stored; contact runs only through platform messages |
| `submit.form.description.placeholder` | The reporter may stay anonymous and should leave out what identifies them |
| `admin.ip_warning.body` | A proxy forwarding IP headers leaks data that can break the reporter's anonymity |

## Confidential is not anonymous

| Key | What it must claim |
| --- | --- |
| `submit.step.mode.confidential.desc` | Name and contact are optional, stored encrypted, shown only to the staff handling the case |
| `submit.step.mode.confidential.info.body` | Same claim: optional, encrypted, decrypted only for the handling staff |
| `admin.report.identity.handler_only` | Only the case handler sees the identity — not every admin |
| `admin.report.identity.reason_hint` | The reason is audit-logged under the viewer's name; the reporter's name must not go in it |
| `admin.report.notes.placeholder` | Internal notes are never visible to the whistleblower |
| `submit.step.mode.secure_email.hint` | The notification email carries no report content |
| `admin.search.hint` | Content is decrypted only for the search and never indexed; the confidential name is never searched |

## The case number and PIN cannot be recovered

| Key | What it must claim |
| --- | --- |
| `submit.sidebar.g02.desc` | Both are needed to return, and neither can be recovered |
| `submit.alert.body` | Save both; they are the only way back and cannot be recovered |
| `success.warning.body` | Save them now; they cannot be recovered |
| `success.confirm.label.html` | The reporter confirms having saved both and understands they cannot be recovered |
| `success.pin_shown_once` | Shown once only; if missed, the report still arrived, and a new report can cite the case number |
| `status.locked.body` | Wrong attempts do not block the right PIN; a lost PIN cannot be recovered |
| `submit.step.review.warning.body` | Once submitted, the report cannot be changed |

## Deadlines: 7 days, 3 months

| Key | What it must claim |
| --- | --- |
| `submit.sidebar.g17.desc` | Receipt confirmed within 7 days, feedback within 3 months |
| `success.next.body.html` | 7 days to acknowledge; 3 months counted **from the acknowledgement**, not from submission |
| `status.no_messages` | Receipt must be confirmed within 7 days of submission |
| `system.receipt_message` | An acknowledgement follows within 7 days, as §17 HinSchG requires |
| `admin.report.detail.sla3m` | The 3-month feedback deadline of §17 (2) HinSchG |

## Closed is not deleted

| Key | What it must claim |
| --- | --- |
| `admin.report.status.confirm_close` | Closing shows the whistleblower a final outcome; it deletes nothing |
| `status.closed.body` | The case is closed and its thread is still readable |
| `admin.report.delete.body` | Deletion is permanent and cannot be undone |
| `admin.report.delete.pending.body` | A **different** admin must confirm the deletion |

## Retention

| Key | What it must claim |
| --- | --- |
| `admin.retention.enabled_notice` | Only closed reports are deleted, `{days}` days after closing; nothing has been deleted early |
| `admin.retention.how.note.html` | A report in any other status is never deleted automatically |
| `admin.retention.legal.hinschg.body.html` | HinSchG requires deletion 3 years after the procedure ends; longer only while necessary |

## A password someone else set

| Key | What it must claim |
| --- | --- |
| `account.forced.body` | Someone else set the password and knows it; nothing else opens until it is changed |
| `account.password.changed` | The password is changed **and** every other session has ended |
| `account.password.totp_hint` | The session alone does not change the password; the current code is needed |

## Telemetry is off by default; the demo is not real

| Key | What it must claim |
| --- | --- |
| `wizard.telemetry.body.html` | Off unless ticked; nothing about reports or users is sent; the far end does not record the address |
| `admin.system.telemetry.body.html` | One request a day and nothing else; the address is not recorded |
| `admin.system.telemetry.locked.demo` | A demo or review instance is never counted |
| `demo.banner.text` | Real reports do not belong in the demo; its data is deleted every 6 hours |
