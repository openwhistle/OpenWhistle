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

## v2.0.0 hardening

Mutations: `docs-tech/mutations/v2.0.0-{security,privacy,wizard,timeouts,platform,review,site}.json`
(281, all red). One row per guard; the test is the first one that fired.

**Found by the v2.0.0 audit.** The first run left 26 of 205 green. Six
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
test, so `v2.0.0-timeouts.json` sets `timeout_seconds: 120` and the script
counts a hang as red.

`v2.0.0-review.json` (the local review login) first left 4 of 27 green: the
disabled-route and hidden-button tests failed the Host barrier before they
reached the flag, a missing demo admin and the `app-setup` profile had no
test. Each got one; the release.md test now reads the numbered step, not the
diagram.
Re-running the other five after merging it: `inactive-reaches-totp` was
stale (`_login_ctx` gained `request`), and `search-order-unstable` was red
only by luck (without the tiebreaker, which of two tied rows wins is a coin
flip on random uuids); its test now also checks the statement's `ORDER BY`.

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

`docs-tech/mutations/v2.0.0-security.json`

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

`docs-tech/mutations/v2.0.0-privacy.json`

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

`docs-tech/mutations/v2.0.0-wizard.json`

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

`docs-tech/mutations/v2.0.0-timeouts.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `clamav-connect-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_when_connecting_hangs` (hangs) |
| `clamav-drain-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_on_drain_timeout` (hangs) |
| `clamav-reply-unbounded` | `app/services/virus_scan.py` | `test_scan_unavailable_on_timeout` (hangs) |

### Build, deployment, LDAP, locales, design

`docs-tech/mutations/v2.0.0-platform.json`

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

### Local review login (maintainer tooling)

`docs-tech/mutations/v2.0.0-review.json`

| Mutation | File | Test that fires |
| --- | --- | --- |
| `review-login-without-demo-mode` | `app/config.py` | `test_local_review_login_requires_demo_mode` |
| `review-startup-warning-dropped` | `app/main.py` | `test_lifespan_warns_loudly_when_local_review_login_is_enabled` |
| `review-route-ignores-flag` | `app/api/auth.py` | `test_local_review_login_route_404_when_disabled` |
| `review-route-any-method` | `app/api/auth.py` | `test_local_review_login_route_404_for_every_method_when_enabled` |
| `review-route-ignores-barrier` | `app/api/auth.py` | `test_local_review_login_404_with_any_proxy_header` |
| `review-route-405-for-other-methods` | `app/api/auth.py` | `test_local_review_login_route_404_for_every_method_when_disabled` |
| `review-barrier-trusts-proxy` | `app/api/auth.py` | `test_local_review_reachable_rejects_any_proxy_header` |
| `review-barrier-any-host` | `app/api/auth.py` | `test_local_review_reachable_rejects_non_loopback_host` |
| `review-barrier-crashes-on-bad-host` | `app/api/auth.py` | `test_local_review_reachable_treats_malformed_bracketed_host_as_unreachable` |
| `review-button-ignores-barrier` | `app/api/auth.py` | `test_login_page_does_not_crash_with_malformed_host` |
| `review-button-ignores-flag` | `app/api/auth.py` | `test_login_page_shows_the_button_only_when_flag_and_barrier_pass` |
| `review-login-skips-csrf` | `app/api/auth.py` | `test_local_review_login_route_rejects_bad_csrf_before_signing_in` |
| `review-login-no-demo-admin-500` | `app/api/auth.py` | `test_local_review_login_404_when_no_demo_admin_exists` |
| `review-login-audits-deactivated` | `app/api/auth.py` | `test_local_review_login_deactivated_admin_redirects_without_audit_row` |
| `review-login-unaudited` | `app/api/auth.py` | `test_local_review_login_signs_in_with_full_session_and_audit_row` |
| `review-button-always-shown` | `app/templates/login.html` | `test_login_page_does_not_crash_with_malformed_host` |
| `review-button-primary-class` | `app/templates/login.html` | `test_review_override_button_has_a_distinct_id_and_non_primary_class` |
| `review-port-merged-not-replaced` | `docker-compose.review.yml` | `test_review_override_binds_the_app_port_to_loopback_only` |
| `review-flag-missing-from-override` | `docker-compose.review.yml` | `test_local_review_login_true_only_in_review_override` |
| `review-flag-in-ci-e2e` | `docker-compose.e2e.yml` | `test_local_review_login_literal_false_or_absent_everywhere_except_allowlist` |
| `review-flag-in-prod-compose` | `docker-compose.prod.yml` | `test_local_review_login_literal_false_or_absent_everywhere_except_allowlist` |
| `review-flag-live-in-ansible` | `ansible/roles/openwhistle/templates/env.j2` | `test_local_review_login_literal_false_or_absent_everywhere_except_allowlist` |
| `review-setup-stack-demo-seeded` | `docker-compose.review.yml` | `test_review_setup_profile_is_a_fresh_install_without_the_review_login` |
| `review-setup-stack-always-on` | `docker-compose.review.yml` | `test_review_setup_profile_is_a_fresh_install_without_the_review_login` |
| `review-matrix-drops-a-page` | `docs-tech/local-review.md` | `test_local_review_page_matrix_covers_every_app_page` |
| `review-matrix-drops-a-site-page` | `docs-tech/local-review.md` | `test_local_review_page_matrix_covers_every_docs_site_page` |
| `review-release-step-dropped` | `docs-tech/release.md` | `test_release_md_names_the_chrome_check_before_the_release_pr` |
| `docs-link-into-docs-tech` | `docs/en/docs/index.html` | `test_no_published_page_links_docs_tech` |

### Admin UI fixes and website

`docs-tech/mutations/v2.0.0-site.json`. The docs mutations run
`tests/e2e/test_layout.py -k docs_page` (every `docs/**/*.html` at 390 and
1024 px, served from a local HTTP server, no app).

The first run left 8 of 48 green. Five category-label paths had no test (the
linked-report list, `/admin/stats` by language and by organisation, both PDF
routes); the nginx snippet's own `Cache-Control` had none; the superadmin
badge test matched the dark override. Each got one. The German landing
page's `min-width: 0` grid children changed nothing at either width and were
deleted, as were the merge's second overflow fix for the deadline table and
the cost grid.
Re-running the other six after the merge: `pdf-view-not-audited` and
`pdf-identity-no-csrf` (privacy) were stale, because both PDF routes now
fetch category labels; the snippets are updated and red.

| Mutation | File | Test that fires |
| --- | --- | --- |
| `icon-block` | `app/static/css/site.css` | `test_icon_class_overrides_svg_reset_to_inline` |
| `static-url-no-version` | `app/templating.py` | `test_static_url_appends_version_query` |
| `base-css-hand-typed` | `app/templates/base.html` | `test_stylesheet_and_script_links_use_static_url_helper` |
| `static-cache-dropped` | `app/middleware.py` | `test_pages_are_never_cached_but_static_files_are` |
| `nginx-static-immutable` | `nginx/snippets/static-location.conf` | `test_nginx_static_location_is_a_shared_snippet_too` |
| `login-card-flush` | `app/static/css/site.css` | `test_panel_before_demo_credentials_has_spacing` |
| `superadmin-label-missing` | `app/locales/en.json` | `test_every_dynamic_locale_key_exists` |
| `role-default-unselected` | `app/templates/admin/users.html` | `test_new_user_role_select_defaults_to_the_least_privileged_role` |
| `role-enum-superadmin-first` | `app/models/user.py` | `test_new_user_role_select_defaults_to_the_least_privileged_role` |
| `badge-superadmin-missing` | `app/static/css/site.css` | `test_every_admin_role_has_a_badge_color` |
| `category-label-ignores-lang` | `app/models/category.py` | `test_dashboard_and_case_page_show_the_category_in_german` |
| `category-filter-ignores-map` | `app/templating.py` | `test_dashboard_and_case_page_show_the_category_in_german` |
| `category-labels-unscoped` | `app/services/categories.py` | `test_category_labels_do_not_leak_across_orgs_with_a_colliding_slug` |
| `dashboard-category-raw` | `app/templates/admin/dashboard.html` | `test_dashboard_and_case_page_show_the_category_in_german` |
| `case-page-category-raw` | `app/templates/admin/report.html` | `test_dashboard_and_case_page_show_the_category_in_german` |
| `linked-report-category-raw` | `app/templates/admin/report.html` | `test_linked_reports_and_stats_show_the_category_in_german` |
| `stats-category-english` | `app/api/admin.py` | `test_linked_reports_and_stats_show_the_category_in_german` |
| `stats-category-unscoped` | `app/api/admin.py` | `test_stats_page_category_label_is_the_own_orgs` |
| `pdf-category-slug` | `app/services/pdf.py` | `test_generate_pdf_prints_the_localised_category_label` |
| `pdf-route-no-label` | `app/api/admin.py` | `test_both_pdf_exports_print_the_category_in_german` |
| `pdf-identity-route-no-label` | `app/api/admin.py` | `test_both_pdf_exports_print_the_category_in_german` |
| `sticky-action-static` | `app/static/css/site.css` | `test_dashboard_table_action_column_is_pinned_and_status_badge_wraps` |
| `status-badge-nowrap` | `app/static/css/site.css` | `test_dashboard_table_action_column_is_pinned_and_status_badge_wraps` |
| `dashboard-header-unpinned` | `app/templates/admin/dashboard.html` | `test_table_stack_sticky_action_column_is_paired_header_and_data` |
| `docs-env-table-unscrolled` | `scripts/build_site.py` (`config_table`) | `test_docs_page_has_no_horizontal_overflow` |
| `de-token-drift` | `docs/de/index.html` | `test_only_tokens_css_defines_custom_properties` (since 2.1.1 the tokens exist once, in `tokens.css`) |
| `de-faq-jsonld-drift` | `docs/de/index.html` | `test_faqpage_jsonld_matches_visible_faq_one_to_one` |
| `en-hreflang-de-dropped` | `docs/en/index.html` | `test_landing_pages_link_each_other_via_hreflang` |
| `de-hreflang-default-dropped` | `docs/de/index.html` | `test_landing_pages_link_each_other_via_hreflang` |
| `de-comparison-table-auto` | `docs/de/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `de-btn-nowrap` | `docs/de/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `docs-nav-blog-missing` | `docs/en/docs/index.html` | `test_every_docs_page_nav_has_the_same_item_set` |
| `roadmap-nav-current-unmarked` | `docs/en/roadmap/index.html` | `test_current_nav_item_is_marked` |
| `roadmap-footer-issues-missing` | `docs/en/roadmap/index.html` | `test_every_page_footer_has_the_same_link_set_as_its_landing_page` |
| `blog-token-drift` | `docs/de/blog/index.html` | `test_only_tokens_css_defines_custom_properties` (since 2.1.1 the tokens exist once, in `tokens.css`) |
| `nav-collapse-768-en` | `docs/en/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-de` | `docs/de/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-docs` | `docs/en/docs/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-roadmap` | `docs/en/roadmap/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-blog` | `docs/de/blog/index.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-hinschg-compliance-leitfaden` | `docs/de/blog/hinschg-compliance-leitfaden.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-interne-meldestelle-einrichten` | `docs/de/blog/interne-meldestelle-einrichten.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-was-ist-neu-in-2-0` | `docs/de/blog/was-ist-neu-in-2-0.html` | `test_docs_page_has_no_horizontal_overflow` |
| `nav-collapse-768-whistleblower-software-vergleich` | `docs/de/blog/whistleblower-software-vergleich.html` | `test_docs_page_has_no_horizontal_overflow` |
| `docs-mono-500-face-missing` | `docs/en/docs/index.html` | `test_every_docs_page_font_usage_has_a_matching_font_face` |
| `roadmap-mono-500-face-missing` | `docs/en/roadmap/index.html` | `test_every_docs_page_font_usage_has_a_matching_font_face` |
| `blog-deadline-table-auto` | `docs/de/blog/hinschg-compliance-leitfaden.html` | `test_docs_page_has_no_horizontal_overflow` |
| `pin-token-nowrap` | `app/static/css/site.css` | `test_token_class_wraps_only_at_the_explicit_hyphen_breaks` |
| `pin-wbr-filter-not-applied` | `app/templates/submit_success.html` | `test_case_number_and_pin_wrap_only_at_hyphens` |
| `review-label-fixed-width` | `app/static/css/site.css` | `test_review_label_stacks_over_its_value` |
| `char-counter-not-localized` | `app/i18n.py` | `test_char_counter_uses_locale_number_format` |
| `stats-grid-panel-margin` | `app/templates/admin/stats.html` | `test_stats_grid_panels_drop_the_stacking_margin` |
| `http-exception-always-json` | `app/main.py` | `test_stale_report_id_returns_styled_html_for_a_browser` |
| `eyebrow-restates-confidential` | `app/locales/de.json` | `test_submit_eyebrow_is_neutral_across_locales` |
| `blog-2-0-date-off-by-one` | `docs/de/blog/was-ist-neu-in-2-0.html` | `test_blog_1_6_release_date_is_2026_09_26` |

**Not a mutation.** The e2e tests that measure the running app
(`tests/e2e/test_admin_table_layout.py`,
`test_review_step_label_and_value_do_not_overlap_in_german`,
`test_stats_panels_share_the_same_top`) run against a built image, so the
script's working-tree edit never reaches them: they stay GREEN whatever it
changes. Each rule is pinned in source instead: `sticky-action-static`,
`status-badge-nowrap`, `dashboard-header-unpinned`, `review-label-fixed-width`
and `stats-grid-panel-margin`.

**Doubly redundant on purpose (PIN/case-number overflow).** The
fix has two independent parts: `.token` no longer forces `white-space:
nowrap`, and the case number/PIN are rendered through `wbr_after_hyphens`
(`app/templating.py`), which inserts a `<wbr>` after each hyphen. In Chromium,
either change alone already prevents the overflow: with `nowrap` removed, the
browser's default line breaking already wraps after a plain hyphen (no
`<wbr>` needed); and a `<wbr>` is honoured as a break opportunity even when
`white-space: nowrap` is reinstated. So a single-property mutation of either
piece against the rendered page (`tests/e2e/test_wb_submission.py::
test_pin_and_case_number_fit_without_scrolling`) stays GREEN — not because
the guard is weak, but because the other half of the fix silently covers for
it. Reverting *both* together (confirmed manually, not via
`mutation_audit.py`, which mutates one file at a time) reproduces the
original overflow exactly (`.token`'s own `scrollWidth` exceeds its
`clientWidth`). Each half is instead pinned by its own reliable, browser-free
source check (`pin-token-nowrap`, `pin-wbr-filter-not-applied`, both group
`D`); the rendered e2e test stays as additional, valuable coverage of the
real behaviour without a dedicated mutation of its own.

### Deployment and upgrade (final review)

`docs-tech/mutations/v2.0.0-ops.json`: 23 mutations, 23 red.
The CI job `nginx-onion-trust` holds three more guards that no pytest can:
nginx started as the demo host runs it (the role's file modes, a non-root
owner, the rendered compose file's `cap_drop`), and header checks written as
`if grep …; then exit 1; fi`, since `set -e` ignores a `!`-negated command.
Each was proven red locally with podman: files written `0640` (nginx:
`Permission denied`), and `X-Forwarded-For` or `X-Real-IP` no longer stripped.

| Mutation | File | Test that fires |
| --- | --- | --- |
| `ansible-nginx-conf-0640` | `ansible/roles/openwhistle/tasks/deploy.yml` | `test_ansible_writes_every_nginx_bind_mount_world_readable` |
| `ansible-snippets-0640` | `ansible/roles/openwhistle/tasks/deploy.yml` | `test_ansible_writes_every_nginx_bind_mount_world_readable` |
| `ansible-snippets-dir-0640` | `ansible/roles/openwhistle/tasks/deploy.yml` | `test_ansible_writes_every_nginx_bind_mount_world_readable` |
| `ansible-snippets-playbook-dir` | `ansible/roles/openwhistle/tasks/deploy.yml` | `test_ansible_deploy_copies_the_real_snippet_files_not_a_retyped_copy` |
| `tls-init-dangling-falls-back` | `scripts/ensure_tls_cert.py` | `test_a_dangling_certificate_symlink_fails_loudly` |
| `tls-init-unreadable-raw` | `scripts/ensure_tls_cert.py` | `test_an_unreadable_operator_key_fails_loudly` |
| `behind-proxy-drifts` | `nginx/nginx.behind-proxy.conf` | `test_the_behind_proxy_nginx_differs_from_nginx_conf_only_in_its_listeners` |
| `behind-proxy-no-strip` | `nginx/nginx.behind-proxy.conf` | `test_the_behind_proxy_nginx_differs_from_nginx_conf_only_in_its_listeners` |
| `behind-proxy-keeps-443` | `docker-compose.behind-proxy.yml` | `test_the_behind_proxy_override_swaps_the_config_and_drops_443` |
| `migration-004-offline` | `migrations/versions/004_encrypt_totp_secrets.py` | `test_migration_004_refuses_offline_sql` |
| `brand-secondary-refused` | `app/config.py` | `test_a_stale_brand_secondary_color_in_env_is_ignored_with_a_warning` |
| `onion-header-always-trusted` | `app/onion.py` | `test_x_ow_onion_is_ignored_without_an_onion_address` |
| `helm-extra-env-dropped` | `charts/openwhistle/templates/configmap.yaml` | `test_helm_extra_env_reaches_the_configmap` |
| `helm-onion-clear-undocumented` | `charts/openwhistle/values.yaml` | `test_the_chart_says_to_clear_x_ow_onion_when_an_onion_address_is_set` |
| `rollback-pins-old-image` | `docs/en/docs/upgrade/index.html` | `test_the_documented_rollback_downgrades_to_the_last_1_5_revision` |
| `docs-python-m-app` | `docs/en/docs/index.html` | `test_the_docs_run_no_module_that_does_not_exist` |
| `machine-path-committed` | `docs-tech/plans/2026-09-24-v1.6-hardening.md` | `test_no_tracked_file_holds_a_machine_local_path` |
| `image-ships-unused-font` | `Dockerfile` | `test_the_image_ships_exactly_the_font_files_the_app_css_uses` |
| `process-note-in-comment` | `app/services/storage.py` | `test_shipped_files_explain_the_code_not_the_review_history` |
| `build-context-has-superpowers` | `.dockerignore` | `test_local_tooling_and_maintainer_docs_stay_out_of_the_build_context` |
| `serena-tracked` | `.gitignore` | `test_local_tooling_and_maintainer_docs_stay_out_of_the_build_context` |
| `docs-link-docs-tech` | `docs/en/docs/index.html` | `test_no_published_page_links_docs_tech` |
| `roadmap-test-chore` | `docs/en/roadmap/index.html` | `test_the_public_roadmap_holds_no_test_chores` |

## SSO linking and authenticator reset (v2.1.0)

`docs-tech/mutations/v2.1.0-auth-recovery.json`: 28 mutations, 28 red, all in
`tests/test_v210_auth_recovery.py`. The rules and why: [threat model](threat-model.md).

| Guard | Test that fires |
| --- | --- |
| A state redeems only for its own purpose | `test_a_login_state_cannot_link_and_a_link_state_cannot_log_in` |
| A link state redeems only for the session that started it | `test_a_link_started_by_one_session_cannot_land_on_another` |
| A link callback without a session is an error page, never a login | `test_link_callback_without_a_session_links_nothing_and_signs_nobody_in` |
| An identity on another account is refused (unique `oidc_sub`) | `test_link_is_refused_when_the_identity_belongs_to_another_account` |
| No unlink of the only way in | `test_unlink_is_refused_when_sso_is_the_only_way_in` |
| Reset: superadmin only, not self, CSRF, not the demo accounts | `test_only_a_superadmin_resets_an_authenticator`, `test_a_superadmin_cannot_reset_their_own_authenticator`, `test_reset_needs_csrf`, `test_demo_accounts_keep_their_authenticator` |
| Reset: new secret, enrolment forced, sessions of that user (only) swept | `test_superadmin_resets_an_authenticator` |
| No session while `totp_enabled` is off | `test_no_session_is_accepted_while_the_authenticator_awaits_enrolment` |
| Browser reset replaces a local password; the old one fails, the new one leads to TOTP setup | `test_superadmin_resets_an_authenticator` |
| The temporary password is in no log, header or audit row | `test_the_temporary_password_leaks_nowhere` |
| An LDAP/SSO account gets no password | `test_an_account_without_a_password_keeps_its_directory_login` |

**Not a guard, so not kept.** A select-then-refuse check for an already linked identity could
never turn a test red: the unique constraint refuses the same link, caught as `IntegrityError`.
The constraint is the guard; the mutation breaks the `except` around the audit flush and commit.

**Not a mutation.** `link-without-session` first stayed green: without the `except`, the
`HTTPException` still answers 401. The test now asserts the error page, not only the status.

## Own password and forced change (v2.1.0)

`docs-tech/mutations/v2.1.0-own-account.json`: 34 mutations, 34 red, all in
`tests/test_v210_own_account.py`. The rules and why: [threat model](threat-model.md).

| Guard | Test that fires |
| --- | --- |
| A change needs a current, unused TOTP code; a wrong one counts | `test_a_session_alone_cannot_change_the_password`, `test_a_totp_code_already_used_is_refused` |
| A change needs the current password; a wrong one counts | `test_a_wrong_current_password_changes_nothing_and_counts` |
| A locked account cannot change, and the lock is the sign-in lock | `test_a_locked_account_cannot_change_even_with_the_right_credentials` |
| Policy, confirmation and "differs from the current one" are checked first | `test_a_form_error_is_answered_before_any_credential_check` |
| CSRF | `test_the_change_needs_csrf` |
| Other sessions end, the current one stays | `test_every_other_session_ends_and_the_current_one_stays`, `test_change_with_the_current_password_and_a_totp_code` |
| Every admin route redirects while forced; the account page, its form and the session timer do not | `test_forced_change_redirects_every_admin_route`, `test_the_session_timer_renews_during_a_forced_change` |
| New account, superadmin reset and host reset set the flag; only the holder's change clears it | `test_a_new_account_enrols_then_must_change_its_password`, `test_a_reset_account_enrols_then_must_change_its_password`, `test_cli_password_reset_forces_a_change_ends_sessions_and_is_audited` |
| No form and no POST without a local password; demo accounts keep theirs | `test_an_account_without_a_password_gets_no_form_and_cannot_post_one`, `test_the_demo_accounts_keep_their_password` |

**Found by the audit.** `exempt-session-refresh-lost` first stayed green: the test client followed
the redirect to `/admin/account` and got a 200 there. The test now refuses redirects and reads the TTL.

## Bug bounty (v2.1.0)

Mutations: `docs-tech/mutations/v2.1.0-bug-bounty.json` (app),
`v2.1.0-attachments.json` (uploads). The deployment and CI guards were each
broken by hand and watched fail; their tests run the real step, filter or
config (jq, bash, `docker compose config`, `helm template`, `nginx -t`).

### App

| Guard | Test that fires |
| --- | --- |
| The image's own CMD writes no request line | `test_the_image_command_writes_no_request_line` |
| A TOTP code is six ASCII digits and authenticates one action, enrolment included | `test_a_fullwidth_copy_of_a_used_code_opens_no_second_session`, `test_the_enrolment_code_cannot_sign_in_a_second_session` |
| The wizard stores only a secret shaped as it issues | `test_the_wizard_refuses_a_secret_it_did_not_issue` |
| A non-ASCII CSRF token is a 403; the page token is the cookie the check reads | `test_a_non_ascii_csrf_token_is_a_403_not_a_500`, `test_the_page_token_matches_the_cookie_the_server_checks` |
| Changing another account: organisation, superadmin tier, demo accounts | `test_an_admin_cannot_reactivate_a_superadmin_another_superadmin_disabled`, `test_a_demo_visitor_cannot_lock_the_next_visitor_out` |
| A confirmed deletion leaves one entry with case number, requester, confirmer | `test_a_confirmed_deletion_is_in_the_audit_log` |
| Four eyes: not an account and one it made | `test_an_account_and_the_account_it_made_are_not_four_eyes`, `test_migration_012_finds_the_maker_in_the_audit_log` |
| LDAP on: local accounts still sign in; a name clash is a 401; the directory's name only | `test_a_local_account_signs_in_while_ldap_is_on`, `test_a_directory_user_named_like_a_local_account_is_refused_not_a_500`, `test_a_directory_entry_without_the_username_attribute_is_refused` |
| One lockout per case-folded username, from the last failure | `test_case_variants_of_a_username_share_one_lockout`, `test_the_lock_lasts_lockout_minutes_from_the_last_failure` |
| A refresh racing a revocation leaves no session | `test_a_refresh_racing_a_revocation_leaves_no_session` |
| Unlink: a directory name counts only with LDAP on | `test_a_directory_name_is_no_way_in_while_ldap_is_off` |
| §17 deadlines: from receipt, calendar months, one computation | `test_every_report_has_a_feedback_deadline_from_receipt`, `test_three_months_are_calendar_months`, `test_the_pdf_calls_seven_days_and_twelve_hours_late`, `test_the_ack_rate_counts_only_reports_whose_week_is_over`, `test_the_dashboard_and_the_case_page_agree_on_the_last_day` |
| Text fields: line breaks count once; the server holds the page's limits | `test_line_breaks_count_once_as_in_the_browser`, `test_an_admin_reply_has_the_limit_its_form_shows`, `test_an_oversized_admin_field_is_refused_not_a_500` |
| A mistyped notification address stays on the form | `test_a_mistyped_notification_address_is_caught_on_the_form` |
| A closed case takes no reply | `test_a_closed_case_takes_no_reply_and_says_so` |
| Case number in any case | `test_a_case_number_typed_in_lower_case_opens_the_case` |
| Retention ends the status sessions of what it deletes | `test_retention_ends_the_status_sessions_of_what_it_deletes` |
| The digest counts cases and says so | `test_the_digest_says_cases_where_it_counts_cases` |
| Every account has an organisation; a superadmin chooses it | `test_an_account_made_before_multi_tenancy_keeps_its_cases`, `test_a_superadmin_gives_another_organisation_its_admin`, `test_an_ldap_account_gets_the_default_organisation` |
| The scheduler runs in UTC whatever `TZ` says | `test_the_scheduler_keeps_utc_whatever_tz_says` |
| The audit export: the page's filters, every row, itself recorded; downloads recorded | `test_the_export_holds_what_the_filtered_page_shows_and_all_of_it`, `test_exporting_the_log_and_downloading_evidence_are_recorded` |
| A search is recorded in every organisation it read | `test_a_search_across_organisations_is_in_each_one_s_log` |
| Unassigning is written as unassigning | `test_unassigning_is_recorded_as_unassigning` |
| The username fields accept what the server accepts | `test_the_username_field_accepts_what_the_server_accepts` |
| No published page calls Fernet AES-256 | `test_no_published_page_calls_fernet_aes_256` |

All in `tests/test_v210_bug_bounty.py`, except the refresh race
(`test_coverage_auth_extended.py`) and unlink (`test_v210_auth_recovery.py`).

### Uploads

| Guard | Test that fires |
| --- | --- |
| Palette survives cleaning (PNG and TIFF) | `test_palette_png_keeps_its_colours_and_transparency`, `test_palette_tiff_inside_office_files_keeps_its_colours` |
| Every animation frame survives | `test_animated_png_and_webp_keep_every_frame` |
| JPEG/PNG/WebP pixels never decoded; JPEG never grows | `test_pixels_are_not_decoded`, `test_jpeg_pixels_are_untouched_and_the_file_does_not_grow` |
| Only orientation left of EXIF | `test_only_the_orientation_is_left_of_the_exif` |
| WebP ICC/XMP dropped, flags cleared; truncated PNG refused | `test_webp_icc_profile_and_xmp_are_removed`, `test_webp_without_orientation_clears_the_exif_flag`, `test_a_truncated_png_is_refused` |
| Nothing after a JPEG's end-of-image; no JFIF APP0 | `test_jpeg_trailer_after_the_image_is_dropped`, `test_jfif_segment_and_its_thumbnail_are_dropped` |
| MPO accepted; GIF/TIFF pixel cap; cleaning off the event loop | `test_mpo_photo_is_accepted_as_its_first_picture`, `test_gif_over_the_pixel_cap_is_refused`, `test_cleaning_runs_off_the_event_loop` |
| The size limit holds after cleaning | `test_a_file_that_grows_past_the_limit_when_cleaned_is_refused` |
| XMP removed from every PDF object; embedded files refused | `test_pdf_page_xmp_is_removed`, `test_pdf_with_an_embedded_file_is_refused` |
| Office: absPath, fileSharing, profile paths, SharePoint, rsids, docVars | `test_office_paths_sharepoint_columns_and_session_ids_are_removed` |

In `tests/test_v210_attachment_fidelity.py`.

### Deployment and CI

| Guard | Test that fires |
| --- | --- |
| Quay cleanup never deletes a digest a kept tag uses | `test_a_digest_shared_with_a_release_tag_is_never_deleted` |
| An uninspectable tag fails the publish | `test_an_uninspectable_tag_fails_the_step` |
| Floating tags go only to the highest stable release | `test_floating_tags_move_only_to_the_highest_stable_release` |
| Publish needs CI, E2E, security and a tag on main | `test_publishing_waits_for_every_check_on_the_same_commit`, `test_a_tag_off_main_is_refused` |
| No example key passes the length check | `test_no_example_key_passes_the_length_check` |
| Restated defaults equal `config.py` | `test_restated_defaults_match_config_py` |
| The certificate before the stack; certbot stops the stack | `tests/test_ansible_certbot.py` |
| Ansible `.env` values pass through Compose unchanged | `test_compose_passes_every_value_through_unchanged` |
| Helm rolls pods on a changed value; no replicas with the HPA; ingress body size | `tests/test_helm_chart.py` |
| Every digest-pinned workflow image is reached by Renovate | `test_every_digest_pinned_image_in_a_workflow_is_managed` |
| Every proxied location, snippets included, is rate-limited | `test_every_public_route_is_rate_limited_in_both_deployments` |
| The TLS key is 0600 from its first byte | `test_the_key_is_never_written_readable_by_others` |

## Repository and release

| Guard | Test |
| --- | --- |
| `docs-tech/` is never published | `test_the_technical_docs_are_not_published` |
| Every published version string equals `app_version`, every image default in the prod compose file too | `test_every_published_version_string_matches` |
| A setting added since the previous release has a CHANGELOG entry | `test_every_new_setting_is_in_the_changelog` |
| Every setting has a docs env-table row and a `docker-compose.prod.yml` line (except `APP_VERSION` and `LOCAL_REVIEW_LOGIN`) | `tests/test_config_documented.py` |
| uv pinned identically in the image and all workflows | `test_uv_version_is_the_same_in_the_image_and_every_workflow` |
| `uv.lock` matches `pyproject.toml` | CI step `uv lock --check` |
| Every tag and platform manifest pullable after publish | the publish workflow's verify loop |
| No serious/critical axe violation, console error or sideways scroll — every page, both themes, 390 and 1440 px | `tests/e2e/test_ui_check.py` |
| Whistleblower flow without JavaScript | `tests/e2e/test_no_js.py` |
