"""S01-S15 offline regressions: synthetic data and deliberately fake providers."""
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from openavatar.db import Database
from openavatar.providers import ProviderError
from openavatar.schemas import CapabilityRoutePayload
from openavatar.services import provider_hub as hub
from openavatar.services.model_connections import MeteredChatProvider
from openavatar.services.training import create_job, get_job, request_cancel, update_job
from test_runtime import create_avatar, make_client


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Unexpected external request'))


def connection(db, key='pc_a', kind='minimax', capabilities=('chat',), costs=None, budget=None, model='model-a', base_url='https://audit.invalid/v1'):
    db.execute('INSERT INTO provider_connections(id,display_name,provider_kind,base_url,capabilities_json,models_json,config_json,consent_json,budget_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,0,0)',
               (key, key, kind, base_url, json.dumps(capabilities), json.dumps({c: model for c in capabilities}),
                json.dumps({'cost_estimates': costs or {}}), json.dumps({c: True for c in set(hub.CONSENT_CLASS.values())}), json.dumps(budget or {})))
    return hub.connection_row(db, key)


def route(db, cap, primary='pc_a', fallbacks=(), model='', config=None):
    return hub.upsert_route(db, CapabilityRoutePayload(capability=cap, primary_connection_id=primary, fallback_connection_ids=list(fallbacks), model=model, config=config or {}))


class FakeProvider:
    model = 'synthetic'
    calls = 0
    closed = False
    def available(self): return True
    def chat(self, messages, **kwargs):
        self.calls += 1
        return 'ok'
    def stream_chat(self, messages):
        self.calls += 1
        try:
            yield '文' * 80
            yield '文' * 80
        finally:
            self.closed = True


