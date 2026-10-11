from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.providers import load_provider_key
from openavatar.services.continuity import finalize_video_continuity, VideoFinalizationAborted
from openavatar.services.minimax import MiniMaxClient, MiniMaxError
from openavatar.services.provider_hub import provider_key_name, find_route
from openavatar.services.training import get_job
from openavatar.services.video_generation import VideoGenerationError, download_video_result, poll_video_generation
from openavatar.services.video_runtime import video_generation_settings, bound_video_settings


def _epoch(transaction) -> str:
    row = transaction.execute("SELECT value FROM schema_meta WHERE key='notification_epoch'").fetchone()
    return str(row['value']) if row else ''


@contextmanager
def _poll_lease(db: Database, job_id: str):
    """A renewable per-job lease shared by manual/background/other DB objects."""
    owner, key, now = uuid.uuid4().hex, f"video-poll:{job_id}", int(time.time())
    with db.transaction() as transaction:
        transaction.execute('BEGIN IMMEDIATE')
        epoch = _epoch(transaction)
        row = transaction.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()
        acquired = False
        if row and row['status'] == 'running':
            transaction.execute(
                "INSERT INTO scheduler_leases(lease_key,owner_id,expires_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(lease_key) DO UPDATE SET owner_id=excluded.owner_id,expires_at=excluded.expires_at,updated_at=excluded.updated_at WHERE scheduler_leases.expires_at<=?",
                (key, owner, now + 120, now, now),
            )
            lease = transaction.execute('SELECT owner_id FROM scheduler_leases WHERE lease_key=?', (key,)).fetchone()
            acquired = bool(lease and lease['owner_id'] == owner)
    if not acquired:
        yield None
        return
    stop = threading.Event()
    def renew():
        while not stop.wait(20):
            with db.transaction() as transaction:
                transaction.execute('BEGIN IMMEDIATE')
                if _epoch(transaction) != epoch:
                    return
                cursor = transaction.execute('UPDATE scheduler_leases SET expires_at=?,updated_at=? WHERE lease_key=? AND owner_id=?', (int(time.time()) + 120, int(time.time()), key, owner))
                if cursor.rowcount != 1:
                    return
    heartbeat = threading.Thread(target=renew, name='video-poll-lease', daemon=True)
    heartbeat.start()
    try:
        yield (key, owner, epoch)
    finally:
        stop.set()
        heartbeat.join(timeout=2)
        db.execute('DELETE FROM scheduler_leases WHERE lease_key=? AND owner_id=?', (key, owner))


def _guard(transaction, job: dict, lease: tuple, *, allow_cancelled: bool = False) -> bool:
    key, owner, epoch = lease
    if _epoch(transaction) != epoch:
        return False
    held = transaction.execute('SELECT owner_id FROM scheduler_leases WHERE lease_key=?', (key,)).fetchone()
    current = transaction.execute('SELECT status,cancel_requested,result_json FROM training_jobs WHERE id=?', (job['id'],)).fetchone()
    if not held or held['owner_id'] != owner or not current or current['status'] != 'running':
        return False
    if current['cancel_requested'] and not allow_cancelled:
        return False
    return str(json.loads(current['result_json'] or '{}').get('provider_task_id') or '') == str(job['result'].get('provider_task_id') or '')


def _is_current(db: Database, job: dict, lease: tuple) -> bool:
    with db.transaction() as transaction:
        return _guard(transaction, job, lease)


def _stop_job(db: Database, job: dict, lease: tuple, *, error: str = '') -> bool:
    with db.transaction() as transaction:
        transaction.execute('BEGIN IMMEDIATE')
        if not _guard(transaction, job, lease, allow_cancelled=True):
            return False
        current = transaction.execute('SELECT cancel_requested FROM training_jobs WHERE id=?', (job['id'],)).fetchone()
        cancelled = bool(current['cancel_requested'])
        if not cancelled and not error:
            return False
        status = 'cancelled' if cancelled else 'failed'
        stage = '已停止本地处理；远端任务可能已计费' if cancelled else '后台视频任务失败'
        now = int(time.time())
        transaction.execute('UPDATE training_jobs SET status=?,stage=?,error=?,updated_at=?,finished_at=? WHERE id=?', (status, stage, error, now, now, job['id']))
        if not cancelled:
            transaction.execute("INSERT INTO user_notifications(avatar_id,kind,title,body,created_at) VALUES(?,'media_job','视频生成失败',?,?)", (job['avatar_id'], error[:1000], now))
        return True


