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

## Whistleblower privacy — v1.5.0

Mutations: `docs-tech/mutations/v1.5.0-privacy.json`. Tests: `tests/test_privacy_v150.py`.

| Guard | Test that fires |
| --- | --- |
| DOCX comment / tracked-change authors, initials, people.xml ids replaced | `test_docx_comment_and_tracked_change_authors_are_anonymised` |
| XLSX legacy comment authors, persons, revision user names replaced; `tc=` thread links kept | `test_xlsx_comment_authors_and_persons_are_anonymised` |
| Office thumbnail removed with its relationship and content-type override | `test_docx_thumbnail_is_removed_with_its_references` |
| Zip entries rewritten without timestamps or extra fields (Unix uid/gid) | `test_office_zip_entries_lose_timestamps_and_extra_fields` |
| Attachment filename encrypted; S3 key never carries it | `test_attachment_filename_is_stored_encrypted`, `test_s3_object_key_does_not_carry_the_filename` |
| Name decrypted on status page, admin page, both downloads, PDF | `test_status_page_download_and_pdf_show_the_decrypted_filename`, `test_admin_report_page_and_download_show_the_decrypted_filename` |
| Migration 003 encrypts existing names, never twice | `test_migration_encrypts_existing_filenames_idempotently` |
| Draft in Redis is ciphertext; key only in the cookie; wrong key = expired | `test_draft_in_redis_reveals_nothing_without_the_cookie_key`, `test_draft_with_the_wrong_key_counts_as_expired` |
| Draft attachment total cap; refused near Redis `maxmemory` | `test_draft_attachments_are_capped_in_total`, `test_draft_attachments_are_refused_when_redis_is_nearly_full`, `test_redis_has_room` |
| New-report and reply notices queued, sent as one digest, once across replicas | `test_new_report_and_reply_are_queued_not_sent`, `test_digest_is_delivered_once_when_replicas_run_together`, `test_whistleblower_reply_queues_a_notification` |
| Retention on by default; admin page says why nothing is deleted yet | `test_retention_enabled_defaults_true`, `test_retention_page_explains_the_default` |
| IP headers and peer address removed before the app; pages `no-store` | `test_ip_headers_and_peer_address_never_reach_the_app`, `test_pages_are_never_cached_but_static_files_are` |
| Helm Ingress turns the ingress-nginx access log off | `test_helm_ingress_turns_the_nginx_access_log_off` |

**Only one replica sends a digest** without a job lock: the queue is read and
cleared in one `MULTI/EXEC`, so concurrent runs get the events exactly once
(`digest-read-not-atomic` turns the concurrency test red).

## Accounts and organisations

| Guard | Test that fires |
| --- | --- |
| OIDC login goes through TOTP | `test_oidc_login_requires_totp` |
| LDAP first login is a case manager; username escaped; LDAPS verifies the certificate | `test_ldap_first_login_provisions_case_manager`, `test_ldap_filter_escapes_username`, `test_ldaps_verifies_server_certificate` |
| Static demo TOTP only for demo accounts | `test_demo_totp_code_only_works_for_demo_accounts` |
| No demo seed into a real installation | `test_foreign_database_detection` |
| Multi-tenant scoping: users page, role change, assignment and its picker, new users' org, audit log, stats, dashboard stats | `tests/test_multitenancy_scoping.py` (one test per guard) |
| Admin notes encrypted | `test_admin_notes_are_stored_encrypted` |

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
