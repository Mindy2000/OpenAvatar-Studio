from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from openavatar.local_model import LocalModelError, local_urlopen
from openavatar.providers import ProviderError, OpenAICompatibleClient
from openavatar.schemas import ProviderConnectionPayload
from openavatar.services.provider_hub import _validate_connection, assert_allowed, discover_models


@pytest.mark.parametrize('url', [
    'https://remote.invalid/v1', 'http://localhost.attacker.invalid/v1',
    'http://127.0.0.1.attacker.invalid/v1', 'http://127.0.0.10/v1',
    'http://localhost@remote.invalid/v1', 'http://remote.invalid@localhost/v1',
    'http://[::1', 'http://localhost:bad/v1', 'http://localhost:99999/v1',
    'http://local\nhost/v1', 'file:///tmp/model',
])
def test_reject_remote_or_malformed_local_connection(url):
    with pytest.raises(ProviderError):
        _validate_connection(ProviderConnectionPayload(display_name='test', provider_kind='local', base_url=url))


@pytest.mark.parametrize('url', ['http://127.0.0.1:1234/v1', 'https://localhost:8443/v1', 'http://[::1]:1234/v1'])
def test_accept_loopback(url):
    assert _validate_connection(ProviderConnectionPayload(display_name='test', provider_kind='local', base_url=url)) == url


def test_previously_saved_remote_local_connection_is_blocked(monkeypatch):
    row = {'id': 'old', 'provider_kind': 'local', 'base_url': 'https://remote.invalid/v1', 'enabled': 1}
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: pytest.fail('Must not contact remote'))
    monkeypatch.setattr('openavatar.services.provider_hub.load_provider_key', lambda *a: pytest.fail('Must validate before loading key'))
    with pytest.raises(ProviderError):
        discover_models(row)
    with pytest.raises(ProviderError):
        assert_allowed(None, row, 'chat')


def test_local_http_ignores_proxy_and_blocks_redirects(monkeypatch):
    visits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            visits.append(self.path)
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/should-not-follow')
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy', '')
    monkeypatch.setenv('NO_PROXY', '')
    monkeypatch.setattr('openavatar.services.provider_hub.load_provider_key', lambda *a: '')
    try:
        assert discover_models({'id': 'test', 'provider_kind': 'local', 'base_url': base}) == []
        assert OpenAICompatibleClient(base, 'model', api_key_required=False).probe()
        with pytest.raises(LocalModelError):
            local_urlopen(base + '/redirect', timeout=2)
        assert '/should-not-follow' not in visits
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
