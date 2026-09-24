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



@pytest.mark.parametrize(
    "previous", ["b" * 10, "a" * 40 + "," + "b" * 10, "a" * 20 + "," + "b" * 20]
)
def test_short_previous_key_is_refused(previous: str) -> None:
    """A too-short entry, including a comma-containing key split into fragments."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(secret_key="s" * 40, encryption_key_previous=previous)  # type: ignore[call-arg]


def test_previous_keys_are_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.encryption import encryption_keys

    monkeypatch.setattr(settings, "encryption_key", _A)
    monkeypatch.setattr(settings, "encryption_key_previous", f"{_B},,{_A} ")
    assert encryption_keys() == [_A, _B, f"{_A} "]


def _rotation_script():  # type: ignore[no-untyped-def]
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "rotate_encryption_key.py"
    spec = importlib.util.spec_from_file_location("rot", path)
    assert spec and spec.loader
    rot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rot)
    return rot


@pytest.mark.asyncio
@pytest.mark.parametrize(("current", "previous"), [("", _A), (_A, "")])
async def test_rotation_script_refuses_without_both_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    current: str, previous: str,
) -> None:
    monkeypatch.setattr(settings, "encryption_key", current)
    monkeypatch.setattr(settings, "encryption_key_previous", previous)
    assert await _rotation_script().main() == 1
    assert "Nothing to rotate from" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_rotation_script_names_unreadable_rows_and_writes_nothing(
    db_session, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sqlalchemy import text

    from app.services.encryption import encrypt_dek
    from app.services.report import create_report

    good, _ = await create_report(db_session, "corruption", "Readable report.")
    bad, _ = await create_report(db_session, "corruption", "Report under a lost key.")
    monkeypatch.setattr(settings, "encryption_key", "c" * 40)
    await db_session.execute(
        text("UPDATE reports SET encrypted_dek = :v WHERE id = :i"),
        {"v": encrypt_dek(b"k" * 32), "i": bad.id},
    )
    await db_session.commit()
    before = dict((await db_session.execute(
        text("SELECT id, encrypted_dek FROM reports"))).tuples().all())

    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    try:
        assert await _rotation_script().main() == 1
        out = capsys.readouterr().out
        assert f"reports.encrypted_dek id={bad.id}" in out
        assert str(good.id) not in out
        after = dict((await db_session.execute(
            text("SELECT id, encrypted_dek FROM reports"))).tuples().all())
        assert after == before
    finally:
        await db_session.execute(text("DELETE FROM reports WHERE id = :i"), {"i": bad.id})
        await db_session.commit()


@pytest.mark.asyncio
async def test_rotation_script_moves_every_value_to_the_new_key(
    db_session, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    import json
    import uuid

    from sqlalchemy import text

    from app.models.audit import AuditLog
    from app.models.user import AdminUser
    from app.services import crypto
    from app.services.encryption import decrypt_dek
    from app.services.report import create_report

    rot = _rotation_script()
    report, _ = await create_report(db_session, "corruption", "Rotation script test report.")
    await db_session.execute(
        text("UPDATE reports SET confidential_name = :v WHERE id = :i"),
        {"v": crypto.encrypt("Jane Doe"), "i": report.id},
    )
    admin = AdminUser(
        id=uuid.uuid4(), username=f"rot-{uuid.uuid4().hex[:8]}", totp_secret="JBSWY3DPEHPK3PXP"
    )
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
    db_session.add_all([admin, retention, reveal])
    await db_session.commit()

    async def raw(sql: str, row_id: object) -> str:
        value = await db_session.scalar(text(sql), {"i": row_id})
        assert isinstance(value, str)
        return value

    # The script rewrites every row of the shared test DB: rotate to _B, check,
    # then rotate back to the default key (SECRET_KEY, set explicitly as current)
    # so later tests read their rows.
    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    try:
        assert await rot.main() == 0
        dek = await raw("SELECT encrypted_dek FROM reports WHERE id = :i", report.id)
        name = await raw("SELECT confidential_name FROM reports WHERE id = :i", report.id)
        totp = await raw("SELECT totp_secret FROM admin_users WHERE id = :i", admin.id)
        reason = json.loads(await raw("SELECT detail FROM audit_log WHERE id = :i", reveal.id))
        plain = json.loads(await raw("SELECT detail FROM audit_log WHERE id = :i", retention.id))

        monkeypatch.setattr(settings, "encryption_key_previous", "")  # new key alone
        assert len(decrypt_dek(dek)) == 32
        assert crypto.decrypt(name) == "Jane Doe"
        assert crypto.decrypt(totp) == "JBSWY3DPEHPK3PXP"
        assert crypto.decrypt(reason["reason"]) == "needed for case"
        assert plain["reason"] == "retention period exceeded"

        monkeypatch.setattr(settings, "encryption_key", settings.secret_key)  # old key alone
        for token in (name, totp, reason["reason"]):
            with pytest.raises(InvalidToken):
                crypto.decrypt(token)
        with pytest.raises(InvalidToken):
            decrypt_dek(dek)
    finally:
        monkeypatch.setattr(settings, "encryption_key", settings.secret_key)
        monkeypatch.setattr(settings, "encryption_key_previous", _B)
        assert await rot.main() == 0
        await db_session.execute(text("DELETE FROM admin_users WHERE id = :i"), {"i": admin.id})
        await db_session.commit()
