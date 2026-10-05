import io
import json
import zipfile

import pytest

from test_runtime import FakeStreamingProvider, create_avatar, make_client


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('preview', [False, True])
def test_text_limit_applies_before_delivery_and_persistence(tmp_path, monkeypatch, stream, preview):
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda *a, **k: '甲' * 120)
    def chunks(*args):
        yield '甲' * 60
        yield '甲' * 60
        raise AssertionError('Do not consume more output after the limit')
    monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', chunks)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        response = client.post(f'/api/avatars/{avatar}/chat' + ('/stream' if stream else ''),
                               json={'message': '请简短回复', 'preview_mode': preview})
        assert response.status_code == 200
        if stream:
            events = [json.loads(line) for line in response.text.splitlines()]
            reply = events[-1]['reply']
            assert ''.join(e['text'] for e in events if e['type'] == 'delta') == reply
        else:
            reply = response.json()['reply']
        assert reply == '甲' * 80
        db = client.app.state.db
        assert db.one("SELECT content FROM messages WHERE avatar_id=? AND role='assistant'", (avatar,))['content'] == reply
        assert db.one('SELECT output_summary FROM decision_explanations WHERE avatar_id=?', (avatar,))['output_summary'] == reply


def test_call_history_and_export_boundaries_preserve_regular_messages(tmp_path, monkeypatch):
    marker = 'CALL_ONLY_SENTINEL_7f4a'
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '保留普通消息'})
        with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
            ws.receive_json()
            ws.send_json({'type': 'user.text', 'text': marker})
            while ws.receive_json()['type'] != 'assistant.done':
                pass
            ws.send_json({'type': 'call.end'})
        db = client.app.state.db
        db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at,message_kind) VALUES(?,?,?,?,?,?)",
                   (avatar, 'user', '保留语音消息', 'chat', 1, 'audio'))
        db.execute("UPDATE messages SET attachment_json=? WHERE avatar_id=? AND message_kind='audio'",
                   (json.dumps({'stored_name': 'voice.webm'}), avatar))
        voice = tmp_path / 'avatars' / avatar / 'chat-attachments' / 'voice.webm'
        voice.parent.mkdir(parents=True, exist_ok=True)
        voice.write_bytes(b'voice note')
        for layer in ['runtime', 'all']:
            result = client.get(f'/api/avatars/{avatar}/history?layer={layer}&limit=500').json()
            assert not any(r.get('channel') == 'voice_call' for r in result['items'])
            assert any(r['content'] == '保留语音消息' for r in result['items'])
            assert any('语音通话' in r['content'] for r in result['items'])
            assert client.get(f'/api/avatars/{avatar}/history?layer={layer}&q={marker}').json()['total'] == 0
        assert len(db.all("SELECT * FROM messages WHERE avatar_id=? AND channel='voice_call'", (avatar,))) == 2
        # Legacy generated audio has no call provenance. Private exports omit it.
        audio = tmp_path / 'avatars' / avatar / 'generated' / 'audio' / 'legacy.mp3'
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(marker.encode())
        for include in [True, False]:
            response = client.post(f'/api/avatars/{avatar}/export?include_call_history={str(include).lower()}')
            assert response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                messages = json.loads(archive.read('messages.json'))
                assert any(r['content'] == '保留普通消息' for r in messages)
                assert any(r['content'] == '保留语音消息' for r in messages)
                assert any(r['channel'] == 'voice_call' for r in messages) is include
                assert any(r['message_kind'] == 'call' for r in messages) is include
                assert bool(json.loads(archive.read('realtime_call_turns.json'))) is include
                assert any(marker.encode() in archive.read(name) for name in archive.namelist()) is include
