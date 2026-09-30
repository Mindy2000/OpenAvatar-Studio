from __future__ import annotations

from openavatar.routes._shared import *


def create_imports_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.post("/api/avatars/{avatar_id}/imports", status_code=201)
    async def import_file(avatar_id: str, request: Request, category: str = "auto") -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        if not bool(avatar["consent_confirmed"]):
            raise HTTPException(400, "导入个人资料前必须确认本人身份或已获得明确授权")
        name = safe_filename(unquote(request.headers.get("X-File-Name", "upload.bin")))
        suffix = Path(name).suffix.lower()
        detected = category_for_suffix(suffix)
        chosen = detected if category == "auto" else category
        if chosen not in {"conversation", "image", "audio", "fictional"}:
            raise HTTPException(415, "仅支持聊天记录、图片、音频和虚构设定文件")
        if chosen == "image" and suffix not in IMAGE_EXTENSIONS:
            raise HTTPException(415, "图片格式不受支持")
        if chosen == "audio" and suffix not in AUDIO_EXTENSIONS:
            raise HTTPException(415, "音频格式不受支持")
        if chosen == "fictional" and suffix not in FICTIONAL_EXTENSIONS:
            raise HTTPException(415, "虚构设定支持 Markdown、TXT、JSON、YAML")
        folder = selected.avatars_dir / avatar_id / "imports" / chosen
        stored_name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{name}"
        target = folder / stored_name
        size = await save_upload(request, target, selected.max_upload_bytes)
        metadata_removed = chosen == "image" and strip_image_metadata(target)
        size = target.stat().st_size
        note = "文件仅保存在本机；已移除 EXIF/GPS 元数据" if metadata_removed else "文件仅保存在本机"
        status = "stored"
        import_id = db.execute(
            "INSERT INTO imports(avatar_id,category,original_name,stored_path,media_type,size_bytes,status,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (avatar_id, chosen, name, str(target.relative_to(selected.data_dir)), request.headers.get("Content-Type") or mimetypes.guess_type(name)[0] or "", size, status, note, int(time.time())),
        )
        imported_memories = 0
        try:
            if chosen == "conversation":
                rows = parse_conversation(target)
                now = int(time.time())
                with db.transaction() as connection:
                    connection.executemany(
                        "INSERT INTO import_rows(import_id,row_index,speaker,content,created_at) VALUES(?,?,?,?,?)",
                        [(import_id, index, row["speaker"], row["content"], now) for index, row in enumerate(rows[:100000])],
                    )
                note = f"已解析 {len(rows)} 条记录，等待确认说话人与排除内容"
                status = "needs_review"
            elif chosen == "image":
                now = int(time.time())
                with db.transaction() as connection:
                    connection.execute("DELETE FROM evidence WHERE source_import_id=?", (import_id,))
                    insert_evidence(
                        connection,
                        avatar_id=avatar_id,
                        source_import_id=import_id,
                        source_type="real_image",
                        title=f"图片素材：{name}",
                        content=f"用户上传的图片素材。\n文件名：{name}\n媒体类型：{request.headers.get('Content-Type') or mimetypes.guess_type(name)[0] or ''}\n大小：{size} bytes",
                        tags=["image", "visual_asset"],
                        derived_kind="image_asset",
                        confidence=1.0,
                        created_at=now,
                    )
                    connection.execute(
                        "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,local_path,provider,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            avatar_id,
                            "reference_image" if avatar["subject_kind"] != "fictional" else "fictional_visual_candidate",
                            "candidate",
                            f"候选图片：{name}",
                            str(target.relative_to(selected.data_dir)),
                            "user_upload",
                            json.dumps({"source_import_id": import_id, "approval_flow": ["candidate", "approved", "canonical", "rejected"]}, ensure_ascii=False),
                            now,
                        ),
                    )
                ocr_result = extract_image_text(db, target)
                text = str(ocr_result.get("text", ""))
                note = str(ocr_result.get("note", ""))
                if text:
                    parsed_rows = parse_text_payload(text)
                    with db.transaction() as connection:
                        connection.executemany(
                            "INSERT INTO import_rows(import_id,row_index,speaker,content,created_at) VALUES(?,?,?,?,?)",
                            [(import_id, index, row["speaker"], row["content"], now) for index, row in enumerate(parsed_rows)],
                        )
                    status = "needs_review"
                    location = "云端 OCR" if ocr_result.get("data_location") == "cloud" else "本地 OCR"
                    note = f"{note}（{location}：{ocr_result.get('provider')}），请确认OCR内容后再用于构建"
            elif chosen == "audio":
                now = int(time.time())
                with db.transaction() as connection:
                    connection.execute("DELETE FROM evidence WHERE source_import_id=?", (import_id,))
                    insert_evidence(
                        connection,
                        avatar_id=avatar_id,
                        source_import_id=import_id,
                        source_type="real_audio",
                        title=f"声音素材：{name}",
                        content=f"用户上传的声音样本，当前作为声音复刻/后续ASR的授权素材保存。\n文件名：{name}\n媒体类型：{request.headers.get('Content-Type') or mimetypes.guess_type(name)[0] or ''}\n大小：{size} bytes",
                        tags=["audio", "voice_sample"],
                        derived_kind="voice_sample",
                        confidence=1.0,
                        created_at=now,
                    )
                    connection.execute(
                        "INSERT INTO voice_transcriptions(avatar_id,source_import_id,provider,model,status,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            avatar_id,
                            import_id,
                            "development",
                            "manual-or-provider-asr",
                            "needs_review",
                            json.dumps({"note": "开发期先记录为待转写；后续可接 ASR provider 或手动确认文本。"}, ensure_ascii=False),
                            now,
                        ),
                    )
            elif chosen == "fictional":
                text = target.read_text(encoding="utf-8-sig", errors="replace")
                parsed = parse_fictional_source(text, str(avatar["name"]), name)
                now = int(time.time())
                with db.transaction() as connection:
                    connection.executemany(
                        "INSERT INTO import_rows(import_id,row_index,speaker,content,created_at) VALUES(?,?,?,?,?)",
                        [
                            (import_id, index, str(item.get("kind", "设定"))[:80], str(item.get("content", ""))[:100000], now)
                            for index, item in enumerate(parsed["evidence"][:2000])
                        ],
                    )
                status = "needs_review"
                note = f"已解析 {len(parsed['evidence'])} 个设定部分，请预览并选择合并或覆盖"
            db.execute("UPDATE imports SET status=?,note=? WHERE id=?", (status, note, import_id))
        except (ValueError, json.JSONDecodeError) as exc:
            status = "needs_review"
            note = f"文件已保存，但自动解析失败：{exc}"
            db.execute("UPDATE imports SET status=?,note=? WHERE id=?", (status, note, import_id))
        job = None
        if chosen in {"audio", "image"}:
            job = create_job(
                db,
                avatar_id,
                "voice" if chosen == "audio" else "visual",
                status="waiting_configuration",
                stage="素材已保存，等待选择构建服务",
                input_summary=f"{name} · {size} bytes",
            )
        elif chosen == "fictional":
            job = create_job(
                db,
                avatar_id,
                "persona",
                status="waiting_review",
                stage="等待用户预览并确认设定",
                input_summary=f"{name} · {size} bytes",
            )
            update_job(db, job["id"], progress=40, result={"import_id": import_id, "source_type": "fictional"})
        return {"id": import_id, "category": chosen, "status": status, "note": note, "memories": imported_memories, "training_job": job}

    def parse_text_payload(text: str) -> list[dict[str, str]]:
        rows = []
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                rows.append({"speaker": "", "content": clean})
        return rows

    @router.get("/api/avatars/{avatar_id}/imports/{import_id}/preview")
    def preview_import(avatar_id: str, import_id: int, limit: int = 300) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        item = db.one("SELECT * FROM imports WHERE id=? AND avatar_id=?", (import_id, avatar_id))
        if not item:
            raise HTTPException(404, "导入记录不存在")
        safe_limit = min(max(limit, 1), 2000)
        rows = db.all(
            "SELECT id,row_index,speaker,content,selected,is_avatar FROM import_rows WHERE import_id=? ORDER BY row_index LIMIT ?",
            (import_id, safe_limit),
        )
        speakers = db.all(
            "SELECT speaker,COUNT(*) AS count FROM import_rows WHERE import_id=? GROUP BY speaker ORDER BY count DESC",
            (import_id,),
        )
        total = db.one("SELECT COUNT(*) AS count FROM import_rows WHERE import_id=?", (import_id,)) or {"count": 0}
        return {"import": item, "speakers": speakers, "rows": rows, "total": int(total["count"]), "truncated": int(total["count"]) > safe_limit}

    @router.post("/api/avatars/{avatar_id}/imports/{import_id}/confirm")
    def confirm_import(avatar_id: str, import_id: int, payload: ImportConfirm) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        item = db.one("SELECT * FROM imports WHERE id=? AND avatar_id=?", (import_id, avatar_id))
        if not item:
            raise HTTPException(404, "导入记录不存在")
        if item["status"] != "needs_review":
            raise HTTPException(409, "这份素材已经处理过，如需重新应用请再次导入")
        if item["category"] == "fictional":
            target = (selected.data_dir / str(item["stored_path"])).resolve()
            if selected.data_dir.resolve() not in target.parents or not target.is_file():
                raise HTTPException(400, "设定源文件已不存在，请重新导入")
            try:
                parsed = parse_fictional_source(target.read_text(encoding="utf-8-sig", errors="replace"), str(avatar["name"]), str(item["original_name"]))
            except (ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(400, f"设定文件无法确认：{exc}") from exc
            current = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
            current_traits = json.loads(current.get("traits_json") or "[]")
            if payload.apply_mode == "replace":
                summary = parsed["summary"]
                traits = parsed["traits"]
                speaking_style = parsed["speaking_style"]
                boundaries = parsed["boundaries"]
            else:
                summary = "\n\n".join(part for part in [str(current.get("summary", "")).strip(), parsed["summary"].strip()] if part)
                traits = list(dict.fromkeys([*current_traits, *parsed["traits"]]))
                speaking_style = "\n".join(part for part in [str(current.get("speaking_style", "")).strip(), parsed["speaking_style"].strip()] if part)
                boundaries = "\n".join(part for part in [str(current.get("boundaries", "")).strip(), parsed["boundaries"].strip()] if part)
            now = int(time.time())
            with db.transaction() as connection:
                connection.execute("DELETE FROM evidence WHERE source_import_id=?", (import_id,))
                connection.execute("DELETE FROM memories WHERE source_import_id=?", (import_id,))
                for evidence_item in parsed["evidence"]:
                    content = str(evidence_item.get("content", ""))[:100000]
                    kind = str(evidence_item.get("kind", "source"))[:80]
                    insert_evidence(
                        connection,
                        avatar_id=avatar_id,
                        source_import_id=import_id,
                        source_type="fictional_source",
                        title=str(evidence_item.get("title", ""))[:200],
                        content=content,
                        tags=[kind],
                        derived_kind=kind,
                        confidence=1.0,
                        created_at=now,
                    )
                    connection.execute(
                        "INSERT INTO memories(avatar_id,source_import_id,speaker,content,kind,is_avatar,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (avatar_id, import_id, str(avatar["name"]), content, f"fictional_{kind[:40]}", 1, 1.0, now),
                    )
                connection.execute(
                    "UPDATE persona_profiles SET summary=?,traits_json=?,speaking_style=?,boundaries=?,source_count=?,updated_at=? WHERE avatar_id=?",
                    (summary[:10000], json.dumps(traits[:30], ensure_ascii=False), speaking_style[:10000], boundaries[:10000], len(parsed["evidence"]), now, avatar_id),
                )
                note = f"已{('覆盖' if payload.apply_mode == 'replace' else '合并')} {len(parsed['evidence'])} 个设定部分"
                connection.execute("UPDATE imports SET status='confirmed',note=? WHERE id=?", (note, import_id))
            waiting_job = db.one(
                "SELECT id FROM training_jobs WHERE avatar_id=? AND job_type='persona' AND status='waiting_review' "
                "AND CAST(json_extract(result_json, '$.import_id') AS INTEGER)=? ORDER BY created_at DESC LIMIT 1",
                (avatar_id, import_id),
            )
            job = update_job(db, str(waiting_job["id"]), status="completed", progress=100, stage="设定已确认并写入人物档案", result={"import_id": import_id, "apply_mode": payload.apply_mode}) if waiting_job else None
            return {"confirmed": True, "accepted": len(parsed["evidence"]), "avatar_utterances": 0, "note": note, "training_job": job}
        rows = db.all("SELECT id,speaker,content FROM import_rows WHERE import_id=? ORDER BY row_index", (import_id,))
        if not rows:
            raise HTTPException(400, "没有可以确认的解析内容")
        excluded = set(payload.excluded_row_ids)
        avatar_speakers = {speaker.strip() for speaker in payload.avatar_speakers}
        known_speakers = {str(row["speaker"]).strip() for row in rows}
        if avatar_speakers and not (avatar_speakers & known_speakers):
            raise HTTPException(400, "选择的人物说话人没有对应内容")
        accepted = 0
        avatar_count = 0
        now = int(time.time())
        with db.transaction() as connection:
            connection.execute("DELETE FROM memories WHERE source_import_id=?", (import_id,))
            connection.execute("DELETE FROM evidence WHERE source_import_id=? AND source_type IN ('real_conversation','real_image_ocr')", (import_id,))
            accepted_lines = []
            avatar_lines = []
            for row in rows:
                is_selected = int(int(row["id"]) not in excluded)
                is_avatar = int(str(row["speaker"]).strip() in avatar_speakers)
                connection.execute("UPDATE import_rows SET selected=?,is_avatar=? WHERE id=?", (is_selected, is_avatar, row["id"]))
                if not is_selected:
                    continue
                line = f"{row['speaker'] or '未知'}: {row['content']}"
                accepted_lines.append(line)
                if is_avatar:
                    avatar_lines.append(str(row["content"]))
                connection.execute(
                    "INSERT INTO memories(avatar_id,source_import_id,speaker,content,kind,is_avatar,created_at) VALUES(?,?,?,?,?,?,?)",
                    (avatar_id, import_id, row["speaker"], row["content"], "conversation", is_avatar, now),
                )
                accepted += 1
                avatar_count += is_avatar
            if accepted_lines:
                source_type = "real_image_ocr" if item["category"] == "image" else "real_conversation"
                derived_kind = "image_ocr" if item["category"] == "image" else "conversation"
                insert_evidence(
                    connection,
                    avatar_id=avatar_id,
                    source_import_id=import_id,
                    source_type=source_type,
                    title=f"{'截图OCR' if item['category'] == 'image' else '聊天记录'}：{item['original_name']}",
                    content="\n".join(accepted_lines),
                    tags=[item["category"], derived_kind],
                    derived_kind=derived_kind,
                    confidence=1.0,
                    created_at=now,
                )
            if avatar_lines:
                insert_evidence(
                    connection,
                    avatar_id=avatar_id,
                    source_import_id=import_id,
                    source_type="real_avatar_utterances",
                    title=f"人物原型表达：{item['original_name']}",
                    content="\n".join(avatar_lines),
                    tags=["style", "avatar_utterances"],
                    derived_kind="speaking_style",
                    confidence=1.0,
                    created_at=now,
                )
            note = f"已确认 {accepted} 条；其中人物原型表达 {avatar_count} 条"
            connection.execute("UPDATE imports SET status='confirmed',note=? WHERE id=?", (note, import_id))
        job = create_job(
            db,
            avatar_id,
            "memory",
            status="completed",
            stage="资料清洗与说话人确认完成",
            input_summary=f"接受 {accepted} 条，人物原型表达 {avatar_count} 条",
        )
        update_job(db, job["id"], progress=100, result={"import_id": import_id, "accepted": accepted, "avatar_utterances": avatar_count})
        rebuild_memory_graph(db, avatar_id, 500)
        return {"confirmed": True, "accepted": accepted, "avatar_utterances": avatar_count, "note": note, "training_job": get_job(db, job["id"])}

    @router.get("/api/avatars/{avatar_id}/evidence")
    def get_evidence(avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        safe_limit = min(max(limit, 1), 500)
        rows = db.all(
            "SELECT id,source_import_id,source_type,title,content,tags_json,derived_kind,confidence,created_at FROM evidence WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
            (avatar_id, safe_limit),
        )
        for row in rows:
            row["tags"] = json.loads(row.pop("tags_json", "[]"))
        return rows

    @router.get("/api/avatars/{avatar_id}/checks")
    def avatar_checks(avatar_id: str) -> dict[str, Any]:
        try:
            return checks_for_avatar(db, avatar_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/build")
    def build_avatar(avatar_id: str) -> dict[str, Any]:
        try:
            result = run_builder(db, avatar_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        rebuild_memory_graph(db, avatar_id, 500)
        build_persona_core(db, avatar_id)
        job = create_job(db, avatar_id, "evaluation", status="completed", stage="构建检查、记忆图谱与 Persona Core 已更新")
        update_job(db, job["id"], progress=100, result=result)
        return {"job_id": job["id"], **result}

    return router
