import json
import time

import pytest

from openavatar.providers import ProviderError
from openavatar.schemas import ProviderConnectionPayload
from openavatar.services import provider_hub as hub
from test_runtime import create_avatar, make_client


def row(url='https://api.minimaxi.com/v1', costs=None):
    return {'id':'price-test', 'enabled':1, 'provider_kind':'minimax', 'base_url':url,
            'config_json':json.dumps({'cost_estimates':costs or {}}),
            'consent_json':json.dumps({'voice_biometric':True}), 'budget_json':'{}'}


def test_mainland_clone_price_is_cny_not_international_usd():
    assert hub.estimate_provider_cost(row(), 'voice_clone') == 9.9
    assert hub.estimate_provider_cost(row(costs={'voice_clone':12}), 'voice_clone') == 12


@pytest.mark.parametrize('host',['https://api.minimax.io/v1','https://api.example.com/v1','https://api.minimaxi.com.evil.test/v1'])
def test_unknown_currency_needs_explicit_cny_price(host):
    with pytest.raises(ProviderError, match='人民币复刻估价'):
        hub.estimate_provider_cost(row(host), 'voice_clone')
    assert hub.estimate_provider_cost(row(host, {'voice_clone':11}), 'voice_clone') == 11


@pytest.mark.parametrize('value',[0,-1,'NaN','Infinity',None,True,'wrong'])
def test_invalid_cloud_clone_price_rejected_before_save(value):
    payload=ProviderConnectionPayload(display_name='Test',provider_kind='minimax',config={'cost_estimates':{'voice_clone':value}})
    with pytest.raises(ProviderError): hub._validate_connection(payload)


@pytest.mark.parametrize('period',['daily','monthly'])
def test_next_clone_must_fit_remaining_budget(tmp_path, monkeypatch, period):
    with make_client(tmp_path,monkeypatch) as client:
        db=client.app.state.db; avatar=create_avatar(client)
        hub.record_provider_usage(db,avatar,'price-test','','chat','ok',estimated_cost=1)
        connection=row();connection['budget_json']=json.dumps({period:10})
        with pytest.raises(ProviderError,match='剩余预算'):hub.prepare_voice_clone_cost(db,connection)
        connection['budget_json']=json.dumps({period:10.9})
        assert hub.prepare_voice_clone_cost(db,connection)==9.9
        # Preflight does not reserve money or fabricate a provider charge.
        assert hub._spent(db,'price-test',0)==1


@pytest.mark.parametrize('reason',['insufficient_budget','unknown_currency','unavailable_route'])
def test_clone_endpoint_blocks_before_upload_or_provider_call(tmp_path,monkeypatch,reason):
    from openavatar.routes import media_runtime
    connection=row()
    connection['budget_json']='{"daily":1}'
    if reason=='unknown_currency':
        connection=row('https://api.minimax.io/v1')
    monkeypatch.setattr(media_runtime,'find_route',lambda *a:{'primary_connection_id':'price-test'})
    monkeypatch.setattr(media_runtime,'route_candidates',lambda *a:[] if reason=='unavailable_route' else [(connection,'speech-2.8-hd',{})])
    def no_provider(*args,**kwargs):
        raise AssertionError('A rejected estimate must not construct a cloud client')
    monkeypatch.setattr(media_runtime,'MiniMaxClient',no_provider)
    with make_client(tmp_path,monkeypatch) as client:
        avatar=create_avatar(client)
        uploaded=client.post(f'/api/avatars/{avatar}/imports?category=audio',content=b'RIFF-test-audio',headers={'Content-Type':'audio/wav','X-File-Name':'sample.wav'}).json()
        response=client.post(f'/api/avatars/{avatar}/training-jobs/{uploaded["training_job"]["id"]}/run',json={'confirm_billable_call':True})
        assert response.status_code==400,response.text
        expected={'insufficient_budget':'剩余预算','unknown_currency':'人民币复刻估价','unavailable_route':'不会改用旧连接'}[reason]
        assert expected in response.json()['detail']
        assert not client.app.state.db.all('SELECT * FROM usage_events WHERE avatar_id=?',(avatar,))
