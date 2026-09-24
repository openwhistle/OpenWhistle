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

## Not defended

| Threat | Why not | What the operator does |
|---|---|---|
| Root on the host, or anyone who can read the container environment | keys must be in memory to decrypt | restrict host access; rotate `ENCRYPTION_KEY` after an incident (docs: Rotating the encryption key) |
| The whistleblower's own device or browser compromised | outside the application | the submit page advises a private device |
| A handler who reveals an identity and passes it on | HinSchG allows the handler to know it | the audit log names who revealed it and why |
| TLS terminated by a proxy the operator configured badly | outside the bundled stack | follow the deployment guide; keep access logs off |
| Traffic analysis across a long time window | batching narrows, cannot remove | raise `NOTIFICATION_BATCH_MINUTES` |
| Content search over more than 5 000 reports per scope | decrypt-in-memory ceiling | narrow with filters (documented limit) |
