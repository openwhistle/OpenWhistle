# Invariants

Reference: which test holds which guard, and what breaking the guard looks
like. Every row was verified by mutation (`scripts/mutation_audit.py`,
`docs-tech/mutations/v1.4.0.json`): 28 mutations, 28 red.

## Whistleblower privacy — attachments

| Guard | Test that fires |
| --- | --- |
| EXIF/GPS and camera data removed from JPEG, WebP; text chunks from PNG; comment from GIF | `test_jpeg_loses_exif_and_gps_but_keeps_orientation`, `test_png_text_chunks_are_removed`, `test_webp_exif_is_removed`, `test_gif_comment_is_removed` |
| Only pixels are copied — nothing Pillow would carry over from `im.info` | `test_png_icc_profile_is_removed` (ICC profiles can name the device) |
| EXIF orientation baked into the pixels | `test_jpeg_loses_exif_and_gps_but_keeps_orientation` |
| PDF document info **and** XMP removed, and the orphaned objects dropped | `test_pdf_document_info_is_removed` |
| DOCX/XLSX core, app and custom properties emptied | `test_office_properties_are_emptied_and_content_kept` |
| Zip bomb refused | `test_office_zip_bomb_is_refused` |
| A file that cannot be cleaned is refused, never stored as-is | `test_unparseable_file_is_refused_not_stored_as_is`, `test_upload_refuses_a_file_that_cannot_be_cleaned` |
| Attachment bytes encrypted with the report key, decrypted on read | `test_attachment_is_stored_encrypted_and_read_back` |

**Found by the v1.4.0 audit.** The PDF fixture had no XMP, so removing the XMP
step stayed green — and once XMP was in the fixture, the shipped code failed:
unlinking `/Metadata` from the catalog left the stream in the file as an
orphaned object. Now removed with `compress_identical_objects(remove_orphans=True)`.

**Deleted by the v1.4.0 audit.** An `is_encrypted` check refused every
encrypted PDF. Removing it stayed green, because a PDF that needs a user
password fails in the generic path anyway — and the check refused
owner-password-only PDFs, which open without a password and clean correctly
(`test_owner_password_only_pdf_is_accepted_and_cleaned`).

## Accounts and organisations

| Guard | Test that fires |
| --- | --- |
| OIDC login goes through TOTP | `test_oidc_login_requires_totp` |
| LDAP first login is a case manager; username escaped; LDAPS verifies the certificate | `test_ldap_first_login_provisions_case_manager`, `test_ldap_filter_escapes_username`, `test_ldaps_verifies_server_certificate` |
| Static demo TOTP only for demo accounts | `test_demo_totp_code_only_works_for_demo_accounts` |
| No demo seed into a real installation | `test_foreign_database_detection` |
| Multi-tenant scoping: users page, role change, assignment and its picker, new users' org, audit log, stats, dashboard stats | `tests/test_multitenancy_scoping.py` (one test per guard) |
| Admin notes encrypted | `test_admin_notes_are_stored_encrypted` |

## Authentication (v1.5.0)

Mutations: `docs-tech/mutations/v1.5.0-auth.json` (35, all red); tests in
`tests/test_v150_auth.py` and `tests/test_oidc.py`.

| Guard | Test that fires |
| --- | --- |
| Correct case number + PIN always opens the case; wrong attempts only inform | `test_correct_pin_opens_case_after_many_wrong_attempts`, `test_wrong_pin_past_the_limit_shows_wait_notice_and_keeps_the_form` |
| Unknown case number still costs a bcrypt check (no timing oracle) | `test_unknown_case_number_costs_a_bcrypt_check` |
| Password spraying: one alert and one audit entry per window, local and LDAP failures | `test_spraying_*` |
| Logouts are POST + CSRF; GET does nothing | `test_get_*_logout_does_not_log_out`, `test_*_logout_without_csrf_token_is_refused` |
| Setup: check and insert under an advisory lock, re-check reads the row again | `test_setup_waits_for_a_concurrent_completion_and_creates_nothing`, `test_setup_recheck_is_not_fooled_by_the_session_cache` |
| `alembic upgrade` waits for the migration advisory lock | `test_alembic_upgrade_waits_for_the_migration_lock` |
| OIDC: PKCE S256, single-use state, ID token signature/iss/aud/exp/nonce/azp | `tests/test_oidc.py` |

**Not a mutation.** Adding `HS256` to the OIDC algorithm allowlist stays green:
the key comes from the JWKS as a `PyJWK` bound to its own algorithm, and PyJWT
refuses a header `alg` that does not match it. The allowlist is kept as a second
line; `test_id_token_that_does_not_verify_is_refused[symmetric alg]` covers the
outcome.

## Repository and release

| Guard | Test |
| --- | --- |
| `docs-tech/` is never published | `test_the_technical_docs_are_not_published` |
| Every published version string equals `app_version` | `test_every_published_version_string_matches` |
| uv pinned identically in the image and all workflows | `test_uv_version_is_the_same_in_the_image_and_every_workflow` |
| `uv.lock` matches `pyproject.toml` | CI step `uv lock --check` |
| Every tag and platform manifest pullable after publish | the publish workflow's verify loop |
| No serious/critical axe violation, console error or sideways scroll — every page, both themes, 390 and 1440 px | `tests/e2e/test_ui_check.py` |
| Whistleblower flow without JavaScript | `tests/e2e/test_no_js.py` |
