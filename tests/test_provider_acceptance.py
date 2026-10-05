"""Data-class authorization checks; no external service is called."""
import pytest
from test_app import make_client
from openavatar.services.provider_hub import CONSENT_CLASS, assert_allowed, connection_row, route_candidates, record_provider_usage
from openavatar.providers import ProviderError


@pytest.mark.parametrize('capability', list(CONSENT_CLASS))
def test_each_cloud_capability_requires_its_own_data_authorization(tmp_path, monkeypatch, capability):
    monkeypatch.setattr('openavatar.services.provider_hub.load_provider_key', lambda *_: 'test-placeholder')
    with make_client(tmp_path) as client:
        payload = {'display_name':'authorization fixture','provider_kind':'openai_compatible',
                   'base_url':'https://example.invalid/v1','capabilities':[capability], 'models':{capability:'fixture'},
                   'consent': {k: True for k in set(CONSENT_CLASS.values())}}
        payload['consent'][CONSENT_CLASS[capability]] = False
        created=client.post('/api/provider-connections',json=payload)
        assert created.status_code==201
        cid=created.json()['id'];db=client.app.state.db
        with pytest.raises(ProviderError, match='尚未授权'):
            assert_allowed(db, connection_row(db,cid), capability)
        assert client.put('/api/capability-routes',json={'capability':capability,'primary_connection_id':cid}).status_code==200
        assert route_candidates(db,capability)==[]
        payload['consent'][CONSENT_CLASS[capability]]=True
        assert client.put('/api/provider-connections/'+cid,json=payload).status_code==200
        assert len(route_candidates(db,capability))==1
