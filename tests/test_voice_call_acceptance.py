import threading
from concurrent.futures import ThreadPoolExecutor

from test_runtime import FakeStreamingProvider, create_avatar, make_client


def test_voice_text_gateway_enforces_80_chars_and_echoes_turn_id(tmp_path, monkeypatch):
    class LongReply(FakeStreamingProvider):
        def stream_chat(self, messages):
            yield '甲' * 60
            yield '乙' * 60
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', LongReply.stream_chat)
        avatar = create_avatar(client)
        with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
            ws.receive_json()
            ws.send_json({'type':'user.text','text':'你好','client_turn_id':'turn-1'})
            assert ws.receive_json()['client_turn_id'] == 'turn-1'
            chunks = []
            while True:
                event = ws.receive_json()
                if event['type'] == 'assistant.delta': chunks.append(event['text'])
                if event['type'] == 'assistant.done': break
            assert len(event['reply']) == 80
            assert ''.join(chunks) == event['reply']
            ws.send_json({'type':'call.end'})
        row = client.app.state.db.one('SELECT assistant_text FROM realtime_call_turns WHERE avatar_id=?', (avatar,))
        assert len(row['assistant_text']) == 80
        messages = client.get(f'/api/avatars/{avatar}/messages').json()
        assert len(messages) == 1
        assert messages[0]['message_kind'] == 'call'
        db = client.app.state.db
        saved = db.all("SELECT * FROM messages WHERE avatar_id=? AND channel='voice_call'", (avatar,))
        assert len(saved) == 2
        # Simulate the previous release, then verify upgrade preserves content.
        db.execute("UPDATE messages SET channel='chat' WHERE avatar_id=? AND channel='voice_call'", (avatar,))
        db.initialize()
        assert len(client.get(f'/api/avatars/{avatar}/messages').json()) == 1
        assert len(db.all("SELECT * FROM messages WHERE avatar_id=? AND channel='voice_call'", (avatar,))) == 2


def test_interrupt_does_not_wait_for_blocking_provider_or_save_stale_reply(tmp_path, monkeypatch):
    blocked = threading.Event()
    release = threading.Event()
    class SlowReply(FakeStreamingProvider):
        def stream_chat(self, messages):
            yield '开头'
            blocked.set()
            release.wait(10)
            yield '不应保存的旧回复'
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', SlowReply.stream_chat)
        avatar = create_avatar(client)
        try:
            with client.websocket_connect(f'/ws/avatars/{avatar}/call') as ws:
                ws.receive_json()
                ws.send_json({'type':'user.text','text':'开始'})
                assert ws.receive_json()['type'] == 'user.committed'
                assert ws.receive_json()['type'] == 'assistant.delta'
                assert blocked.wait(2)
                ws.send_json({'type':'call.interrupt'})
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(ws.receive_json)
                    try:
                        assert future.result(timeout=2)['type'] == 'assistant.interrupted'
                    finally:
                        release.set()
                ws.send_json({'type':'ping'})
                assert ws.receive_json()['type'] == 'pong'
                ws.send_json({'type':'call.end'})
        finally:
            release.set()
        assert not client.app.state.db.all('SELECT * FROM realtime_call_turns WHERE avatar_id=?', (avatar,))
        assert not client.app.state.db.all("SELECT * FROM messages WHERE avatar_id=? AND message_kind<>'call'", (avatar,))
        assert len(client.app.state.db.all("SELECT * FROM messages WHERE avatar_id=? AND message_kind='call'", (avatar,))) == 1
