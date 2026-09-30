from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AvatarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(default="", max_length=500)
    relationship: str = Field(default="朋友", max_length=80)
    subject_kind: Literal["self", "authorized_person", "fictional"] = "self"
    adult_subject: bool = True
    consent_confirmed: bool = False
    avatar_primary_language: Literal["zh-CN", "en-US", "bilingual", "custom"] = "zh-CN"
    avatar_secondary_languages: list[str] = Field(default_factory=list, max_length=8)
    avatar_response_mode: Literal["follow_user", "fixed_primary", "bilingual_mix", "scene_based"] = "follow_user"
    world_region: Literal["mainland_china", "north_america", "japan", "europe", "custom"] = "mainland_china"
    world_type: Literal["realistic", "fictional", "hybrid"] = "realistic"
    world_region_custom: dict[str, Any] = Field(default_factory=dict)


class AvatarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    purpose: str | None = Field(default=None, max_length=500)
    relationship: str | None = Field(default=None, max_length=80)
    consent_confirmed: bool | None = None
    proactive_enabled: bool | None = None
    proactive_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    avatar_primary_language: Literal["zh-CN", "en-US", "bilingual", "custom"] | None = None
    avatar_secondary_languages: list[str] | None = Field(default=None, max_length=8)
    avatar_response_mode: Literal["follow_user", "fixed_primary", "bilingual_mix", "scene_based"] | None = None
    world_region: Literal["mainland_china", "north_america", "japan", "europe", "custom"] | None = None
    world_type: Literal["realistic", "fictional", "hybrid"] | None = None
    world_region_custom: dict[str, Any] | None = None


class PersonaUpdate(BaseModel):
    summary: str = Field(max_length=10000)
    traits: list[str] = Field(default_factory=list, max_length=30)
    speaking_style: str = Field(max_length=10000)
    boundaries: str = Field(max_length=10000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    preview_mode: bool = False


class HistoricalCorrectionPayload(BaseModel):
    speaker: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=100000)
    note: str = Field(default="", max_length=1000)


class TimelineChangePreviewPayload(BaseModel):
    timeline_kind: Literal["official", "preview"] = "official"
    action: Literal["edit", "delete"]
    message_id: int = Field(ge=1)
    replacement_text: str = Field(default="", max_length=10000)


class TimelineApplyPayload(BaseModel):
    preview_token: str = Field(min_length=1, max_length=100)


class TimelineBranchPayload(BaseModel):
    branch_id: str = Field(min_length=1, max_length=100)


class TimelineCandidatePayload(BaseModel):
    status: Literal["available", "approved", "rejected", "used"]
    confirmed: bool = False


class ImportConfirm(BaseModel):
    avatar_speakers: list[str] = Field(default_factory=list, max_length=100)
    excluded_row_ids: list[int] = Field(default_factory=list, max_length=100000)
    apply_mode: Literal["merge", "replace"] = "merge"


class ModelSettings(BaseModel):
    mode: Literal["local", "cloud"] = "local"
    provider_name: str = Field(default="openrouter", max_length=80)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openrouter/auto"
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    cloud_data_consent: bool = False


class AvatarModelSettings(BaseModel):
    mode: Literal["inherit", "local", "cloud"] = "inherit"
    connection_id: str = Field(default="", max_length=80)
    provider_name: str = Field(default="custom-api", max_length=80)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openrouter/auto"
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    cloud_data_consent: bool = False


class ModelConnectionPayload(BaseModel):
    display_name: str = Field(default="我的模型连接", min_length=1, max_length=80)
    connection_type: Literal["cloud_openai", "local_openai", "ollama", "custom_local_adapter"] = "cloud_openai"
    provider_name: str = Field(default="自定义 API", max_length=80)
    base_url: str = Field(default="https://api.example.com/v1", max_length=500)
    model: str = Field(default="", max_length=200)
    adapter_kind: Literal["openai_compatible", "ollama"] = "openai_compatible"
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    cloud_data_consent: bool = False


class ModelConnectionTestPayload(ModelConnectionPayload):
    connection_id: str = Field(default="", max_length=80)


ProviderCapability = Literal[
    "chat", "vision", "asr", "tts", "voice_clone", "image", "video", "realtime_video"
]


class ProviderConnectionPayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    provider_kind: Literal["minimax", "aliyun", "north", "openrouter", "openai_compatible", "local"]
    base_url: str = Field(default="", max_length=500)
    region: str = Field(default="", max_length=80)
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    consent: dict[str, bool] = Field(default_factory=dict)
    budget: dict[str, float] = Field(default_factory=dict)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    enabled: bool = True


