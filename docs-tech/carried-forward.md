# Carried forward

Found by a piece of work and deliberately not fixed, with enough context to act
on. **Not** a place for defects a release caused — a release is complete or it
is not finished. Newest first.

## From the 2026-09-23 audit (after v1.3.0)

| Area | Finding | Why not yet |
| --- | --- | --- |
| Accessibility | Form errors are banners only; fields carry no `aria-invalid` / `aria-describedby` | touches every form template; own change |
| Admin UX | No case-number or text search on the dashboard; the audit log shows raw `action` + JSON detail | feature work |
| Copy | Title Case headings and buttons; "Your identity is completely protected" overpromises | needs a copy pass in four languages |
| Privacy | Filenames are stored as uploaded (can contain a name); comment and tracked-change authors inside Office files are kept | encrypting the filename needs a wider column and a migration |
| OIDC | No PKCE; the `id_token` and `nonce` are never validated (userinfo only) | move to authlib's OIDC client |
| Rate limits | `/reply` limits PIN guesses by the client-supplied `session_token`; the status lockout is keyed by the 5-digit case number, so a third party can lock a whistleblower out; admin login lockout is per username only (no brake on spraying) | a rate-limit redesign in one piece |
| Session | CSRF cookie without `Secure`; logout is a GET | small, but changes every template's logout link |
| Timing | New-report notifications fire at submission time, which can be correlated with who was at their desk | needs a batching design |
| Retention | Off by default | turning it on deletes closed reports older than 3 years on upgrade — the operator's decision |
| Setup wizard | The setup-complete check and the admin insert are not atomic | two simultaneous first-run requests only |
| Helm | Migrations run in every replica at startup | a pre-upgrade Job; single-replica installs are unaffected |
