"""Canonical Ed25519 envelopes; trust stays in workspace-local pipeline storage."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected finite JSON-serializable data") from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _storage(workspace: Path) -> Path:
    root = Path(workspace).resolve() / ".codex" / "arena"
    for component in (root.parent, root, root / "keys"):
        if component.is_symlink():
            raise ValueError("Signing storage must not be a symlink")
    return root


def write_json(path: Path, value: object) -> None:
    """Atomic JSON writes, avoiding readers seeing a partial signed record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + os.urandom(6).hex())
    temporary.write_bytes(canonical(value) + b"\n")
    os.replace(temporary, path)


@contextmanager
def pipeline_lock(workspace: Path, name: str = "pipeline", timeout: float = 60):
    """Cross-process lock used for a complete registry/evidence transaction."""
    path = _storage(workspace) / (name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Pipeline lock must not be a symlink")
    stream = path.open("a+b")
    stream.seek(0, 2)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out acquiring pipeline transaction lock") from None
                time.sleep(.02)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def _trust(workspace: Path) -> dict:
    path = _storage(workspace) / "trust.json"
    if not path.exists():
        return {"schema_version": 1, "active": None, "keys": {}}
    if path.is_symlink():
        raise ValueError("Trust store must not be a symlink")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema_version"] != 1 or not isinstance(document["keys"], dict):
            raise ValueError("Malformed trust store")
        return document
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed trust store") from exc


def rotate_key(workspace: Path, revoke_previous: bool = False) -> str:
    root = _storage(workspace)
    trust = _trust(workspace)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(public).hexdigest()
    root.joinpath("keys").mkdir(parents=True, exist_ok=True)
    key_path = root / "keys" / (key_id + ".pem")
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass  # Windows ACL inheritance is managed by the workspace owner.
    if revoke_previous and trust["active"]:
        trust["keys"][trust["active"]]["revoked"] = True
    trust["keys"][key_id] = {"public_key": base64.b64encode(public).decode("ascii"), "revoked": False}
    trust["active"] = key_id
    write_json(root / "trust.json", trust)
    return key_id


def ensure_local_key(workspace: Path) -> str:
    trust = _trust(workspace)
    active = trust.get("active")
    if active and active in trust["keys"] and not trust["keys"][active].get("revoked"):
        return active
    return rotate_key(workspace)


def revoke_key(workspace: Path, key_id: str) -> None:
    trust = _trust(workspace)
    if key_id not in trust["keys"]:
        raise ValueError("Unknown signing key")
    trust["keys"][key_id]["revoked"] = True
    if trust["active"] == key_id:
        trust["active"] = None
    write_json(_storage(workspace) / "trust.json", trust)


def sign_payload(workspace: Path, payload: dict, purpose: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(purpose, str) or not purpose:
        raise ValueError("Signature requires a payload mapping and purpose")
    key_id = ensure_local_key(workspace)
    path = _storage(workspace) / "keys" / (key_id + ".pem")
    if path.is_symlink():
        raise ValueError("Private key must not be a symlink")
    try:
        private = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot load local signing key") from exc
    bound = {"schema_version": 1, "purpose": purpose, "key_id": key_id, "payload": json.loads(canonical(payload))}
    bound["signature"] = base64.b64encode(private.sign(canonical(bound))).decode("ascii")
    return bound


def verify_payload(workspace: Path, envelope: dict, purpose: str) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "purpose", "key_id", "payload", "signature"}:
        raise ValueError("Malformed signed envelope")
    if envelope["schema_version"] != 1 or envelope["purpose"] != purpose or not isinstance(envelope["payload"], dict) or not isinstance(envelope["key_id"], str) or not isinstance(envelope["signature"], str):
        raise ValueError("Signature purpose/schema mismatch")
    record = _trust(workspace)["keys"].get(envelope["key_id"])
    if not record or record.get("revoked"):
        raise ValueError("Untrusted or revoked signing key")
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(record["public_key"], validate=True))
        signature = base64.b64decode(envelope["signature"], validate=True)
        public.verify(signature, canonical({key: value for key, value in envelope.items() if key != "signature"}))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Invalid signature") from exc
    return json.loads(canonical(envelope["payload"]))
