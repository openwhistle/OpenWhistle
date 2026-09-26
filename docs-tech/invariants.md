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

## Usability (v1.5, `docs-tech/mutations/v1.5.0-ux.json`, 24 red)

| Guard | Test that fires |
| --- | --- |
| A failed field gets `aria-invalid` and `aria-describedby` → inline message (wizard, status, login, TOTP, setup) | `tests/test_v150_ux.py` `test_*_marks_*`, `test_setup_wizard_errors_sit_next_to_their_fields` |
| Blank admin login answers on the form, not with 422 JSON | `test_login_empty_fields_answer_on_the_form` |
| `t()` never marks a plain message safe, whatever it ends with | `test_plain_message_passed_through_t_is_never_marked_safe` |
| Case-number search: LIKE wildcards escaped, case-manager scope kept, links keep `q` | `test_search_escapes_like_wildcards`, `test_search_keeps_the_case_manager_restriction`, `test_dashboard_search_form_and_links_keep_the_query` |
| Audit entries: every action labelled in 4 languages, detail escaped, CSV keeps codes | `test_every_audit_action_has_a_label_in_every_language`, `test_audit_log_shows_labels_and_readable_detail` |

## v1.6.0 hardening

Mutations: `docs-tech/mutations/v1.6.0-{security,privacy,wizard,timeouts,platform}.json`
(206, all red). One row per guard; the test is the first one that fired.

**Found by the v1.6.0 audit.** The first run left 26 of 205 green. Six
had a test that the spec did not run (the S3 key tests live in
`tests/test_issue_45_s3_missing.py`, the case-manager counts in
`tests/test_v160_design.py`); twenty had none: eighteen got one, two are
recorded below. The new tests pin, among others, the setup token surviving a
page reload, a session token without `exp` (401, not a 500), the downgrade of
migration 004 naming an unreadable secret, a deactivated user's TOTP setup
page, the organisation bound of the content search, a lost commit reply with
an attachment, and the 4 KiB bound on a clamd reply (an over-long `FOUND` reply is refused as
*unavailable*, never parsed as a signature).

The three ClamAV timeouts were added after that run: removing one hangs its
test, so `v1.6.0-timeouts.json` sets `timeout_seconds: 120` and the script
counts a hang as red.

**Not mutations.**

- The role check for an *unassigned* case in `can_reveal_identity`: only
  admins and superadmins can open an unassigned case at all
  (`_can_access_report`), so removing it changes nothing a request can see.
  It stays as the explicit statement of the rule.
- `_save_submission` fixing `report_id` at the first save: an id-less draft
  gets one on its first load anyway (`_ASSIGN_REPORT_ID`, one `SET NX` per
  draft), so removing it only moves where the id is first written.
- `submit_get` recovered a claimed draft before asking `_submit_outcome`,
  which recovers it again once `pending` has expired. The first call was
  redundant and is deleted; `test_worker_dying_after_the_claim_gives_the_draft_back_when_pending_expires`
  covers the path.

### Setup, sessions, roles, keys, audit scope

