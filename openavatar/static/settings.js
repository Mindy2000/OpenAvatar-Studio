async function loadAvatarModelSettings() {
  if (!state.currentId) return;
  const [values, rules] = await Promise.all([
    api(`/api/avatars/${state.currentId}/settings/model`),
    api(`/api/avatars/${state.currentId}/proactive-rules`),
  ]);
  await loadModelConnections();
  $("#avatarModelMode").value = values.connection_id ? "connection" : "inherit";
  fillConnectionSelect($("#avatarConnectionSelect"), values.connection_id || state.selectedConnectionId);
  renderConnectionHint("#avatarConnectionHint", $("#avatarConnectionSelect").value);
  $("#avatarModelResult").textContent = values.effective.inherited
    ? `当前继承默认连接：${values.effective.provider_name} · ${values.effective.model}`
    : `当前使用指定连接：${values.effective.provider_name} · ${values.effective.model}`;
  $("#proactiveDailyMax").value = rules.daily_max;
  $("#proactiveCooldown").value = rules.cooldown_after_user_reply_minutes;
  $("#proactiveWindows").value = formatWindows(rules.allowed_windows);
  $("#proactiveQuiet").value = formatQuiet(rules.quiet_hours);
  $("#proactiveTopics").value = (rules.topic_scope || []).join(", ");
  $("#proactiveTone").value = rules.tone || "";
  $("#proactiveUseMemory").checked = Boolean(rules.use_long_term_memory);
  $("#proactiveAdvanceWorld").checked = Boolean(rules.allow_world_event_advancement);
}

function parseWindows(text) {
  return String(text || "").split(",").map(item => item.trim()).filter(Boolean).map(item => {
    const [start, end] = item.split("-").map(part => part.trim());
    return { start: start || "09:00", end: end || "22:30" };
  });
}

function formatWindows(windows) {
  return (windows || []).map(item => `${item.start || "09:00"}-${item.end || "22:30"}`).join(", ");
}

function parseQuiet(text) {
  const [start, end] = String(text || "").split("-").map(part => part.trim());
  return { start: start || "23:00", end: end || "08:30" };
}

function formatQuiet(value) {
  return `${value?.start || "23:00"}-${value?.end || "08:30"}`;
}

async function loadTrainingJobs() {
  const jobs = await api(`/api/avatars/${state.currentId}/training-jobs`);
  const done = jobs.filter(job => job.status === "completed").length;
  const active = jobs.filter(job => ["queued", "running"].includes(job.status)).length;
  const waiting = jobs.filter(job => ["waiting_configuration", "needs_review"].includes(job.status)).length;
  const cost = jobs.reduce((sum, job) => sum + Number(job.actual_cost || 0), 0);
  $("#trainingDone").textContent = done; $("#trainingActive").textContent = active; $("#trainingWaiting").textContent = waiting; $("#trainingCost").textContent = cost.toFixed(2);
  const typeNames = { persona: "人格构建", memory: "记忆整理", voice: "声音构建", visual: "形象构建", video: "视频生成", evaluation: "构建检查" };
  const statusNames = { queued: "排队中", running: "进行中", completed: "已完成", failed: "失败", cancelled: "已取消", waiting_configuration: "等待配置", needs_review: "等待人工复核" };
  $("#trainingJobs").innerHTML = jobs.length ? jobs.map(job => `<article class="training-job"><div class="job-top"><b>${typeNames[job.job_type] || escapeHtml(job.job_type)}</b><span class="job-status ${job.status}">${statusNames[job.status] || escapeHtml(job.status)}</span></div><progress class="job-progress" max="100" value="${Math.max(0, Math.min(100, Number(job.progress) || 0))}"></progress><div class="job-meta"><span>${escapeHtml(job.stage || "等待更新")}</span><span>${job.result?.provider || job.provider ? `服务：${escapeHtml(job.result?.provider || job.provider)}` : "尚未选择服务"}</span></div>${job.result?.asset_url ? (job.job_type === "video" ? `<video class="training-preview" src="${escapeHtml(job.result.asset_url)}" controls playsinline></video>` : `<img class="training-preview" src="${escapeHtml(job.result.asset_url)}" alt="生成的人物参考图">`) : ""}${job.result?.provider_task_id && !job.result?.asset_url ? `<p class="job-hint">服务商任务：${escapeHtml(job.result.provider_task_id)} · ${escapeHtml(job.result.provider_status || "PENDING")}</p>` : ""}${job.result?.reference_audit?.length ? `<p class="job-hint">本次实际使用 ${job.result.reference_audit.length} 项连续性参考素材</p>` : ""}${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ""}${(job.status === "waiting_configuration" && ["voice", "visual", "video"].includes(job.job_type)) || (job.job_type === "video" && job.status === "running") ? `<button class="primary" data-action="run-cloud-job" data-job-id="${job.id}">${job.job_type === "video" && job.status === "running" ? "立即检查结果" : "使用云端 API 执行"}</button>` : ""}${job.status === "needs_review" && job.result?.continuity_run_id ? `<button class="primary" data-action="approve-video-review" data-run-id="${escapeHtml(job.result.continuity_run_id)}">人工确认可用</button>` : ""}${job.status === "failed" || job.status === "cancelled" ? `<button class="secondary" data-action="retry-job" data-job-id="${job.id}">重试</button>` : ""}${["queued", "running"].includes(job.status) ? `<button class="ghost" data-action="cancel-job" data-job-id="${job.id}">取消</button>` : ""}</article>`).join("") : `<div class="empty-card">还没有构建任务。导入并确认资料后，任务会显示在这里。</div>`;
  await loadBuildPanels();
}

