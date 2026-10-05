"""Scheduling checks use a deterministic local model, never a cloud account."""
import asyncio
import time

import pytest

from test_app import create_avatar, make_client
from openavatar.services import proactive_runtime


@pytest.mark.parametrize('case,expected', [
    ('allowed', 1), ('disabled', 0), ('not_ready', 0), ('quiet', 0),
    ('outside_window', 0), ('overnight', 1), ('daily_limit', 0),
    ('interval', 0), ('user_cooldown', 0), ('preview_ignored', 1),
    ('unavailable', 0), ('empty_response', 0), ('long_response', 1),
])
def test_proactive_scheduling_combinations(tmp_path, monkeypatch, case, expected):
    now = int(time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1)))
    monkeypatch.setattr(proactive_runtime.time, 'time', lambda: now)
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind='fictional')
        aid = avatar['id']
        base = f'/api/avatars/{aid}'
        client.patch(base, json={'proactive_enabled': case != 'disabled', 'proactive_interval_minutes': 60})
        rules = {'daily_max': 1, 'allowed_windows': [], 'quiet_hours': {}, 'cooldown_after_user_reply_minutes': 120}
        if case == 'quiet':
            rules['quiet_hours'] = {'start': '11:00', 'end': '13:00'}
        if case == 'outside_window':
            rules['allowed_windows'] = [{'start': '18:00', 'end': '22:00'}]
        if case == 'overnight':
            rules['allowed_windows'] = [{'start': '20:00', 'end': '13:00'}]
        if case == 'interval':
            rules['daily_max'] = 2
        assert client.put(base + '/proactive-rules', json=rules).status_code == 200
        db = client.app.state.db
        if case in {'daily_limit', 'interval', 'user_cooldown', 'preview_ignored'}:
            user = case in {'user_cooldown', 'preview_ignored'}
            db.execute('INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)',
                       (aid, 'user' if user else 'assistant', 'local fixture',
                        'preview' if case == 'preview_ignored' else 'official' if user else 'proactive', now - 60))
        calls = []

        class LocalFixture:
            def available(self):
                return case != 'unavailable'

            def chat(self, messages):
                calls.append(messages)
                return '' if case == 'empty_response' else '甲' * 120 if case == 'long_response' else '记得午休，下午见。'

        before = db.one("SELECT COUNT(*) AS n FROM messages WHERE avatar_id=? AND channel='proactive'", (aid,))['n']
        asyncio.run(proactive_runtime.proactive_tick(
            client.app, completion_report=lambda *_: {'can_start_official': case != 'not_ready'},
            model_client=lambda *_: LocalFixture(),
        ))
        after = db.one("SELECT COUNT(*) AS n FROM messages WHERE avatar_id=? AND channel='proactive'", (aid,))['n']
        if case == 'long_response':
            assert len(db.one("SELECT content FROM messages WHERE avatar_id=? AND channel='proactive'", (aid,))['content']) == 80
        assert after - before == expected
        assert len(calls) == (1 if expected or case == 'empty_response' else 0)
        if calls:
            instruction = calls[0][0]
            assert instruction['role'] == 'system'
            assert '2026-10-04 12:00' in instruction['content']
            assert '没有实时天气' in instruction['content']
            assert '最多80字' in instruction['content']


def test_package_preserves_zero_proactive_limit(tmp_path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind='fictional')
        base = f"/api/avatars/{avatar['id']}"
        assert client.put(base + '/proactive-rules', json={'daily_max': 0}).status_code == 200
        exported = client.post(base + '/export')
        assert exported.status_code == 200
        imported = client.post('/api/packages/import', content=exported.content, headers={
            'Content-Type': 'application/zip', 'X-File-Name': 'zero-limit.openavatar.zip', 'X-Rights-Confirmed': 'true',
        })
        assert imported.status_code == 201
        rules = client.get(f"/api/avatars/{imported.json()['id']}/proactive-rules").json()
        assert rules['daily_max'] == 0
