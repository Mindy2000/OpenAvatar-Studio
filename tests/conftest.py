"""Keep module-level application initialization away from users' runtime data."""
import os
import ipaddress
import socket
import tempfile


_session_data = tempfile.TemporaryDirectory(prefix="openavatar-pytest-")
os.environ["OPENAVATAR_DATA_DIR"] = _session_data.name


import keyring
import pytest


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Regression tests may use loopback servers, never a paid provider."""
    def allowed(sock, address):
        if sock.family == socket.AF_UNIX:
            return
        host = str(address[0])
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise AssertionError(f"External network is disabled in tests: {host}")

    for method in ("connect", "connect_ex", "sendto"):
        original = getattr(socket.socket, method)

        def guarded(sock, *args, _method=method, _original=original, **kwargs):
            address = args[-1] if _method == "sendto" else args[0]
            allowed(sock, address)
            return _original(sock, *args, **kwargs)

        monkeypatch.setattr(socket.socket, method, guarded)


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    """Exercise credential operations without reading or changing the OS keyring."""
    credentials = {}
    from openavatar import providers
    monkeypatch.setattr(providers, "_credential_cache", {})
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