async function loadBuildPanels() {
  const [checks, world, proposals, rights, visual, voices, transcripts, routes, devVoices, graph, core, decisions, usage, mediaReviews, videoStatus, assetSets, scenes, continuityRuns] = await Promise.all([
    api(`/api/avatars/${state.currentId}/checks`),
    api(`/api/avatars/${state.currentId}/world`),
    api(`/api/avatars/${state.currentId}/world/proposals`),
    api(`/api/avatars/${state.currentId}/rights`),
    api(`/api/avatars/${state.currentId}/visual-assets`),
    api(`/api/avatars/${state.currentId}/voice-profiles`),
    api(`/api/avatars/${state.currentId}/voice-transcriptions`),
    api("/api/settings/model-routes"),
    api("/api/voice/development-voices"),
    api(`/api/avatars/${state.currentId}/memory-graph`),
    api(`/api/avatars/${state.currentId}/persona-core`),
    api(`/api/avatars/${state.currentId}/diagnostics/decisions`),
    api(`/api/avatars/${state.currentId}/diagnostics/usage`),
    api(`/api/avatars/${state.currentId}/media-reviews`),
    api(`/api/avatars/${state.currentId}/video-call/status`),
    api(`/api/avatars/${state.currentId}/visual-asset-sets`),
    api(`/api/avatars/${state.currentId}/scene-profiles`),
    api(`/api/avatars/${state.currentId}/continuity/runs`),
  ]);
  const activeVoice = voices.find(item => item.active) || voices[0] || {};
  const canonicalVisual = visual.find(item => item.status === "canonical");
  const approvedVisuals = visual.filter(item => item.status === "approved").length;
  const pendingProposals = proposals.filter(item => item.status === "pending").length;
  const levelNames = { required: "必须项", recommended: "推荐项", advanced: "高级项" };
  $("#buildCenterTitle").textContent = checks.route === "fictional" ? "虚构数字人的可运行里世界" : "真实素材到多模态数字人";
  $("#buildCenterLead").textContent = checks.route === "fictional" ? "必须项完成后可正式使用；可选模块决定里世界深度，事件推进默认进入审批。" : "真实路线必须先有文本人格素材，再用音频、视觉、长期记忆继续增强。";
  const jobs = await api(`/api/avatars/${state.currentId}/training-jobs`);
  renderNextAction(checks, proposals, transcripts, jobs);
  $("#buildPanels").innerHTML = `
    <article class="build-panel build-score"><header><span>COMPLETION STANDARD</span><b>${checks.score}</b></header>
      <div class="completion-groups">${Object.entries(checks.groups || {}).map(([level, group]) => `<span class="${group.complete ? "passed" : "pending"}">${levelNames[level] || level} ${group.passed}/${group.total}</span>`).join("")}</div>
      ${["required", "recommended", "advanced"].map(level => `<section class="check-level"><h4>${levelNames[level]}</h4>${checks.checks.filter(item => (item.level || item.severity) === level).map(item => `<p class="${item.passed ? "passed" : "pending"}">${item.passed ? "✓" : "○"} ${escapeHtml(item.name)}<small>${escapeHtml(item.recommendation || item.severity)}</small></p>`).join("")}</section>`).join("")}</article>
    <article class="build-panel"><header><span>WORLD MODEL</span><b>${world.facts.length}</b></header>
      <p><strong>${pendingProposals} 个待审批提案</strong><small>受保护事实必须由用户批准，运行时不能直接覆盖 canon。</small></p>
      ${(world.facts.length ? world.facts.slice(0, 8) : [{ fact_key: "尚未生成", value: "运行统一 Builder 后生成第一批世界事实" }]).map(item => `<p><strong>${escapeHtml(item.fact_key)}</strong><small>${escapeHtml(compactValue(item.value))}</small></p>`).join("")}</article>
    <article class="build-panel"><header><span>VISUAL APPROVAL</span><b>${visual.length}</b></header>
      <p><strong>${canonicalVisual ? "已有 canonical 身份参考" : "尚未锁定 canonical"}</strong><small>${approvedVisuals} 张 approved；候选图不会自动进入正式身份。</small></p>
      ${(visual.length ? visual.slice(0, 8) : [{ label: "暂无视觉候选", status: "draft", asset_kind: "identity" }]).map(item => visualAssetRow(item)).join("")}</article>
    ${continuityBuildPanel(assetSets, scenes, continuityRuns)}
    <article class="build-panel"><header><span>VOICE CHOICE</span><b>${voices.length}</b></header>
      <p><strong>${escapeHtml(activeVoice.voice_name || "待用户选择")}</strong><small>${escapeHtml(activeVoice.provider || "user_choice")} · ${escapeHtml(activeVoice.profile_kind || "synthetic_or_api")}</small></p>
      ${voices.map(item => voiceProfileRow(item)).join("") || devVoices.map(item => `<p><strong>${escapeHtml(item.voice_name)}</strong><small>${escapeHtml(item.provider)} · ${escapeHtml(item.profile_kind)}</small></p>`).join("")}</article>
    ${voiceCloneFlowPanel(checks, voices, transcripts, jobs)}
    ${videoCallBuildPanel(videoStatus)}
    ${worldRegionPanel(world)}
    <article class="build-panel"><header><span>RIGHTS</span><b>${rights.length}</b></header>
      ${rights.map(item => `<p><strong>${escapeHtml(item.grant_type)}</strong><small>${escapeHtml(item.rights_scope)} · ${item.revocable ? "可撤销" : "不可撤销"}</small></p>`).join("") || "<p><strong>暂无授权记录</strong><small>真实素材路线需要记录授权边界</small></p>"}</article>
    ${materialQualityPanel(checks, voices, visual, transcripts)}
    ${releaseCheckPanel(checks, proposals, transcripts)}
    ${settingMapPanel(world)}`;
  $("#worldProposalList").innerHTML = proposals.length ? proposals.map(item => `<article class="approval-item ${item.status}">
    <div><b>${escapeHtml(item.fact_key)}</b><small>${escapeHtml(item.status)} · ${escapeHtml(item.reality_kind)} · ${escapeHtml(item.mutability)}</small></div>
    <p>${escapeHtml(compactValue(item.value))}</p>
    ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
    ${item.status === "pending" ? `<div class="inline-actions"><button class="secondary" data-action="review-world-proposal" data-proposal-id="${item.id}" data-review-action="approve">批准</button><button class="ghost" data-action="review-world-proposal" data-proposal-id="${item.id}" data-review-action="reject">拒绝</button></div>` : ""}
  </article>`).join("") : `<div class="empty-card">没有待处理的世界事实提案。运行 Builder 或手动新增事实后会显示。</div>`;
  $("#transcriptionList").innerHTML = transcripts.length ? transcripts.map(item => `<article class="approval-item ${item.status}">
    <div><b>音频 #${item.source_import_id || item.id}</b><small>${escapeHtml(item.status)} · ${escapeHtml(item.provider)} · ${escapeHtml(item.model)}</small></div>
    ${item.status === "needs_review" ? `<textarea rows="3" data-transcription-text="${item.id}" placeholder="填入 ASR 或人工整理后的文本">${escapeHtml(item.transcript || "")}</textarea><div class="inline-actions"><button class="secondary" data-action="run-transcription" data-transcription-id="${item.id}">使用 ASR 自动转写</button><button class="secondary" data-action="confirm-transcription" data-transcription-id="${item.id}">确认转写并作为表达样本</button></div>` : `<p>${escapeHtml(item.transcript)}</p>`}
  </article>`).join("") : `<div class="empty-card">还没有声音转写记录。上传音频后会进入这里。</div>`;
  $("#modelRouteList").innerHTML = routes.map(item => `<article class="route-item">
    <div><b>${escapeHtml(item.role)}</b><small>${escapeHtml(item.latency_class)} · ${escapeHtml(item.cost_class)}</small></div>
    <label>Provider<input data-route-field="provider" data-route="${escapeHtml(item.role)}" value="${escapeHtml(item.provider)}"></label>
    <label>模型<input data-route-field="primary_model" data-route="${escapeHtml(item.role)}" value="${escapeHtml(item.primary_model)}"></label>
    <button class="secondary" data-action="save-model-route" data-route="${escapeHtml(item.role)}">保存</button>
  </article>`).join("");
  $("#memoryGraphList").innerHTML = graph.nodes?.length ? graph.nodes.slice(0, 14).map(item => `<article class="approval-item">
    <div><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.node_type)} · ${(Number(item.weight) || 0).toFixed(2)} · ${item.evidence_count} 条证据</small></div>
  </article>`).join("") : `<div class="empty-card">还没有记忆图谱。确认聊天记录或运行统一 Builder 后会生成。</div>`;
  const persona = core.core?.persona || {};
  const coreNodes = core.core?.memory_graph?.top_nodes || [];
  $("#personaCoreList").innerHTML = `<article class="approval-item">
    <div><b>${escapeHtml(core.digest?.slice(0, 10) || "未生成")}</b><small>Persona Core · ${coreNodes.length} 个核心记忆节点</small></div>
    <p>${escapeHtml(persona.summary || "尚未形成人格核心摘要")}</p>
  </article>${(core.core?.feedback_rules || []).slice(0, 6).map(item => `<article class="approval-item"><div><b>${escapeHtml(item.dimension)}</b><small>${escapeHtml(item.signal)} · ${Number(item.weight).toFixed(2)}</small></div><p>${escapeHtml(item.rule_text)}</p></article>`).join("")}`;
  $("#diagnosticList").innerHTML = `
    <article class="approval-item"><div><b>${decisions.length} 条决策解释</b><small>最近聊天、构建和模型选择记录</small></div>${decisions.slice(0, 3).map(item => `<p>${escapeHtml(item.decision_kind)}：${escapeHtml(item.output_summary)}</p>`).join("")}</article>
    <article class="approval-item"><div><b>${usage.length} 条用量记录</b><small>模型、延迟、状态</small></div>${usage.slice(0, 3).map(item => `<p>${escapeHtml(item.role)} · ${escapeHtml(item.model)} · ${item.latency_ms}ms</p>`).join("")}</article>
    <article class="approval-item"><div><b>${mediaReviews.length} 条媒体评审</b><small>视觉一致性和用户反馈</small></div>${mediaReviews.slice(0, 3).map(item => `<p>${escapeHtml(item.review_kind)} · ${item.score}</p>`).join("")}</article>`;
}

