"""Tests for service-layer functions."""


from app.services.auth import hash_password, hash_pin, verify_password, verify_pin
from app.services.mfa import generate_totp_secret, get_totp, verify_totp
from app.services.pin import generate_pin


def test_password_hash_and_verify() -> None:
    password = "correct-horse-battery-staple-99"  # noqa: S105
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_pin_hash_and_verify() -> None:
    pin = generate_pin()
    assert len(pin) == 36  # UUID4 length
    hashed = hash_pin(pin)
    assert verify_pin(pin, hashed)
    assert not verify_pin("wrong-pin", hashed)


def test_generate_pin_is_unique() -> None:
    pins = {generate_pin() for _ in range(100)}
    assert len(pins) == 100


def test_totp_secret_generation() -> None:
    secret = generate_totp_secret()
    assert len(secret) == 32


def test_totp_verify_valid_code() -> None:
    secret = generate_totp_secret()
    totp = get_totp(secret)
    current_code = totp.now()
    assert verify_totp(secret, current_code)


def test_totp_verify_invalid_code() -> None:
    secret = generate_totp_secret()
    assert not verify_totp(secret, "000000")
