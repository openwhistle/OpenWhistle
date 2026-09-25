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
    # Scoped to the two rows this test created: main() touches the whole shared
    # test DB, but this assertion must not depend on what other tests left behind.
    own_rows = text("SELECT id, encrypted_dek FROM reports WHERE id IN (:good, :bad)")
    own_ids = {"good": good.id, "bad": bad.id}
    before = dict((await db_session.execute(own_rows, own_ids)).tuples().all())

    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)
    try:
        assert await _rotation_script().main() == 1
        out = capsys.readouterr().out
        assert f"reports.encrypted_dek id={bad.id}" in out
        assert str(good.id) not in out
        after = dict((await db_session.execute(own_rows, own_ids)).tuples().all())
        assert after == before
    finally:
        # Full cleanup: an un-deleted `good` row would persist under the default
        # key forever, which is harmless by itself but the invariant this whole
        # file depends on is that no row is left behind under a non-default key.
        await db_session.execute(
            text("DELETE FROM reports WHERE id IN (:good, :bad)"), {"good": good.id, "bad": bad.id}
        )
        await db_session.commit()


@pytest.fixture
async def _clean_stray_rotation_state(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """This file's tests rotate the *entire* shared reports/admin_users/audit_log
    tables (main() has no notion of "this test's rows"). A previous run that
    died between the forward and backward rotation below would leave rows
    stuck under _A/_B/"c"*40 forever, and every later test touching those
    tables — anywhere in the suite — would then fail to decrypt them. Restore
    everything to the default key first, so this test's own round trip can't
    be sabotaged by state it did not create, and so a prior failure heals
    instead of compounding.
    """
    monkeypatch.setattr(settings, "encryption_key", settings.secret_key)
    monkeypatch.setattr(settings, "encryption_key_previous", f"{_A},{_B},{'c' * 40}")
    await _rotation_script().main()


@pytest.mark.asyncio
async def test_rotation_script_moves_every_value_to_the_new_key(
    db_session, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    _clean_stray_rotation_state,  # type: ignore[no-untyped-def]
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
        # Full cleanup: main() operates on the whole shared test DB, so a row
        # left behind here under a non-default key would break the next run
        # of any rotation test that happens to touch it.
        monkeypatch.setattr(settings, "encryption_key", settings.secret_key)
        monkeypatch.setattr(settings, "encryption_key_previous", _B)
        assert await rot.main() == 0
        await db_session.execute(text("DELETE FROM admin_users WHERE id = :i"), {"i": admin.id})
        await db_session.execute(
            text("DELETE FROM audit_log WHERE id IN (:retention, :reveal)"),
            {"retention": retention.id, "reveal": reveal.id},
        )
        await db_session.execute(text("DELETE FROM reports WHERE id = :i"), {"i": report.id})
        await db_session.commit()


@pytest.mark.asyncio
async def test_rotation_script_flags_a_row_changed_during_the_run(
    db_session, monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A row rewritten between the script's read and its guarded write (e.g. a
    concurrent TOTP re-enrolment) is skipped, not failed — but the operator
    must be told to re-run before it is safe to empty ENCRYPTION_KEY_PREVIOUS.

    Simulated with a proxy around only the single engine main() creates for
    itself (never a shared SQLAlchemy class or instance): the proxy's begin()
    performs the "concurrent" write before handing back a connection that
    sees it, reproducing the gap between the script's read and its guarded
    write without touching any connection used by the rest of the test suite.
    """
    import contextlib

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine as real_create_async_engine

    from app.services import crypto
    from app.services.report import create_report

    report, _ = await create_report(db_session, "corruption", "Lost update simulation.")
    await db_session.execute(
        text("UPDATE reports SET confidential_name = :v WHERE id = :i"),
        {"v": crypto.encrypt("Old Name"), "i": report.id},
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "encryption_key", _B)
    monkeypatch.setattr(settings, "encryption_key_previous", settings.secret_key)

    triggered = [False]

    def patched_create_async_engine(*args, **kwargs):  # type: ignore[no-untyped-def]
        # AsyncEngine has no writable `begin` attribute, so wrap it in a plain
        # proxy instead of patching the instance or the class. This one real
        # engine is private to this call: main() creates it, uses it through
        # the proxy, and disposes it; nothing else ever touches it.
        real_engine = real_create_async_engine(*args, **kwargs)

        class _EngineProxy:
            def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
                return getattr(real_engine, name)

            def begin(self):  # type: ignore[no-untyped-def]
                @contextlib.asynccontextmanager
                async def _begin():  # type: ignore[no-untyped-def]
                    async with real_engine.begin() as conn:
                        if not triggered[0]:
                            triggered[0] = True
                            await conn.execute(
                                text("UPDATE reports SET confidential_name = :v WHERE id = :i"),
                                {"v": crypto.encrypt("Rewritten meanwhile"), "i": report.id},
                            )
                        yield conn

                return _begin()

        return _EngineProxy()

    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", patched_create_async_engine
    )
    try:
        assert await _rotation_script().main() == 0
        assert "Re-run before emptying ENCRYPTION_KEY_PREVIOUS." in capsys.readouterr().out
    finally:
        # main() just rotated the *entire* shared reports/admin_users/audit_log
        # tables to _B, not just this test's own row — rotate everything back
        # to the default key before cleaning up, or every other row in the
        # suite is left permanently unreadable under the real ENCRYPTION_KEY.
        monkeypatch.setattr(settings, "encryption_key", settings.secret_key)
        monkeypatch.setattr(settings, "encryption_key_previous", _B)
        assert await _rotation_script().main() == 0
        await db_session.execute(text("DELETE FROM reports WHERE id = :i"), {"i": report.id})
        await db_session.commit()