def test_s01_chat_budget_blocks_known_overage_before_provider(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        row = connection(db, costs={'chat': 1}, budget={'daily': .5})
        fake = FakeProvider()
        with pytest.raises(ProviderError, match='剩余预算'):
            MeteredChatProvider(fake, db, avatar, row).chat([{'content': 'hi'}])
        assert fake.calls == 0
        assert not db.all('SELECT * FROM usage_events WHERE provider=?', (row['id'],))


def test_s01_atomic_reservations_across_database_instances_and_failed_cost(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, costs={'chat': 1}, budget={'daily': 1.5})
        gate = threading.Barrier(2)
        def run():
            separate = Database(db.path)
            gate.wait(timeout=3)
            try:
                return hub.begin_provider_usage(separate, avatar, 'pc_a', 'm', 'chat')
            except ProviderError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            events = list(pool.map(lambda _: run(), range(2)))
        assert len([e for e in events if e]) == 1
        event = next(e for e in events if e)
        hub.finish_provider_usage(db, event, 'failed')
        hub.finish_provider_usage(db, event, 'ok')
        usage = db.one('SELECT * FROM usage_events WHERE id=?', (event,))
        assert usage['estimated_cost'] == 1 and usage['status'] == 'failed'
        assert json.loads(usage['metadata_json'])['settlement'] == 'unknown'
        with pytest.raises(ProviderError, match='剩余预算'):
            hub.begin_provider_usage(db, avatar, 'pc_a', 'm', 'chat')


def test_s01_unknown_price_budget_and_changed_ceiling_are_blocked(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, kind='openai_compatible', budget={'daily': 2})
        with pytest.raises(ProviderError, match='单次估价'):
            hub.begin_provider_usage(db, avatar, 'pc_a', 'm', 'chat')
        db.execute('UPDATE provider_connections SET config_json=? WHERE id=?', ('{"cost_estimates":{"chat":1}}', 'pc_a'))
        with pytest.raises(ProviderError, match='估价已改变'):
            hub.begin_provider_usage(db, avatar, 'pc_a', 'm', 'chat', cost_ceiling=.5)
        assert not db.all("SELECT * FROM usage_events WHERE provider='pc_a'")


def test_s02_truncated_stream_finalizes_once_and_closes_upstream(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        row = connection(db, costs={'chat': .4})
        fake = FakeProvider()
        stream = MeteredChatProvider(fake, db, avatar, row).stream_chat([{'content': 'hi'}])
        assert len(next(stream)) == 80
        stream.close()
        rows = db.all("SELECT * FROM usage_events WHERE provider='pc_a'")
        assert len(rows) == 1 and rows[0]['estimated_cost'] == .4
        assert rows[0]['status'] == 'interrupted' and fake.closed


def test_s02_asr_uses_configured_price_for_each_started_attempt(tmp_path, monkeypatch):
    import openavatar.routes.identity as identity
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, capabilities=('asr',), costs={'asr': .4})
        route(db, 'asr')
        upload = client.post(f'/api/avatars/{avatar}/imports?category=audio', content=b'RIFF-synthetic', headers={'Content-Type':'audio/wav', 'X-File-Name':'sample.wav'})
        upload.raise_for_status()
        source = upload.json()['id'] if 'id' in upload.json() else upload.json()['import']['id']
        row = db.one('SELECT id FROM voice_transcriptions WHERE source_import_id=?', (source,))
        monkeypatch.setattr(identity.MiniMaxClient, 'transcribe', lambda *a, **k: {'text':'测试', 'file_id':'fake'})
        for _ in range(2):
            response = client.post(f'/api/avatars/{avatar}/voice-transcriptions/{row["id"]}/run', json={'confirm_billable_call':True})
            assert response.status_code == 200, response.text
        usage = db.all("SELECT * FROM usage_events WHERE provider='pc_a'")
        assert len(usage) == 2 and sum(x['estimated_cost'] for x in usage) == .8


def voice_job(client, db, avatar, tmp_path):
    (tmp_path / 'sample.wav').write_bytes(b'synthetic')
    db.execute("INSERT INTO imports(avatar_id,category,original_name,stored_path,media_type,size_bytes,status,created_at) VALUES(?,'audio','sample.wav','sample.wav','audio/wav',1,'uploaded',0)", (avatar,))
    return create_job(db, avatar, 'voice')


def test_s03_same_job_runs_once_and_cancelled_result_does_not_activate(tmp_path, monkeypatch):
    import openavatar.routes.media_runtime as media
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, capabilities=('voice_clone',), costs={'voice_clone':1})
        route(db, 'voice_clone')
        job = voice_job(client, db, avatar, tmp_path)
        entered, release = threading.Event(), threading.Event()
        calls = []
        def clone(*a, **k):
            calls.append(k['voice_id']); entered.set()
            assert release.wait(4)
            return {'voice_id':k['voice_id']}
        monkeypatch.setattr(media.MiniMaxClient, 'clone_voice', clone)
        endpoint = f'/api/avatars/{avatar}/training-jobs/{job["id"]}/run'
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, endpoint, json={'confirm_billable_call':True})
            assert entered.wait(4)
            duplicate = client.post(endpoint, json={'confirm_billable_call':True})
            assert duplicate.status_code == 409
            request_cancel(db, job['id'])
            release.set()
            result = first.result(timeout=5)
        assert result.status_code == 200 and len(calls) == 1
        assert get_job(db, job['id'])['status'] == 'cancelled'
        assert not db.all("SELECT * FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1", (avatar,))
        assert client.post(endpoint, json={'confirm_billable_call':True}).status_code == 409
        assert len(db.all("SELECT * FROM usage_events WHERE provider='pc_a'")) == 1


def test_s03_cancel_before_dispatch_cannot_claim_or_call(tmp_path, monkeypatch):
    import openavatar.routes.media_runtime as media
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, capabilities=('voice_clone',), costs={'voice_clone':1})
        route(db, 'voice_clone')
        job = voice_job(client, db, avatar, tmp_path)
        request_cancel(db, job['id'])
        monkeypatch.setattr(media.MiniMaxClient, 'clone_voice', lambda *a, **k: pytest.fail('cancelled call'))
        response = client.post(f'/api/avatars/{avatar}/training-jobs/{job["id"]}/run', json={'confirm_billable_call':True})
        assert response.status_code == 409


