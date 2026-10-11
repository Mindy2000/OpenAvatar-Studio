from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from openavatar.services.proactive import get_proactive_rules, proactive_time_allowed
from openavatar.services.memory_intelligence import effective_memories
from openavatar.services.persona_core import current_persona_core
from openavatar.services.world_regions import avatar_language_profile
from openavatar.services.world_model import WorldModelError
from openavatar.services.world_runtime import advance_world


async def proactive_worker(app: FastAPI, *, completion_report: Callable, model_client: Callable) -> None:
    while True:
        await asyncio.sleep(60)
        await proactive_tick(app, completion_report=completion_report, model_client=model_client)


def _claim_attempt(db, avatar_id, now, rules, revision, request_epoch):
    # The eligibility check and persisted attempt are one cross-process reservation.
    with db.transaction() as connection:
        connection.execute('BEGIN IMMEDIATE')
        epoch = connection.execute("SELECT value FROM schema_meta WHERE key='notification_epoch'").fetchone()
        if not epoch or epoch['value'] != request_epoch:
            return None
        avatar = connection.execute('SELECT * FROM avatars WHERE id=?', (avatar_id,)).fetchone()
        runtime = connection.execute('SELECT * FROM proactive_runtime_state WHERE avatar_id=?', (avatar_id,)).fetchone()
        if not avatar or not avatar['proactive_enabled'] or not avatar['consent_confirmed'] or not runtime or runtime['paused'] or runtime['config_revision'] != revision:
            return None
        attempts = connection.execute('SELECT COUNT(*) FROM proactive_attempts WHERE avatar_id=? AND started_at>=?', (avatar_id, now-86400)).fetchone()[0]
        legacy = connection.execute("SELECT COUNT(*) FROM messages WHERE avatar_id=? AND channel='proactive' AND created_at>=? AND id NOT IN (SELECT message_id FROM proactive_attempts WHERE avatar_id=?)", (avatar_id, now-86400, avatar_id)).fetchone()[0]
        if attempts + legacy >= int(rules['daily_max']):
            return None
        last_attempt = connection.execute('SELECT MAX(started_at) FROM proactive_attempts WHERE avatar_id=?', (avatar_id,)).fetchone()[0] or 0
        last_success = connection.execute("SELECT MAX(created_at) FROM messages WHERE avatar_id=? AND channel='proactive'", (avatar_id,)).fetchone()[0] or 0
        if now-max(last_attempt, last_success) < int(avatar['proactive_interval_minutes'])*60:
            return None
        last_user = connection.execute("SELECT MAX(created_at) FROM messages WHERE avatar_id=? AND role='user' AND channel<>'preview'", (avatar_id,)).fetchone()[0] or 0
        if last_user and now-last_user < int(rules['cooldown_after_user_reply_minutes'])*60:
            return None
        attempt = connection.execute('INSERT INTO proactive_attempts(avatar_id,started_at,config_revision) VALUES(?,?,?)', (avatar_id, now, revision)).lastrowid
        return int(attempt), dict(avatar)


def _finish_attempt(db, avatar_id, attempt, revision, request_epoch, *, content='', error=''):
    now = int(time.time())
    with db.transaction() as connection:
        connection.execute('BEGIN IMMEDIATE')
        epoch = connection.execute("SELECT value FROM schema_meta WHERE key='notification_epoch'").fetchone()
        if not epoch or epoch['value'] != request_epoch:
            return False
        row = connection.execute('SELECT status FROM proactive_attempts WHERE id=?', (attempt,)).fetchone()
        if not row or row['status'] != 'pending':
            return False
        fresh = connection.execute('SELECT a.proactive_enabled,a.consent_confirmed,r.config_revision FROM avatars a JOIN proactive_runtime_state r ON r.avatar_id=a.id WHERE a.id=?', (avatar_id,)).fetchone()
        current = fresh and fresh['proactive_enabled'] and fresh['consent_confirmed'] and fresh['config_revision'] == revision
        status, message_id = 'discarded', 0
        if current and content:
            message_id = connection.execute('INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)', (avatar_id, 'assistant', content, 'proactive', now)).lastrowid
            status = 'completed'
            connection.execute('UPDATE proactive_runtime_state SET consecutive_failures=0 WHERE avatar_id=?', (avatar_id,))
        elif current:
            status = 'failed'
            connection.execute('UPDATE proactive_runtime_state SET consecutive_failures=consecutive_failures+1,paused=CASE WHEN consecutive_failures+1>=3 THEN 1 ELSE 0 END WHERE avatar_id=?', (avatar_id,))
        connection.execute('UPDATE proactive_attempts SET status=?,finished_at=?,error=?,message_id=? WHERE id=?', (status, now, error, message_id, attempt))
        return status == 'completed'


