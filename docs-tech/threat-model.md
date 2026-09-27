# Threat model

Type: explanation. What OpenWhistle defends, against whom, and what it deliberately does not.

## Assets

| Asset | Where it lives |
|---|---|
| Who the whistleblower is | never stored for anonymous reports; confidential: encrypted name/contact |
| What they reported | description, messages, attachments: encrypted per report (DEK) |
| When and from where they reported | IP never reaches the app; times stored as the day (migration 006, `day_floor`); the notification digest interval bounds the precision too, so it defaults to a day (`NOTIFICATION_BATCH_MINUTES=1440`) |
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
| Admin who links SSO, or someone luring them | an identity on another account | link state bound to purpose and session; `oidc_sub` unique | `test_a_link_started_by_one_session_cannot_land_on_another` |
| Admin who set someone else's password (new account, reset, host script) | that account, later | the holder must replace it before any other admin page opens; only the holder's own change clears the flag | `test_forced_change_redirects_every_admin_route` |
| Someone at an unattended, signed-in desk | the account for good | a password change needs the current password and a fresh TOTP code | `test_a_session_alone_cannot_change_the_password` |
| Thief of a lost or stolen phone | the second factor | superadmin or host resets it; old secret gone, sessions ended | `test_superadmin_resets_an_authenticator` |
| Slack/Teams provider | case volume and timing | webhooks carry counts only | `test_webhook_payloads_carry_no_case_number` |
| Whoever runs or watches `telemetry.wdkro.de` | which organisations run OpenWhistle | off unless an admin agrees; only a random id and the version, no host, URL or counts; no redirect followed; the far end keeps no address | `test_a_report_is_one_get_with_the_id_and_the_version_and_nothing_else`, `test_nothing_is_sent_without_consent_or_under_a_hard_off` |
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

**One draft, at most one report.** Every draft carries a report id from its
first non-empty save, and every submit of it inserts that primary key. A draft
saved before v2.0.0 gets its id when it is loaded: `SET NX` on a side key
(`…:report-id`, a random UUID, deleted with the draft) that every concurrent
loader reads back, and only while the draft is still the one it read. PostgreSQL refuses
a second insert, whatever Redis holds and however late a request runs. A submit
that loses that race shows the existing report's case number, and its PIN while
the stored result is there.

| Fault | What the reporter sees | Reports |
| --- | --- | --- |
| Two clicks at once | the same case number and PIN on both | 1 |
| Worker dies after the claim | "still being processed", then the draft at review once `pending` (120 s) expires | 0, then 1 on submit |
| Commit reply lost | the case number and PIN (checked on a fresh session) | 1 |
| Result write fails after the commit | the PIN in the first response; later the case number only | 1 |
| Submit fails or times out before the commit | the review step: "NOT sent, answers kept" | 0, then 1 on submit |
| Submit fails or times out during the commit, and the check finds no report | "still being processed" (the commit may still land); after `pending` expires, the draft at review or the case number | 0 or 1 |
| Commit reply and the check both lost | "still being processed"; after `pending` expires, the case number only | 1 |
| A submit still running after `pending` expired | the draft may come back; a resubmit shows the one report | 1 |

The claim is a `RENAME` of the draft, so a dead worker loses nothing. After
`pending` expires, the claimed draft is given back only if the database has no
report with its id; otherwise the session gets a page with the case number that
says the PIN was shown once and cannot be shown again. Claim to commit is
bounded at 30 s (`asyncio.timeout` and `statement_timeout`), the check at 30 s
more, both under the 120 s `pending`. A request that outlives it anyway (a
paused process) compares its claim nonce before it deletes or restores
anything, so it never touches a newer claim. Until a case number is known, the
waiting click says "still being processed", keeps the cookie, and promises kept
answers only while the claimed draft exists.

Residual: the PIN of a report whose first response was lost (the reply-and-
check double fault, or a result write that failed while the first response
never arrived) is gone. The reporter sees the case number and is told to submit
a new report if they need to follow up.

Pinned by `test_the_result_is_kept_120_seconds_for_a_second_click`,
`test_concurrent_final_submits_create_one_report_and_both_show_the_pin`,
`test_worker_dying_after_the_claim_gives_the_draft_back_when_pending_expires`,
`test_commit_whose_reply_is_lost_counts_as_done`,
`test_a_lost_result_write_after_the_commit_never_reopens_the_draft`,
`test_commit_and_lookup_both_failing_yield_one_report`,
`test_a_submit_outliving_pending_still_yields_one_report`,
`test_a_draft_back_after_its_report_was_committed_makes_no_second_report`,
`test_a_stale_save_of_a_pre_v1_6_draft_yields_one_report`,
`test_a_submit_failing_before_its_commit_says_not_sent_and_keeps_the_answers` and
`test_a_commit_failing_without_a_report_is_pending_not_not_sent`.

## Linking SSO and resetting an authenticator (v2.1.0)