`docs-tech/mutations/v1.6.0-security.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `setup-token-unchecked` | `app/api/wizard.py` | `test_setup_without_the_right_token_is_refused` |
| `setup-token-kept-after-setup` | `app/api/wizard.py` | `test_setup_with_the_token_creates_the_admin_and_deletes_the_token` |
| `setup-get-no-token` | `app/api/wizard.py` | `test_get_setup_recreates_a_lost_token` |
| `setup-token-absent-key-crashes` | `app/services/setup_token.py` | `test_setup_post_refused_when_the_redis_key_is_absent` |
| `configured-token-loses-to-stale` | `app/services/setup_token.py` | `test_configured_setup_token_overrides_a_stale_stored_token` |
| `random-token-overwritten` | `app/services/setup_token.py` | `test_get_setup_keeps_the_token_it_already_created` |
| `setup-token-short-accepted` | `app/config.py` | `test_setup_token_validator` |
| `lifespan-no-setup-token` | `app/main.py` | `test_startup_creates_the_setup_token_only_while_setup_is_open` |
| `totp-plaintext` | `app/models/user.py` | `test_totp_secret_is_stored_encrypted` |
| `migration-004-encrypts-twice` | `migrations/versions/004_encrypt_totp_secrets.py` | `test_migration_004_round_trip_encrypts_and_stays_idempotent` |
| `migration-004-downgrade-narrows-garbage` | `migrations/versions/004_encrypt_totp_secrets.py` | `test_migration_004_downgrade_names_an_unreadable_secret` |
| `refresh-no-csrf` | `app/api/auth.py` | `test_session_refresh_without_csrf_header_is_refused` |
| `session-age-unchecked` | `app/api/deps.py` | `test_session_older_than_the_absolute_limit_is_rejected` |
| `exp-not-capped` | `app/services/auth.py` | `test_refresh_never_extends_past_the_absolute_limit` |
| `refresh-resets-auth-time` | `app/api/auth.py` | `test_refresh_never_extends_past_the_absolute_limit` |
| `refresh-without-claims` | `app/api/auth.py` | `test_session_refresh_never_restarts_the_clock_when_claims_are_missing` |
| `auth-time-ignored` | `app/services/auth.py` | `test_session_older_than_the_absolute_limit_is_rejected` |
| `session-too-old-never` | `app/services/auth.py` | `test_session_older_than_the_absolute_limit_is_rejected` |
| `redis-session-outlives-jwt` | `app/services/auth.py` | `test_refresh_never_extends_past_the_absolute_limit` |
| `cookie-outlives-jwt` | `app/api/auth.py` | `test_refresh_never_extends_past_the_absolute_limit` |
| `jwt-exp-not-required` | `app/services/auth.py` | `test_a_session_token_without_exp_or_sub_is_refused` |
| `inactive-reaches-totp` | `app/api/auth.py` | `test_deactivated_user_never_reaches_the_totp_step` |
| `inactive-gets-session` | `app/api/auth.py` | `test_user_deactivated_between_password_and_totp_gets_no_session` |
| `inactive-mfa-setup-post` | `app/api/auth.py` | `test_deactivated_user_mfa_setup_makes_no_state_change` |
| `inactive-mfa-setup-get` | `app/api/auth.py` | `test_deactivated_user_gets_no_mfa_setup_page` |
| `unknown-role-admin` | `app/api/admin.py` | `test_unknown_role_creates_no_user` |
| `unknown-role-change-400` | `app/api/admin.py` | `test_unknown_role_change_is_422_and_changes_nothing` |
| `new-user-defaults-to-admin` | `app/api/admin.py` | `test_a_new_user_without_a_role_is_a_case_manager` |
| `ip-dismiss-any-role` | `app/api/admin.py` | `test_case_manager_cannot_dismiss_the_ip_warning` |
| `audit-row-without-report-org` | `app/services/audit.py` | `test_audit_rows_carry_the_report_org_and_else_the_actor_org` |
| `audit-row-without-actor-org` | `app/services/audit.py` | `test_audit_rows_carry_the_report_org_and_else_the_actor_org` |
| `orgless-admin-sees-all-orgless-rows` | `app/services/audit.py` | `test_org_less_admin_sees_only_their_own_org_less_audit_rows` |
| `migration-005-no-backfill` | `migrations/versions/005_audit_org_backfill.py` | `test_migration_005_backfills_audit_org_from_report_or_actor` |
| `key-is-secret-key` | `app/services/encryption.py` | `test_encryption_does_not_depend_on_secret_key` |
| `previous-keys-ignored` | `app/services/encryption.py` | `test_without_encryption_key_secret_key_still_decrypts` |
| `field-crypto-current-key-only` | `app/services/crypto.py` | `test_without_encryption_key_secret_key_still_decrypts` |
| `short-encryption-key` | `app/config.py` | `test_short_encryption_key_is_refused` |
| `short-previous-key` | `app/config.py` | `test_short_previous_key_is_refused` |
| `rotation-runs-without-both-keys` | `scripts/rotate_encryption_key.py` | `test_rotation_script_refuses_without_both_keys` |
| `rotation-writes-despite-failures` | `scripts/rotate_encryption_key.py` | `test_rotation_script_names_unreadable_rows_and_writes_nothing` |
| `rotation-lost-update` | `scripts/rotate_encryption_key.py` | `test_rotation_script_flags_a_row_changed_during_the_run` |
| `rotation-touches-plain-reasons` | `scripts/rotate_encryption_key.py` | `test_rotation_script_moves_every_value_to_the_new_key` |
| `collision-full-rollback` | `app/services/report.py` | `test_case_number_collision_keeps_the_callers_objects_loaded` |
| `retry-any-integrity-error` | `app/services/report.py` | `test_create_report_does_not_retry_other_integrity_errors` |
| `flush-any-redis` | `tests/conftest.py` | `test_refuses_db_0` |

### Identity, audit trail, search, day-only times, notifications, uploads, onion

`docs-tech/mutations/v1.6.0-privacy.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `case-manager-counts-all` | `app/api/admin.py` | `test_case_manager_pill_counts_only_their_cases` |
| `identity-always-shown` | `app/api/admin.py` | `test_case_page_hides_identity_and_records_the_view` |
| `view-not-audited` | `app/api/admin.py` | `test_case_page_hides_identity_and_records_the_view` |
| `pdf-view-not-audited` | `app/api/admin.py` | `test_pdf_export_omits_identity_by_default` |
| `refused-reveal-not-audited` | `app/api/admin.py` | `test_reveal_without_a_reason_is_refused` |
| `reveal-without-reason` | `app/api/admin.py` | `test_reveal_without_a_reason_is_refused` |
| `reason-unbounded` | `app/api/admin.py` | `test_reveal_without_a_reason_is_refused` |
| `reason-too-short-accepted` | `app/api/admin.py` | `test_reveal_without_a_reason_is_refused` |
| `reason-not-stripped` | `app/api/admin.py` | `test_reveal_without_a_reason_is_refused` |
| `reveal-gate-open` | `app/api/admin.py` | `test_multi_tenant_unassigned_reveal_is_for_the_case_org_only` |
| `reveal-no-csrf` | `app/api/admin.py` | `test_reveal_without_csrf_token_is_refused` |
| `pdf-identity-no-csrf` | `app/api/admin.py` | `test_pdf_export_csrf_is_required_for_the_identity_export` |
| `reason-stored-plain` | `app/api/admin.py` | `test_handler_reveal_shows_identity_once_and_audits_the_reason` |
| `pdf-reason-stored-plain` | `app/api/admin.py` | `test_pdf_with_identity_needs_a_reason_and_is_audited` |
| `pdf-reveal-not-audited` | `app/api/admin.py` | `test_audit_csv_translates_the_via_label_for_a_pdf_export` |
| `pdf-reveal-skips-the-gate` | `app/api/admin.py` | `test_pdf_export_with_identity_is_refused_to_a_non_handler` |
| `any-assigned-admin-reveals` | `app/api/admin.py` | `test_admin_who_is_not_the_handler_cannot_reveal` |
| `reveal-across-orgs` | `app/api/admin.py` | `test_multi_tenant_unassigned_reveal_is_for_the_case_org_only` |
| `orgless-report-never-revealed` | `app/api/admin.py` | `test_multi_tenant_unassigned_reveal_is_for_the_case_org_only` |
| `reveal-form-for-everyone` | `app/templates/admin/report.html` | `test_admin_who_is_not_the_handler_cannot_reveal` |
| `case-page-shows-the-reason` | `app/templates/admin/_audit.html` | `test_case_page_says_a_reason_was_recorded_but_not_what` |
| `reason-not-decrypted-for-the-log` | `app/templating.py` | `test_audit_detail_decrypts_a_reveal_reason_and_keeps_a_plain_one` |
| `case-views-always-listed` | `app/api/admin.py` | `test_audit_trail_hides_case_views_unless_asked` |
| `csv-formula-kept` | `app/api/admin.py` | `test_audit_csv_neutralises_formulas` |
| `csv-detail-forgeable` | `app/api/admin.py` | `test_audit_csv_detail_cannot_be_forged_by_a_reason` |
| `csv-unreadable-reason-unmarked` | `app/api/admin.py` | `test_audit_csv_marks_an_unreadable_reason` |
| `search-matches-the-identity` | `app/services/report.py` | `test_dashboard_search_never_matches_the_confidential_name` |
| `search-unlimited` | `app/services/report.py` | `test_content_search_limit_caps_how_many_reports_are_decrypted` |
| `search-order-unstable` | `app/services/report.py` | `test_content_search_limit_tiebreaks_deterministically_on_equal_timestamp` |
| `search-not-nfc` | `app/services/report.py` | `test_content_search_normalizes_unicode_composition_before_matching` |
| `search-lowercase-only` | `app/services/report.py` | `test_content_search_matches_strasse_case_folded` |
| `search-ignores-assignment` | `app/services/report.py` | `test_content_search_limit_caps_how_many_reports_are_decrypted` |
| `search-ignores-view-filters` | `app/services/report.py` | `test_content_search_respects_the_active_status_and_location_filter` |
| `search-ignores-org` | `app/services/report.py` | `test_content_search_stays_inside_the_callers_organisation` |
| `content-hits-dropped` | `app/services/report.py` | `test_dashboard_search_finds_words_inside_reports` |
| `list-order-unstable` | `app/services/report.py` | `test_equal_submission_days_page_in_a_stable_id_order` |
| `counts-ignore-assignment` | `app/services/report.py` | `test_case_manager_pill_counts_only_their_cases` |
| `counts-ignore-location` | `app/services/report.py` | `test_status_pills_keep_and_count_within_the_location_and_search` |
| `stats-ignore-assignment` | `app/services/report.py` | `test_case_manager_statistics_cover_only_their_cases` |
| `exact-times` | `app/services/report.py` | `test_submission_and_receipt_carry_only_the_day` |
| `submission-exact-time` | `app/services/report.py` | `test_submission_and_receipt_carry_only_the_day` |
| `upload-exact-time` | `app/services/attachment.py` | `test_attachment_upload_time_is_the_day` |
| `reply-exact-time` | `app/services/report.py` | `test_whistleblower_reply_on_a_new_day_is_that_midnight` |
| `thread-order-lost` | `app/services/report.py` | `test_same_day_whistleblower_reply_stays_after_the_admin_reply` |
| `thread-time-race` | `app/services/report.py` | `test_concurrent_whistleblower_replies_get_distinct_ordered_times` |
| `receipt-shown-exact` | `app/services/report.py` | `test_case_page_and_pdf_show_whistleblower_times_as_the_day_only` |
| `wb-message-shown-exact` | `app/services/report.py` | `test_case_page_and_pdf_show_whistleblower_times_as_the_day_only` |
| `pdf-submitted-exact` | `app/services/pdf.py` | `test_case_page_and_pdf_show_whistleblower_times_as_the_day_only` |
| `pdf-message-exact` | `app/services/pdf.py` | `test_case_page_and_pdf_show_whistleblower_times_as_the_day_only` |
| `migration-006-receipt-exact` | `migrations/versions/006_whistleblower_times_by_day.py` | `test_migration_006_rounds_existing_rows_keeps_order_and_round_trips` |
| `migration-006-order-lost` | `migrations/versions/006_whistleblower_times_by_day.py` | `test_migration_006_rounds_existing_rows_keeps_order_and_round_trips` |
| `local-time-shifts-the-day` | `app/templates/base.html` | `test_local_time_script_shows_date_only_values_as_the_utc_day` |
| `demo-seed-exact-times` | `app/services/demo_seed.py` | `test_demo_seed_stores_reporter_times_as_the_day` |
| `pdf-identity-default` | `app/services/pdf.py` | `test_pdf_export_omits_identity_by_default` |
| `webhook-lists-cases` | `app/services/notifications.py` | `test_digest_webhook_body_has_no_case_number` |
| `reminder-webhook-dropped` | `app/services/reminders.py` | `test_reminder_run_sends_one_webhook_with_counts` |
| `reminder-ack-not-counted` | `app/services/reminders.py` | `test_reminder_run_sends_one_webhook_with_counts` |
| `legacy-office-accepted-message` | `app/services/attachment.py` | `test_legacy_office_files_are_refused_with_a_way_out` |
| `xlsx-author-label-kept` | `app/services/attachment.py` | `test_xlsx_comment_author_label_is_removed_but_the_comment_is_kept` |
| `xlsx-label-replaced-everywhere` | `app/services/attachment.py` | `test_xlsx_comment_only_first_run_label_is_replaced` |
| `rekey-without-copy` | `app/services/attachment.py` | `test_legacy_s3_keys_are_moved_to_bare_uuids` |
| `rekey-repoints-after-failed-copy` | `app/services/attachment.py` | `test_failed_copy_leaves_the_row_untouched` |
| `rekey-on-every-replica` | `app/services/attachment.py` | `test_run_s3_rekey_noop_when_another_replica_holds_the_lock` |
| `rekey-failure-logs-message` | `app/main.py` | `test_log_rekey_task_result_logs_exception_type_not_message` |
| `legacy-key-in-lookup-error` | `app/services/attachment.py` | `test_read_attachment_lookup_error_has_no_filename` |
| `legacy-key-in-delete-log` | `app/services/attachment.py` | `test_failed_object_delete_logs_no_key` |
| `legacy-key-in-s3-put-log` | `app/services/storage.py` | `test_s3_put_logs_no_filename` |
| `legacy-key-in-s3-delete-log` | `app/services/storage.py` | `test_s3_delete_logs_no_filename` |
| `legacy-key-in-s3-not-found` | `app/services/storage.py` | `test_s3_get_missing_object_message_has_no_filename` |
| `scanner-down-accepts` | `app/services/attachment.py` | `test_upload_is_refused_when_the_scanner_is_unreachable` |
| `infected-accepted` | `app/services/attachment.py` | `test_upload_is_refused_when_the_scanner_is_unreachable` |
| `scan-when-unconfigured` | `app/services/virus_scan.py` | `test_scanning_off_by_default_never_connects` |
| `unknown-reply-is-clean` | `app/services/virus_scan.py` | `test_scan_unavailable_on_non_ok_non_found_reply` |
| `truncated-reply-escapes` | `app/services/virus_scan.py` | `test_scan_unavailable_when_reply_has_no_terminator` |
| `overlong-reply-escapes` | `app/services/virus_scan.py` | `test_a_reply_longer_than_the_bound_is_not_trusted` |
| `reply-buffer-unbounded` | `app/services/virus_scan.py` | `test_a_reply_longer_than_the_bound_is_not_trusted` |
| `blank-signature-is-clean` | `app/services/virus_scan.py` | `test_scan_reports_clean_and_infected` |
| `onion-header-never-sent` | `app/middleware.py` | `test_onion_location_header_points_to_the_same_page` |
| `onion-header-on-onion` | `app/middleware.py` | `test_onion_location_header_not_sent_on_the_onion_service_itself` |
| `onion-header-on-assets` | `app/middleware.py` | `test_onion_location_header_absent_for_static_assets` |
| `hsts-on-onion` | `app/middleware.py` | `test_hsts_absent_over_the_onion_listener` |
| `hsts-never` | `app/middleware.py` | `test_hsts_present_on_a_normal_host` |
| `csrf-cookie-secure-on-onion` | `app/csrf.py` | `test_cookies_have_no_secure_flag_over_the_onion_listener` |
| `cookies-secure-on-onion` | `app/onion.py` | `test_cookies_have_no_secure_flag_over_the_onion_listener` |
| `cookie-secure-guesses` | `app/onion.py` | `test_cookie_secure_fails_loudly_when_security_middleware_never_ran` |
| `onion-trusts-host` | `app/onion.py` | `test_onion_location_header_still_sent_when_host_is_onion_but_nginx_never_marked_it` |
| `onion-any-header-value` | `app/onion.py` | `test_is_onion_request_trusts_only_the_exact_nginx_header` |
| `onion-location-unvalidated` | `app/config.py` | `test_onion_location_refuses_invalid_values` |
| `onion-note-always-shown` | `app/templates/submit.html` | `test_submit_page_hides_onion_note_when_unset` |

