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


def test_private_export_omits_chat_notes_merged_into_other_memory_kinds(tmp_path, monkeypatch):
    from openavatar.services.memory_intelligence import merge_memories
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        marker = 'PRIVATE_MERGED_CHAT_7520'
        client.post(f'/api/avatars/{avatar}/chat', json={'message': marker}).raise_for_status()
        source = messages(client, avatar)[0]['id']
        note = act(client, avatar, source, 'remember', marker).json()['memory']['id']
        primary = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','公开校园事实','fact',0)", (avatar,))
        parent = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','公开课程事实','fact',0)", (avatar,))
        unrelated = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','独立保留的事实','fact',0)", (avatar,))
        merge_memories(db, avatar, primary, note)
        merge_memories(db, avatar, parent, primary)
        full = client.post(f'/api/avatars/{avatar}/export')
        with zipfile.ZipFile(io.BytesIO(full.content)) as archive:
            assert marker.encode() in archive.read('memories.json')
        private = client.post(f'/api/avatars/{avatar}/export?include_conversations=false&include_call_history=false')
        private.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(private.content)) as archive:
            assert all(marker.encode() not in archive.read(name) for name in archive.namelist())
            exported = json.loads(archive.read('memories.json'))
            assert [row['id'] for row in exported] == [unrelated]
        # The private source must stay traceable even after rollback deletes it.
        base = f'/api/avatars/{avatar}'
        preview = client.post(base + '/timeline/preview-change', json={'timeline_kind': 'official', 'action': 'delete', 'message_id': source}).json()
        client.post(base + '/timeline/apply-change', json={'preview_token': preview['preview_token']}).raise_for_status()
        assert db.one('SELECT id FROM memories WHERE id=?', (note,)) is None
        private = client.post(base + '/export?include_conversations=false&include_call_history=false')
        private.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(private.content)) as archive:
            assert all(marker.encode() not in archive.read(name) for name in archive.namelist())
            assert [row['id'] for row in json.loads(archive.read('memories.json'))] == [unrelated]
        package = client.post(base + '/export')
        imported = client.post('/api/packages/import', content=package.content, headers={
            'Content-Type': 'application/zip', 'X-File-Name': 'avatar.openavatar.zip', 'X-Rights-Confirmed': 'true',
        })
        imported.raise_for_status()
        private = client.post(f"/api/avatars/{imported.json()['id']}/export?include_conversations=false&include_call_history=false")
        private.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(private.content)) as archive:
            assert all(marker.encode() not in archive.read(name) for name in archive.namelist())
            assert [row['content'] for row in json.loads(archive.read('memories.json'))] == ['独立保留的事实']


def test_maintenance_edit_and_reject_remove_stale_chat_context_and_merged_copies(tmp_path, monkeypatch):
    from openavatar.services.memory_intelligence import merge_memories
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **_: captured.append(rows) or '好的。')
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        for action in ['edit', 'reject']:
            old_fact, new_fact = f'OLD_MAINTENANCE_{action}', f'NEW_MAINTENANCE_{action}'
            client.post(f'/api/avatars/{avatar}/chat', json={'message': old_fact}).raise_for_status()
            source = messages(client, avatar)[-2]['id']
            note = act(client, avatar, source, 'remember', old_fact).json()['memory']['id']
            parent = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','校园事实','fact',0)", (avatar,))
            merge_memories(db, avatar, parent, note)
            # The source is already merged; editing it is possible in the existing maintenance page.
            if action == 'edit':
                response = client.patch(f'/api/avatars/{avatar}/memories/{note}', json={'content': new_fact, 'kind': 'chat_note', 'confidence': 1})
            else:
                response = client.post(f'/api/avatars/{avatar}/memories/{note}/review', json={'action': 'reject'})
            response.raise_for_status()
            client.post(f'/api/avatars/{avatar}/chat', json={'message': '你现在记得什么？'}).raise_for_status()
            prompt = json.dumps(captured[-1], ensure_ascii=False)
            assert old_fact not in prompt
            assert (new_fact in prompt) == (action == 'edit')
            assert db.one('SELECT context_excluded FROM messages WHERE id=?', (source,))['context_excluded']
            assert db.one('SELECT confidence FROM memories WHERE id=?', (parent,))['confidence'] == 0


