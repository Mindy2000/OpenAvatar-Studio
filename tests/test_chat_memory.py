"""Explicit note controls preserve history but remove stale facts from model input."""
import io
import json
import zipfile

from test_runtime import FakeStreamingProvider, create_avatar, make_client


def act(client, avatar, message, action, content='', **extra):
    return client.post(f'/api/avatars/{avatar}/messages/{message}/memory', json={
        'action': action, 'content': content, 'confirmed': True, **extra,
    })


def messages(client, avatar, preview=False):
    return client.get(f'/api/avatars/{avatar}/messages', params={'timeline_kind': 'preview' if preview else 'official'}).json()


def test_confirmed_notes_correct_and_forget_real_context(tmp_path, monkeypatch):
    captured = []
    def reply(self, rows, **kwargs):
        captured.append(rows)
        return '收到，我们下次再聊。'
    monkeypatch.setattr(FakeStreamingProvider, 'chat', reply)
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '我的学校是旧校名A'}).raise_for_status()
        row = messages(client, avatar)[0]
        endpoint = f'/api/avatars/{avatar}/messages/{row["id"]}/memory'
        assert client.post(endpoint, json={'action': 'remember', 'content': row['content']}).status_code == 400
        for _ in range(2):
            result = act(client, avatar, row['id'], 'remember', row['content'])
            assert result.status_code == 200, result.text
            assert result.json()['remembered'] and result.json()['cloud_calls'] == 0
        db = client.app.state.db
        assert db.one('SELECT COUNT(*) n FROM memories WHERE source_message_id=?', (row['id'],))['n'] == 1
        result = act(client, avatar, row['id'], 'correct', '我的学校是新校名B')
        assert result.status_code == 200, result.text
        assert result.json()['context_excluded']
        assert all(item['context_excluded'] for item in messages(client, avatar))
        assert messages(client, avatar)[0]['content'] == '我的学校是旧校名A'
        assert len(captured) == 1  # memory actions themselves do not call any provider
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '我的学校是哪所？'}).raise_for_status()
        prompt = json.dumps(captured[-1], ensure_ascii=False)
        assert '新校名B' in prompt and '旧校名A' not in prompt
        act(client, avatar, row['id'], 'forget').raise_for_status()
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '我的学校是哪所？'}).raise_for_status()
        prompt = json.dumps(captured[-1], ensure_ascii=False)
        assert '新校名B' not in prompt and '旧校名A' not in prompt
        assert not client.get(endpoint).json()['remembered']
        graph = db.all('SELECT label FROM memory_graph_nodes WHERE avatar_id=?', (avatar,))
        assert not any('校名' in r['label'] for r in graph)


def test_memory_scope_preview_ownership_and_nontext(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **_: captured.append(rows) or '好的。')
    with make_client(tmp_path, monkeypatch) as client:
        avatar, other = create_avatar(client), create_avatar(client)
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '预览秘密X', 'preview_mode': True}).raise_for_status()
        row = messages(client, avatar, True)[0]
        assert act(client, avatar, row['id'], 'remember', '预览秘密X').status_code == 404
        assert act(client, other, row['id'], 'remember', '预览秘密X', preview_mode=True).status_code == 404
        act(client, avatar, row['id'], 'remember', '预览秘密X', preview_mode=True).raise_for_status()
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '你记得什么？'}).raise_for_status()
        assert '预览秘密X' not in json.dumps(captured[-1], ensure_ascii=False)
        client.post(f'/api/avatars/{avatar}/chat', json={'message': '你记得什么？', 'preview_mode': True}).raise_for_status()
        assert '预览秘密X' in json.dumps(captured[-1], ensure_ascii=False)
        db = client.app.state.db
        for kind, channel, content, code in [('image', 'chat', '[图片]', 400), ('text', 'voice_call', '通话', 404), ('audio', 'chat', '[语音]', 400)]:
            mid = db.execute('INSERT INTO messages(avatar_id,role,content,channel,message_kind,created_at) VALUES(?,?,?,?,?,0)', (avatar, 'user', content, channel, kind))
            assert act(client, avatar, mid, 'remember', content).status_code == code


