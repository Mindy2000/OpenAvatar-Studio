"""Keep module-level application initialization away from users' runtime data."""
import os
import tempfile


_session_data = tempfile.TemporaryDirectory(prefix="openavatar-pytest-")
os.environ["OPENAVATAR_DATA_DIR"] = _session_data.name


import keyring
import pytest


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    """Exercise credential operations without reading or changing the OS keyring."""
    credentials = {}
    for name in ('OPENAVATAR_API_KEY', 'OPENAVATAR_ALIYUN_API_KEY', 'OPENAVATAR_KIMI_API_KEY', 'NORTH_API_KEY'):
        monkeypatch.delenv(name, raising=False)

    def get_password(service, account):
        return credentials.get((service, account))

    def set_password(service, account, value):
        credentials[service, account] = value

    def delete_password(service, account):
        if (service, account) not in credentials:
            raise keyring.errors.PasswordDeleteError('Credential not found')
        del credentials[service, account]

    monkeypatch.setattr(keyring, 'get_password', get_password)
    monkeypatch.setattr(keyring, 'set_password', set_password)
    monkeypatch.setattr(keyring, 'delete_password', delete_password)
