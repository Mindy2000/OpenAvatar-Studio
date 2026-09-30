from __future__ import annotations

import json
import time
import uuid

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.providers import load_provider_key
from openavatar.services.continuity import finalize_video_continuity, get_continuity_run, update_continuity_run
from openavatar.services.minimax import MiniMaxClient, MiniMaxError
from openavatar.services.provider_hub import provider_key_name
from openavatar.services.training import get_job, update_job
from openavatar.services.video_generation import VideoGenerationError, VideoGenerationSettings, download_video_result, poll_video_generation, start_video_generation
from openavatar.services.video_runtime import continuity_first_frame, continuity_reference_inputs, video_generation_settings


def _notify(db: Database, avatar_id: str, title: str, body: str, action_url: str = "") -> None:
    db.execute(
        "INSERT INTO user_notifications(avatar_id,kind,title,body,action_url,created_at) VALUES(?,?,?,?,?,?)",
        (avatar_id, "media_job", title[:200], body[:1000], action_url[:500], int(time.time())),
    )


def poll_video_jobs(db: Database, settings: Settings, *, limit: int = 8) -> int:
    """Advance submitted video jobs without requiring the user to keep clicking refresh."""
    rows = db.all(
        "SELECT id FROM training_jobs WHERE job_type='video' AND status='running' ORDER BY updated_at LIMIT ?",
        (limit,),
    )
    advanced = 0
    for row in rows:
        job = get_job(db, str(row["id"]))
        result = job.get("result") or {}
        task_id = str(result.get("provider_task_id") or "")
        run_id = str(result.get("continuity_run_id") or "")
        if not task_id or not run_id:
            continue
        if job.get("cancel_requested"):
            update_job(db, job["id"], status="cancelled", stage="任务已取消")
            advanced += 1
            continue
        if int(job.get("started_at") or job.get("created_at") or 0) < int(time.time()) - 6 * 3600:
            update_job(db, job["id"], status="failed", stage="视频任务超时", error="服务商任务超过 6 小时未完成")
            _notify(db, job["avatar_id"], "视频生成超时", "任务已停止轮询，可在构建中心重试。")
            advanced += 1
            continue
        provider = str(result.get("provider") or job.get("provider") or "")
        try:
            urls: list[str] = []
            requires_auth = False
            api_key = ""
            connection = db.one("SELECT * FROM provider_connections WHERE id=? AND enabled=1", (provider,))
            if connection and str(connection.get("provider_kind")) == "minimax":
                config = json.loads(str(connection.get("config_json") or "{}"))
                client = MiniMaxClient(load_provider_key(provider_key_name(provider)), str(connection["base_url"]), endpoints=config.get("endpoints", {}), timeout=90)
                polled = client.query_video(task_id)
                if not polled["done"]:
                    continue
                urls = [str(value) for value in polled.get("urls") or []]
            else:
                generation = video_generation_settings(db, settings, str(job["avatar_id"]), str(result.get("prompt") or ""))
                polled = poll_video_generation(generation, provider=provider or generation.provider, task_id=task_id, polling_url=str(result.get("polling_url") or ""))
                if not polled.get("done"):
                    continue
                urls = [str(polled["remote_url"])]
                requires_auth = bool(polled.get("requires_auth"))
                api_key = generation.openrouter_api_key
            if not urls:
                raise VideoGenerationError("视频任务完成但没有结果地址")
            filename = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
            target = settings.avatars_dir / str(job["avatar_id"]) / "generated" / "video" / filename
            media_type = download_video_result(urls[0], target, api_key=api_key if requires_auth else "")
            review = finalize_video_continuity(db, settings, avatar_id=str(job["avatar_id"]), job_id=str(job["id"]), run_id=run_id, video_path=target)
            completed = review.get("sendable", False)
            if not completed and review.get("visual_review", {}).get("available") and int(job.get("attempt") or 0) < 1:
                contract = get_continuity_run(db, str(job["avatar_id"]), run_id)["contract"]
                refs = continuity_reference_inputs(settings, contract)
                retry_prompt = f"{str(result.get('prompt') or '')}\n上一次连续性检查未通过。减少镜头运动，保持人物、服装、物品和场景结构完全稳定。"
                retry_polling_url = ""
                retry_provider = provider
                if connection and str(connection.get("provider_kind")) == "minimax":
                    route_config = {}
                    retry = client.create_video(
                        retry_prompt,
                        model=str(result.get("model") or "MiniMax-H3"),
                        reference_images=[str(item["url"]) for item in refs],
                        config=route_config,
                    )
                    retry_task_id = str(retry["task_id"])
                else:
                    generation = VideoGenerationSettings(
                        **{**generation.__dict__, "reference_images": tuple(str(item["url"]) for item in refs)}
                    )
                    first_frame = continuity_first_frame(settings, contract, allow_data_url=generation.provider == "aliyun")
                    retry = start_video_generation(generation, prompt=retry_prompt, first_frame=first_frame, metadata={"auto_retry": True})
                    retry_task_id = str(retry["task_id"])
                    retry_polling_url = str(retry.get("polling_url") or "")
                    retry_provider = str(retry.get("provider") or provider)
                db.execute("UPDATE training_jobs SET attempt=attempt+1 WHERE id=?", (job["id"],))
                update_continuity_run(db, run_id, status="resubmitted", provider=retry_provider, provider_task_id=retry_task_id)
                retry_result = {
                    **result,
                    "provider": retry_provider,
                    "provider_task_id": retry_task_id,
                    "polling_url": retry_polling_url,
                    "previous_candidate_url": f"/api/avatars/{job['avatar_id']}/generated/video/{filename}",
                    "auto_retry": True,
                }
                update_job(db, job["id"], status="running", progress=40, stage="首版未通过，后台已自动重试一次", result=retry_result)
                advanced += 1
                continue
            next_status = "completed" if completed else "needs_review"
            next_result = {**result, "asset_url": f"/api/avatars/{job['avatar_id']}/generated/video/{filename}", "remote_url": urls[0], "media_type": media_type, "continuity_review": review}
            update_job(db, job["id"], status=next_status, progress=100, stage="视频已完成" if completed else "视频已生成，等待人工复核", result=next_result, error="")
            _notify(db, str(job["avatar_id"]), "视频生成完成" if completed else "视频等待复核", "后台任务已经完成，可在构建中心查看。", f"/avatars/{job['avatar_id']}")
            advanced += 1
        except (MiniMaxError, VideoGenerationError, OSError, ValueError, json.JSONDecodeError) as exc:
            update_job(db, job["id"], status="failed", stage="后台视频任务失败", error=str(exc))
            _notify(db, str(job["avatar_id"]), "视频生成失败", str(exc))
            advanced += 1
    return advanced
