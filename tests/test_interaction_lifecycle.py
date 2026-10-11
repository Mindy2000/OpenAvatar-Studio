"""Races use temporary DBs, fake providers and deterministic barriers; no paid calls."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_runtime import make_client, create_avatar
from test_chat_vision import configure, image_message
from openavatar.services import chat_vision, proactive_runtime
from openavatar.providers import ProviderError


def mutate(client, avatar, row, action='delete', replacement='corrected description'):
    base = f'/api/avatars/{avatar}/timeline'
    preview = client.post(base + '/preview-change', json={'action': action, 'message_id': row['id'], 'timeline_kind': 'official', 'replacement_text': replacement})
    assert preview.status_code == 200, preview.text
    result = client.post(base + '/apply-change', json={'preview_token': preview.json()['preview_token']})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize('change', ['delete', 'edit', 'exclude', 'restore'])
def test_pending_image_cannot_revive_changed_source(tmp_path, monkeypatch, change):
    blocked, release = threading.Event(), threading.Event()
    def provider(*args, **kwargs):
        blocked.set(); assert release.wait(5)
        return json.dumps({'description': 'original scene', 'reply': 'late response'})
    monkeypatch.setattr(chat_vision.VisionClient, 'chat', provider)
    with make_client(tmp_path, monkeypatch) as c:
        avatar = create_avatar(c); connection = configure(c, avatar); row = image_message(c, avatar)
        db = c.app.state.db
        db.execute('UPDATE provider_connections SET config_json=? WHERE id=?', (json.dumps({'cost_estimates': {'vision': 0.05}}), connection['id']))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(c.post, f'/api/avatars/{avatar}/messages/{row["id"]}/understand', json={'confirm_billable_call': True})
            try:
                assert blocked.wait(2)
                if change == 'exclude':
                    db.execute('UPDATE messages SET context_excluded=1 WHERE id=?', (row['id'],))
                else:
                    changed = mutate(c, avatar, row, 'edit' if change == 'edit' else 'delete')
                    if change == 'restore':
                        from openavatar.services.timeline_archive import restore_branch
                        restore_branch(db, avatar, changed['frozen_branch_id'])
                release.set(); result = pending.result(3)
            finally:
                release.set()
        assert result.status_code == 409, result.text
        assert not db.all("SELECT * FROM messages WHERE avatar_id=? AND role='assistant'", (avatar,))
        usage = db.all("SELECT * FROM usage_events WHERE avatar_id=? AND operation='vision'", (avatar,))
        assert len(usage) == 1 and usage[0]['status'] == 'interrupted'
        assert usage[0]['estimated_cost'] > 0


def test_image_cache_invalidated_by_source_or_reply_change(tmp_path, monkeypatch):
    seen = []
    def provider(*args, **kwargs):
        seen.append(1)
        return json.dumps({'description': 'scene', 'reply': f'reply {len(seen)}'})
    monkeypatch.setattr(chat_vision.VisionClient, 'chat', provider)
    with make_client(tmp_path, monkeypatch) as c:
        avatar = create_avatar(c); configure(c, avatar); row = image_message(c, avatar)
        path = f'/api/avatars/{avatar}/messages/{row["id"]}/understand'
        assert c.post(path, json={'confirm_billable_call': True}).status_code == 200
        assert c.post(path, json={'confirm_billable_call': True}).json()['cached'] is True
        mutate(c, avatar, row, 'edit')
        source = c.get(f'/api/avatars/{avatar}/messages').json()[0]
        assert source['attachment'].get('vision', {}).get('status') != 'done'
        new = c.post(path, json={'confirm_billable_call': True})
        assert new.json()['cached'] is False and new.json()['reply'] == 'reply 2'
        reply_id = c.app.state.db.one('SELECT MAX(id) id FROM messages WHERE avatar_id=?', (avatar,))['id']
        c.app.state.db.execute('DELETE FROM messages WHERE id=?', (reply_id,))
        assert c.post(path, json={'confirm_billable_call': True}).json()['reply'] == 'reply 3'
        assert len(seen) == 3


def test_parallel_image_clicks_make_one_provider_attempt(tmp_path, monkeypatch):
    blocked, release = threading.Event(), threading.Event()
    calls = []
    def provider(*args, **kwargs):
        calls.append(1); blocked.set(); assert release.wait(5)
        return json.dumps({'description': 'scene', 'reply': 'one reply'})
    monkeypatch.setattr(chat_vision.VisionClient, 'chat', provider)
    with make_client(tmp_path, monkeypatch) as c:
        avatar = create_avatar(c); configure(c, avatar); row = image_message(c, avatar)
        path = f'/api/avatars/{avatar}/messages/{row["id"]}/understand'
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(c.post, path, json={'confirm_billable_call': True})
            try:
                assert blocked.wait(2)
                assert c.post(path, json={'confirm_billable_call': True}).status_code == 409
                release.set(); assert pending.result(3).status_code == 200
            finally:
                release.set()
        assert len(calls) == 1


def setup_proactive(c, *, daily=10):
    avatar = create_avatar(c)
    response = c.put(f'/api/avatars/{avatar}/proactive-settings', json={
        'proactive_enabled': True, 'proactive_interval_minutes': 360, 'daily_max': daily,
        'allowed_windows': [], 'quiet_hours': {}, 'use_long_term_memory': True})
    assert response.status_code == 200, response.text
    return avatar


def tick(c, provider):
    asyncio.run(proactive_runtime.proactive_tick(c.app, completion_report=lambda *_: {'can_start_official': True}, model_client=lambda *_: provider))


def test_proactive_settings_validate_all_before_any_update(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        avatar = create_avatar(c)
        response = c.put(f'/api/avatars/{avatar}/proactive-settings', json={'proactive_enabled': True, 'proactive_interval_minutes': 360, 'daily_max': 25})
        assert response.status_code == 422
        assert c.get(f'/api/avatars/{avatar}').json()['proactive_enabled'] is False
        assert not c.app.state.db.all('SELECT * FROM proactive_attempts')


def test_failed_proactive_attempts_obey_interval_pause_and_manual_resume(tmp_path, monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr(proactive_runtime.time, 'time', lambda: now[0])
    monkeypatch.setattr(proactive_runtime, 'proactive_time_allowed', lambda *_: True)
    calls = []
    class Failure:
        def available(self): return True
        def chat(self, messages): calls.append(messages); raise ProviderError('private error details')
    with make_client(tmp_path, monkeypatch) as c:
        avatar = setup_proactive(c)
        for _ in range(3): tick(c, Failure())
        assert len(calls) == 1
        now[0] += 360*60; tick(c, Failure())
        now[0] += 360*60; tick(c, Failure())
        now[0] += 360*60; tick(c, Failure())
        assert len(calls) == 3
        runtime = c.get(f'/api/avatars/{avatar}/proactive-rules').json()['runtime']
        assert runtime['paused'] == 1 and runtime['consecutive_failures'] == 3
        assert 'private' not in runtime['last_attempt']['error']
        assert c.put(f'/api/avatars/{avatar}/proactive-rules', json={'daily_max': 10, 'allowed_windows': [], 'quiet_hours': {}}).status_code == 200
        tick(c, Failure()); assert len(calls) == 4


def test_failed_attempts_count_toward_daily_limit(tmp_path, monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr(proactive_runtime.time, 'time', lambda: now[0])
    monkeypatch.setattr(proactive_runtime, 'proactive_time_allowed', lambda *_: True)
    calls = []
    class Failure:
        def available(self): return True
        def chat(self, messages): calls.append(1); return ''
    with make_client(tmp_path, monkeypatch) as c:
        setup_proactive(c, daily=2)
        for _ in range(4): tick(c, Failure()); now[0] += 360*60
        assert len(calls) == 2


@pytest.mark.parametrize('change', ['disable', 'disable_reenable', 'rules'])
def test_pending_proactive_is_discarded_after_config_change(tmp_path, monkeypatch, change):
    monkeypatch.setattr(proactive_runtime, 'proactive_time_allowed', lambda *_: True)
    blocked, release = threading.Event(), threading.Event()
    calls = []
    class Delayed:
        def available(self): return True
        def chat(self, messages): calls.append(messages); blocked.set(); assert release.wait(5); return 'late greeting'
    with make_client(tmp_path, monkeypatch) as c:
        avatar = setup_proactive(c)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(tick, c, Delayed())
            try:
                assert blocked.wait(2)
                # A second worker cannot dispatch while this attempt is pending.
                tick(c, Delayed()); assert len(calls) == 1
                if change == 'rules':
                    c.put(f'/api/avatars/{avatar}/proactive-rules', json={'tone': 'changed'})
                else:
                    c.patch(f'/api/avatars/{avatar}', json={'proactive_enabled': False})
                    if change == 'disable_reenable': c.patch(f'/api/avatars/{avatar}', json={'proactive_enabled': True})
                release.set(); pending.result(3)
            finally: release.set()
        assert not c.app.state.db.all("SELECT * FROM messages WHERE channel='proactive'")
        assert c.app.state.db.one('SELECT status FROM proactive_attempts')['status'] == 'discarded'


@pytest.mark.parametrize('use_memory', [True, False])
def test_proactive_uses_corrected_memory_language_and_region(tmp_path, monkeypatch, use_memory):
    monkeypatch.setattr(proactive_runtime, 'proactive_time_allowed', lambda *_: True)
    seen = []
    class Provider:
        def available(self): return True
        def chat(self, messages): seen.extend(messages); return 'A'*120
    with make_client(tmp_path, monkeypatch) as c:
        avatar = setup_proactive(c)
        assert c.patch(f'/api/avatars/{avatar}', json={'avatar_primary_language': 'en-US', 'world_region': 'north_america'}).status_code == 200
        db = c.app.state.db
        mid = db.execute('INSERT INTO memories(avatar_id,content,origin_kind,created_at) VALUES(?,?,?,?)', (avatar, 'OLD_CITY', 'imported_history', 1))
        assert c.put(f'/api/avatars/{avatar}/history/{mid}/correction', json={'content': 'CORRECTED_CITY', 'note': 'test correction'}).status_code == 200
        c.put(f'/api/avatars/{avatar}/proactive-rules', json={'use_long_term_memory': use_memory, 'allowed_windows': [], 'quiet_hours': {}})
        tick(c, Provider())
        prompt = json.dumps(seen, ensure_ascii=False)
        assert 'OLD_CITY' not in prompt
        assert ('CORRECTED_CITY' in prompt) == use_memory
        assert 'English' in prompt and '北美' in prompt
        assert len(db.one("SELECT content FROM messages WHERE channel='proactive'")['content']) == 80


@pytest.mark.parametrize('provider_result', ['success', 'failure'])
def test_pending_image_cannot_write_through_database_restore(tmp_path, monkeypatch, provider_result):
    blocked, release = threading.Event(), threading.Event()
    def provider(*args, **kwargs):
        blocked.set(); assert release.wait(5)
        if provider_result == 'failure':
            raise ProviderError('late failure before restore')
        return json.dumps({'description': 'before restore', 'reply': 'late restored reply'})
    monkeypatch.setattr(chat_vision.VisionClient, 'chat', provider)
    with make_client(tmp_path, monkeypatch) as c:
        avatar = create_avatar(c); configure(c, avatar); row = image_message(c, avatar)
        db = c.app.state.db
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(c.post, f'/api/avatars/{avatar}/messages/{row["id"]}/understand', json={'confirm_billable_call': True})
            try:
                assert blocked.wait(2)
                # Snapshot while the provider is pending: restored IDs and source data
                # are deliberately identical, so source signatures alone cannot help.
                snapshot = db.backup(tmp_path / 'pending-vision.sqlite')
                old_epoch = db.notification_epoch()
                db.restore(snapshot)
                assert db.notification_epoch() != old_epoch
                source_before = db.one('SELECT * FROM messages WHERE id=?', (row['id'],))
                usage_before = db.all("SELECT * FROM usage_events WHERE operation='vision'")
                release.set(); response = pending.result(3)
            finally:
                release.set()
        assert response.status_code == 409, response.text
        assert db.one('SELECT * FROM messages WHERE id=?', (row['id'],)) == source_before
        assert not db.all("SELECT * FROM messages WHERE avatar_id=? AND role='assistant'", (avatar,))
        assert db.all("SELECT * FROM usage_events WHERE operation='vision'") == usage_before


@pytest.mark.parametrize('provider_result', ['success', 'failure'])
def test_pending_proactive_cannot_write_through_database_restore(tmp_path, monkeypatch, provider_result):
    monkeypatch.setattr(proactive_runtime, 'proactive_time_allowed', lambda *_: True)
    blocked, release = threading.Event(), threading.Event()
    class Delayed:
        def available(self): return True
        def chat(self, messages):
            blocked.set(); assert release.wait(5)
            if provider_result == 'failure':
                raise ProviderError('before restore failure')
            return 'late restored greeting'
    with make_client(tmp_path, monkeypatch) as c:
        avatar = setup_proactive(c)
        db = c.app.state.db
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(tick, c, Delayed())
            try:
                assert blocked.wait(2)
                snapshot = db.backup(tmp_path / 'pending-proactive.sqlite')
                old_epoch = db.notification_epoch()
                db.restore(snapshot)
                assert db.notification_epoch() != old_epoch
                attempts_before = db.all('SELECT * FROM proactive_attempts WHERE avatar_id=?', (avatar,))
                state_before = db.one('SELECT * FROM proactive_runtime_state WHERE avatar_id=?', (avatar,))
                assert attempts_before[0]['status'] == 'pending'
                release.set(); pending.result(3)
            finally:
                release.set()
        assert not db.all("SELECT * FROM messages WHERE avatar_id=? AND channel='proactive'", (avatar,))
        assert db.all('SELECT * FROM proactive_attempts WHERE avatar_id=?', (avatar,)) == attempts_before
        assert db.one('SELECT * FROM proactive_runtime_state WHERE avatar_id=?', (avatar,)) == state_before
