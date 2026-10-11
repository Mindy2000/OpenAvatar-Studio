"""First-run decisions and read-only configuration checks; no real credentials."""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openavatar.db import Database
from openavatar.routes.setup import create_setup_router
from openavatar.services import setup
from openavatar.services.provider_hub import record_provider_usage


@pytest.fixture
def local_setup(tmp_path, monkeypatch):
    db = Database(tmp_path / "setup.sqlite")
    db.initialize()
    monkeypatch.setattr(setup, "has_key", lambda _: True)

    def no_network(*args, **kwargs):
        raise AssertionError("Setup must not probe network services")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    monkeypatch.setattr("openavatar.services.provider_hub.load_provider_key", no_network)
    app = FastAPI()
    app.include_router(create_setup_router(SimpleNamespace(db=db)))
    with TestClient(app) as client:
        yield db, client


def connection(db, connection_id="pc_test", **overrides):
    data = {"id": connection_id, "display_name": "Test service", "provider_kind": "minimax",
            "base_url": "https://example.invalid/v1", "capabilities_json": json.dumps(["chat", "tts", "vision"]),
            "models_json": json.dumps({"chat": "fixture-chat", "tts": "fixture-tts", "vision": "fixture-vision"}),
            "consent_json": json.dumps({"text": True, "image": True}), "budget_json": "{}", "enabled": 1,
            "created_at": 1, "updated_at": 1, **overrides}
    columns = ",".join(data)
    db.execute(f"INSERT INTO provider_connections({columns}) VALUES({','.join('?' for _ in data)})", tuple(data.values()))
    return connection_id


def route(db, capability="chat", primary="pc_test", fallback=None, avatar_id="", model=""):
    db.execute("INSERT INTO capability_routes(scope_type,avatar_id,capability,primary_connection_id,fallback_connection_ids_json,model,updated_at) VALUES(?,?,?,?,?,?,?)",
               ("avatar" if avatar_id else "global", avatar_id, capability, primary, json.dumps(fallback or []), model, 1))


def avatar(db, avatar_id="a_test"):
    db.execute("INSERT INTO avatars(id,name,subject_kind,created_at,updated_at) VALUES(?,?,?,?,?)", (avatar_id, "测试人物 <name>", "fictional", 1, 1))
    return avatar_id


def test_new_database_auto_opens_and_skip_survives_reload(local_setup):
    db, client = local_setup
    initial = client.get('/api/setup/status').json()
    assert initial['auto_show'] is True
    assert initial['avatar'] is None
    assert initial['capabilities']['chat']['issues'] == ['route_missing']
    assert client.put('/api/setup/dismiss').json() == {'dismissed': True}
    reopened = client.get('/api/setup/status').json()
    assert reopened['dismissed'] is True and reopened['auto_show'] is False
    # A skip does not fabricate a connection, avatar or rights confirmation.
    assert not db.all('SELECT * FROM avatars')
    assert not db.all('SELECT * FROM provider_connections')


@pytest.mark.parametrize('existing', ['avatar', 'connection', 'legacy_setting', 'old_onboarding'])
def test_existing_user_is_never_forced_into_guide(local_setup, existing):
    db, client = local_setup
    if existing == 'avatar': avatar(db)
    elif existing == 'connection': connection(db)
    elif existing == 'legacy_setting': db.set_setting('model', {'model': 'old-model'})
    else: db.set_setting('onboarding_completed', True)
    assert client.get('/api/setup/status').json()['auto_show'] is False


@pytest.mark.parametrize(('changes', 'issue'), [
    ({'enabled': 0}, 'connection_disabled'),
    ({'capabilities_json': '[]'}, 'capability_disabled'),
    ({'consent_json': '{}'}, 'consent_missing'),
    ({'models_json': '{}'}, 'model_missing'),
    ({'base_url': 'file:///private/test'}, 'address_invalid'),
    ({'budget_json': '{"daily":"invalid"}'}, 'budget_invalid'),
])
def test_incomplete_connection_explains_the_missing_requirement(local_setup, changes, issue):
    db, client = local_setup
    connection(db, **changes); route(db)
    result = client.get('/api/setup/status').json()['capabilities']['chat']
    assert result['ready'] is False
    assert issue in result['issues']


def test_missing_key_is_reported_without_exposing_any_credential(local_setup, monkeypatch):
    db, client = local_setup
    connection(db); route(db)
    monkeypatch.setattr(setup, 'has_key', lambda _: False)
    result = client.get('/api/setup/status').json()
    assert result['capabilities']['chat']['issues'] == ['credentials_missing']
    assert 'api_key' not in json.dumps(result)


def test_credential_store_failure_is_sanitized(local_setup, monkeypatch):
    db, client = local_setup
    connection(db); route(db)
    def broken(_): raise RuntimeError('private-account-path-and-secret')
    monkeypatch.setattr(setup, 'has_key', broken)
    response = client.get('/api/setup/status')
    assert response.status_code == 200
    assert response.json()['capabilities']['chat']['issues'] == ['credentials_unavailable']
    assert 'private-account' not in response.text


@pytest.mark.parametrize('period', ['daily', 'monthly'])
def test_exhausted_budget_is_not_ready(local_setup, period):
    db, client = local_setup
    connection(db, budget_json=json.dumps({period: 1})); route(db)
    record_provider_usage(db, avatar(db), 'pc_test', 'fixture', 'chat', 'ok', estimated_cost=1)
    result = client.get('/api/setup/status').json()['capabilities']['chat']
    assert result['ready'] is False and 'budget_exhausted' in result['issues']