def test_s04_s05_video_stays_bound_and_failed_quality_never_regenerates(tmp_path, monkeypatch):
    import openavatar.services.media_jobs as jobs
    from openavatar.services.video_runtime import video_connection_snapshot
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        row = connection(db, key='pc_video_owner', kind='openrouter', capabilities=('video',), costs={'video':.5})
        job = create_job(db, avatar, 'video')
        update_job(db, job['id'], status='running', result={'provider':'openrouter', 'provider_task_id':'task-a', 'continuity_run_id':'fake-run', 'connection_snapshot':video_connection_snapshot(row, 'video-model', {'duration':8, 'resolution':'720p'})})
        key_reads, polls = [], []
        monkeypatch.setattr('openavatar.services.video_runtime.load_provider_key', lambda name: key_reads.append(name) or 'owner-key')
        def poll(generation, **kwargs):
            polls.append((generation, kwargs))
            return {'done':True, 'remote_url':'https://audit.invalid/result.mp4'}
        monkeypatch.setattr(jobs, 'poll_video_generation', poll)
        monkeypatch.setattr(jobs, 'download_video_result', lambda *a, **k:'video/mp4')
        def finalize(fake_db, settings, **kwargs):
            review={'sendable':False, 'visual_review':{'available':True}}
            with fake_db.transaction() as transaction:
                transaction.execute('BEGIN IMMEDIATE')
                assert kwargs['commit_guard'](transaction)
                kwargs['on_commit'](transaction, review)
            return review
        monkeypatch.setattr(jobs, 'finalize_video_continuity', finalize)
        monkeypatch.setattr('openavatar.services.video_generation.start_video_generation', lambda *a, **k:pytest.fail('Unapproved quality retry'))
        # Disabling uploads does not change the account needed to retrieve an already paid result.
        db.execute("UPDATE provider_connections SET consent_json='{}',enabled=0 WHERE id='pc_video_owner'")
        assert jobs.poll_video_jobs(db, client.app.state.settings, job_id=job['id']) == 1
        assert get_job(db, job['id'])['status'] == 'needs_review'
        assert key_reads == [hub.provider_key_name('pc_video_owner')]
        assert polls[0][0].openrouter_api_key == 'owner-key'
        assert polls[0][0].openrouter_model == 'video-model'
        assert polls[0][0].duration == 8


def add_voice(db, avatar, owner):
    db.execute("INSERT INTO provider_assets(avatar_id,kind,provider,external_id,created_at) VALUES(?,'voice',?,'account-a-voice',0)", (avatar, owner))


@pytest.mark.parametrize('disabled', [False, True])
def test_s06_s07_speech_does_not_cross_voice_account_or_legacy_route(tmp_path, monkeypatch, disabled):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, key='pc_other', capabilities=('tts',), costs={'tts':.2})
        route(db, 'tts', primary='pc_other')
        add_voice(db, avatar, 'pc_owner')
        db.set_setting('cloud_services', {'cloud_data_consent':True})
        if disabled: db.execute("UPDATE provider_connections SET enabled=0 WHERE id='pc_other'")
        response = client.post(f'/api/avatars/{avatar}/speech', json={'text':'你好', 'confirm_billable_call':True})
        assert response.status_code == 400, response.text
        assert not db.all("SELECT * FROM usage_events WHERE provider='pc_other'")


