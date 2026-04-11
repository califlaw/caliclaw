from __future__ import annotations

import pytest
from pathlib import Path

from security.vault import Vault


@pytest.fixture
def vault(tmp_path):
    v = Vault(
        vault_path=tmp_path / "vault" / "secrets.enc",
        key_path=tmp_path / "vault" / "vault.key",
    )
    return v


def test_initialize_and_unlock(vault):
    vault.initialize("test-password-123")
    assert vault.is_unlocked()

    # Create new vault instance and unlock
    vault2 = Vault(vault_path=vault._vault_path, key_path=vault._key_path)
    assert not vault2.is_unlocked()
    assert vault2.unlock("test-password-123")
    assert vault2.is_unlocked()


def test_wrong_password(vault):
    vault.initialize("correct-password")

    vault2 = Vault(vault_path=vault._vault_path, key_path=vault._key_path)
    assert not vault2.unlock("wrong-password")
    assert not vault2.is_unlocked()


def test_set_and_get_secret(vault):
    vault.initialize("pwd123")
    vault.set("api_key", "sk-12345")
    vault.set("db_pass", "supersecret")

    assert vault.get("api_key") == "sk-12345"
    assert vault.get("db_pass") == "supersecret"
    assert vault.get("nonexistent") is None


def test_persistence(vault):
    vault.initialize("persist-test")
    vault.set("key1", "value1")

    # Reopen
    vault2 = Vault(vault_path=vault._vault_path, key_path=vault._key_path)
    vault2.unlock("persist-test")
    assert vault2.get("key1") == "value1"


def test_delete_secret(vault):
    vault.initialize("del-test")
    vault.set("to_delete", "value")
    assert vault.delete("to_delete")
    assert vault.get("to_delete") is None
    assert not vault.delete("nonexistent")


def test_list_keys(vault):
    vault.initialize("list-test")
    vault.set("a", "1")
    vault.set("b", "2")
    vault.set("c", "3")

    keys = vault.list_keys()
    assert set(keys) == {"a", "b", "c"}


def test_locked_vault_raises(vault):
    with pytest.raises(RuntimeError, match="locked"):
        vault.get("anything")

    with pytest.raises(RuntimeError, match="locked"):
        vault.set("key", "value")


def test_files_have_secure_permissions(vault):
    """Vault files must be created with mode 0600 atomically (no race window)."""
    import stat
    vault.initialize("master-pwd")
    vault.set("api_key", "secret-value")

    key_mode = stat.S_IMODE(vault._key_path.stat().st_mode)
    vault_mode = stat.S_IMODE(vault._vault_path.stat().st_mode)

    assert key_mode == 0o600, f"key file has mode {oct(key_mode)}, expected 0o600"
    assert vault_mode == 0o600, f"vault file has mode {oct(vault_mode)}, expected 0o600"


def test_overwrite_preserves_secure_mode(vault):
    """Multiple writes (set/delete) must keep secure mode on every write."""
    import stat
    vault.initialize("master-pwd")
    for i in range(5):
        vault.set(f"key_{i}", f"value_{i}")
        mode = stat.S_IMODE(vault._vault_path.stat().st_mode)
        assert mode == 0o600, f"After write {i}: mode {oct(mode)}"