def test_imported_usage_does_not_block_setup_and_get_is_read_only(local_setup):
    db, client = local_setup
    connection(db, budget_json='{"daily":1}'); route(db)
    record_provider_usage(db, avatar(db), 'pc_test', 'fixture', 'chat', 'ok', estimated_cost=100, metadata={'imported_history': True})
    before = db.all('SELECT * FROM usage_events')
    result = client.get('/api/setup/status').json()
    assert result['capabilities']['chat']['ready'] is True
    assert db.all('SELECT * FROM usage_events') == before
    assert not db.all('SELECT * FROM app_settings')


def test_local_chat_requires_no_key_but_address_must_stay_local(local_setup, monkeypatch):
    db, client = local_setup
    connection(db, provider_kind='local', base_url='http://127.0.0.1:1234/v1', consent_json='{}')
    route(db)
    def forbidden(_): raise AssertionError('A local connection needs no credential check')
    monkeypatch.setattr(setup, 'has_key', forbidden)
    assert client.get('/api/setup/status').json()['capabilities']['chat']['ready'] is True
    db.execute("UPDATE provider_connections SET base_url='https://example.invalid/v1'")
    assert 'address_invalid' in client.get('/api/setup/status').json()['capabilities']['chat']['issues']


def test_chat_can_use_ready_fallback_but_vision_does_not_skip_missing_key(local_setup, monkeypatch):
    db, client = local_setup
    connection(db, 'pc_primary'); connection(db, 'pc_backup')
    route(db, primary='pc_primary', fallback=['pc_backup'])
    route(db, capability='vision', primary='pc_primary', fallback=['pc_backup'])
    monkeypatch.setattr(setup, 'has_key', lambda key: key.endswith('pc_backup'))
    result = client.get('/api/setup/status').json()['capabilities']
    assert result['chat']['ready'] and result['chat']['using_fallback']
    assert result['vision']['ready'] is False
    assert result['vision']['connection_id'] == 'pc_primary'


def test_disabled_primary_allows_runtime_eligible_vision_fallback(local_setup):
    db, client = local_setup
    connection(db, 'pc_primary', enabled=0); connection(db, 'pc_backup')
    route(db, capability='vision', primary='pc_primary', fallback=['pc_backup'])
    assert client.get('/api/setup/status').json()['capabilities']['vision']['ready'] is True


def test_avatar_route_overrides_global_and_required_checks_reuse_readiness(local_setup):
    db, client = local_setup
    connection(db, 'pc_global'); connection(db, 'pc_avatar', enabled=0)
    aid = avatar(db)
    route(db, primary='pc_global'); route(db, primary='pc_avatar', avatar_id=aid)
    result = client.get('/api/setup/status', params={'avatar_id': aid}).json()
    assert result['capabilities']['chat']['scope'] == 'avatar'
    assert result['capabilities']['chat']['ready'] is False
    assert result['required']['ready'] is False
    assert '模型设置' in [item['name'] for item in result['required']['missing']]
    assert result['avatar']['name'] == '测试人物 <name>'
    db.execute("UPDATE provider_connections SET enabled=1 WHERE id='pc_avatar'")
    result = client.get('/api/setup/status').json()
    assert '模型设置' not in [item['name'] for item in result['required']['missing']]
    assert result['required']['ready'] is False  # A connection is not a completed persona.


def test_unknown_avatar_and_empty_route_are_clear(local_setup):
    db, client = local_setup
    assert client.get('/api/setup/status?avatar_id=missing').status_code == 404
    route(db, primary='')
    assert client.get('/api/setup/status').json()['capabilities']['chat']['issues'] == ['connection_missing']


def test_start_chat_requires_persona_checks_as_well_as_model(local_setup):
    db, client = local_setup
    aid = avatar(db)
    connection(db); route(db)
    for content in ['identity', 'personality', 'speaking', 'boundaries']:
        db.execute('INSERT INTO evidence(avatar_id,source_type,content,created_at) VALUES(?,?,?,?)', (aid, 'fictional_source', content, 1))
    result = client.get('/api/setup/status').json()
    assert result['required']['ready'] is True
    assert result['required']['missing'] == []
    db.execute('UPDATE provider_connections SET enabled=0')
    result = client.get('/api/setup/status').json()
    assert result['required']['ready'] is False
    assert [item['name'] for item in result['required']['missing']] == ['模型设置']


def test_unsupported_speech_adapter_is_not_advertised_as_ready(local_setup):
    db, client = local_setup
    connection(db, provider_kind='openai_compatible'); route(db, capability='tts')
    result = client.get('/api/setup/status').json()['capabilities']['tts']
    assert result['ready'] is False and 'adapter_unsupported' in result['issues']


def test_legacy_connection_works_without_recreating_it(local_setup):
    db, client = local_setup
    now = int(time.time())
    db.execute("INSERT INTO model_connections(id,display_name,connection_type,provider_name,base_url,model,cloud_data_consent,last_test_status,last_tested_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ('mc_old', 'Existing connection', 'cloud_openai', 'fixture', 'https://example.invalid/v1', 'fixture', 1, 'ok', now, now, now))
    db.set_setting('selected_model_connection_id', 'mc_old')
    result = client.get('/api/setup/status').json()
    assert result['auto_show'] is False
    assert result['capabilities']['chat']['ready'] is True
    assert result['capabilities']['chat']['source'] == 'legacy'
    db.execute('UPDATE model_connections SET last_tested_at=1')
    assert 'legacy_test_required' in client.get('/api/setup/status').json()['capabilities']['chat']['issues']