### Submission wizard (#94 port)

`docs-tech/mutations/v1.6.0-wizard.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `any-action-processed` | `app/api/reports.py` | `test_unknown_action_on_a_fresh_session_stores_no_file` |
| `stale-step-processed` | `app/api/reports.py` | `test_stale_earlier_step_is_not_reprocessed` |
| `step-renders-post-result` | `app/api/reports.py` | `test_every_step_transition_redirects_to_get` |
| `flash-sticks` | `app/api/reports.py` | `test_validation_error_is_a_one_shot_flash` |
| `back-drops-attachments` | `app/api/reports.py` | `test_back_then_next_without_files_keeps_attachments` |
| `rejected-description-lost` | `app/api/reports.py` | `test_too_short_description_is_kept_in_the_textarea` |
| `remove-outside-attachments-step` | `app/api/reports.py` | `test_remove_is_refused_outside_the_attachments_step` |
| `remove-negative-index` | `app/api/reports.py` | `test_remove_out_of_range_index_changes_nothing` |
| `remove-no-csrf` | `app/api/reports.py` | `test_remove_requires_csrf` |
| `report-id-not-used` | `app/services/report.py` | `test_commit_whose_reply_is_lost_counts_as_done` |
| `legacy-draft-ids-race` | `app/api/reports.py` | `test_a_stale_save_of_a_pre_v1_6_draft_yields_one_report` |
| `legacy-draft-id-for-a-spent-draft` | `app/api/reports.py` | `test_a_pre_v1_6_draft_spent_while_loading_is_not_given_an_id` |
| `legacy-draft-load-unbounded` | `app/api/reports.py` | `test_a_draft_re_saved_without_an_id_on_every_load_is_given_up_after_3_attempts` |
| `claim-overwrites-a-claim` | `app/api/reports.py` | `test_a_second_claim_never_takes_over_a_claimed_draft` |
| `waiting-click-holds-a-transaction` | `app/api/reports.py` | `test_waiting_click_holds_no_database_transaction` |
| `no-final-revalidation` | `app/api/reports.py` | `test_review_revalidates_the_draft_before_creating_a_report` |
| `final-check-ignores-location` | `app/api/reports.py` | `test_location_deactivated_after_its_step_returns_to_the_location_step` |
| `final-check-ignores-mode` | `app/api/reports.py` | `test_review_revalidates_the_draft_before_creating_a_report` |
| `description-minimum-dropped` | `app/api/reports.py` | `test_too_short_description_is_kept_in_the_textarea` |
| `report-committed-alone` | `app/api/reports.py` | `test_failed_attachment_store_leaves_no_report_and_restores_the_draft` |
| `attachments-committed-alone` | `app/api/reports.py` | `test_commit_whose_reply_is_lost_counts_as_done` |
| `submit-unbounded` | `app/api/reports.py` | `test_claim_to_commit_is_bounded_well_under_pending` |
| `statement-unbounded` | `app/api/reports.py` | `test_claim_to_commit_is_bounded_well_under_pending` |
| `failed-submit-keeps-the-draft-claimed` | `app/api/reports.py` | `test_slow_winner_that_fails_leaves_the_draft_reachable` |
| `issued-commit-says-not-sent` | `app/api/reports.py` | `test_a_commit_failing_without_a_report_is_pending_not_not_sent` |
| `second-click-gets-no-pin` | `app/api/reports.py` | `test_concurrent_final_submits_create_one_report_and_both_show_the_pin` |
| `result-kept-briefly` | `app/api/reports.py` | `test_the_result_is_kept_120_seconds_for_a_second_click` |
| `finish-clears-a-newer-claim` | `app/api/reports.py` | `test_a_late_submit_never_touches_a_newer_claim` |
| `give-back-over-a-newer-claim` | `app/api/reports.py` | `test_a_late_submit_never_touches_a_newer_claim` |
| `recover-over-a-changed-claim` | `app/api/reports.py` | `test_recovery_never_acts_on_a_claim_that_changed_since_it_was_read` |
| `recover-gives-back-a-committed-draft` | `app/api/reports.py` | `test_a_lost_result_write_after_the_commit_never_reopens_the_draft` |
| `start-over-keeps-report-id` | `app/api/reports.py` | `test_start_over_deletes_a_pre_v1_6_drafts_report_id_too` |

### Timeouts (spec bounds a hang at 120 s)

`docs-tech/mutations/v1.6.0-timeouts.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `clamav-connect-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_when_connecting_hangs` (hangs) |
| `clamav-drain-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_on_drain_timeout` (hangs) |
| `clamav-reply-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_on_timeout` (hangs) |