def test_s08_removed_capability_and_s09_unprobed_connection(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db = client.app.state.db
        connection(db, capabilities=('chat','tts'))
        route(db, 'chat')
        db.execute("UPDATE provider_connections SET capabilities_json='[\"tts\"]' WHERE id='pc_a'")
        assert not hub.route_candidates(db, 'chat')
        tested = hub.test_connection(db, 'pc_a')
        assert tested['status'] == 'untested' and tested['ok'] is False
        assert '尚未验证' in tested['message']


@pytest.mark.parametrize('status', ['failed','cancelled','expired'])
def test_s10_minimax_terminal_failure_stops_polling(monkeypatch, status):
    from openavatar.services.minimax import MiniMaxClient, MiniMaxError
    monkeypatch.setattr(MiniMaxClient, '_get', lambda *a, **k:{'status':status, 'message':'synthetic reason'})
    with pytest.raises(MiniMaxError, match='synthetic reason'):
        MiniMaxClient('synthetic').query_video('fake-task')


def test_s12_primary_model_override_does_not_replace_fallback_model(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db = client.app.state.db
        connection(db, model='primary-default')
        connection(db, key='pc_b', kind='aliyun', model='fallback-default')
        route(db, 'chat', fallbacks=('pc_b',), model='primary-override')
        assert [entry[1] for entry in hub.route_candidates(db, 'chat')] == ['primary-override','fallback-default']


def test_s13_capability_report_uses_unified_asr_not_legacy_key(tmp_path, monkeypatch):
    from openavatar.providers import ProviderConfig
    from openavatar.services.capabilities import capability_report
    with make_client(tmp_path, monkeypatch) as client:
        db = client.app.state.db
        connection(db, capabilities=('asr',), costs={'asr':.1})
        route(db, 'asr')
        monkeypatch.setattr('openavatar.services.capabilities.load_provider_key', lambda name:'fake' if name == hub.provider_key_name('pc_a') else '')
        monkeypatch.setattr('openavatar.services.capabilities.detect_local_ocr', lambda:[])
        report = capability_report(db, ProviderConfig(), FakeProvider())
        asr = next(item for item in report['items'] if item['key'] == 'asr')
        assert asr['status'] == 'available' and asr['provider'] == 'pc_a'
        db.execute("UPDATE provider_connections SET enabled=0 WHERE id='pc_a'")
        asr = next(item for item in capability_report(db, ProviderConfig(), FakeProvider())['items'] if item['key']=='asr')
        assert asr['status'] == 'needs_setup'


def test_s14_local_ocr_uses_no_proxy_no_redirect_opener(tmp_path, monkeypatch):
    import openavatar.services.ocr as ocr
    image = tmp_path/'synthetic.png'; image.write_bytes(b'not-personal')
    calls=[]
    monkeypatch.setattr(ocr, 'load_provider_key', lambda *_:'')
    monkeypatch.setattr(ocr, 'local_urlopen', lambda request, **kwargs: calls.append(request.full_url) or io.BytesIO(b'{"text":"local"}'))
    text, _ = ocr._run_http({'id':'fake', 'connection_type':'local_http', 'base_url':'http://127.0.0.1:9999/ocr'}, image)
    assert text == 'local' and calls == ['http://127.0.0.1:9999/ocr']


def test_s15_aliyun_clone_retains_region_enrollment_target_and_owner(tmp_path, monkeypatch):
    import openavatar.routes.media_runtime as media
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, kind='aliyun', capabilities=('voice_clone','tts'), costs={'voice_clone':1, 'tts':.2}, model='enrollment-model', base_url='https://region.audit.invalid/compatible-mode/v1')
        db.execute("UPDATE provider_connections SET models_json=? WHERE id='pc_a'", (json.dumps({'voice_clone':'enrollment-model', 'tts':'approved-tts-model'}),))
        route(db, 'voice_clone', model='enrollment-override')
        job=voice_job(client, db, avatar, tmp_path)
        seen=[]
        monkeypatch.setattr(media, 'load_provider_key', lambda *_:'fake-key')
        def clone(self, sample, **kwargs):
            seen.append((self.base_url, kwargs))
            return {'voice_id':'account-specific'}
        monkeypatch.setattr(media.AliyunAvatarClient, 'clone_voice', clone)
        result=client.post(f'/api/avatars/{avatar}/training-jobs/{job["id"]}/run', json={'confirm_billable_call':True})
        assert result.status_code==200, result.text
        assert seen[0][0]=='https://region.audit.invalid'
        assert seen[0][1]['clone_model']=='enrollment-override'
        assert seen[0][1]['target_model']=='approved-tts-model'
        assert db.one("SELECT provider FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1", (avatar,))['provider']=='pc_a'
        assert db.one("SELECT estimated_cost FROM usage_events WHERE provider='pc_a'")['estimated_cost']==1


@pytest.mark.parametrize('budget, expected_calls', [(.4,0),(2,1)])
def test_s01_s02_video_submission_is_metered_before_polling(tmp_path, monkeypatch, budget, expected_calls):
    import openavatar.routes.media_runtime as media
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, capabilities=('video',), costs={'video':.5}, budget={'daily':budget})
        route(db, 'video')
        job = create_job(db, avatar, 'video')
        monkeypatch.setattr(media, 'build_continuity_contract', lambda *a, **k:{'ready_for_video':True,'first_frame':{'remote_url':'https://audit.invalid/frame.jpg'},'references':[]})
        calls=[]
        monkeypatch.setattr(media.MiniMaxClient, 'create_video', lambda *a, **k:calls.append(k) or {'task_id':'remote-task','mode':'first_frame'})
        response=client.post(f'/api/avatars/{avatar}/training-jobs/{job["id"]}/run', json={'confirm_billable_call':True})
        assert len(calls)==expected_calls
        usage=db.all("SELECT * FROM usage_events WHERE provider='pc_a'")
        if expected_calls:
            assert response.status_code==200, response.text
            assert response.json()['result']['connection_snapshot']['connection_id']=='pc_a'
            assert len(usage)==1 and usage[0]['estimated_cost']==.5
            assert response.json()['status']=='running'
        else:
            assert response.status_code==502 and not usage


