from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(slots=True)
class MeshIdentity:
    node_id: str
    name: str
    cert_path: Path
    key_path: Path
    fingerprint: str


def _fingerprint(cert_path: Path) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex()


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return str(sock.getsockname()[0])
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        sock.close()


def ensure_identity(root: str | Path, name: str | None = None) -> MeshIdentity:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    cert_path = root / "mesh-cert.pem"
    key_path = root / "mesh-key.pem"
    meta_path = root / "identity.json"

    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    node_id = str(meta.get("node_id") or uuid.uuid4())
    node_name = str(name or meta.get("name") or socket.gethostname() or "Astra")

    if not cert_path.exists() or not key_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"Astra Mesh {node_name}"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Astra-PC"),
        ])
        sans = [
            x509.DNSName("localhost"),
            x509.DNSName(socket.gethostname()),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
        try:
            ip = local_ip()
            if ip != "127.0.0.1":
                sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except Exception:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        try:
            key_path.chmod(0o600)
        except Exception:
            pass

    meta_path.write_text(
        json.dumps({"node_id": node_id, "name": node_name}, indent=2),
        encoding="utf-8",
    )
    return MeshIdentity(
        node_id=node_id,
        name=node_name,
        cert_path=cert_path,
        key_path=key_path,
        fingerprint=_fingerprint(cert_path),
    )
