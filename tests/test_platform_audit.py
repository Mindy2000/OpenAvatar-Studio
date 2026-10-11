"""Regression checks for runtime, migration and notification audit findings."""
import asyncio
import hashlib
import sqlite3
import threading
import time

import pytest

from openavatar.db import Database
from openavatar.migrations import LATEST_SCHEMA_VERSION
from openavatar.runtime import BackgroundSupervisor, LeaseManager, Metrics, PeriodicJob
from test_runtime import make_client, create_avatar, FakeStreamingProvider


def test_synchronous_job_does_not_block_requests_or_release_lease_before_finishing(tmp_path):
    db = Database(tmp_path / 'runtime.sqlite')
    db.initialize()
    entered, release = threading.Event(), threading.Event()
    first, other = LeaseManager(db, 'first'), LeaseManager(db, 'other')

    def slow_poll():
        entered.set()
        assert release.wait(3)

    async def check():
        supervisor = BackgroundSupervisor(first, Metrics())
        supervisor.start([PeriodicJob('slow', 60, slow_poll, lease_seconds=5)])
        start = time.monotonic()
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            # An independent coroutine remains runnable during the blocking call.
            await asyncio.sleep(.01)
            assert time.monotonic() - start < 1
            stopping = asyncio.create_task(supervisor.stop())
            await asyncio.sleep(.02)
            assert not stopping.done()
            assert not other.acquire('slow', 5)
        finally:
            release.set()
            if 'stopping' in locals():
                await stopping
            else:
                await supervisor.stop()
        assert other.acquire('slow', 5)

    asyncio.run(check())


def test_v8_upgrade_backs_up_before_adding_columns_and_is_idempotent(tmp_path):
    db = Database(tmp_path / 'runtime.sqlite')
    db.initialize()
    db.execute('ALTER TABLE messages DROP COLUMN context_excluded')
    db.execute("UPDATE schema_meta SET value='8' WHERE key='schema_version'")
    db.execute("INSERT INTO app_settings(key,value_json,updated_at) VALUES('audit_marker','42',0)")
    db.initialize()
    backup = tmp_path / f'runtime.before-v{LATEST_SCHEMA_VERSION}.backup.sqlite'
    assert backup.is_file()
    with sqlite3.connect(backup) as source:
        assert source.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == '8'
        assert 'context_excluded' not in {row[1] for row in source.execute('PRAGMA table_info(messages)')}
        assert source.execute("SELECT value_json FROM app_settings WHERE key='audit_marker'").fetchone()[0] == '42'
    assert 'context_excluded' in {row['name'] for row in db.all('PRAGMA table_info(messages)')}
    epoch = db.notification_epoch()
    db.initialize()
    assert db.notification_epoch() == epoch
    assert len(list(tmp_path.glob('*.backup.sqlite'))) == 1


def test_future_schema_is_rejected_without_modifying_database(tmp_path):
    db = Database(tmp_path / 'future.sqlite')
    db.initialize()
    db.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
    before = hashlib.sha256(db.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='高于当前程序'):
        db.initialize()
    assert hashlib.sha256(db.path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob('*.backup.sqlite'))


def test_restored_notification_epoch_resets_high_browser_cursor_and_rejects_stale_ack(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        db = client.app.state.db
        db.execute("INSERT INTO user_notifications(kind,title,created_at) VALUES('audit','restored message',0)")
        first = client.get('/api/notifications/feed').json()
        backup = client.post('/api/system/backup').json()['filename']
        for index in range(4):
            db.execute("INSERT INTO user_notifications(kind,title,created_at) VALUES('audit',?,0)", (f'new {index}',))
        assert client.post(f'/api/system/backups/{backup}/restore', params={'confirmation':'RESTORE OPENAVATAR DATABASE'}).status_code == 200
        feed = client.get('/api/notifications/feed', params={'after_id':5,'epoch':first['epoch']}).json()
        assert feed['epoch'] != first['epoch']
        assert feed['after_id'] == 0 and [row['title'] for row in feed['items']] == ['restored message']
        notification_id = feed['items'][0]['id']
        assert client.post(f'/api/notifications/{notification_id}/read', params={'epoch':first['epoch']}).status_code == 409
        assert client.post(f'/api/notifications/{notification_id}/read', params={'epoch':feed['epoch']}).status_code == 200
        assert client.get('/api/notifications/feed', params={'epoch':feed['epoch']}).json()['items'] == []


@pytest.mark.parametrize('streaming', [False, True])
def test_reply_started_before_database_restore_cannot_repopulate_chat(tmp_path, monkeypatch, streaming):
    with make_client(tmp_path, monkeypatch) as client:
        avatar = create_avatar(client)
        db = client.app.state.db
        backup = db.backup(tmp_path / 'before-request.sqlite')

        def answer(_self, messages, **kwargs):
            db.restore(backup)
            return 'Reply from the previous database'

        def stream(_self, messages):
            yield 'Partial text'
            db.restore(backup)
            yield 'Late text'

        monkeypatch.setattr(FakeStreamingProvider, 'chat', answer)
        monkeypatch.setattr(FakeStreamingProvider, 'stream_chat', stream)
        endpoint = f'/api/avatars/{avatar}/chat' + ('/stream' if streaming else '')
        response = client.post(endpoint, json={'message': 'Before restore'})
        if streaming:
            assert '"type": "error"' in response.text
            assert '"type": "done"' not in response.text
        else:
            assert response.status_code == 409, response.text
        assert db.all('SELECT * FROM messages WHERE avatar_id=?', (avatar,)) == []
        assert client.app.state.runs.snapshot() == []