Until v2.1.0 nothing wrote `oidc_sub`, so SSO login could never succeed, and a lost authenticator
meant editing the database. Each rule below is a trust decision; the tests are in
`tests/test_v210_auth_recovery.py`, the mutations in `docs-tech/mutations/v2.1.0-auth-recovery.json`.

| Rule | Why |
| --- | --- |
| Only the account holder links, while signed in with first factor + TOTP | an admin linking for someone else would decide who that person is at the IdP; self-service needs no such trust |
| The link state stores `purpose: link` and `sha256(user id : session token)`; the callback redeems it only with both matching | a login state must never write an identity, and a flow started in the attacker's session must never land on the victim's |
| A link callback without a live session renders an error, never a login | a link state is not a first factor |
| `oidc_sub` stays unique on its own, not per issuer; a clash is refused, never moved | one configured IdP; the constraint is the check, so a race cannot win either |
| An account with no password and no LDAP cannot unlink | it would have no first factor left |
| Linking changes no login requirement: every path still ends in `_second_factor` | SSO replaces the password, never TOTP |
| Reset in the browser: superadmin only, never one's own account | resetting is taking over the second factor; one's own reset would end the caller's session |
| A browser reset also replaces a local password with a random temporary one, shown once to the superadmin, never logged or audited | a reset often follows a suspected compromise; with the old password, whoever holds it would enrol their own authenticator at `/admin/mfa/setup` |
| LDAP and SSO accounts keep their first factor | the directory or provider owns it; resetting it there is the operator's step |
| A reset replaces the secret and clears `totp_enabled`; no session is accepted while it is clear | the old app must stop at once, in the same commit, before Redis is swept |
| After the commit, every session, TOTP-pending and TOTP-setup key of the user is deleted | a session minted from the old secret must not outlive re-enrolment |
| The CLI prints the new secret once and enrols it; it works for any account | it is the way back when the last superadmin lost their phone; whoever runs the host holds the keys anyway |
| `DEMO_MODE` refuses resetting the demo accounts | the public demo must keep its static code |

## Changing one's own password (v2.1.0)

Until v2.1.0 no page let an admin change their own password, so whoever set it for someone else
(an admin on `/admin/users`, a superadmin reset) knew it for good. Tests:
`tests/test_v210_own_account.py`; mutations: `docs-tech/mutations/v2.1.0-own-account.json`.

| Rule | Why |
| --- | --- |
| A change needs the current password **and** a current, single-use TOTP code | a session alone is a cookie; whoever sits at an open desk or holds a stolen cookie must not turn it into the account for good |
| Wrong passwords and codes count on the sign-in counter of the account (`admin_ratelimit`) | the form is a second guessing oracle for both factors; one counter keeps the lockout the same wherever the guess comes from |
| Form errors (mismatch, policy, same as current) are answered before any credential check | a typo must not burn the TOTP code or count as a failed guess |
| The new password must differ from the current one | otherwise the forced change could keep the password someone else knows |
| After the change, every other session and pending login of the account ends; the current one stays | whoever knew the old password may hold a session; the holder must not be signed out mid-change |
| `must_change_password` is set by an admin creating the account, a superadmin reset with a temporary password, and the host's `--username` reset | each one has seen the password |
| The host's reset sets it too, even for the operator's own account | the script cannot tell who the holder is; one extra change is cheaper than a password two people know |
| While set, `get_current_admin` refuses every admin route with a redirect to `/admin/account`; only the account page, its form and the session timer use `get_signed_in_admin` | the rule lives in the one dependency every route already passes through, so a new route cannot forget it |
| A new or reset account enrols its authenticator first, then changes the password | the change needs a TOTP code; logout and `/admin/mfa/setup` need no session and stay open |
| Only the holder's own change clears the flag | a reset or a role change must never release it |
| Accounts without a local password (LDAP, SSO) get no form, and a POST is 404 | their directory or provider owns the password |
| `DEMO_MODE` refuses changing the demo accounts' password (403), and the page says so | the public demo must stay open to every visitor |

## Not defended

| Threat | Why not | What the operator does |
|---|---|---|
| Root on the host, or anyone who can read the container environment | keys must be in memory to decrypt | restrict host access; rotate `ENCRYPTION_KEY` after an incident (docs: Rotating the encryption key) |
| The whistleblower's own device or browser compromised | outside the application | the submit page advises a private device |
| A handler who reveals an identity and passes it on | HinSchG allows the handler to know it | the audit log names who revealed it and why |
| TLS terminated by a proxy the operator configured badly | outside the bundled stack | follow the deployment guide; keep access logs off |
| Traffic analysis across a long time window | batching narrows, cannot remove | raise `NOTIFICATION_BATCH_MINUTES` |
| The installation count's source address | a TCP request has one; the far end is trusted not to log it, and anyone on the path sees that this host talks to `telemetry.wdkro.de` once a day | leave it off, or send it through a proxy; the id and version alone name no organisation |
| Content search over more than 5 000 reports per scope | decrypt-in-memory ceiling | narrow with filters (documented limit) |