class CapabilityRoutePayload(BaseModel):
    scope_type: Literal["global", "avatar"] = "global"
    avatar_id: str = Field(default="", max_length=80)
    capability: ProviderCapability
    primary_connection_id: str = Field(default="", max_length=80)
    fallback_connection_ids: list[str] = Field(default_factory=list, max_length=8)
    model: str = Field(default="", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class OcrConnectionPayload(BaseModel):
    display_name: str = Field(default="我的 OCR", min_length=1, max_length=80)
    connection_type: Literal["local_command", "local_http", "cloud_api"] = "local_command"
    provider_name: str = Field(default="自定义 OCR", max_length=80)
    command_template: str = Field(default="", max_length=1000)
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    api_key_required: bool = False
    cloud_data_consent: bool = False
    enabled: bool = True


class OcrConnectionTestPayload(OcrConnectionPayload):
    connection_id: str = Field(default="", max_length=80)


class CloudServiceSettings(BaseModel):
    aliyun_api_key: str = Field(default="", max_length=1000)
    clear_aliyun_api_key: bool = False
    voice_clone_model: str = Field(default="qwen-voice-enrollment", max_length=120)
    voice_target_model: str = Field(default="qwen3-tts-vc-2026-01-22", max_length=120)
    voice_tts_model: str = Field(default="qwen3-tts-vc-2026-01-22", max_length=120)
    image_reference_model: str = Field(default="qwen-image-2.0-pro", max_length=120)
    video_model: str = Field(default="wan2.7-i2v-2026-04-25", max_length=120)
    north_api_key: str = Field(default="", max_length=1000)
    clear_north_api_key: bool = False
    north_api_url: str = Field(default="https://api.atlasv1.com", max_length=500)
    north_face_url: str = Field(default="", max_length=1000)
    north_idle_timeout: int = Field(default=300, ge=30, le=3600)
    north_price_per_second: float = Field(default=0.00194, ge=0, le=10)
    video_call_enabled: bool = True
    scene_background_enabled: bool = True
    camera_flip_enabled: bool = True
    vision_feedback_enabled: bool = True
    smart_interrupt_enabled: bool = True
    cloud_data_consent: bool = False


class TrainingRun(BaseModel):
    confirm_billable_call: bool = False


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    confirm_billable_call: bool = False


class ModelRouteUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=80)
    provider: str = Field(default="openrouter", max_length=80)
    primary_model: str = Field(default="", max_length=200)
    fallback_models: list[str] = Field(default_factory=list, max_length=10)
    latency_class: str = Field(default="background", max_length=40)
    cost_class: str = Field(default="cheap", max_length=40)


class VoiceProfileCreate(BaseModel):
    provider: str = Field(default="api", max_length=80)
    voice_id: str = Field(default="", max_length=500)
    voice_name: str = Field(default="自定义声音", max_length=200)
    profile_kind: str = Field(default="api_tts", max_length=80)
    model: str = Field(default="", max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = False


class TranscriptionConfirm(BaseModel):
    transcript: str = Field(min_length=1, max_length=100000)
    speaker: str = Field(default="", max_length=120)
    use_as_memory: bool = True


class VisualAssetUpdate(BaseModel):
    status: Literal["candidate", "approved", "canonical", "rejected", "retired"]
    label: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=1000)


class VisualAssetSetCreate(BaseModel):
    set_type: Literal["identity", "wardrobe", "prop", "scene"]
    semantic_key: str = Field(default="", max_length=120)
    label: str = Field(min_length=1, max_length=200)
    invariants: list[str] = Field(default_factory=list, max_length=30)
    negative_constraints: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["candidate", "approved", "canonical"] = "candidate"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualAssetSetUpdate(BaseModel):
    status: Literal["candidate", "approved", "canonical", "rejected", "retired"] | None = None
    label: str | None = Field(default=None, max_length=200)
    invariants: list[str] | None = Field(default=None, max_length=30)
    negative_constraints: list[str] | None = Field(default=None, max_length=30)