def test_s02_s15_aliyun_tts_success_keeps_voice_and_region_and_records_cost(tmp_path, monkeypatch):
    import openavatar.services.aliyun as aliyun
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, kind='aliyun', capabilities=('tts',), costs={'tts':.2}, model='tts-model', base_url='https://region.audit.invalid/compatible-mode/v1')
        route(db, 'tts')
        add_voice(db, avatar, 'pc_a')
        observed=[]
        def synth(self,text,**kwargs):
            observed.append((self.base_url,text,kwargs))
            return {'output':{'url':'https://audit.invalid/fake.mp3'}}
        def download(url,target,**kwargs):
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'synthetic audio')
            return 'audio/mpeg'
        monkeypatch.setattr(aliyun.AliyunAvatarClient, 'synthesize', synth)
        monkeypatch.setattr(aliyun, 'download_provider_asset', download)
        response=client.post(f'/api/avatars/{avatar}/speech', json={'text':'你好','confirm_billable_call':True})
        assert response.status_code==200, response.text
        assert observed==[('https://region.audit.invalid','你好',{'voice_id':'account-a-voice','model':'tts-model'})]
        usage=db.one("SELECT * FROM usage_events WHERE provider='pc_a'")
        assert usage['estimated_cost']==.2 and usage['status']=='ok'


@pytest.mark.parametrize('capability', hub.CAPABILITIES)
def test_s01_uniform_budget_reservations_cover_every_routed_capability(tmp_path, monkeypatch, capability):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db, capabilities=(capability,), costs={capability:1}, budget={'daily':.5})
        with pytest.raises(ProviderError, match='剩余预算'):
            hub.begin_provider_usage(db, avatar, 'pc_a', 'model', capability)
        assert not db.all("SELECT * FROM usage_events WHERE provider='pc_a'")


def test_s02_success_settles_frozen_prices_but_interrupted_keeps_reservation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        connection(db)
        event = hub.begin_provider_usage(db, avatar, 'pc_a', 'm', 'chat', input_units=1000, output_units=4096)
        before=db.one('SELECT estimated_cost FROM usage_events WHERE id=?',(event,))['estimated_cost']
        db.execute("UPDATE provider_connections SET config_json='{" + '"cost_estimates":{"chat":100}' + "}' WHERE id='pc_a'")
        hub.finish_provider_usage(db,event,'ok',input_units=1000,output_units=20)
        after=db.one('SELECT * FROM usage_events WHERE id=?',(event,))
        assert 0 < after['estimated_cost'] < before
        assert json.loads(after['metadata_json'])['pricing_snapshot']['config_json']=='{"cost_estimates": {}}'


def test_s02_closing_failover_stream_finalizes_the_active_attempt(tmp_path, monkeypatch):
    from openavatar.services.model_connections import FailoverChatProvider
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar = client.app.state.db, create_avatar(client)
        row=connection(db,costs={'chat':.4})
        first, unused=FakeProvider(),FakeProvider()
        stream=FailoverChatProvider([MeteredChatProvider(first,db,avatar,row),unused]).stream_chat([{'content':'hi'}])
        assert len(next(stream))==80
        stream.close()
        usage=db.all("SELECT * FROM usage_events WHERE provider='pc_a'")
        assert len(usage)==1 and usage[0]['status']=='interrupted'
        assert first.closed and unused.calls==0