### Build, deployment, LDAP, locales, design

`docs-tech/mutations/v1.6.0-platform.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `http-proxied` | `nginx/nginx.conf` | `test_nginx_redirects_http_and_strips_ip_headers_on_https` |
| `old-tls-protocols` | `nginx/nginx.conf` | `test_nginx_tls_listener_offers_only_tls_1_2_and_1_3` |
| `ip-header-forwarded` | `nginx/snippets/proxy-headers.conf` | `test_nginx_redirects_http_and_strips_ip_headers_on_https` |
| `client-onion-header-forwarded` | `nginx/snippets/proxy-headers.conf` | `test_x_ow_onion_is_cleared_by_default_and_set_only_on_the_onion_listener` |
| `onion-listener-unmarked` | `nginx/nginx.conf` | `test_x_ow_onion_is_cleared_by_default_and_set_only_on_the_onion_listener` |
| `onion-shares-the-rate-budget` | `nginx/nginx.conf` | `test_onion_listener_has_its_own_higher_budget_rate_limit_zone` |
| `ansible-nginx-forwards-onion-header` | `ansible/roles/openwhistle/templates/nginx.conf.j2` | `test_ansible_nginx_template_includes_the_shared_snippets_not_a_second_copy` |
| `compose-writable-root` | `docker-compose.prod.yml` | `test_compose_app_is_read_only_without_capabilities` |
| `compose-image-latest` | `docker-compose.prod.yml` | `test_prod_compose_pins_the_image_version` |
| `onion-port-public` | `docker-compose.prod.yml` | `test_docker_compose_publishes_the_onion_port_on_localhost_only` |
| `bind-mount-without-selinux-label` | `docker-compose.prod.yml` | `test_compose_host_bind_mounts_carry_the_selinux_label` |
| `clamav-on-the-proxy-network` | `docker-compose.prod.yml` | `test_clamav_service_is_identical_and_hardened_in_both_compose_files` |
| `base-image-unpinned` | `Dockerfile` | `test_base_images_are_pinned_by_digest` |
| `curl-in-the-image` | `Dockerfile` | `test_runtime_image_has_no_curl_and_a_python_healthcheck` |
| `helm-writable-root` | `charts/openwhistle/templates/deployment.yaml` | `test_helm_container_security_context` |
| `helm-ingress-unlimited` | `charts/openwhistle/values.yaml` | `test_every_public_route_is_rate_limited_in_both_deployments` |
| `helm-notes-without-crit` | `charts/openwhistle/templates/NOTES.txt` | `test_the_chart_requires_crit_error_logging_where_the_operator_reads` |
| `tls-key-world-readable` | `scripts/ensure_tls_cert.py` | `test_operator_certificate_wins` |
| `tls-cert-regenerated` | `scripts/ensure_tls_cert.py` | `test_self_signed_certificate_is_created_once` |
| `action-pinned-by-tag` | `.github/workflows/ci.yml` | `test_every_workflow_action_is_pinned_by_commit_sha` |
| `env-j2-incomplete` | `ansible/roles/openwhistle/templates/env.j2` | `test_every_config_field_appears_in_ansible_env_j2` |
| `ldap-empty-password` | `app/services/ldap_auth.py` | `test_empty_password_never_binds` |
| `ldap-cert-not-demanded` | `app/services/ldap_auth.py` | `test_ldaps_demands_a_valid_certificate` |
| `ldap-filter-unescaped` | `app/services/ldap_auth.py` | `test_filter_escapes_the_username` |
| `ldap-start-tls-skipped` | `app/services/ldap_auth.py` | `test_start_tls_happens_before_any_bind` |
| `ldap-connection-left-open` | `app/services/ldap_auth.py` | `test_wrong_password_still_closes_both_connections` |
| `ldap-tls-floor-dropped` | `app/services/ldap_auth.py` | `test_ldaps_demands_a_valid_certificate` |
| `ldap-private-ca-ignored` | `app/services/ldap_auth.py` | `test_ldaps_accepts_the_right_name_signed_by_ldaptls_cacert` |
| `ldap-follows-referrals` | `app/services/ldap_auth.py` | `test_options_bound_referrals_and_timeout` |
| `ldap-referral-as-user` | `app/services/ldap_auth.py` | `test_unknown_user_is_refused` |
| `fr-key-missing` | `app/locales/fr.json` | `test_locale_has_exactly_the_keys_of_en` |
| `pyproject-version-drift` | `pyproject.toml` | `TestConfigV100Defaults::test_every_published_version_string_matches` |
| `tls-init-version-drift` | `docker-compose.prod.yml` | `TestConfigV100Defaults::test_every_published_version_string_matches` |
| `nav-ignores-role` | `app/templating.py` | `test_case_manager_sees_only_pages_they_may_open` |
| `brand-secondary-back` | `app/config.py` | `test_brand_secondary_colour_is_gone` |
| `panel-header-shouted` | `app/static/css/site.css` | `test_panel_headers_and_labels_are_not_shouted` |
| `eyebrows-everywhere` | `app/templates/admin/users.html` | `test_eyebrows_are_the_exception` |

## Repository and release

| Guard | Test |
| --- | --- |
| `docs-tech/` is never published | `test_the_technical_docs_are_not_published` |
| Every published version string equals `app_version`, every image default in the prod compose file too | `test_every_published_version_string_matches` |
| A setting added since the previous release has a CHANGELOG entry | `test_every_new_setting_is_in_the_changelog` |
| Every setting has a docs env-table row and a `docker-compose.prod.yml` line | `tests/test_config_documented.py` |
| uv pinned identically in the image and all workflows | `test_uv_version_is_the_same_in_the_image_and_every_workflow` |
| `uv.lock` matches `pyproject.toml` | CI step `uv lock --check` |
| Every tag and platform manifest pullable after publish | the publish workflow's verify loop |
| No serious/critical axe violation, console error or sideways scroll — every page, both themes, 390 and 1440 px | `tests/e2e/test_ui_check.py` |
| Whistleblower flow without JavaScript | `tests/e2e/test_no_js.py` |
