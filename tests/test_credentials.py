import keyring
import pytest

from openavatar.providers import ProviderError, delete_provider_key, load_provider_key, store_provider_key


def test_provider_credentials_can_be_saved_loaded_and_deleted():
    provider = 'model_connection:test-only'
    assert load_provider_key(provider) == ''
    store_provider_key(provider, 'test-only-placeholder')
    assert load_provider_key(provider) == 'test-only-placeholder'
    delete_provider_key(provider)
    assert load_provider_key(provider) == ''
    delete_provider_key(provider)


def test_credential_backend_errors_are_not_silenced(monkeypatch):
    def unavailable(*args):
        raise keyring.errors.NoKeyringError('No test backend')

    monkeypatch.setattr(keyring, 'get_password', unavailable)
    monkeypatch.setattr(keyring, 'set_password', unavailable)
    with pytest.raises(ProviderError, match='无法写入'):
        store_provider_key('test-only', 'test-only-placeholder')
    with pytest.raises(ProviderError, match='无法从系统安全凭据库删除'):
        delete_provider_key('test-only')