@pytest.mark.parametrize('backup_contains_pending', [False, True])
def test_s02_late_completion_cannot_rewrite_restored_usage_ids(tmp_path, monkeypatch, backup_contains_pending):
    with make_client(tmp_path, monkeypatch) as client:
        db, avatar=client.app.state.db,create_avatar(client)
        connection(db,costs={'chat':.4})
        if not backup_contains_pending:
            backup=db.backup(tmp_path/'before-attempt.sqlite')
        old=hub.begin_provider_usage(db,avatar,'pc_a','m','chat')
        if backup_contains_pending:
            backup=db.backup(tmp_path/'with-pending.sqlite')
        db.restore(backup)
        current = old if backup_contains_pending else hub.begin_provider_usage(db,avatar,'pc_a','m','chat')
        assert int(current)==int(old)
        hub.finish_provider_usage(db,old,'ok',input_units=0,output_units=1)
        assert db.one('SELECT status FROM usage_events WHERE id=?',(current,))['status']=='pending'
        if not backup_contains_pending:
            hub.finish_provider_usage(db,current,'ok')
            assert db.one('SELECT status FROM usage_events WHERE id=?',(current,))['status']=='ok'


def test_s13_capabilities_endpoint_preserves_asr_and_tts_when_chat_disabled(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db=client.app.state.db
        connection(db,key='pc_chat',capabilities=('chat',))
        connection(db,key='pc_speech',capabilities=('asr','tts'),costs={'asr':.1,'tts':.2})
        route(db,'chat',primary='pc_chat')
        route(db,'asr',primary='pc_speech');route(db,'tts',primary='pc_speech')
        db.execute("UPDATE provider_connections SET enabled=0 WHERE id='pc_chat'")
        monkeypatch.setattr('openavatar.services.capabilities.load_provider_key',lambda name:'fake' if name==hub.provider_key_name('pc_speech') else '')
        monkeypatch.setattr('openavatar.services.capabilities.detect_local_ocr',lambda:[])
        response=client.get('/api/capabilities')
        assert response.status_code==200,response.text
        report={item['key']:item for item in response.json()['items']}
        assert report['chat']['status']=='needs_setup'
        assert report['asr']['status']=='available' and report['tts']['status']=='available'


def polling_fixture(client, db, avatar, monkeypatch):
    import openavatar.services.media_jobs as jobs
    import openavatar.services.continuity as continuity
    from openavatar.services.video_runtime import video_connection_snapshot
    row=connection(db,kind='minimax',capabilities=('video',),costs={'video':.5})
    job=create_job(db,avatar,'video')
    run=continuity.create_continuity_run(db,avatar,job['id'],'synthetic',{'identity_set_id':'test-identity','references':[]})
    update_job(db,job['id'],status='running',result={'provider':'pc_a','provider_task_id':'task-a','continuity_run_id':run['id'],'connection_snapshot':video_connection_snapshot(row,'test-model',{})})
    monkeypatch.setattr(jobs.MiniMaxClient,'query_video',lambda *a,**k:{'done':True,'urls':['https://audit.invalid/a.mp4']})
    monkeypatch.setattr(continuity,'extract_video_keyframes',lambda *a,**k:[])
    monkeypatch.setattr('openavatar.services.video_review.review_video_frames',lambda *a,**k:{'sendable':False,'available':True})
    return job,run


def test_s03_video_poll_lease_serializes_manual_and_background_across_databases(tmp_path,monkeypatch):
    import openavatar.services.media_jobs as jobs
    with make_client(tmp_path,monkeypatch) as client:
        db,avatar=client.app.state.db,create_avatar(client)
        job,run=polling_fixture(client,db,avatar,monkeypatch)
        entered,release=threading.Event(),threading.Event();downloads=[]
        def download(url,target,**kwargs):
            downloads.append(url);entered.set();assert release.wait(4)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'synthetic');return 'video/mp4'
        monkeypatch.setattr(jobs,'download_video_result',download)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(jobs.poll_video_jobs,db,client.app.state.settings,job_id=job['id'])
            assert entered.wait(4)
            second=pool.submit(jobs.poll_video_jobs,Database(db.path),client.app.state.settings,job_id=job['id'])
            assert second.result(timeout=3)==0
            release.set();assert first.result(timeout=5)==1
        assert len(downloads)==1
        assert get_job(db,job['id'])['status']=='needs_review'
        assert len(db.all('SELECT * FROM media_reviews WHERE avatar_id=?',(avatar,)))==1
        assert not db.all("SELECT * FROM scheduler_leases WHERE lease_key LIKE 'video-poll:%'")