def _proactive_messages(db, avatar, rules, now):
    avatar_id = str(avatar['id'])
    core = current_persona_core(db, avatar_id)['core']
    persona = core.get('persona', {})
    language = core.get('language_profile', avatar_language_profile(avatar))
    region = language.get('world_region_rules', {})
    memory_context = ''
    if rules['use_long_term_memory']:
        rows = effective_memories(db, avatar_id, 'official')
        rows = sorted(rows, key=lambda item: item.get('id', 0), reverse=True)[:12]
        memory_context = '可参考的有效长期记忆：' + '；'.join(str(row['content'])[:120] for row in rows)
    world = '\n'.join(f"- {item['key']}: {json.dumps(item['value'], ensure_ascii=False)}" for item in core.get('world_context', [])[:80])
    feedback = '\n'.join(f"- {item['rule_text']}" for item in core.get('feedback_rules', [])[:12] if item.get('active'))
    local_clock = time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(now))
    constraints = (
        f"你是数字人{avatar['name']}，与用户的关系是{avatar['relationship']}。\n"
        f"数字人语言策略：{language.get('language_label', {}).get('instruction', '主要使用自然中文表达。')} 回复模式：{language.get('response_mode_label', {}).get('name_zh', '')}。\n"
        f"世界地区：{region.get('name_zh', '')}；世界类型：{language.get('world_type', '')}。称呼、节日、作息和社会规则应符合世界地区。\n"
        f"人格：{persona.get('summary', '')}；表达方式：{persona.get('speaking_style', '')}；边界：{persona.get('boundaries', '')}。\n"
        f"有效世界事实：\n{world}\n用户反馈规则：\n{feedback}\n"
        f"本机当前时间：{local_clock}。按此时间选择问候，不能在晚上说早安。"
        '没有实时天气、位置、课程表或用户当前活动信息，不得声称知道这些情况；不要编造冷热、晴雨或正在发生的事。'
        '只使用提供的有效事实，可以表达关心或询问近况。只输出问候正文，最多80字（字符，含标点）。'
    )
    prompt = (f"这是用户主动开启的本地主动联系功能。语气：{rules['tone']}。主题范围：{', '.join(rules['topic_scope'])}。"
              f"{memory_context}。写一条自然、简短、不虚构新事实的问候。")
    return [{'role': 'system', 'content': constraints}, {'role': 'user', 'content': prompt}]


async def proactive_tick(app: FastAPI, *, completion_report: Callable[[Any, str], dict[str, Any]], model_client: Callable[[Any, Any, str], Any]) -> None:
    db, now = app.state.db, int(time.time())
    for avatar in db.all('SELECT * FROM avatars WHERE proactive_enabled=1 AND consent_confirmed=1'):
        avatar_id = str(avatar['id'])
        request_epoch = db.notification_epoch()
        if not completion_report(db, avatar_id)['can_start_official']:
            continue
        db.execute('INSERT OR IGNORE INTO proactive_runtime_state(avatar_id,config_revision) VALUES(?,?)', (avatar_id, uuid.uuid4().hex))
        revision = db.one('SELECT config_revision FROM proactive_runtime_state WHERE avatar_id=?', (avatar_id,))['config_revision']
        rules = get_proactive_rules(db, avatar_id)
        if not proactive_time_allowed(rules, now):
            continue
        claimed = _claim_attempt(db, avatar_id, now, rules, revision, request_epoch)
        if not claimed:
            continue
        attempt, avatar = claimed
        try:
            client = model_client(db, app.state.settings, avatar_id)
            if not client.available():
                raise ValueError('provider unavailable')
            messages = _proactive_messages(db, avatar, rules, now)
            content = (await asyncio.to_thread(client.chat, messages)).strip()[:80]
            if not content:
                raise ValueError('empty greeting')
        except asyncio.CancelledError:
            _finish_attempt(db, avatar_id, attempt, revision, request_epoch, error='主动联系已中断；已发送的服务请求可能仍计费。')
            raise
        except Exception:
            # Never persist provider error strings: they can contain private prompts/URLs.
            _finish_attempt(db, avatar_id, attempt, revision, request_epoch, error='主动联系未完成，请检查对话服务。没有立即重试；连续失败三次后暂停。')
            continue
        committed = _finish_attempt(db, avatar_id, attempt, revision, request_epoch, content=content)
        if committed and rules['allow_world_event_advancement'] and avatar['subject_kind'] == 'fictional':
            try:
                advance_world(db, avatar_id, seconds=60, force_minor_event=False)
            except (ValueError, WorldModelError):
                pass