function continuityBuildPanel(assetSets, scenes, runs) {
  const typeNames = { identity: "人物", wardrobe: "服装", prop: "物品", scene: "场景" };
  const approved = assetSets.filter(item => ["approved", "canonical"].includes(item.status));
  const groundedScenes = scenes.filter(item => item.route === "image_grounded" || item.route === "model_grounded");
  const latest = runs[0];
  return `<article class="build-panel"><header><span>VISUAL CONTINUITY</span><b>${approved.length}/${assetSets.length}</b></header>
    <p><strong>一致性素材包</strong><small>人物、服装、物品和场景按组管理；视频只使用已批准素材。</small></p>
    <div class="completion-groups">${["identity", "wardrobe", "prop", "scene"].map(type => {
      const count = approved.filter(item => item.set_type === type).length;
      return `<span class="${count ? "passed" : "pending"}">${typeNames[type]} ${count}</span>`;
    }).join("")}</div>
    <p><strong>${groundedScenes.length} 个场景已有关键图</strong><small>${scenes.filter(item => item.route === "image_bootstrap").length} 个场景仍会在视频前触发关键首帧门禁。</small></p>
    ${latest ? `<p><strong>最近连续性任务：${escapeHtml(latest.status)}</strong><small>${escapeHtml(latest.prompt || "")}</small></p>` : ""}
    <button class="secondary" data-action="organize-visual-assets">整理现有素材为一致性资产包</button>
  </article>`;
}

