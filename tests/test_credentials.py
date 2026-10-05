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


def test_repeated_and_concurrent_reads_reuse_process_credentials(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time

    reads = []

    def read(service, account):
        reads.append(account)
        time.sleep(0.01)
        return 'test-only-placeholder'

    monkeypatch.setattr(keyring, 'get_password', read)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(load_provider_key, ['cached-test'] * 4)) == ['test-only-placeholder'] * 4
    assert len(reads) == 1
    store_provider_key('cached-test', 'updated-placeholder')
    assert load_provider_key('cached-test') == 'updated-placeholder'
    delete_provider_key('cached-test')
    load_provider_key('cached-test')
    assert len(reads) == 2
