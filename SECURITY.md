# Security Policy

## Supported versions

Security fixes are released for the latest published version. Always run the most
recent release; see the [releases page](https://github.com/openwhistle/OpenWhistle/releases)
and the in-app **Admin → System** page for update status.

| Version | Supported |
| ------- | --------- |
| Latest  | ✅        |
| Older   | ❌        |

## Reporting a vulnerability

Please report vulnerabilities **privately** — do not open a public issue.

- Preferred: GitHub's [private vulnerability reporting](https://github.com/openwhistle/OpenWhistle/security/advisories/new)
  ("Report a vulnerability" on the Security tab).

Because OpenWhistle protects whistleblowers, we especially value reports about
anonymity leaks, authorization/tenant-isolation bypasses, and anything that could
deanonymize a reporter. We aim to acknowledge reports promptly and will credit
reporters (with their consent) in the advisory and here.

## Security acknowledgements

Our thanks to those who have responsibly disclosed security issues:

- **[@openblow](https://github.com/openblow)** — reported the four advisories
  fixed in v1.1.1 (report object-level authorization / deanonymization,
  privilege escalation, stored XSS, and weak/duplicated HTTP security headers).