function videoCallBuildPanel(status) {
  const supports = status.supports || {};
  return `<article class="build-panel"><header><span>REALTIME VIDEO</span><b>${status.available ? "READY" : "SETUP"}</b></header>
    <p class="${status.available ? "passed" : "pending"}"><strong>North/Atlas 固定 provider</strong><small>${escapeHtml(status.reason || "")}</small></p>
    <p><strong>身份参考</strong><small>${status.hasCanonicalOrApprovedFace ? "使用 canonical/approved 本地图" : status.hasFaceUrl ? "使用 HTTPS Face URL" : "需要批准或锁定一张身份参考图"}</small></p>
    <p><strong>LiveKit 实时口型</strong><small>${supports.livekit ? "已启用协议" : "未启用"} · ${supports.sceneBackground ? "背景" : "无背景"} · ${supports.cameraFlip ? "翻转" : "无翻转"}</small></p>
    <p><strong>费用提示</strong><small>预计 ${Number(status.settings?.north_price_per_second || 0).toFixed(5)} / 秒，开始通话前仍需确认。</small></p>
  </article>`;
}

function compactValue(value) {
  const text = typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
  return text.length > 240 ? `${text.slice(0, 240)}...` : text;
}

function visualAssetRow(item) {
  const actions = item.status === "candidate" ? `<span class="mini-actions"><button data-action="update-visual-asset" data-asset-id="${item.id}" data-status="approved">批准</button><button data-action="update-visual-asset" data-asset-id="${item.id}" data-status="rejected">拒绝</button></span>` : item.status === "approved" ? `<span class="mini-actions"><button data-action="update-visual-asset" data-asset-id="${item.id}" data-status="canonical">设为 canonical</button></span>` : "";
  const classify = ["approved", "canonical"].includes(item.status) ? `<span class="mini-actions visual-classify"><button data-action="classify-visual-asset" data-asset-id="${item.id}" data-asset-status="${item.status}" data-set-type="identity">人物</button><button data-action="classify-visual-asset" data-asset-id="${item.id}" data-asset-status="${item.status}" data-set-type="wardrobe">服装</button><button data-action="classify-visual-asset" data-asset-id="${item.id}" data-asset-status="${item.status}" data-set-type="prop">物品</button><button data-action="classify-visual-asset" data-asset-id="${item.id}" data-asset-status="${item.status}" data-set-type="scene">场景</button></span>` : "";
  const preview = item.asset_url ? `<img class="visual-thumb" src="${escapeHtml(item.asset_url)}" alt="视觉候选图">` : "";
  return `<p>${preview}<strong>${escapeHtml(item.label || item.asset_kind)}</strong><small>${escapeHtml(item.status)} · ${escapeHtml(item.asset_kind)}</small>${actions}${classify}</p>`;
}