@pytest.mark.parametrize('change',['cancel','restore'])
def test_s03_video_download_cancel_or_restore_discards_before_review(tmp_path,monkeypatch,change):
    import openavatar.services.media_jobs as jobs
    with make_client(tmp_path,monkeypatch) as client:
        db,avatar=client.app.state.db,create_avatar(client)
        job,run=polling_fixture(client,db,avatar,monkeypatch)
        backup=db.backup(tmp_path/'before-download.sqlite')
        def download(url,target,**kwargs):
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'synthetic')
            if change=='cancel': request_cancel(Database(db.path),job['id'])
            else: db.restore(backup)
            return 'video/mp4'
        monkeypatch.setattr(jobs,'download_video_result',download)
        monkeypatch.setattr(jobs,'finalize_video_continuity',lambda *a,**k:pytest.fail('late video must never enter review'))
        jobs.poll_video_jobs(db,client.app.state.settings,job_id=job['id'])
        assert not db.all('SELECT * FROM media_reviews WHERE avatar_id=?',(avatar,))
        assert not db.all('SELECT * FROM video_keyframes WHERE avatar_id=?',(avatar,))
        assert not db.all('SELECT * FROM user_notifications WHERE avatar_id=?',(avatar,))
        assert get_job(db,job['id'])['status']==('cancelled' if change=='cancel' else 'running')


def test_s03_video_cancel_during_review_cannot_register_keyframes_or_finish(tmp_path,monkeypatch):
    import openavatar.services.media_jobs as jobs
    import openavatar.services.continuity as continuity
    with make_client(tmp_path,monkeypatch) as client:
        db,avatar=client.app.state.db,create_avatar(client)
        job,run=polling_fixture(client,db,avatar,monkeypatch)
        def download(url,target,**kwargs):
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'synthetic');return 'video/mp4'
        monkeypatch.setattr(jobs,'download_video_result',download)
        monkeypatch.setattr(continuity,'extract_video_keyframes',lambda *a,**k:[{'id':0,'local_path':'synthetic.jpg','position_ms':0,'quality_score':80,'binding':{}}])
        def review(*a,**k):
            request_cancel(Database(db.path),job['id'])
            return {'sendable':True,'available':True}
        monkeypatch.setattr('openavatar.services.video_review.review_video_frames',review)
        jobs.poll_video_jobs(db,client.app.state.settings,job_id=job['id'])
        assert get_job(db,job['id'])['status']=='cancelled'
        assert not db.all('SELECT * FROM video_keyframes WHERE avatar_id=?',(avatar,))
        assert not db.all('SELECT * FROM media_reviews WHERE avatar_id=?',(avatar,))
        assert db.one('SELECT status FROM continuity_runs WHERE id=?',(run['id'],))['status']!='approved'


def test_s03_restoring_during_clone_discards_old_result_and_usage_completion(tmp_path,monkeypatch):
    import openavatar.routes.media_runtime as media
    with make_client(tmp_path,monkeypatch) as client:
        db,avatar=client.app.state.db,create_avatar(client)
        connection(db,capabilities=('voice_clone',),costs={'voice_clone':1});route(db,'voice_clone')
        job=voice_job(client,db,avatar,tmp_path)
        backup=db.backup(tmp_path/'before-clone.sqlite')
        def clone(*a,**k):
            db.restore(backup)
            return {'voice_id':'late-old-account-result'}
        monkeypatch.setattr(media.MiniMaxClient,'clone_voice',clone)
        response=client.post(f'/api/avatars/{avatar}/training-jobs/{job["id"]}/run',json={'confirm_billable_call':True})
        assert response.status_code==409,response.text
        assert get_job(db,job['id'])['status']=='queued'
        assert not db.all("SELECT * FROM provider_assets WHERE avatar_id=? AND kind='voice'",(avatar,))
        assert not db.all("SELECT * FROM usage_events WHERE provider='pc_a'")