def test_timeline_removes_merged_chat_facts_and_restores_without_reviving_stopped_notes(tmp_path, monkeypatch):
    from openavatar.services.memory_intelligence import merge_memories
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **_: captured.append(rows) or '好的。')
    with make_client(tmp_path, monkeypatch) as client:
        for baseline in (False, True):
            for stop_before_restore in (False, True):
                avatar = create_avatar(client)
                db = client.app.state.db
                base = f'/api/avatars/{avatar}'
                note_ids, source_ids = [], []
                for text in ('EARLY_FACT_A', 'REMOVED_FACT_B'):
                    client.post(base + '/chat', json={'message': text}).raise_for_status()
                    source_ids.append(messages(client, avatar)[-2]['id'])
                    note_ids.append(act(client, avatar, source_ids[-1], 'remember', text).json()['memory']['id'])
                primary = note_ids[0]
                if baseline:
                    primary = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','独立校园事实','fact',0)", (avatar,))
                merge_memories(db, avatar, primary, note_ids[1])
                # Preview notes must survive all changes to the official branch.
                preview_source = db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,'user','PREVIEW_FACT_C','preview',0)", (avatar,))
                preview_note = act(client, avatar, preview_source, 'remember', 'PREVIEW_FACT_C', preview_mode=True).json()['memory']['id']
                preview = client.post(base + '/timeline/preview-change', json={'timeline_kind': 'official', 'action': 'delete', 'message_id': source_ids[1]}).json()
                changed = client.post(base + '/timeline/apply-change', json={'preview_token': preview['preview_token']})
                changed.raise_for_status()
                client.post(base + '/chat', json={'message': '你现在记得什么？'}).raise_for_status()
                assert 'REMOVED_FACT_B' not in json.dumps(captured[-1], ensure_ascii=False)
                if stop_before_restore:
                    if baseline:
                        client.post(base + f'/memories/{primary}/review', json={'action': 'reject'}).raise_for_status()
                    else:
                        act(client, avatar, source_ids[0], 'forget').raise_for_status()
                client.post(base + '/timeline/restore', json={'branch_id': changed.json()['frozen_branch_id']}).raise_for_status()
                client.post(base + '/chat', json={'message': '你现在记得什么？'}).raise_for_status()
                prompt = json.dumps(captured[-1], ensure_ascii=False)
                assert db.one('SELECT confidence FROM memories WHERE id=?', (primary,))['confidence'] == (0 if stop_before_restore else 1)
                assert ('REMOVED_FACT_B' in prompt) == (not stop_before_restore)
                assert 'PREVIEW_FACT_C' not in prompt
                assert db.one('SELECT confidence FROM memories WHERE id=?', (preview_note,))['confidence'] == 1


def test_restoring_snapshot_does_not_revive_stopped_message_without_saved_note(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(FakeStreamingProvider, 'chat', lambda self, rows, **_: captured.append(rows) or '好的。')
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        base = f'/api/avatars/{avatar}'
        for text in ('STOP_WITHOUT_NOTE_1427', '待删除后续消息'):
            client.post(base + '/chat', json={'message': text}).raise_for_status()
        rows = messages(client, avatar)
        preview = client.post(base + '/timeline/preview-change', json={'timeline_kind': 'official', 'action': 'delete', 'message_id': rows[-2]['id']}).json()
        changed = client.post(base + '/timeline/apply-change', json={'preview_token': preview['preview_token']}).json()
        act(client, avatar, rows[0]['id'], 'forget').raise_for_status()
        client.post(base + '/timeline/restore', json={'branch_id': changed['frozen_branch_id']}).raise_for_status()
        client.post(base + '/chat', json={'message': '你现在记得什么？'}).raise_for_status()
        assert 'STOP_WITHOUT_NOTE_1427' not in json.dumps(captured[-1], ensure_ascii=False)
        restored = messages(client, avatar)
        assert all(row['context_excluded'] for row in restored[:2])


def test_restore_before_new_merge_keeps_independent_fact(tmp_path, monkeypatch):
    from openavatar.services.memory_intelligence import merge_memories
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        base = f'/api/avatars/{avatar}'
        primary = db.execute("INSERT INTO memories(avatar_id,speaker,content,kind,created_at) VALUES(?,'用户','独立校园事实','fact',0)", (avatar,))
        client.post(base + '/chat', json={'message': '封存前的普通聊天'}).raise_for_status()
        preview = client.post(base + '/timeline/preview-change', json={'timeline_kind': 'official', 'action': 'delete', 'message_id': messages(client, avatar)[0]['id']}).json()
        frozen = client.post(base + '/timeline/apply-change', json={'preview_token': preview['preview_token']}).json()['frozen_branch_id']
        client.post(base + '/chat', json={'message': 'NEW_BRANCH_PRIVATE_FACT'}).raise_for_status()
        note = act(client, avatar, messages(client, avatar)[0]['id'], 'remember', 'NEW_BRANCH_PRIVATE_FACT').json()['memory']['id']
        merge_memories(db, avatar, primary, note)
        restored = client.post(base + '/timeline/restore', json={'branch_id': frozen})
        restored.raise_for_status()
        row = db.one('SELECT content,confidence FROM memories WHERE id=?', (primary,))
        assert row == {'content': '独立校园事实', 'confidence': 1}
        # Switching back must recover the saved merged branch as well.
        client.post(base + '/timeline/restore', json={'branch_id': restored.json()['frozen_branch_id']}).raise_for_status()
        row = db.one('SELECT content,confidence FROM memories WHERE id=?', (primary,))
        assert row == {'content': '独立校园事实\nNEW_BRANCH_PRIVATE_FACT', 'confidence': 1}