function voiceProfileRow(item) {
  return `<p><strong>${item.active ? "● " : ""}${escapeHtml(item.voice_name || item.voice_id || "未命名声音")}</strong><small>${escapeHtml(item.provider)} · ${escapeHtml(item.profile_kind)} · ${escapeHtml(item.status)}</small>${!item.active ? `<span class="mini-actions"><button data-action="select-voice-profile" data-profile-id="${item.id}">选择</button></span>` : ""}</p>`;
}

function voiceCloneFlowPanel(checks, voices, transcripts, jobs) {
  if ((checks.route || "real") === "fictional") return "";
  const hasAudio = (checks.checks || []).find(item => item.name === "声音样本")?.passed;
  const hasTranscript = transcripts.some(item => item.status === "confirmed");
  const hasVoiceJob = jobs.some(job => job.job_type === "voice");
  const activeVoice = voices.some(item => item.active && item.profile_kind !== "none");
  const clonedVoice = voices.some(item => ["voice_clone", "cloned_voice", "api_tts"].includes(item.profile_kind) && item.status !== "candidate");
  const steps = [
    ["上传声音样本", hasAudio],
    ["质量检查与授权记录", hasAudio],
    ["转写确认", hasTranscript],
    ["选择复刻服务", hasVoiceJob || activeVoice],
    ["试听并启用声音档案", clonedVoice || activeVoice],
  ];
  return `<article class="build-panel voice-flow-panel"><header><span>VOICE CLONE CORE</span><b>${steps.filter(item => item[1]).length}/5</b></header>
    <p><strong>真实素材路线的声音复制流程</strong><small>音频不是人格来源，而是音色与表达样本来源。完成试听确认后才建议正式启用声音。</small></p>
    <div class="voice-flow-steps">${steps.map(([label, done]) => `<span class="${done ? "done" : ""}">${done ? "✓ " : "○ "}${escapeHtml(label)}</span>`).join("")}</div>
  </article>`;
}

async function openSettings() {
  closeAuxiliaryDialogs();
  const cloud = await api("/api/settings/cloud-services");
  await loadModelConnections();
  await loadOcrConnections();
  await loadProviderHub();
  setSettingsTab("providerHubPanel");
  if (!$("#settingsDialog").dataset.editConnectionId) fillConnectionEditor();
  $("#dialogAliyunKey").value = "";
  $("#dialogVoiceCloneModel").value = cloud.voice_clone_model;
  $("#dialogVoiceTargetModel").value = cloud.voice_target_model;
  $("#dialogImageModel").value = cloud.image_reference_model;
  $("#dialogNorthKey").value = "";
  $("#dialogNorthApiUrl").value = cloud.north_api_url || "https://api.atlasv1.com";
  $("#dialogNorthFaceUrl").value = cloud.north_face_url || "";
  $("#dialogNorthIdleTimeout").value = cloud.north_idle_timeout || 300;
  $("#dialogNorthPrice").value = cloud.north_price_per_second || 0.00194;
  $("#dialogVideoCallEnabled").checked = cloud.video_call_enabled !== false;
  $("#dialogVideoScene").checked = cloud.scene_background_enabled !== false;
  $("#dialogVideoFlip").checked = cloud.camera_flip_enabled !== false;
  $("#dialogVideoVision").checked = cloud.vision_feedback_enabled !== false;
  $("#dialogVideoInterrupt").checked = cloud.smart_interrupt_enabled !== false;
  $("#dialogMediaConsent").checked = cloud.cloud_data_consent;
  $("#settingsDialog").showModal();
}

const providerCapabilityLabels = { chat: "对话", vision: "视觉理解", asr: "语音转写", tts: "语音合成", voice_clone: "声音复刻", image: "图片生成", video: "视频生成", realtime_video: "实时视频" };
const providerConsentLabels = { text: "文字", audio: "音频", voice_biometric: "声音生物特征", image: "图片", video: "视频/实时轨道" };

async function loadProviderHub() {
  const data = await api("/api/provider-hub");
  state.providerHub = data;
  const editing = data.connections.find(item => item.id === $("#settingsDialog").dataset.editProviderId);
  renderProviderEditor(editing || null);
  renderProviderConnections();
  renderCapabilityRoutes();
  return data;
}

