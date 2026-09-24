"""Column types shared by the models."""

from __future__ import annotations

from typing import Any

from sqlalchemy.types import Text, TypeDecorator

from app.services.crypto import decrypt, encrypt


class EncryptedText(TypeDecorator[str]):
    """Plaintext in Python, a Fernet token (app.services.crypto) in the database."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        # Fail closed: a value that does not decrypt (corruption, tampering, a
        # rotated SECRET_KEY) raises — it is never shown as an empty string.
        return None if value is None else decrypt(value)
