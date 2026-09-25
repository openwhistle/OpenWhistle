"""Give nginx a certificate: the operator's from nginx/certs, else a self-signed one.

    python scripts/ensure_tls_cert.py <operator-cert-dir> <nginx-cert-dir> <hostname>

Runs as the one-shot `tls-init` service before nginx starts. Imports no app
settings, so it needs no SECRET_KEY.
"""

from __future__ import annotations

import datetime
import shutil
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
        .subject_name(name).issuer_name(name).public_key(key.public_key())
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


def ensure(src: Path, dst: Path, hostname: str) -> str:
    dst.mkdir(parents=True, exist_ok=True)
    if (src / _CERT).is_file() and (src / _KEY).is_file():
        shutil.copyfile(src / _CERT, dst / _CERT)
        shutil.copyfile(src / _KEY, dst / _KEY)
        (dst / _KEY).chmod(0o600)  # copyfile keeps the umask mode, not the source's
        return "provided"
    if (dst / _CERT).is_file() and (dst / _KEY).is_file():
        return "kept"
    cert, key = _self_signed(hostname)
    (dst / _KEY).write_bytes(key)
    (dst / _KEY).chmod(0o600)
    (dst / _CERT).write_bytes(cert)
    return "self-signed"


if __name__ == "__main__":
    host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    result = ensure(Path(sys.argv[1]), Path(sys.argv[2]), host)
    print(f"TLS certificate: {result}")
