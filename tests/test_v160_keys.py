"""v1.6.0: encryption has its own key, and old keys can be rotated out."""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from app.config import settings

_A = "a" * 40
_B = "b" * 40


def test_encryption_does_not_depend_on_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import crypto

    monkeypatch.setattr(settings, "encryption_key", _A)
    token = crypto.encrypt("identity")
    monkeypatch.setattr(settings, "secret_key", "another-jwt-signing-key-0123456789")
    assert crypto.decrypt(token) == "identity"


def test_without_encryption_key_secret_key_still_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import crypto, encryption

    monkeypatch.setattr(settings, "encryption_key", "")
    old_field = crypto.encrypt("identity")
    old_dek = encryption.encrypt_dek(b"k" * 32)
    monkeypatch.setattr(settings, "encryption_key", _A)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    assert crypto.decrypt(old_field) == "identity"
    assert encryption.decrypt_dek(old_dek) == b"k" * 32


def test_rotation_moves_data_to_the_current_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import crypto, encryption

    monkeypatch.setattr(settings, "encryption_key", _A)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    field, dek = crypto.encrypt("identity"), encryption.encrypt_dek(b"k" * 32)

    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", _A)
    field, dek = crypto.rotate(field), encryption.rotate_dek(dek)

    monkeypatch.setattr(settings, "encryption_key_previous", "")
    assert crypto.decrypt(field) == "identity"
    assert encryption.decrypt_dek(dek) == b"k" * 32


def test_a_key_that_was_dropped_no_longer_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import crypto

    monkeypatch.setattr(settings, "encryption_key", _A)
    token = crypto.encrypt("identity")
    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", "")
    with pytest.raises(InvalidToken):
        crypto.decrypt(token)


def test_short_encryption_key_is_refused() -> None:
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(secret_key="s" * 40, encryption_key="short")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_rotation_script_rewraps_report_keys(
    db_session, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    import importlib.util
    import json
    import uuid

    from sqlalchemy import text

    from app.models.audit import AuditLog
    from app.services import crypto
    from app.services.encryption import decrypt_dek
    from app.services.report import create_report

    spec = importlib.util.spec_from_file_location("rot", "scripts/rotate_encryption_key.py")
    assert spec and spec.loader
    rot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rot)

    report, _ = await create_report(db_session, "corruption", "Rotation script test report.")
    # A plaintext "reason" (the retention job writes one) must not be touched,
    # nor abort the run; an identity reveal's encrypted reason must be rotated.
    retention = AuditLog(
        id=uuid.uuid4(), admin_username="system", action="report.auto_deleted",
        detail=json.dumps({"reason": "retention period exceeded"}),
    )
    reveal = AuditLog(
        id=uuid.uuid4(), admin_username="system", action="report.identity_revealed",
        report_id=report.id, detail=json.dumps({"reason": crypto.encrypt("needed for case")}),
    )
    db_session.add_all([retention, reveal])
    await db_session.commit()

    # The script rewrites every row of the shared test DB: rotate to _B, check,
    # then rotate back to the default key so later tests read their rows.
    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    try:
        assert await rot.main() == 0
        monkeypatch.setattr(settings, "encryption_key_previous", "")
        dek = await db_session.scalar(
            text("SELECT encrypted_dek FROM reports WHERE id = :i"), {"i": report.id}
        )
        assert len(decrypt_dek(dek)) == 32
        details = dict((await db_session.execute(
            text("SELECT id, detail FROM audit_log WHERE id IN (:a, :b)"),
            {"a": retention.id, "b": reveal.id},
        )).tuples().all())
        assert json.loads(details[retention.id])["reason"] == "retention period exceeded"
        assert crypto.decrypt(json.loads(details[reveal.id])["reason"]) == "needed for case"
    finally:
        monkeypatch.setattr(settings, "encryption_key", "")
        monkeypatch.setattr(settings, "encryption_key_previous", _B)
        assert await rot.main() == 0
