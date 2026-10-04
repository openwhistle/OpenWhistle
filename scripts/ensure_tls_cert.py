"""Give nginx a certificate: the operator's from nginx/certs, else a self-signed one.

    python scripts/ensure_tls_cert.py <operator-cert-dir> <nginx-cert-dir> <hostname>

Runs as the one-shot `tls-init` service before nginx starts. Imports no app
settings, so it needs no SECRET_KEY.
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_CERT, _KEY = "fullchain.pem", "privkey.pem"


def _self_signed(hostname: str) -> tuple[bytes, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname), x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


def _operator_pair(src: Path) -> tuple[bytes, bytes] | None:
    """The operator's certificate and key, or None when neither is there.

    Anything half-there fails loudly instead of falling back to self-signed:
    a symlink (certbot's /etc/letsencrypt/live) dangles inside the container,
    and a key only its non-root host owner may read is unreadable here."""
    paths = (src / _CERT, src / _KEY)
    if not any(p.is_symlink() or p.exists() for p in paths):
        return None
    try:
        return paths[0].read_bytes(), paths[1].read_bytes()
    except OSError as exc:
        raise SystemExit(
            f"tls-init: cannot read {exc.filename}: {exc.strerror}. Copy the certificate"
            f" and key into nginx/certs/ (mounted at {src}); do not symlink them. The key"
            " must be root-owned 0600, or 0644."
        ) from exc


def _write_key(path: Path, data: bytes) -> None:
    """0600 from the first byte: write_bytes() then chmod() left the key at the
    umask's 0644 until the chmod."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o600)  # an existing file keeps its old mode otherwise
        f.write(data)


def _stale_self_signed(cert_pem: bytes, hostname: str) -> bool:
    """A kept certificate of our own that no longer names TLS_HOSTNAME."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except ValueError, x509.ExtensionNotFound:
        return False  # not ours to judge: keep it
    return cert.issuer == cert.subject and hostname not in san.get_values_for_type(x509.DNSName)


def ensure(src: Path, dst: Path, hostname: str) -> str:
    dst.mkdir(parents=True, exist_ok=True)
    pair = _operator_pair(src)
    if pair:
        (dst / _CERT).write_bytes(pair[0])
        _write_key(dst / _KEY, pair[1])
        return "provided"
    if (dst / _CERT).is_file() and (dst / _KEY).is_file():
        if not _stale_self_signed((dst / _CERT).read_bytes(), hostname):
            return "kept"
    cert, key = _self_signed(hostname)
    _write_key(dst / _KEY, key)
    (dst / _CERT).write_bytes(cert)
    return "self-signed"


if __name__ == "__main__":
    host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    result = ensure(Path(sys.argv[1]), Path(sys.argv[2]), host)
    print(f"TLS certificate: {result}")