def test_memory_package_keeps_exclusion_and_source_link(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        client.post(f'/api/avatars/{avatar}/chat', json={'message': 'NOTE_PRIVATE_123'}).raise_for_status()
        row = messages(client, avatar)[0]
        act(client, avatar, row['id'], 'correct', 'NOTE_PRIVATE_CORRECTED').raise_for_status()
        package = client.post(f'/api/avatars/{avatar}/export')
        package.raise_for_status()
        imported = client.post('/api/packages/import', content=package.content, headers={
            'Content-Type': 'application/zip', 'X-File-Name': 'avatar.openavatar.zip', 'X-Rights-Confirmed': 'true',
        })
        imported.raise_for_status()
        new_avatar = imported.json()['id']
        new_row = messages(client, new_avatar)[0]
        assert new_row['id'] != row['id'] and new_row['context_excluded'] and new_row['remembered']
        state = client.get(f'/api/avatars/{new_avatar}/messages/{new_row["id"]}/memory').json()
        assert state['memory']['content'] == 'NOTE_PRIVATE_CORRECTED'
        act(client, new_avatar, new_row['id'], 'forget').raise_for_status()
        assert not messages(client, new_avatar)[0]['remembered']
        private = client.post(f'/api/avatars/{avatar}/export?include_conversations=false&include_call_history=false')
        with zipfile.ZipFile(io.BytesIO(private.content)) as archive:
            assert all(b'NOTE_PRIVATE' not in archive.read(name) for name in archive.namelist())


def test_merged_notes_forget_transitively_after_package_import(tmp_path, monkeypatch):
    from openavatar.services.memory_intelligence import merge_memories, sleep_consolidation
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        source_ids, note_ids = [], []
        for content in ['NOTE_A', 'FORGET_FACT_B', 'NOTE_C']:
            mid = db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,'user',?,'chat',0)", (avatar, content))
            source_ids.append(mid)
            response = act(client, avatar, mid, 'remember', content)
            response.raise_for_status()
            note_ids.append(response.json()['memory']['id'])
        sleep_consolidation(db, avatar)
        assert not db.one("SELECT id FROM memories WHERE avatar_id=? AND kind='consolidated_summary'", (avatar,))
        merge_memories(db, avatar, note_ids[0], note_ids[1])
        merge_memories(db, avatar, note_ids[2], note_ids[0])
        state = client.get(f'/api/avatars/{avatar}/messages/{source_ids[1]}/memory').json()
        assert state['merged_dependents'] == 1
        package = client.post(f'/api/avatars/{avatar}/export')
        imported = client.post('/api/packages/import', content=package.content, headers={
            'Content-Type': 'application/zip', 'X-File-Name': 'avatar.openavatar.zip', 'X-Rights-Confirmed': 'true',
        })
        imported.raise_for_status()
        new_avatar = imported.json()['id']
        new_source = next(row for row in messages(client, new_avatar) if row['content'] == 'FORGET_FACT_B')
        state = client.get(f'/api/avatars/{new_avatar}/messages/{new_source["id"]}/memory').json()
        assert state['merged_dependents'] == 1
        act(client, avatar, source_ids[1], 'forget').raise_for_status()
        act(client, new_avatar, new_source['id'], 'correct', 'CORRECTED_FACT_B').raise_for_status()
        for aid in (avatar, new_avatar):
            active = db.all("SELECT content FROM memories WHERE avatar_id=? AND confidence>0", (aid,))
            assert all('FORGET_FACT_B' not in row['content'] for row in active)
        assert db.one("SELECT id FROM memories WHERE avatar_id=? AND content='CORRECTED_FACT_B' AND confidence>0", (new_avatar,))


def test_explicit_note_cannot_leak_via_legacy_consolidation_or_preview_merge(tmp_path, monkeypatch):
    import pytest
    from openavatar.services.memory_intelligence import merge_memories, sleep_consolidation
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        official = db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,'user','可撤回事实','chat',0)", (avatar,))
        preview = db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,'user','预览事实','preview',0)", (avatar,))
        first = act(client, avatar, official, 'remember', '可撤回事实').json()['memory']['id']
        second = act(client, avatar, preview, 'remember', '预览事实', preview_mode=True).json()['memory']['id']
        with pytest.raises(ValueError, match='预览'):
            merge_memories(db, avatar, first, second)
        legacy = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户确认','旧资料','imported',0)", (avatar,))
        merge_memories(db, avatar, legacy, first)
        sleep_consolidation(db, avatar)
        assert not db.one("SELECT id FROM memories WHERE avatar_id=? AND kind='consolidated_summary' AND content LIKE '%可撤回事实%'", (avatar,))
        act(client, avatar, official, 'forget').raise_for_status()
        assert not db.one("SELECT id FROM memories WHERE avatar_id=? AND confidence>0 AND content LIKE '%可撤回事实%'", (avatar,))
