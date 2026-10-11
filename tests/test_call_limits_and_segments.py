"""Call tests use a temporary DB and local substitutes, never cloud providers."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import openavatar.routes.calls as calls
from openavatar.providers import ProviderError
from openavatar.services.call_policy import CallLimit, CallLimits, CallPolicy, SentenceSegments, call_cost
from test_runtime import FakeStreamingProvider, create_avatar, make_client


def until(ws, event_type):
    while True:
        event = ws.receive_json()
        if event['type'] == event_type:
            return event
        assert event['type'] not in {'call.error', 'call.ended'}, event


def stub_costs(monkeypatch, *, chat_cost=.1, speech_cost=.1, synthesize=None):
    row = {'id': 'test-call-provider', 'provider_kind': 'minimax', 'config_json': '{}'}
    monkeypatch.setattr(calls, 'select_call_chat', lambda prepared: (prepared['client'], row, chat_cost))
    monkeypatch.setattr(calls, 'select_call_voice', lambda *_: {'row': row, 'model': 'unchanged-voice-model', 'voice_id': 'approved-voice', 'config': {}})
    monkeypatch.setattr(calls, 'call_cost', lambda *_args, **_kwargs: speech_cost)
    monkeypatch.setattr(calls, 'assert_allowed', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(calls, 'refresh_call_voice', lambda *_: None)
    invoked = []
    def fake_speech(plan, text, target):
        invoked.append((plan['voice_id'], text))
        if synthesize:
            synthesize()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'local test audio')
        return 'audio/mpeg'
    monkeypatch.setattr(calls, 'synthesize_call_segment', fake_speech)
    return invoked


@pytest.mark.parametrize('minutes,budget', [(0, 5), (121, 5), ('nan', 5), (True, 5), (10, 'inf'), (10, 0), (10, 1001)])
def test_invalid_call_limits(minutes, budget):
    with pytest.raises(ProviderError):
        CallLimits.parse(minutes, budget)


def test_estimate_reservations_deadline_and_warnings():
    clock = [0.0]
    policy = CallPolicy(CallLimits.parse(1, 1), clock=lambda: clock[0])
    policy.reserve(.8)
    assert policy.snapshot()['budget_warning']
    assert policy.estimated_reserved_cny == .8
    with pytest.raises(CallLimit, match='剩余估算额度'):
        policy.reserve(.3)
    assert policy.estimated_reserved_cny == .8
    clock[0] = 50
    assert policy.snapshot()['time_warning']
    clock[0] = 60
    with pytest.raises(CallLimit) as ended:
        policy.check()
    assert ended.value.reason == 'time_limit'


def test_unknown_cloud_price_is_not_free():
    with pytest.raises(ProviderError, match='人民币单次估价'):
        call_cost({'provider_kind': 'openai_compatible'}, 'tts', input_units=20)
    assert call_cost({'provider_kind': 'local'}, 'chat', input_units=20) == 0
    assert call_cost({'provider_kind': 'minimax'}, 'tts', input_units=20) == .002


def test_complete_sentences_early_and_at_most_three_segments():
    split = SentenceSegments()
    assert split.push('第一句') == []
    assert split.push('。第二句！') == ['第一句。', '第二句！']
    assert split.push('第三句。第四句。') == []
    assert split.push('', final=True) == ['第三句。第四句。']
    split = SentenceSegments()
    assert sum(len(x) for x in split.push('甲' * 100, final=True)) == 80


def test_chunk_boundary_does_not_turn_decimal_point_into_sentence():
    split = SentenceSegments()
    assert split.push('路程是1.') == []
    assert split.push('5公里。') == ['路程是1.5公里。']
    split = SentenceSegments()
    assert split.push('Walk 1.') == []
    assert split.push('5 miles. Then rest.') == ['Walk 1.5 miles.']
    assert split.push('', final=True) == [' Then rest.']


def test_period_at_chunk_end_waits_for_space_or_final_boundary():
    split = SentenceSegments()
    assert split.push('Hello.') == []
    assert split.push(' How are you?') == ['Hello.', ' How are you?']
    assert split.push('', final=True) == []


def test_server_rejects_invalid_configuration_before_start(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?max_minutes=999') as ws:
            assert ws.receive_json()['type'] == 'call.error'
        assert not client.app.state.db.all('SELECT * FROM realtime_call_sessions')


def test_five_rounds_no_fixed_demo_limit(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
            started = ws.receive_json()
            assert started['max_minutes'] == 10 and started['estimated_budget_cny'] == 5
            for n in range(5):
                ws.send_json({'type': 'user.text', 'text': f'第{n}轮'})
                assert until(ws, 'assistant.done')['reply']
            ws.send_json({'type': 'call.end'})
        assert len(client.app.state.db.all('SELECT * FROM realtime_call_turns')) == 5
        assert len(client.get(f'/api/avatars/{avatar}/messages').json()) == 1


def test_early_audio_before_model_done_and_no_duplicate_synthesis(tmp_path, monkeypatch):
    release, blocked = threading.Event(), threading.Event()
    def streaming(self, messages):
        yield '第一句已经完整。'
        blocked.set()
        release.wait(5)
        yield '这是第二句。'
    invoked = stub_costs(monkeypatch)
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', streaming)
        avatar = create_avatar(client)
        try:
            with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
                started = ws.receive_json()
                ws.send_json({'type': 'user.text', 'text': '开始'})
                segment = until(ws, 'assistant.segment')
                assert blocked.wait(2)
                payload = {'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0}
                path = f"/api/avatars/{avatar}/calls/{started['call_id']}/speech"
                response = client.post(path, json=payload)
                assert response.status_code == 200, response.text
                assert not release.is_set()
                assert response.content == b'local test audio'
                assert client.post(path, json=payload).status_code == 409
                assert len(invoked) == 1 and invoked[0][0] == 'approved-voice'
                release.set()
                until(ws, 'assistant.done')
                ws.send_json({'type': 'call.end'})
        finally:
            release.set()
        stored = client.app.state.db.one('SELECT metadata_json FROM realtime_call_sessions')
        assert json.loads(stored['metadata_json'])['estimated_reserved_cny'] == .2


def test_budget_covers_chat_and_tts_before_provider_invocation(tmp_path, monkeypatch):
    invoked = stub_costs(monkeypatch, chat_cost=.4, speech_cost=.2)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?estimated_budget_cny=0.5') as ws:
            started = ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': '开始'})
            segment = until(ws, 'assistant.segment')
            response = client.post(f"/api/avatars/{avatar}/calls/{started['call_id']}/speech", json={
                'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0})
            assert response.status_code == 409
            event = until(ws, 'call.ended')
            assert event['reason'] == 'budget_limit' and event['estimated_reserved_cny'] == .4
        assert invoked == []


def test_chat_budget_is_enforced_even_without_browser_speech(tmp_path, monkeypatch):
    stub_costs(monkeypatch, chat_cost=.2)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?estimated_budget_cny=0.4') as ws:
            ws.receive_json()
            for _ in range(2):
                ws.send_json({'type': 'user.text', 'text': '继续'})
                until(ws, 'assistant.done')
            ws.send_json({'type': 'user.text', 'text': '超额'})
            assert until(ws, 'call.ended')['reason'] == 'budget_limit'
        assert len(client.app.state.db.all('SELECT * FROM realtime_call_turns')) == 2


def test_silence_still_ends_at_server_deadline(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(calls, 'CallPolicy', lambda limits: CallPolicy(limits, clock=lambda: clock[0]))
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?max_minutes=1') as ws:
            ws.receive_json()
            clock[0] = 61
            assert until(ws, 'call.ended')['reason'] == 'time_limit'


def test_interrupt_during_synthesis_ignores_old_return_and_keeps_reservation(tmp_path, monkeypatch):
    blocked, release = threading.Event(), threading.Event()
    def slow():
        blocked.set()
        release.wait(5)
    invoked = stub_costs(monkeypatch, synthesize=slow)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
            started = ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': '开始'})
            segment = until(ws, 'assistant.segment')
            until(ws, 'assistant.done')
            path = f"/api/avatars/{avatar}/calls/{started['call_id']}/speech"
            payload = {'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0}
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, path, json=payload)
                try:
                    assert blocked.wait(2)
                    ws.send_json({'type': 'call.interrupt'})
                    ws.send_json({'type': 'ping'})
                    until(ws, 'pong')
                    release.set()
                    assert future.result(timeout=3).status_code == 409
                finally:
                    release.set()
            assert client.post(path, json=payload).status_code == 409
            ws.send_json({'type': 'call.end'})
        assert len(invoked) == 1
        saved = json.loads(client.app.state.db.one('SELECT metadata_json FROM realtime_call_sessions')['metadata_json'])
        assert saved['estimated_reserved_cny'] == .2


def configured_voice(client, avatar, *, key='isolated-test-key', consent=True, enabled=True, price=.1, route=True):
    base = f'/api/avatars/{avatar}'
    voices = client.get(base + '/voice-profiles').json()
    voice = next(item for item in voices if item['voice_id'] == 'female-chengshu')
    assert client.post(base + f"/voice-profiles/{voice['id']}/select").status_code == 200
    connection = client.post('/api/provider-connections', json={
        'display_name': 'isolated-voice', 'provider_kind': 'minimax', 'api_key': key or 'isolated-test-key',
        'capabilities': ['tts'], 'consent': {'text': consent}, 'enabled': enabled,
        'models': {'tts': 'unchanged-voice-model'}, 'config': {'cost_estimates': {'tts': price}},
    }).json()
    if route:
        assert client.put('/api/capability-routes', json={
            'capability': 'tts', 'primary_connection_id': connection['id'], 'model': 'unchanged-voice-model',
        }).status_code == 200
    if not key:
        from openavatar.providers import delete_provider_key
        from openavatar.services.provider_hub import provider_key_name
        delete_provider_key(provider_key_name(connection['id']))
    return connection


@pytest.mark.parametrize('problem', ['missing-route', 'no-key', 'no-consent', 'disabled', 'no-estimate', 'voice-off'])
def test_voice_preflight_refuses_before_chat_or_session_spend(tmp_path, monkeypatch, problem):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        configured_voice(client, avatar, key='' if problem == 'no-key' else 'isolated-test-key',
                         consent=problem != 'no-consent', enabled=problem != 'disabled',
                         price=0 if problem == 'no-estimate' else .1, route=problem != 'missing-route')
        if problem == 'voice-off':
            none = next(item for item in client.get(f'/api/avatars/{avatar}/voice-profiles').json() if item['profile_kind'] == 'none')
            client.post(f"/api/avatars/{avatar}/voice-profiles/{none['id']}/select")
        invoked = []
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', lambda *_: invoked.append(True) or iter(['unexpected']))
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?voice=true') as ws:
            event = ws.receive_json()
            assert event['type'] == 'call.error' and event['fatal']
        assert not invoked
        assert not client.app.state.db.all('SELECT * FROM realtime_call_sessions')
        assert not client.app.state.db.all("SELECT * FROM usage_events WHERE operation IN ('chat','tts')")


@pytest.mark.parametrize('kind', ['builtin', 'connection-clone', 'legacy-kind', 'other-account'])
def test_voice_plan_preserves_presets_and_exact_clone_account(tmp_path, monkeypatch, kind):
    from openavatar.services.call_policy import select_call_voice
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        connection = configured_voice(client, avatar)
        db = client.app.state.db
        if kind != 'builtin':
            db.execute('UPDATE voice_profiles SET active=0 WHERE avatar_id=?', (avatar,))
            owner = connection['id'] if kind == 'connection-clone' else 'minimax' if kind == 'legacy-kind' else 'pc_different_account'
            db.execute("INSERT INTO provider_assets(avatar_id,kind,provider,external_id,created_at) VALUES(?,?,?,?,?)",
                       (avatar, 'voice', owner, 'approved-cloned-voice', 1))
        if kind == 'other-account':
            with pytest.raises(ProviderError, match='不匹配'):
                select_call_voice(db, avatar)
        else:
            plan = select_call_voice(db, avatar)
            assert plan['row']['id'] == connection['id']
            assert plan['model'] == 'unchanged-voice-model'
            assert plan['voice_id'] == ('female-chengshu' if kind == 'builtin' else 'approved-cloned-voice')


def test_voice_round_joint_estimate_blocks_chat_before_spend(tmp_path, monkeypatch):
    stub_costs(monkeypatch, chat_cost=.3)
    plan = {'row': {'id': 'test-call-provider', 'provider_kind': 'minimax', 'config_json': '{"cost_estimates":{"tts":0.1}}'},
            'model': 'unchanged-voice-model', 'voice_id': 'approved-voice', 'config': {}}
    monkeypatch.setattr(calls, 'preflight_call_voice', lambda *_: plan)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        invoked = []
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', lambda *_: invoked.append(True) or iter(['unexpected']))
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?voice=true&estimated_budget_cny=.5') as ws:
            assert ws.receive_json()['type'] == 'call.started'
            ws.send_json({'type': 'user.text', 'text': '合计不足'})
            ended = until(ws, 'call.ended')
            assert ended['reason'] == 'budget_limit' and ended['estimated_reserved_cny'] == 0
        assert not invoked
        assert not client.app.state.db.all('SELECT * FROM realtime_call_turns')


def test_joint_feasibility_check_does_not_reserve_three_unused_segments(tmp_path, monkeypatch):
    invoked = stub_costs(monkeypatch, chat_cost=.1, speech_cost=.1)
    plans = []
    plan = {'row': {'id': 'test-call-provider', 'provider_kind': 'minimax', 'config_json': '{"cost_estimates":{"tts":0.1}}'},
            'model': 'unchanged-voice-model', 'voice_id': 'approved-voice', 'config': {}}
    monkeypatch.setattr(calls, 'preflight_call_voice', lambda *_: plans.append(plan) or plan)
    monkeypatch.setattr(calls, 'select_call_voice', lambda *_: pytest.fail('voice plan must stay fixed'))
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?voice=true&estimated_budget_cny=1') as ws:
            started = ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': '开始'})
            segment = until(ws, 'assistant.segment')
            until(ws, 'assistant.done')
            response = client.post(f"/api/avatars/{avatar}/calls/{started['call_id']}/speech", json={
                'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0})
            assert response.status_code == 200
            ws.send_json({'type': 'call.end'})
        assert len(plans) == len(invoked) == 1
        saved = json.loads(client.app.state.db.one('SELECT metadata_json FROM realtime_call_sessions')['metadata_json'])
        assert saved['estimated_reserved_cny'] == .2


def test_old_speech_failure_does_not_end_new_run(tmp_path, monkeypatch):
    blocked, release = threading.Event(), threading.Event()
    def old_failure():
        blocked.set()
        release.wait(5)
        raise ProviderError('old interrupted request failed')
    stub_costs(monkeypatch, synthesize=old_failure)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
            started = ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': '旧轮'})
            segment = until(ws, 'assistant.segment')
            until(ws, 'assistant.done')
            path = f"/api/avatars/{avatar}/calls/{started['call_id']}/speech"
            payload = {'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0}
            with ThreadPoolExecutor(max_workers=1) as pool:
                old = pool.submit(client.post, path, json=payload)
                try:
                    assert blocked.wait(2)
                    ws.send_json({'type': 'call.interrupt'})
                    ws.send_json({'type': 'user.text', 'text': '新轮'})
                    new = until(ws, 'assistant.done')
                    assert new['run_id'] != segment['run_id']
                    release.set()
                    assert old.result(timeout=3).status_code == 409
                    ws.send_json({'type': 'ping'})
                    assert until(ws, 'pong')['type'] == 'pong'
                    ws.send_json({'type': 'user.text', 'text': '还能继续'})
                    until(ws, 'assistant.done')
                finally:
                    release.set()
            ws.send_json({'type': 'call.end'})
        assert len(client.app.state.db.all('SELECT * FROM realtime_call_turns')) == 3


@pytest.mark.parametrize('change', ['disable-before-chat', 'revoke-before-tts', 'raise-estimate'])
def test_active_voice_plan_rechecks_same_connection_permissions_and_price(tmp_path, monkeypatch, change):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        connection = configured_voice(client, avatar)
        db = client.app.state.db
        invoked = []
        monkeypatch.setattr(calls, 'synthesize_call_segment', lambda *_: invoked.append(True))
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?voice=true&estimated_budget_cny=.5') as ws:
            started = ws.receive_json()
            assert started['type'] == 'call.started'
            if change == 'revoke-before-tts':
                ws.send_json({'type': 'user.text', 'text': '开始'})
                segment = until(ws, 'assistant.segment')
                until(ws, 'assistant.done')
                db.execute('UPDATE provider_connections SET consent_json=? WHERE id=?', ('{"text":false}', connection['id']))
                response = client.post(f"/api/avatars/{avatar}/calls/{started['call_id']}/speech", json={
                    'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0})
                assert response.status_code == 502
            else:
                if change == 'raise-estimate':
                    db.execute('UPDATE provider_connections SET config_json=? WHERE id=?', ('{"cost_estimates":{"tts":0.2}}', connection['id']))
                else:
                    db.execute('UPDATE provider_connections SET enabled=0 WHERE id=?', (connection['id'],))
                ws.send_json({'type': 'user.text', 'text': '不应调用'})
            ended = until(ws, 'call.ended')
            assert ended['estimated_reserved_cny'] == 0
        assert not invoked
        assert len(db.all('SELECT * FROM realtime_call_turns')) == (1 if change == 'revoke-before-tts' else 0)


@pytest.mark.parametrize('outcome', ['interrupted', 'failed'])
def test_pending_speech_counts_towards_connection_budget_before_completion(tmp_path, monkeypatch, outcome):
    from openavatar.services.provider_hub import assert_allowed, connection_row
    blocked, release = threading.Event(), threading.Event()

    def slow_speech():
        blocked.set()
        release.wait(5)
        if outcome == 'failed':
            raise ProviderError('isolated provider failure')

    invoked = stub_costs(monkeypatch, synthesize=slow_speech)
    monkeypatch.setattr(calls, 'assert_allowed', assert_allowed)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        connection = configured_voice(client, avatar)
        db = client.app.state.db
        # One reply costs .1, up to three speech segments cost .3. A pending
        # segment must count, even after interruption, before the next .4 check.
        db.execute('UPDATE provider_connections SET budget_json=? WHERE id=?',
                   ('{"daily":0.51}', connection['id']))
        row = connection_row(db, connection['id'])
        monkeypatch.setattr(calls, 'select_call_chat', lambda prepared: (prepared['client'], row, .1))
        with client.websocket_connect(f'/ws/avatars/{avatar}/call?voice=true') as ws:
            started = ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': '第一轮'})
            segment = until(ws, 'assistant.segment')
            until(ws, 'assistant.done')
            payload = {'token': started['token'], 'run_id': segment['run_id'], 'segment_id': 0}
            path = f"/api/avatars/{avatar}/calls/{started['call_id']}/speech"
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(client.post, path, json=payload)
                try:
                    assert blocked.wait(2)
                    reserved = db.one("SELECT * FROM usage_events WHERE operation='tts'")
                    assert reserved and reserved['status'] == 'reserved'
                    assert reserved['estimated_cost'] == .1
                    ws.send_json({'type': 'call.interrupt'})
                    ws.send_json({'type': 'user.text', 'text': '第二轮'})
                    while True:
                        event = ws.receive_json()
                        if event['type'] in {'call.ended', 'assistant.done'}:
                            break
                    assert event['type'] == 'call.ended', event
                    assert '预算' in event['message']
                    release.set()
                    assert pending.result(timeout=3).status_code == 409
                finally:
                    release.set()
        records = db.all("SELECT * FROM usage_events WHERE json_extract(metadata_json,'$.estimate_reserved')=1 ORDER BY id")
        assert len(records) == 2, 'update each reservation rather than inserting a second expense'
        assert [record['status'] for record in records] == ['ok', 'interrupted_or_failed']
        assert sum(record['estimated_cost'] for record in records) == .2
        assert len(invoked) == 1
        assert len(db.all('SELECT * FROM realtime_call_turns')) == 1

        from openavatar.services.provider_hub import _spent
        package = client.post(f'/api/avatars/{avatar}/export')
        imported = client.post('/api/packages/import', content=package.content, headers={
            'Content-Type': 'application/zip', 'X-File-Name': 'call-budget.zip', 'X-Rights-Confirmed': 'true'})
        assert imported.status_code == 201, imported.text
        assert _spent(db, connection['id'], 0) == .2
        copied = db.all("SELECT * FROM usage_events WHERE avatar_id=? AND json_extract(metadata_json,'$.estimate_reserved')=1",
                        (imported.json()['id'],))
        assert len(copied) == 2
        assert all(json.loads(record['metadata_json'])['imported_history'] for record in copied)


def test_interrupted_chat_updates_existing_pending_reservation(tmp_path, monkeypatch):
    blocked, release = threading.Event(), threading.Event()

    def slow_reply(self, messages):
        yield '开头'
        blocked.set()
        release.wait(5)
        yield '旧回复'

    stub_costs(monkeypatch, chat_cost=.3)
    monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', slow_reply)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        try:
            with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
                ws.receive_json()
                ws.send_json({'type': 'user.text', 'text': '开始'})
                until(ws, 'assistant.delta')
                assert blocked.wait(2)
                record = db.one('SELECT * FROM usage_events')
                assert record['status'] == 'reserved' and record['estimated_cost'] == .3
                ws.send_json({'type': 'call.interrupt'})
                until(ws, 'assistant.interrupted')
                ws.send_json({'type': 'ping'})
                until(ws, 'pong')
                completed = db.one('SELECT * FROM usage_events')
                assert completed['id'] == record['id']
                assert completed['status'] == 'interrupted_or_failed'
                assert completed['estimated_cost'] == .3
                assert len(db.all('SELECT * FROM usage_events')) == 1
                ws.send_json({'type': 'call.end'})
        finally:
            release.set()
