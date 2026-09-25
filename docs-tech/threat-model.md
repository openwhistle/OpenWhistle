# Threat model

Type: explanation. What OpenWhistle defends, against whom, and what it deliberately does not.

## Assets

| Asset | Where it lives |
|---|---|
| Who the whistleblower is | never stored for anonymous reports; confidential: encrypted name/contact |
| What they reported | description, messages, attachments: encrypted per report (DEK) |
| When and from where they reported | IP never reaches the app; times stored as the day |
| Access to a case | case number + UUID PIN (bcrypt), admin password + TOTP |
| Keys | `ENCRYPTION_KEY` (data), `SECRET_KEY` (sessions), in the environment only |

## Attackers and what stops them

| Attacker | Wants | Stopped by | Pinned by |
|---|---|---|---|
| Employer's IT watching the office network | who reported | no IP anywhere; Tor onion address; digest-batched notices | `test_ip_headers_and_peer_address_never_reach_the_app`, `test_onion_location_header_points_to_the_same_page` |
| Someone reaching a fresh install first | admin account | setup token | `test_setup_without_the_right_token_is_refused` |
| Thief of a database dump | content, identities, second factors | envelope encryption, encrypted TOTP secrets, key outside the DB | `test_totp_secret_is_stored_encrypted`, `tests/test_privacy_v150.py` |
| Admin who is not the handler | a confidential identity | identity only for the handler, audited reason | `test_admin_who_is_not_the_handler_cannot_reveal` |
| Admin of another organisation | other tenants' cases or audit rows | object-level checks, org-scoped audit | `tests/test_multitenancy_scoping.py` |
| Password sprayer, TOTP guesser | an admin session | lockout, spraying alert, single-use TOTP | `tests/test_v150_auth.py` |
| Stolen admin session cookie | lasting access | 60 min TTL, 12 h absolute limit, CSRF on refresh | `test_session_older_than_the_absolute_limit_is_rejected` |
| Slack/Teams provider | case volume and timing | webhooks carry counts only | `test_webhook_payloads_carry_no_case_number` |
| Malicious upload | admin's machine | type + magic check, metadata strip, optional ClamAV fail-closed | `test_upload_is_refused_when_the_scanner_is_unreachable` |

## The PIN in Redis for 120 seconds

A double click on "Submit" sends two requests, and the browser shows only the
last response. The request that claims the draft creates the report. The other
would show an empty wizard, and the reporter would never see the PIN. So the
winner stores `{case number, PIN, attachment names}` for 120 s. The other
request reads it once (`GETDEL`) and shows the same page.

| | Draft | Claimed draft | Stored result |
| --- | --- | --- | --- |
| Holds | description, identity (confidential), attachments | the same bytes, renamed | case number, PIN, file names |
| Encrypted with | the key in the reporter's cookie only | the same key | the same key |
| Lives | up to 2 h | the draft's remaining TTL; deleted once the commit is confirmed | 120 s, deleted on first read |

Anyone who can read that key can already read the draft, which is the report
itself, for longer. The PIN never reaches the database in clear or a log line.

The claim is a `RENAME`, not a delete, so a worker that dies between the claim
and the commit loses nothing. Once `pending` (120 s) expires, the next request
of that session gets the draft back at the review step. A commit whose reply
was lost is checked on a fresh session before the draft is given back, so it
never yields a second report. Until a case number is known, the waiting click
says "still being processed" and keeps the cookie. It never says "received".

Pinned by `test_the_result_is_kept_120_seconds_for_a_second_click`,
`test_concurrent_final_submits_create_one_report_and_both_show_the_pin`,
`test_worker_dying_after_the_claim_gives_the_draft_back_when_pending_expires`
and `test_commit_whose_reply_is_lost_counts_as_done`.

## Not defended

| Threat | Why not | What the operator does |
|---|---|---|
| Root on the host, or anyone who can read the container environment | keys must be in memory to decrypt | restrict host access; rotate `ENCRYPTION_KEY` after an incident (docs: Rotating the encryption key) |
| The whistleblower's own device or browser compromised | outside the application | the submit page advises a private device |
| A handler who reveals an identity and passes it on | HinSchG allows the handler to know it | the audit log names who revealed it and why |
| TLS terminated by a proxy the operator configured badly | outside the bundled stack | follow the deployment guide; keep access logs off |
| Traffic analysis across a long time window | batching narrows, cannot remove | raise `NOTIFICATION_BATCH_MINUTES` |
| Content search over more than 5 000 reports per scope | decrypt-in-memory ceiling | narrow with filters (documented limit) |
