async function loadGuidedBuilder() {
  if (!state.currentId || state.creationMode !== "fictional") return;
  state.guided = await api(`/api/avatars/${state.currentId}/guided-builder`);
  const active = state.guided.questions.filter(item => item.enabled);
  const firstOpen = active.findIndex(item => !item.answered);
  state.guidedIndex = firstOpen >= 0 ? firstOpen : 0;
  renderGuidedBuilder();
}

function renderGuidedBuilder() {
  const panel = $("#guidedBuilderPanel");
  if (!state.guided || state.creationMode !== "fictional") { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  const questions = state.guided.questions || [];
  renderWorldModules(state.guided.modules || []);
  const activeQuestions = questions.filter(row => row.enabled);
  const item = activeQuestions[state.guidedIndex] || state.guided.next_question || activeQuestions[0];
  $("#guidedProgress").textContent = `${state.guided.progress}%`;
  if (!item) {
    $("#guidedTitle").textContent = "设定问答已完成";
    $("#guidedPrompt").textContent = "可以继续导入文档、视觉候选或声音素材，也可以进入下一步选择模型。";
    $("#guidedAnswer").value = "";
    $("#guidedAnswer").disabled = true;
    return;
  }
  $("#guidedTitle").textContent = `${item.module} · ${item.title}`;
  $("#guidedPrompt").textContent = item.prompt;
  $("#guidedAnswer").disabled = false;
  $("#guidedAnswer").value = item.answer || "";
}

function renderWorldModules(modules) {
  const grouped = modules.reduce((acc, item) => {
    (acc[item.category] ||= []).push(item);
    return acc;
  }, {});
  $("#worldModuleSelector").innerHTML = Object.entries(grouped).map(([category, items]) => `<section class="module-group">
    <b>${escapeHtml(category)}</b>
    <div>${items.map(item => `<label class="module-chip ${item.required ? "required" : ""} ${item.answered ? "answered" : ""}">
      <input type="checkbox" data-module-key="${escapeHtml(item.key)}" ${item.enabled ? "checked" : ""} ${item.required ? "disabled" : ""}>
      <span>${escapeHtml(item.name)}<small>${item.required ? "必须" : item.answered ? "已回答" : "可选"}</small></span>
    </label>`).join("")}</div>
  </section>`).join("");
}

function renderReadinessBanner() {
  const report = state.current?.readiness;
  if (!report) return;
  const node = $("#readinessBanner");
  const route = report.route === "fictional" ? ui("虚构设定路线", "Fictional path") : ui("真实素材路线", "Real-material path");
  if (report.can_start_official) {
    state.previewMode = false;
    node.innerHTML = `<b>${route} · ${ui("正式可用", "Ready for official use")}</b><span>${ui("必须项已完成。推荐项和高级项可以继续补强。", "Required items are complete. Recommended and advanced items can still improve quality.")}</span>`;
    node.className = "readiness-banner official";
  } else {
    node.innerHTML = `<b>${route} · ${ui("预览测试模式", "Preview test mode")}</b><span>${ui("必须项", "Required")} ${escapeHtml(report.summary.required)}${ui("，未完成前不能正式使用。", ". Official use remains locked until these items are complete.")}</span><button class="secondary" data-action="enable-preview">${ui("开启预览试聊", "Start preview chat")}</button>`;
    node.className = `readiness-banner ${state.previewMode ? "preview-on" : ""}`;
  }
}

function renderProfile() {
  const persona = state.current?.persona || {};
  const lang = state.current?.language_profile || {};
  const region = lang.world_region_rules || {};
  $("#profileSummary").innerHTML = `<h3>${escapeHtml(state.current.name)}</h3><p>${escapeHtml(persona.summary || "尚未生成人格摘要")}</p>
    <div class="profile-meta"><span class="tag">${escapeHtml(state.interfaceLanguage === "en-US" ? (lang.language_label?.name_en || lang.avatar_primary_language || "Chinese") : (lang.language_label?.name_zh || lang.avatar_primary_language || "中文"))}</span><span class="tag">${escapeHtml(state.interfaceLanguage === "en-US" ? (region.name_en || lang.world_region || "Mainland China") : (region.name_zh || lang.world_region || "中国大陆"))}</span><span class="tag">${escapeHtml(lang.world_type || "realistic")}</span></div>
    <div>${(persona.traits || []).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>
    <h4>说话方式</h4><p>${escapeHtml(persona.speaking_style || "尚未分析")}</p><h4>人物边界</h4><p>${escapeHtml(persona.boundaries || "尚未设置")}</p>
    <small>资料来源：${persona.source_count || 0} 条 · 证据：${state.current.evidence_count || 0} 条 · 原始文件：${state.current.imports?.length || 0} 个</small>`;
}

function renderNextAction(checks, proposals, transcripts, jobs) {
  const required = (checks.checks || []).find(item => (item.level || item.severity) === "required" && !item.passed);
  const pendingTranscript = transcripts.find(item => item.status === "needs_review");
  const pendingProposal = proposals.find(item => item.status === "pending");
  const waitingJob = jobs.find(job => job.status === "waiting_configuration");
  const recommended = (checks.checks || []).find(item => (item.level || item.severity) === "recommended" && !item.passed);
  let title = "可以开始使用";
  let body = "必须项已经完成。接下来可以继续补强声音、视觉、长期记忆和里世界。";
  let action = "";
  if (required) {
    title = `先完成：${required.name}`;
    body = required.recommendation || "完成这个必须项后，数字人才能进入正式使用。";
  } else if (pendingTranscript) {
    title = "确认声音转写";
    body = "音频只有确认转写后，才能变成表达样本和长期记忆线索。";
    action = "到 VOICE TRANSCRIPTS 面板填写并确认。";
  } else if (pendingProposal) {
    title = "审批世界事实";
    body = "里世界的高影响变化需要你批准，避免运行时自动改 canon。";
    action = "到 WORLD PROPOSALS 面板批准或拒绝。";
  } else if (waitingJob) {
    title = `配置${waitingJob.job_type === "voice" ? "声音" : "视觉"}构建服务`;
    body = waitingJob.stage || "有构建任务正在等待服务商配置。";
  } else if (recommended) {
    title = `建议补强：${recommended.name}`;
    body = recommended.recommendation || "补强推荐项可以提高稳定性。";
  }
  $("#nextActionCard").innerHTML = `<div><span>NEXT STEP</span><b>${escapeHtml(title)}</b><p>${escapeHtml(body)}</p>${action ? `<small>${escapeHtml(action)}</small>` : ""}</div>`;
}

function materialQualityPanel(checks, voices, visual, transcripts) {
  const route = checks.route || "real";
  const required = (checks.checks || []).filter(item => (item.level || item.severity) === "required");
  const requiredPassed = required.filter(item => item.passed).length;
  const transcriptReady = transcripts.filter(item => item.status === "confirmed").length;
  const visualReady = visual.filter(item => ["approved", "canonical"].includes(item.status)).length;
  const voiceReady = voices.filter(item => item.active).length;
  const score = Math.round(((required.length ? requiredPassed / required.length : 1) * 55) + Math.min(transcriptReady, 2) * 10 + Math.min(visualReady, 2) * 10 + Math.min(voiceReady, 1) * 15);
  const guidance = route === "fictional"
    ? "虚构路线重点看身份、人格、说话方式、边界和里世界模块是否足够。"
    : "真实路线重点看文本人格素材、声音样本、声音转写和视觉身份是否足够。";
  return `<article class="build-panel"><header><span>MATERIAL QUALITY</span><b>${Math.min(score, 100)}</b></header>
    <p><strong>素材质量评分</strong><small>${guidance}</small></p>
    <p class="${requiredPassed === required.length ? "passed" : "pending"}"><strong>必须项 ${requiredPassed}/${required.length}</strong><small>必须项完成后才能正式使用。</small></p>
    <p><strong>声音确认 ${transcriptReady}</strong><small>音频转写确认越多，表达样本越稳。</small></p>
    <p><strong>视觉审批 ${visualReady}</strong><small>approved/canonical 图片会让视觉身份更清楚。</small></p>
  </article>`;
}

function releaseCheckPanel(checks, proposals, transcripts) {
  const blocked = (checks.checks || []).filter(item => (item.level || item.severity) === "required" && !item.passed);
  const pendingProposals = proposals.filter(item => item.status === "pending").length;
  const pendingTranscripts = transcripts.filter(item => item.status === "needs_review").length;
  const ready = blocked.length === 0;
  return `<article class="build-panel"><header><span>PRE-LAUNCH CHECK</span><b>${ready ? "OK" : blocked.length}</b></header>
    <p class="${ready ? "passed" : "pending"}"><strong>${ready ? "可以正式使用" : "暂不建议正式使用"}</strong><small>${ready ? "必须项已完成，剩余是推荐和高级补强。" : blocked.map(item => item.name).join("、")}</small></p>
    <p class="${pendingProposals ? "pending" : "passed"}"><strong>世界审批 ${pendingProposals}</strong><small>高影响事实不应绕过用户审批。</small></p>
    <p class="${pendingTranscripts ? "pending" : "passed"}"><strong>声音转写 ${pendingTranscripts}</strong><small>确认后才能进入证据和记忆。</small></p>
  </article>`;
}

function settingMapPanel(world) {
  const facts = world.facts || [];
  const count = key => facts.filter(item => String(item.fact_key || "").includes(key)).length;
  return `<article class="build-panel"><header><span>SETTING MAP</span><b>${facts.length}</b></header>
    <p><strong>身份与人格</strong><small>${count("identity") + count("persona")} 条事实</small></p>
    <p><strong>地点与组织</strong><small>${count("place") + count("city") + count("organization")} 条事实</small></p>
    <p><strong>规则与边界</strong><small>${count("rule") + count("governance") + count("boundary")} 条事实</small></p>
    <p><strong>运行状态</strong><small>${count("resource") + count("runtime") + count("mood")} 条事实</small></p>
  </article>`;
}

function worldRegionPanel(world) {
  const profile = world.language_profile || state.current?.language_profile || {};
  const rules = profile.world_region_rules || {};
  const social = rules.social_rules || [];
  const holidays = rules.holidays || [];
  return `<article class="build-panel"><header><span>WORLD REGION</span><b>${escapeHtml(rules.name_zh || profile.world_region || "-")}</b></header>
    <p><strong>数字人语言</strong><small>${escapeHtml(profile.language_label?.name_zh || profile.avatar_primary_language || "未设置")} · ${escapeHtml(profile.response_mode_label?.name_zh || "")}</small></p>
    <p><strong>世界类型</strong><small>${escapeHtml(profile.world_type || "realistic")}</small></p>
    <p><strong>社会规则</strong><small>${social.map(item => escapeHtml(item)).join("、") || "未设置"}</small></p>
    <p><strong>节日/特殊日期</strong><small>${holidays.map(item => escapeHtml(item)).join("、") || "按自定义规则运行"}</small></p>
  </article>`;
}

async function loadEvidence() {
  if (!state.currentId) return;
  const rows = await api(`/api/avatars/${state.currentId}/evidence`);
  const list = $("#evidenceList");
  if (!rows.length) {
    list.innerHTML = `<div class="empty-card">还没有证据。确认聊天记录、截图 OCR，或上传声音/图片素材后会显示在这里。</div>`;
    return;
  }
  list.innerHTML = rows.map(row => `<article class="evidence-item">
    <div class="evidence-top"><b>${escapeHtml(row.title || row.derived_kind || "证据")}</b><span>${escapeHtml(row.source_type)}</span></div>
    <p>${escapeHtml(String(row.content || "").slice(0, 420))}${String(row.content || "").length > 420 ? "..." : ""}</p>
    <div>${(row.tags || []).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
  </article>`).join("");
}

async function loadMessages() {
  const rows = await api(`/api/avatars/${state.currentId}/messages?timeline_kind=${state.previewMode ? "preview" : "official"}`);
  const list = $("#messageList");
  if (!rows.length) list.innerHTML = `<div class="empty-chat"><h3>从一句自然的问候开始</h3><p>回复由你在 AI 设置中选择的模型生成。</p></div>`;
  else list.innerHTML = rows.map(row => `<div class="message ${row.role} ${row.channel === "proactive" ? "proactive" : ""}"><span>${escapeHtml(row.content)}</span>${row.role === "assistant" ? `<button class="message-audio" data-action="speak-message" title="使用复刻声音播放">♫</button>` : ""}</div>`).join("");
  state.lastProactiveMessageId = Math.max(state.lastProactiveMessageId, ...rows.filter(row => row.channel === "proactive").map(row => Number(row.id)), 0);
  list.scrollTop = list.scrollHeight;
}

function timelineRecordCard(item, editable = false) {
  const label = item.layer === "historical" ? ui("永久历史", "Permanent history") : item.channel === "preview" ? ui("预览测试", "Preview test") : ui("系统新聊天", "New chat");
  const correction = item.corrected ? `<em>${ui("已校正显示", "Corrected display")}</em>` : "";
  const actions = item.layer === "historical"
    ? `<div class="timeline-actions"><button class="secondary" data-action="correct-history" data-memory-id="${item.id}">${ui("校正显示", "Correct display")}</button></div>`
    : editable ? `<div class="timeline-actions"><button class="secondary" data-action="timeline-edit" data-message-id="${item.id}">${ui("修改", "Edit")}</button><button class="danger" data-action="timeline-delete" data-message-id="${item.id}">${ui("删除", "Delete")}</button></div>` : "";
  return `<article class="timeline-record ${item.layer}"><header><b>${escapeHtml(item.speaker)}</b><span>${escapeHtml(label)}</span>${correction}</header><p>${escapeHtml(item.content || (item.media_url ? "[媒体消息]" : ""))}</p>${actions}</article>`;
}

function renderTimelineRecords(target, items, editable = false) {
  if (!items.length) {
    target.innerHTML = `<div class="empty-card">${ui("没有找到记录", "No records found")}</div>`;
    return;
  }
  const groups = new Map();
  items.forEach(item => { if (!groups.has(item.day)) groups.set(item.day, []); groups.get(item.day).push(item); });
  target.innerHTML = [...groups].map(([day, rows]) => `<section class="timeline-day"><h4>${escapeHtml(day)}</h4>${rows.map(item => timelineRecordCard(item, editable)).join("")}</section>`).join("");
}

async function loadHistoryRecords() {
  if (!state.currentId) return;
  const params = new URLSearchParams({
    q: $("#historySearch").value.trim(), day: $("#historyDay").value.trim(),
    layer: $("#historyLayer").value, timeline_kind: state.historyKind, limit: "500",
  });
  const result = await api(`/api/avatars/${state.currentId}/history?${params}`);
  $("#historySummary").textContent = ui(`共 ${result.total} 条；浏览不会改变人物记忆`, `${result.total} records; browsing does not change memory`);
  renderTimelineRecords($("#historyRecords"), result.items, false);
}

async function loadLifeArchive() {
  if (!state.currentId) return;
  const kind = state.timelineKind;
  const [overview, records, candidates] = await Promise.all([
    api(`/api/avatars/${state.currentId}/timeline?timeline_kind=${kind}`),
    api(`/api/avatars/${state.currentId}/history?layer=runtime&timeline_kind=${kind}&limit=500`),
    api(`/api/avatars/${state.currentId}/timeline/media-candidates`),
  ]);
  $("#timelineHistoricalCount").textContent = overview.historical_count;
  $("#timelineRuntimeCount").textContent = overview.runtime_count;
  $("#timelineCandidateCount").textContent = overview.candidate_count;
  $("#timelineRuleNote").textContent = kind === "preview"
    ? ui("这是独立的测试时间线，不影响正式关系和正式人生档案。", "This is an isolated test timeline and does not affect the official relationship or life archive.")
    : ui("删除全部新聊天后，人物仍保留导入历史形成的基础关系，不会变成陌生人。", "If all new chats are removed, imported history still preserves the baseline relationship.");
  renderTimelineRecords($("#activeTimelineRecords"), records.items, true);
  const frozen = overview.branches.filter(item => item.status === "frozen");
  $("#timelineBranches").innerHTML = frozen.length ? frozen.map(item => `<article class="timeline-branch"><div><b>${escapeHtml(item.label || ui("封存版本", "Archived version"))}</b><small>${escapeHtml(item.mutation_action || "")} · ${ui("影响", "Affected")} ${item.impact?.affected_messages || 0} ${ui("条聊天", "messages")}</small></div><div class="timeline-actions"><button class="secondary" data-action="timeline-restore" data-branch-id="${item.id}">${ui("恢复并互换", "Restore and swap")}</button><button class="danger" data-action="timeline-purge" data-branch-id="${item.id}">${ui("永久删除", "Delete permanently")}</button></div></article>`).join("") : `<div class="empty-card">${ui("还没有封存版本", "No archived versions")}</div>`;
  $("#timelineCandidates").innerHTML = candidates.length ? candidates.map(item => `<article class="timeline-branch"><div><b>${escapeHtml(item.media_type || ui("媒体", "Media"))}</b><small>${item.reuse_policy === "automatic" ? ui("数字人生成 · 可自动复用", "Avatar-generated · automatic reuse") : ui("再次使用前需要确认", "Confirmation required before reuse")} · ${escapeHtml(item.status)}</small></div>${item.reuse_policy === "permission_required" && item.status === "available" ? `<button class="secondary" data-action="timeline-approve-media" data-candidate-id="${item.id}">${ui("确认可复用", "Approve reuse")}</button>` : ""}</article>`).join("") : `<div class="empty-card">${ui("暂无候选媒体", "No media candidates")}</div>`;
}

async function prepareTimelineChange(action, messageId) {
  const current = await api(`/api/avatars/${state.currentId}/history?layer=runtime&timeline_kind=${state.timelineKind}&limit=500`);
  const record = current.items.find(item => Number(item.id) === Number(messageId));
  if (!record) throw new Error(ui("当前时间线中找不到这条聊天", "Message not found in the current timeline"));
  let replacement = "";
  if (action === "edit") {
    replacement = prompt(ui("修改这条聊天。修改后，它之后的内容会进入封存区。", "Edit this message. Everything after it will be archived."), record.content);
    if (replacement === null) return;
    replacement = replacement.trim();
    if (!replacement) throw new Error(ui("修改后的内容不能为空", "Replacement text cannot be empty"));
  }
  const preview = await api(`/api/avatars/${state.currentId}/timeline/preview-change`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeline_kind: state.timelineKind, action, message_id: Number(messageId), replacement_text: replacement }),
  });
  const impact = preview.impact;
  const message = ui(
    `将有 ${impact.affected_messages} 条新聊天和相关共同变化进入封存区。永久历史改动 0 条，独立世界状态改动 0 项。继续吗？`,
    `${impact.affected_messages} new messages and related shared changes will be archived. Permanent history changes: 0. Independent world changes: 0. Continue?`,
  );
  if (!confirm(message)) return;
  await api(`/api/avatars/${state.currentId}/timeline/apply-change`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preview_token: preview.preview_token }) });
  await Promise.all([loadLifeArchive(), loadMessages()]);
  toast(ui("当前时间线已更新，原版本已封存", "Timeline updated; the previous version was archived"));
}

async function pollProactiveMessages() {
  if (!state.currentId || document.hidden) return;
  const rows = await api(`/api/avatars/${state.currentId}/messages?limit=20&timeline_kind=official`);
  const fresh = rows.filter(row => row.channel === "proactive" && Number(row.id) > state.lastProactiveMessageId);
  if (!fresh.length) return;
  state.lastProactiveMessageId = Math.max(...fresh.map(row => Number(row.id)));
  await loadMessages();
  const latest = fresh[fresh.length - 1];
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(state.current?.name || "OpenAvatar Studio", { body: latest.content });
  }
}