def _poll_one(db: Database, settings: Settings, job: dict, lease: tuple) -> int:
    result = job.get('result') or {}
    task_id, run_id = str(result.get('provider_task_id') or ''), str(result.get('continuity_run_id') or '')
    if not task_id or not run_id:
        return 0
    if not _is_current(db, job, lease):
        return int(_stop_job(db, job, lease))
    if int(job.get('started_at') or job.get('created_at') or 0) < int(time.time()) - 6 * 3600:
        return int(_stop_job(db, job, lease, error='服务商任务超过 6 小时未完成'))
    provider = str(result.get('provider') or job.get('provider') or '')
    target = None
    try:
        requires_auth, api_key = False, ''
        snapshot = result.get('connection_snapshot') or {}
        connection_id = str(snapshot.get('connection_id') or result.get('connection_id') or provider)
        connection = db.one('SELECT * FROM provider_connections WHERE id=?', (connection_id,))
        if not snapshot and not connection and find_route(db, 'video', str(job['avatar_id'])):
            raise VideoGenerationError('旧视频任务缺少提交账号记录，无法安全改用当前或旧账号；请保留远端任务 ID 供人工核对')
        if snapshot and (not connection or any(str(connection[key]) != str(snapshot[key]) for key in ('base_url', 'provider_kind'))):
            raise VideoGenerationError('原视频连接已删除或地址/类型改变，不能切换账号查询')
        if connection and str(connection.get('provider_kind')) == 'minimax':
            config = snapshot.get('config') or json.loads(str(connection.get('config_json') or '{}'))
            client = MiniMaxClient(load_provider_key(provider_key_name(connection_id)), str(connection['base_url']), endpoints=config.get('endpoints', {}), timeout=90)
            polled = client.query_video(task_id)
            if not polled['done']:
                return 0
            urls = [str(value) for value in polled.get('urls') or []]
        else:
            generation = bound_video_settings(db, snapshot) if snapshot else video_generation_settings(db, settings, str(job['avatar_id']), str(result.get('prompt') or ''))
            polled = poll_video_generation(generation, provider=generation.provider if snapshot else provider or generation.provider, task_id=task_id, polling_url=str(result.get('polling_url') or ''))
            if not polled.get('done'):
                return 0
            urls = [str(polled['remote_url'])]
            requires_auth, api_key = bool(polled.get('requires_auth')), generation.openrouter_api_key
        if not urls:
            raise VideoGenerationError('视频任务完成但没有结果地址')
        if not _is_current(db, job, lease):
            return int(_stop_job(db, job, lease))
        filename = f'{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4'
        target = settings.avatars_dir / str(job['avatar_id']) / 'generated' / 'video' / filename
        media_type = download_video_result(urls[0], target, api_key=api_key if requires_auth else '', **({'auth_origin': generation.openrouter_base_url} if requires_auth else {}))
        if not _is_current(db, job, lease):
            target.unlink(missing_ok=True)
            return int(_stop_job(db, job, lease))
        def commit(transaction, review):
            completed, now = bool(review.get('sendable')), int(time.time())
            next_result = {**result, 'asset_url': f"/api/avatars/{job['avatar_id']}/generated/video/{filename}", 'remote_url': urls[0], 'media_type': media_type, 'continuity_review': review}
            transaction.execute('UPDATE training_jobs SET status=?,progress=100,stage=?,result_json=?,error=\'\',updated_at=?,finished_at=? WHERE id=?', ('completed' if completed else 'needs_review', '视频已完成' if completed else '视频已生成，等待人工复核', json.dumps(next_result, ensure_ascii=False), now, now, job['id']))
            transaction.execute("INSERT INTO user_notifications(avatar_id,kind,title,body,action_url,created_at) VALUES(?,'media_job',?,'后台任务已经完成，可在构建中心查看。',?,?)", (job['avatar_id'], '视频生成完成' if completed else '视频等待复核', f"/avatars/{job['avatar_id']}", now))
        # Extraction and remote review happen before a single guarded commit.
        # Rejected quality never authorizes another paid generation.
        finalize_video_continuity(db, settings, avatar_id=str(job['avatar_id']), job_id=str(job['id']), run_id=run_id, video_path=target,
                                  commit_guard=lambda transaction: _guard(transaction, job, lease), on_commit=commit)
        return 1
    except VideoFinalizationAborted:
        if target is not None:
            target.unlink(missing_ok=True)
        return int(_stop_job(db, job, lease))
    except (MiniMaxError, VideoGenerationError, OSError, ValueError, json.JSONDecodeError) as exc:
        return int(_stop_job(db, job, lease, error=str(exc)))


def poll_video_jobs(db: Database, settings: Settings, *, limit: int = 8, job_id: str = '') -> int:
    rows = db.all("SELECT id FROM training_jobs WHERE job_type='video' AND status='running' AND (?='' OR id=?) ORDER BY updated_at LIMIT ?", (job_id, job_id, limit))
    advanced = 0
    for row in rows:
        with _poll_lease(db, str(row['id'])) as lease:
            if lease is None:
                continue
            try:
                job = get_job(db, str(row['id']))
            except KeyError:
                continue
            advanced += _poll_one(db, settings, job, lease)
    return advanced
