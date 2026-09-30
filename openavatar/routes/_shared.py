from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from openavatar import __version__
from openavatar.config import Settings, ensure_directories, load_settings
from openavatar.db import Database
from openavatar.local_model import LocalModelError, validate_local_url
from openavatar.providers import (
    ChatProvider,
    ProviderConfig,
    ProviderError,
    build_provider,
    delete_api_key,
    delete_provider_key,
    load_api_key,
    load_provider_key,
    normalize_openai_base_url,
    scoped_provider_key_name,
    store_api_key,
    store_provider_key,
)
from openavatar.schemas import (
    AvatarCreate,
    AvatarModelSettings,
    AvatarUpdate,
    CallSessionCreate,
    CallTurnCreate,
    ChatRequest,
    CloudServiceSettings,
    EvaluationFeedback,
    GuidedBuilderAnswer,
    HistoricalCorrectionPayload,
    ImportConfirm,
    MediaFeedbackPayload,
    MemoryMergePayload,
    MemoryPatch,
    MemoryReviewPayload,
    ModelConnectionPayload,
    ModelConnectionTestPayload,
    ModelRouteUpdate,
    ModelSettings,
    OcrConnectionPayload,
    OcrConnectionTestPayload,
    OnboardingState,
    InterfaceLanguageUpdate,
    PersonaFeedbackPayload,
    PersonaUpdate,
    ProactiveRulesPayload,
    SpeechRequest,
    TrainingRun,
    TimelineApplyPayload,
    TimelineBranchPayload,
    TimelineCandidatePayload,
    TimelineChangePreviewPayload,
    TranscriptionConfirm,
    VideoCallEventCreate,
    VideoCallBackgroundRequest,
    VideoCallVisionFeedback,
    VisualAssetUpdate,
    VoiceProfileCreate,
    WorldAdvancePayload,
    WorldConflictReview,
    WorldFactPayload,
    WorldModuleUpdate,
    WorldProposalReview,
)
from openavatar.services.importers import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    category_for_suffix,
    parse_conversation,
    safe_filename,
    strip_image_metadata,
)
from openavatar.services.fictional import FICTIONAL_EXTENSIONS, parse_fictional_source
from openavatar.services.builder import checks_for_avatar, run_builder
from openavatar.services.capabilities import capability_report
from openavatar.services.diagnostics import system_diagnostics
from openavatar.services.guided_builder import guided_state, record_answer, update_module
from openavatar.services.model_router import list_routes, update_route
from openavatar.services.ocr import (
    detect_local_ocr,
    extract_image_text,
    provider_key as ocr_provider_key,
    public_ocr_connection,
    upsert_ocr_connection,
    validate_ocr_payload,
)
from openavatar.services.packages import delete_avatar_files, export_avatar, import_avatar_package, inspect_avatar_package
from openavatar.services.media_review import create_visual_review, media_reviews, record_media_feedback
from openavatar.services.memory_intelligence import (
    memory_graph,
    memory_revisions,
    merge_memories,
    rebuild_memory_graph,
    review_memory,
    revise_memory,
    sleep_consolidation,
)
from openavatar.services.persona import build_profile, relevant_memories, style_signature
from openavatar.services.persona_core import (
    build_persona_core,
    current_persona_core,
    decision_explanations,
    feedback_rules,
    record_decision,
    record_feedback_rule,
    record_usage,
    usage_events,
)
from openavatar.services.http_security import install_local_security
from openavatar.services.proactive import get_proactive_rules, update_proactive_rules
from openavatar.services.proactive_runtime import proactive_worker
from openavatar.services.quality import create_readiness_evaluation
from openavatar.services.real_materials import write_material_report
from openavatar.services.readiness import completion_report, route_text
from openavatar.services.templates import template_payload
from openavatar.services.training import claim_job, create_job, get_job, list_jobs, request_cancel, retry_job, update_job
from openavatar.services.timeline_archive import (
    apply_change as apply_timeline_change,
    correct_historical_memory,
    delete_branch as delete_timeline_branch,
    list_candidates as list_timeline_candidates,
    overview as timeline_overview,
    preview_change as preview_timeline_change,
    restore_branch as restore_timeline_branch,
    search_records,
    update_candidate as update_timeline_candidate,
)
from openavatar.services.voice import create_voice_profile, ensure_voice_choices, list_development_voices, select_voice_profile
from openavatar.services.world_model import WorldModelError, create_fact_from_payload, list_proposals, review_proposal
from openavatar.services.world_runtime import advance_world, resolve_conflict, rollback_last_event, runtime_state, scan_consistency
from openavatar.services.world_regions import avatar_language_profile, current_interface_language, normalize_language, world_options
from openavatar.services.aliyun import AliyunAvatarClient, AliyunError, download_provider_asset, extract_urls
from openavatar.services.video_call import (
    VideoCallStartRequest,
    close_north_session,
    start_north_video_call,
    video_call_provider_status,
)
from openavatar.services.video_generation import (
    VideoGenerationError,
    VideoGenerationSettings,
    build_first_frame,
    download_video_result,
    poll_video_generation,
    select_video_tier,
    start_video_generation,
)



from openavatar.application import *
from openavatar.services.avatar_access import *
from openavatar.services.evidence import *
from openavatar.services.model_connections import *
from openavatar.services.video_runtime import *