function renderProviderEditor(item = null) {
  const data = state.providerHub || { capabilities: [], presets: {} };
  const kind = item?.provider_kind || $("#providerKind")?.value || "minimax";
  const preset = data.presets?.[kind] || {};
  const capabilities = item?.capabilities || preset.capabilities || [];
  const models = item?.models || preset.models || {};
  $("#providerKind").value = kind;
  $("#providerDisplayName").value = item?.display_name || preset.label || "我的服务连接";
  $("#providerBaseUrl").value = item?.base_url || preset.base_url || "";
  $("#providerRegion").value = item?.region || "";
  $("#providerApiKey").value = "";
  $("#providerDailyBudget").value = Number(item?.budget?.daily || 0);
  $("#providerMonthlyBudget").value = Number(item?.budget?.monthly || 0);
  $("#providerAdvancedConfig").value = Object.keys(item?.config || {}).length ? JSON.stringify(item.config, null, 2) : "";
  $("#providerCapabilityChecks").innerHTML = data.capabilities.map(capability => `<label><input type="checkbox" data-provider-capability="${capability}" ${capabilities.includes(capability) ? "checked" : ""}> ${providerCapabilityLabels[capability] || capability}</label>`).join("");
  $("#providerModelFields").innerHTML = data.capabilities.map(capability => `<label>${providerCapabilityLabels[capability] || capability} 模型<input data-provider-model="${capability}" value="${escapeHtml(models[capability] || "")}" placeholder="未填写则使用服务默认"></label>`).join("");
  $("#providerConsentChecks").innerHTML = Object.entries(providerConsentLabels).map(([key, label]) => `<label><input type="checkbox" data-provider-consent="${key}" ${item?.consent?.[key] ? "checked" : ""}> 允许发送${label}</label>`).join("");
  $("#settingsDialog").dataset.editProviderId = item?.id || "";
}

function providerPayload() {
  const configText = $("#providerAdvancedConfig").value.trim();
  return {
    display_name: $("#providerDisplayName").value,
    provider_kind: $("#providerKind").value,
    base_url: $("#providerBaseUrl").value,
    region: $("#providerRegion").value,
    capabilities: $$('[data-provider-capability]:checked').map(node => node.dataset.providerCapability),
    models: Object.fromEntries($$('[data-provider-model]').map(node => [node.dataset.providerModel, node.value.trim()]).filter(([, value]) => value)),
    consent: Object.fromEntries($$('[data-provider-consent]').map(node => [node.dataset.providerConsent, node.checked])),
    budget: { daily: Number($("#providerDailyBudget").value || 0), monthly: Number($("#providerMonthlyBudget").value || 0) },
    config: configText ? JSON.parse(configText) : {}, api_key: $("#providerApiKey").value, enabled: true,
  };
}

function renderProviderConnections() {
  const connections = state.providerHub?.connections || [];
  $("#providerConnectionList").innerHTML = connections.length ? connections.map(item => `<article class="connection-row"><div><b>${escapeHtml(item.display_name)}</b><small>${escapeHtml(item.provider_kind)} · ${(item.capabilities || []).map(cap => providerCapabilityLabels[cap] || cap).join(" / ")}</small><small>${escapeHtml(item.base_url)} · ${item.has_api_key ? "Key 已安全保存" : "无 Key"}</small><small>${escapeHtml(item.last_test_message || item.last_test_status)}</small></div><span class="mini-actions"><button type="button" data-action="test-provider-connection" data-provider-id="${item.id}">测试</button><button type="button" data-action="edit-provider-connection" data-provider-id="${item.id}">编辑</button><button type="button" data-action="delete-provider-connection" data-provider-id="${item.id}">删除</button></span></article>`).join("") : `<div class="empty-card">还没有统一服务连接。推荐先添加 MiniMax 或阿里云直连。</div>`;
}

function renderCapabilityRoutes() {
  const hub = state.providerHub || { capabilities: [], connections: [], routes: [] };
  const scope = $("#capabilityRouteScope")?.value === "avatar" && state.currentId ? "avatar" : "global";
  const avatarId = scope === "avatar" ? state.currentId : "";
  const avatarOption = $("#capabilityRouteScope option[value='avatar']");
  if (avatarOption) { avatarOption.disabled = !state.currentId; avatarOption.textContent = state.currentId ? "当前数字人" : "当前没有打开数字人"; }
  const optionsFor = capability => hub.connections.filter(item => item.enabled && (item.capabilities || []).includes(capability)).map(item => `<option value="${item.id}">${escapeHtml(item.display_name)}</option>`).join("");
  $("#capabilityRouteList").innerHTML = hub.capabilities.map(capability => {
    const route = hub.routes.find(item => item.scope_type === scope && item.avatar_id === avatarId && item.capability === capability) || {};
    const options = optionsFor(capability);
    return `<article class="route-item"><div><b>${providerCapabilityLabels[capability] || capability}</b><small>主服务失败、未授权或超预算时尝试备用服务</small></div><label>主连接<select data-cap-route-primary="${capability}"><option value="">未配置</option>${options}</select></label><label>备用连接<select data-cap-route-fallback="${capability}"><option value="">无</option>${options}</select></label><label>覆盖模型<input data-cap-route-model="${capability}" value="${escapeHtml(route.model || "")}" placeholder="留空使用连接默认"></label><button type="button" class="secondary" data-action="save-capability-route" data-capability="${capability}">保存</button></article>`;
  }).join("");
  hub.capabilities.forEach(capability => {
    const route = hub.routes.find(item => item.scope_type === scope && item.avatar_id === avatarId && item.capability === capability) || {};
    const primary = $(`[data-cap-route-primary="${capability}"]`);
    const fallback = $(`[data-cap-route-fallback="${capability}"]`);
    if (primary) primary.value = route.primary_connection_id || "";
    if (fallback) fallback.value = route.fallback_connection_ids?.[0] || "";
  });
}

