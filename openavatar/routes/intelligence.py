from __future__ import annotations

from openavatar.routes._shared import *


def create_intelligence_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/memory-graph")
    def avatar_memory_graph(avatar_id: str, limit: int = 80) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return memory_graph(db, avatar_id, limit)

    @router.post("/api/avatars/{avatar_id}/memory-graph/rebuild")
    def rebuild_avatar_memory_graph(avatar_id: str, limit: int = 500) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return rebuild_memory_graph(db, avatar_id, limit)

    @router.get("/api/avatars/{avatar_id}/memory-revisions")
    def avatar_memory_revisions(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return memory_revisions(db, avatar_id)

    @router.patch("/api/avatars/{avatar_id}/memories/{memory_id}")
    def patch_avatar_memory(avatar_id: str, memory_id: int, payload: MemoryPatch) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            values = payload.model_dump(exclude_none=True, exclude={"note"})
            result = revise_memory(db, avatar_id, memory_id, values, action="edit", note=payload.note)
            rebuild_memory_graph(db, avatar_id, 500)
            return result
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/memories/{memory_id}/review")
    def review_avatar_memory(avatar_id: str, memory_id: int, payload: MemoryReviewPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            result = review_memory(db, avatar_id, memory_id, payload.action, payload.note)
            rebuild_memory_graph(db, avatar_id, 500)
            return result
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/memories/merge")
    def merge_avatar_memories(avatar_id: str, payload: MemoryMergePayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            result = merge_memories(db, avatar_id, payload.primary_id, payload.duplicate_id)
            rebuild_memory_graph(db, avatar_id, 500)
            return result
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/memories/consolidate")
    def consolidate_avatar_memories(avatar_id: str, limit: int = 120) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return sleep_consolidation(db, avatar_id, limit)

    @router.get("/api/avatars/{avatar_id}/training-jobs")
    def training_jobs(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return list_jobs(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/evaluate")
    def evaluate_avatar(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        result = create_readiness_evaluation(db, avatar_id)
        job = create_job(db, avatar_id, "evaluation", status="completed", stage="关键盲测与完成标准已生成")
        update_job(db, job["id"], progress=100, result=result)
        return {"job_id": job["id"], **result}

    @router.get("/api/avatars/{avatar_id}/quality-evaluations")
    def quality_evaluations(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        rows = db.all(
            "SELECT id,evaluation_kind,status,score,checks_json,samples_json,user_feedback_json,created_at,updated_at FROM quality_evaluations WHERE avatar_id=? ORDER BY id DESC LIMIT 100",
            (avatar_id,),
        )
        for row in rows:
            row["checks"] = json.loads(row.pop("checks_json", "[]"))
            row["samples"] = json.loads(row.pop("samples_json", "[]"))
            row["user_feedback"] = json.loads(row.pop("user_feedback_json", "{}"))
        return rows

    @router.post("/api/avatars/{avatar_id}/quality-evaluations/{evaluation_id}/feedback")
    def quality_feedback(avatar_id: str, evaluation_id: int, payload: EvaluationFeedback) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        row = db.one("SELECT * FROM quality_evaluations WHERE id=? AND avatar_id=?", (evaluation_id, avatar_id))
        if not row:
            raise HTTPException(404, "质量评测不存在")
        feedback = json.loads(str(row.get("user_feedback_json") or "{}"))
        feedback.setdefault("items", []).append({"rating": payload.rating, "note": payload.note, "created_at": int(time.time())})
        db.execute(
            "UPDATE quality_evaluations SET user_feedback_json=?,updated_at=? WHERE id=?",
            (json.dumps(feedback, ensure_ascii=False), int(time.time()), evaluation_id),
        )
        return next(item for item in quality_evaluations(avatar_id) if int(item["id"]) == evaluation_id)

    @router.get("/api/avatars/{avatar_id}/persona-core")
    def get_avatar_persona_core(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return current_persona_core(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/persona-core/rebuild")
    def rebuild_avatar_persona_core(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return build_persona_core(db, avatar_id)

    @router.get("/api/avatars/{avatar_id}/persona-feedback-rules")
    def avatar_persona_feedback_rules(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return feedback_rules(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/persona-feedback-rules", status_code=201)
    def add_avatar_persona_feedback_rule(avatar_id: str, payload: PersonaFeedbackPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        result = record_feedback_rule(
            db,
            avatar_id,
            dimension=payload.dimension,
            signal=payload.signal,
            rule_text=payload.rule_text,
            weight=payload.weight,
        )
        build_persona_core(db, avatar_id)
        return result

    @router.get("/api/avatars/{avatar_id}/diagnostics/decisions")
    def avatar_decision_diagnostics(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return decision_explanations(db, avatar_id)

    @router.get("/api/avatars/{avatar_id}/diagnostics/usage")
    def avatar_usage_diagnostics(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return usage_events(db, avatar_id)

    @router.get("/api/avatars/{avatar_id}/proactive-rules")
    def proactive_rules(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return get_proactive_rules(db, avatar_id)

    @router.put("/api/avatars/{avatar_id}/proactive-rules")
    def save_proactive_rules(avatar_id: str, payload: ProactiveRulesPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return update_proactive_rules(db, avatar_id, payload.model_dump())

    return router

