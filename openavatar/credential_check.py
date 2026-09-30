"""Frozen-app credential smoke check using only an isolated random test account."""
from uuid import UUID

import keyring

SERVICE = "OpenAvatar Studio CI credential check"
VALUE = "openavatar-non-secret-test-value"


def check_credential(action: str, account: str) -> int:
    # Never accept real provider account names or expose existing credentials.
    account = str(UUID(account))
    if action == "write":
        if keyring.get_password(SERVICE, account) is not None:
            raise RuntimeError("Test account already exists")
        keyring.set_password(SERVICE, account, VALUE)
    elif action == "read":
        if keyring.get_password(SERVICE, account) != VALUE:
            raise RuntimeError("Credential did not persist across processes")
    elif action == "delete":
        if keyring.get_password(SERVICE, account) is not None:
            keyring.delete_password(SERVICE, account)
    elif action == "absent":
        if keyring.get_password(SERVICE, account) is not None:
            raise RuntimeError("Credential was not deleted")
    else:
        raise ValueError("Unknown credential check action")
    return 0