async function loadOcrConnections() {
  const data = await api("/api/ocr-connections");
  state.ocrConnections = data.connections || [];
  state.selectedOcrId = data.selected_ocr_connection_id || "";
  $("#ocrDetectedList").innerHTML = (data.detected || []).map(item => `<article class="connection-row compact">
    <div><b>${escapeHtml(item.display_name)}</b><small>${escapeHtml(item.status)} · ${escapeHtml(item.data_location)}</small><small>${escapeHtml(item.note)}</small></div>
  </article>`).join("");
  $("#ocrConnectionList").innerHTML = state.ocrConnections.length ? state.ocrConnections.map(item => `<article class="connection-row ${item.id === state.selectedOcrId ? "selected" : ""}">
    <div><b>${escapeHtml(item.display_name)}</b><small>${escapeHtml(ocrTypeName(item.connection_type))} · ${item.has_api_key ? "Key 已保存" : "无 Key"}</small><small>${escapeHtml(item.base_url || item.command_template)}</small><small>${escapeHtml(item.last_test_message || item.last_test_status)}</small></div>
    <span class="mini-actions"><button type="button" data-action="select-ocr-connection" data-ocr-id="${escapeHtml(item.id)}">设为 OCR</button><button type="button" data-action="edit-ocr-connection" data-ocr-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-action="delete-ocr-connection" data-ocr-id="${escapeHtml(item.id)}">删除</button></span>
  </article>`).join("") : `<div class="empty-card">没有自定义 OCR。系统会优先尝试本机已有 OCR；不可用时可以手动补文字。</div>`;
  if (!$("#settingsDialog").dataset.editOcrId) fillOcrEditor();
  return data;
}

function ocrTypeName(type) {
  return ({ local_command: "本地命令", local_http: "本地 HTTP", cloud_api: "云端 OCR API" })[type] || type;
}

function fillOcrEditor(item = null) {
  $("#ocrType").value = item?.connection_type || "local_command";
  $("#ocrName").value = item?.display_name || "我的 OCR";
  $("#ocrProvider").value = item?.provider_name || "自定义 OCR";
  $("#ocrBaseUrl").value = item?.base_url || "";
  $("#ocrCommand").value = item?.command_template || "tesseract {image} stdout -l chi_sim+eng";
  $("#ocrApiKey").value = "";
  $("#ocrKeyRequired").checked = Boolean(item?.api_key_required);
  $("#ocrConsent").checked = Boolean(item?.cloud_data_consent);
  $("#settingsDialog").dataset.editOcrId = item?.id || "";
  updateOcrHints();
}

function updateOcrHints() {
  const type = $("#ocrType").value;
  $("#ocrCommand").closest("label").classList.toggle("hidden", type !== "local_command");
  $("#ocrBaseUrl").closest("label").classList.toggle("hidden", type === "local_command");
  $("#ocrApiKey").closest("label").classList.toggle("hidden", type === "local_command");
  $("#ocrKeyRequired").closest(".check-card").classList.toggle("hidden", type === "local_command");
  $("#ocrConsent").closest(".check-card").classList.toggle("hidden", type !== "cloud_api");
  if (type === "local_http" && !$("#ocrBaseUrl").value) $("#ocrBaseUrl").value = "http://127.0.0.1:8866/ocr";
  if (type === "cloud_api" && !$("#ocrBaseUrl").value) $("#ocrBaseUrl").value = "https://api.example.com/ocr";
}

function ocrPayload() {
  return {
    display_name: $("#ocrName").value,
    connection_type: $("#ocrType").value,
    provider_name: $("#ocrProvider").value,
    command_template: $("#ocrCommand").value,
    base_url: $("#ocrBaseUrl").value,
    api_key: $("#ocrApiKey").value,
    api_key_required: $("#ocrKeyRequired").checked,
    cloud_data_consent: $("#ocrConsent").checked,
    enabled: true,
  };
}

async function loadModelConnections() {
  const data = await api("/api/model-connections");
  state.modelConnections = data.connections || [];
  state.selectedConnectionId = data.selected_connection_id || "";
  renderConnectionList();
  fillConnectionSelect($("#wizardConnectionSelect"), state.selectedConnectionId);
  if ($("#avatarConnectionSelect")) fillConnectionSelect($("#avatarConnectionSelect"), $("#avatarConnectionSelect").value || state.selectedConnectionId);
  renderConnectionHint("#wizardConnectionHint", $("#wizardConnectionSelect")?.value || state.selectedConnectionId);
  return data;
}

function connectionTypeName(type) {
  return ({ cloud_openai: "云端 API", local_openai: "本地 OpenAI 兼容", ollama: "Ollama", custom_local_adapter: "自定义本地" })[type] || type;
}

function fillConnectionSelect(select, selectedId = "") {
  if (!select) return;
  select.innerHTML = state.modelConnections.length
    ? state.modelConnections.map(item => `<option value="${escapeHtml(item.id)}" ${item.id === selectedId ? "selected" : ""}>${escapeHtml(item.display_name)} · ${escapeHtml(connectionTypeName(item.connection_type))} · ${escapeHtml(item.model)}</option>`).join("")
    : `<option value="">还没有模型连接</option>`;
}