class VisualAssetItemCreate(BaseModel):
    visual_asset_id: int = Field(default=0, ge=0)
    role: Literal[
        "reference", "front", "left", "right", "back", "full_body", "detail",
        "holding", "wide", "key_frame", "first_frame", "history_keyframe",
    ] = "reference"
    local_path: str = Field(default="", max_length=1000)
    remote_url: str = Field(default="", max_length=4000)
    status: Literal["candidate", "approved", "canonical", "rejected", "retired"] = "candidate"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneProfileCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    semantic_key: str = Field(default="", max_length=120)
    stable_features: list[str] = Field(default_factory=list, max_length=40)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    topology: dict[str, Any] = Field(default_factory=dict)
    status: Literal["candidate", "approved", "canonical"] = "candidate"
    route: Literal["image_bootstrap", "image_grounded", "model_grounded"] = "image_bootstrap"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    stable_features: list[str] | None = Field(default=None, max_length=40)
    negative_constraints: list[str] | None = Field(default=None, max_length=40)
    topology: dict[str, Any] | None = None
    status: Literal["candidate", "approved", "canonical", "rejected", "retired"] | None = None
    route: Literal["image_bootstrap", "image_grounded", "model_grounded"] | None = None


class ContinuityPlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    hints: dict[str, Any] = Field(default_factory=dict)


class WorldFactPayload(BaseModel):
    fact_key: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=20000)
    reality_kind: str = "fictional_runtime"
    mutability: str = "evolving"
    reason: str = Field(default="", max_length=1000)


class WorldProposalReview(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=1000)


class GuidedBuilderAnswer(BaseModel):
    question_key: str = Field(min_length=1, max_length=80)
    answer: str = Field(min_length=1, max_length=20000)


class WorldModuleUpdate(BaseModel):
    enabled: bool = True


class EvaluationFeedback(BaseModel):
    rating: Literal["like", "unlike", "too_long", "too_cold", "invented", "off_style"]
    note: str = Field(default="", max_length=1000)


class ProactiveRulesPayload(BaseModel):
    daily_max: int = Field(default=2, ge=0, le=24)
    allowed_windows: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    quiet_hours: dict[str, str] = Field(default_factory=dict)
    topic_scope: list[str] = Field(default_factory=list, max_length=20)
    use_long_term_memory: bool = True
    allow_world_event_advancement: bool = False
    tone: str = Field(default="自然、简短、有边界感", max_length=500)
    cooldown_after_user_reply_minutes: int = Field(default=120, ge=15, le=10080)


class WorldAdvancePayload(BaseModel):
    seconds: int = Field(default=3600, ge=60, le=604800)
    force_minor_event: bool = False


class WorldConflictReview(BaseModel):
    action: Literal["keep_existing", "accept_candidate", "dismiss"]
    note: str = Field(default="", max_length=1000)


class MemoryPatch(BaseModel):
    speaker: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, max_length=100000)
    kind: str | None = Field(default=None, max_length=80)
    is_avatar: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str = Field(default="", max_length=1000)


class MemoryReviewPayload(BaseModel):
    action: Literal["approve", "downgrade", "reject"]
    note: str = Field(default="", max_length=1000)


class MemoryMergePayload(BaseModel):
    primary_id: int = Field(ge=1)
    duplicate_id: int = Field(ge=1)


class PersonaFeedbackPayload(BaseModel):
    dimension: str = Field(default="style", max_length=80)
    signal: str = Field(default="off_style", max_length=80)
    rule_text: str = Field(min_length=1, max_length=1000)
    weight: float = Field(default=0.5, ge=0, le=1)


class MediaFeedbackPayload(BaseModel):
    feedback: str = Field(default="good", max_length=80)
    comment: str = Field(default="", max_length=1000)


class CallSessionCreate(BaseModel):
    provider: str = Field(default="protocol-only", max_length=80)
    mode: Literal["voice", "video"] = "voice"
    user_camera_enabled: bool = False
    confirm_billable_call: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallTurnCreate(BaseModel):
    user_transcript: str = Field(default="", max_length=20000)
    assistant_text: str = Field(default="", max_length=20000)
    asr_latency_ms: int = Field(default=0, ge=0)
    llm_latency_ms: int = Field(default=0, ge=0)
    tts_latency_ms: int = Field(default=0, ge=0)
    interrupted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoCallEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class VideoCallVisionFeedback(BaseModel):
    feedback: str = Field(default="clear", max_length=80)
    comment: str = Field(default="", max_length=1000)
    frame_summary: str = Field(default="", max_length=2000)


class VideoCallBackgroundRequest(BaseModel):
    prompt: str = Field(default="", max_length=1000)
    mode: Literal["scene", "flipped"] = "scene"


class OnboardingState(BaseModel):
    completed: bool = True


class InterfaceLanguageUpdate(BaseModel):
    language: Literal["zh-CN", "en-US"] = "zh-CN"
