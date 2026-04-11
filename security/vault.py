from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from core.config import get_settings

logger = logging.getLogger(__name__)


class Vault:
    """Encrypted credential storage using Fernet (AES-128-CBC)."""

    def __init__(self, vault_path: Optional[Path] = None, key_path: Optional[Path] = None):
        settings = get_settings()
        self._vault_path = vault_path or (settings.project_root / "vault" / "secrets.enc")
        self._key_path = key_path or settings.vault_key_path
        self._fernet: Optional[Fernet] = None
        self._secrets: Dict[str, str] = {}

    def _derive_key(self, password: bytes, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password))

    def initialize(self, master_password: str) -> None:
        """Initialize vault with a master password."""
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)

        salt = os.urandom(16)
        key = self._derive_key(master_password.encode(), salt)

        # Atomic write with mode 0600 — no race window
        _write_secure(self._key_path, salt)

        self._fernet = Fernet(key)
        self._secrets = {}
        self._save()
        logger.info("Vault initialized at %s", self._vault_path)

    def unlock(self, master_password: str) -> bool:
        """Unlock vault with master password. Returns True if successful."""
        try:
            if not self._key_path.exists():
                return False

            salt = self._key_path.read_bytes()
            key = self._derive_key(master_password.encode(), salt)
            self._fernet = Fernet(key)

            if self._vault_path.exists():
                encrypted = self._vault_path.read_bytes()
                decrypted = self._fernet.decrypt(encrypted)
                self._secrets = json.loads(decrypted)
            else:
                self._secrets = {}

            logger.info("Vault unlocked")
            return True
        except (ValueError, InvalidToken, OSError) as e:
            logger.error("Failed to unlock vault: %s", e)
            self._fernet = None
            return False

    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def get(self, name: str) -> Optional[str]:
        if not self.is_unlocked():
            raise RuntimeError("Vault is locked")
        return self._secrets.get(name)

    def set(self, name: str, value: str) -> None:
        if not self.is_unlocked():
            raise RuntimeError("Vault is locked")
        self._secrets[name] = value
        self._save()
        logger.info("Vault: stored secret '%s'", name)

    def delete(self, name: str) -> bool:
        if not self.is_unlocked():
            raise RuntimeError("Vault is locked")
        if name in self._secrets:
            del self._secrets[name]
            self._save()
            return True
        return False

    def list_keys(self) -> list[str]:
        if not self.is_unlocked():
            raise RuntimeError("Vault is locked")
        return list(self._secrets.keys())

    def _save(self) -> None:
        assert self._fernet is not None
        data = json.dumps(self._secrets).encode()
        encrypted = self._fernet.encrypt(data)
        _write_secure(self._vault_path, encrypted)


def _write_secure(path: Path, data: bytes) -> None:
    """Atomically write bytes to path with mode 0600.

    Uses os.open with O_CREAT|O_WRONLY|O_TRUNC and mode=0o600 so the file
    is created with secure permissions BEFORE any data is written.
    No race window between create and chmod.
    """
    # Apply umask 0 temporarily so mode bits are honored exactly
    old_umask = os.umask(0)
    try:
        fd = os.open(
            str(path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
    finally:
        os.umask(old_umask)

    try:
        os.write(fd, data)
    finally:
        os.close(fd)

    # Ensure existing files also get correct mode (in case file pre-existed)
    os.chmod(str(path), 0o600)