function renderConnectionHint(selector, connectionId) {
  const node = $(selector);
  if (!node) return;
  const item = state.modelConnections.find(row => row.id === connectionId);
  node.innerHTML = item ? `<b>${escapeHtml(item.display_name)}</b><span>${escapeHtml(item.base_url)} · ${escapeHtml(item.provider_name)} · ${item.has_api_key ? "Key 已保存在系统凭据库" : "本地免 Key 或尚未保存 Key"}</span>` : `<b>还没有模型连接</b><span>请先在全局 AI 设置中新建一个云端或本地连接。</span>`;
}

function renderConnectionList() {
  const list = $("#dialogConnectionList");
  if (!list) return;
  list.innerHTML = state.modelConnections.length ? state.modelConnections.map(item => `<article class="connection-row ${item.id === state.selectedConnectionId ? "selected" : ""}">
    <div><b>${escapeHtml(item.display_name)}</b><small>${escapeHtml(connectionTypeName(item.connection_type))} · ${escapeHtml(item.model)} · ${item.has_api_key ? "Key 已保存" : "无 Key"}</small><small>${escapeHtml(item.base_url)}</small><small>${escapeHtml(item.last_test_message || item.last_test_status)}</small></div>
    <span class="mini-actions"><button type="button" data-action="select-model-connection" data-connection-id="${escapeHtml(item.id)}">设为默认</button><button type="button" data-action="edit-model-connection" data-connection-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-action="delete-model-connection" data-connection-id="${escapeHtml(item.id)}">删除</button></span>
  </article>`).join("") : `<div class="empty-card">还没有连接。可以保存一个 OpenRouter、LM Studio、Ollama 或自定义本地适配器。</div>`;
}

function connectionPayload() {
  return {
    display_name: $("#connectionName").value,
    connection_type: $("#connectionType").value,
    provider_name: $("#connectionProvider").value,
    base_url: $("#connectionBaseUrl").value,
    model: $("#connectionModel").value,
    adapter_kind: $("#connectionAdapterKind").value,
    api_key: $("#connectionApiKey").value,
    cloud_data_consent: $("#connectionConsent").checked,
  };
}

function fillConnectionEditor(item = null) {
  $("#connectionType").value = item?.connection_type || "cloud_openai";
  $("#connectionName").value = item?.display_name || "我的模型连接";
  $("#connectionProvider").value = item?.provider_name || "自定义 API";
  $("#connectionBaseUrl").value = item?.base_url || "https://openrouter.ai/api/v1";
  $("#connectionModel").value = item?.model || "openrouter/auto";
  $("#connectionAdapterKind").value = item?.adapter_kind || "openai_compatible";
  $("#connectionApiKey").value = "";
  $("#connectionConsent").checked = Boolean(item?.cloud_data_consent);
  $("#settingsDialog").dataset.editConnectionId = item?.id || "";
  updateConnectionEditorHints();
}

function updateConnectionEditorHints() {
  const type = $("#connectionType").value;
  const advanced = $("#modelSettingsPanel .advanced-settings");
  if (advanced && type !== "cloud_openai") advanced.open = true;
  $("#adapterKindLabel").classList.toggle("hidden", type !== "custom_local_adapter");
  if (type === "ollama") {
    $("#connectionProvider").value = "Ollama";
    if (!$("#connectionBaseUrl").value || $("#connectionBaseUrl").value.startsWith("https://")) $("#connectionBaseUrl").value = "http://127.0.0.1:11434";
    if (!$("#connectionModel").value || $("#connectionModel").value === "openrouter/auto") $("#connectionModel").value = "qwen3:8b";
  }
  if (type === "local_openai" && $("#connectionBaseUrl").value.startsWith("https://")) $("#connectionBaseUrl").value = "http://127.0.0.1:1234/v1";
  if (type === "custom_local_adapter" && $("#connectionBaseUrl").value.startsWith("https://")) $("#connectionBaseUrl").value = "http://127.0.0.1:8000/v1";
  $("#connectionConsent").closest(".check-card").classList.toggle("hidden", type !== "cloud_openai");
}

async function saveModelConnection(resultNode) {
  const id = $("#settingsDialog").dataset.editConnectionId || "";
  const result = await api(id ? `/api/model-connections/${encodeURIComponent(id)}` : "/api/model-connections", {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(connectionPayload()),
  });
  $("#connectionApiKey").value = "";
  $("#settingsDialog").dataset.editConnectionId = result.id;
  resultNode.textContent = `连接已保存：${result.display_name}`;
  await loadHealth();
  await loadModelConnections();
  return result;
}

async function saveCurrentAvatarModelSettings(payload, resultNode) {
  if (!state.currentId) throw new Error("请先创建数字人");
  const result = await api(`/api/avatars/${state.currentId}/settings/model`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  resultNode.textContent = result.effective.inherited ? "已继承全局模型设置。" : `已保存这个数字人的模型设置：${result.effective.provider_name} · ${result.effective.model}`;
  await loadHealth();
  return result;
}
