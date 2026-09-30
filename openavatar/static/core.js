const state = { avatars: [], currentId: null, current: null, step: 1, currentImport: null, creationMode: "real", fictionalFlow: "guided", guided: null, guidedIndex: 0, previewMode: false, historyKind: "official", timelineKind: "official", modelConnections: [], selectedConnectionId: "", ocrConnections: [], selectedOcrId: "", pendingPackageFile: null, pendingVisualClassification: null, interfaceLanguage: "zh-CN", messages: {}, worldOptions: null, videoCall: null, videoCallStatus: null, livekit: null, livekitRoom: null, livekitAudioContext: null, livekitAudioDest: null, livekitAudioPromise: null, livekitSilenceSource: null, userMedia: null, speechRecognition: null, currentSpeechSource: null, callCameraEnabled: false, callMicrophoneEnabled: false, lastProactiveMessageId: 0, lastNotificationId: Number(localStorage.getItem("openavatar.lastNotificationId") || 0), activeChat: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const originalText = new WeakMap();
const originalPlaceholder = new WeakMap();
const isFilePreview = window.location.protocol === "file:";

async function api(path, options = {}) {
  if (isFilePreview) {
    throw new Error("请通过 start.command、start.sh、start.bat 或桌面应用打开。直接打开 index.html 只能看到静态页面，不能使用预设和后端能力。");
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.className = "toast", 3600);
  if (error) {
    const tray = $("#errorTray");
    $("#errorTrayMessage").textContent = message;
    tray.classList.remove("hidden");
    let history = [];
    try { history = JSON.parse(sessionStorage.getItem("openavatar.errors") || "[]"); } catch (_) { history = []; }
    if (!Array.isArray(history)) history = [];
    history.push({ message, created_at: Date.now() });
    try { sessionStorage.setItem("openavatar.errors", JSON.stringify(history.slice(-20))); } catch (_) {}
  }
}

async function pollNotifications() {
  const items = await api(`/api/notifications?after_id=${state.lastNotificationId}`);
  for (const item of items) {
    state.lastNotificationId = Math.max(state.lastNotificationId, Number(item.id) || 0);
    toast(`${item.title}${item.body ? `：${item.body}` : ""}`);
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(item.title, { body: item.body || "OpenAvatar 后台任务有新进展" });
    }
    await api(`/api/notifications/${item.id}/read`, { method: "POST" });
  }
  localStorage.setItem("openavatar.lastNotificationId", String(state.lastNotificationId));
}

function t(key, fallback = "") {
  return state.messages[key] || fallback || key;
}

function ui(chinese, english) {
  return state.interfaceLanguage === "en-US" ? english : chinese;
}

function applyI18n() {
  document.documentElement.lang = state.interfaceLanguage;
  $$("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n, node.textContent); });
  $$("[data-i18n-html]").forEach(node => { node.innerHTML = t(node.dataset.i18nHtml, node.innerHTML); });
  const literals = state.messages.literals || {};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  textNodes.forEach(node => {
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    const source = originalText.get(node);
    const clean = source.trim();
    node.nodeValue = clean && literals[clean] ? source.replace(clean, literals[clean]) : source;
  });
  $$("[placeholder]").forEach(node => {
    if (!originalPlaceholder.has(node)) originalPlaceholder.set(node, node.getAttribute("placeholder"));
    const source = originalPlaceholder.get(node);
    node.setAttribute("placeholder", literals[source] || source);
  });
  $$(".language-switch button").forEach(node => node.classList.toggle("active", node.dataset.language === state.interfaceLanguage));
  const count = $("#avatarCount");
  if (count) count.textContent = `${state.avatars.length} ${t("home.countUnit", "个项目")}`;
  $$(".dialog-close").forEach(node => { if (!node.getAttribute("aria-label")) node.setAttribute("aria-label", state.interfaceLanguage === "en-US" ? "Close" : "关闭"); });
}

function translateAddedTree(root) {
  if (state.interfaceLanguage !== "en-US" || !root) return;
  const literals = state.messages.literals || {};
  const nodes = root.nodeType === Node.TEXT_NODE ? [root] : [];
  if (root.nodeType === Node.ELEMENT_NODE) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) nodes.push(walker.currentNode);
  }
  nodes.forEach(node => {
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    const source = originalText.get(node);
    const clean = source.trim();
    if (clean && literals[clean]) node.nodeValue = source.replace(clean, literals[clean]);
  });
}

const i18nObserver = new MutationObserver(mutations => {
  mutations.forEach(mutation => mutation.addedNodes.forEach(translateAddedTree));
});
i18nObserver.observe(document.documentElement, { childList: true, subtree: true });

async function loadI18n(language = "") {
  if (isFilePreview) return;
  const preferred = language || localStorage.getItem("openavatar.interfaceLanguage") || "zh-CN";
  const payload = await api(`/api/i18n/${encodeURIComponent(preferred)}`);
  state.interfaceLanguage = payload.selected || payload.language || preferred;
  const selectedPayload = state.interfaceLanguage === payload.language ? payload : await api(`/api/i18n/${encodeURIComponent(state.interfaceLanguage)}`);
  state.messages = selectedPayload.messages || {};
  localStorage.setItem("openavatar.interfaceLanguage", state.interfaceLanguage);
  applyI18n();
}

async function setInterfaceLanguage(language) {
  const result = await api("/api/settings/interface-language", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language }) });
  await loadI18n(result.language);
  await loadHealth();
  await loadAvatars();
  if (state.current) {
    renderReadinessBanner();
    renderProfile();
    if (state.guided) renderGuidedBuilder();
  }
  toast(language === "en-US" ? "Interface language saved" : "界面语言已保存");
}

function labelFor(item) {
  if (!item) return "";
  return state.interfaceLanguage === "en-US" ? (item.name_en || item.label || item.name_zh || item.key) : (item.name_zh || item.label || item.name_en || item.key);
}

function fillSelect(selector, items, valueKey = "key") {
  const node = $(selector);
  if (!node || !items) return;
  node.innerHTML = items.map(item => `<option value="${escapeHtml(item[valueKey])}">${escapeHtml(labelFor(item))}</option>`).join("");
}

async function loadWorldOptions() {
  if (isFilePreview) return;
  state.worldOptions = await api("/api/world-options");
  fillSelect("#avatarLanguageSelect", state.worldOptions.avatar_languages);
  fillSelect("#avatarResponseModeSelect", state.worldOptions.response_modes);
  fillSelect("#worldRegionSelect", state.worldOptions.world_regions);
  fillSelect("#worldTypeSelect", state.worldOptions.world_types);
}

function showFilePreviewNotice() {
  if (!isFilePreview) return;
  const node = document.createElement("div");
  node.className = "file-preview-notice";
  node.innerHTML = "<b>当前只是静态预览</b><span>请用 start.command、start.sh、start.bat 或桌面应用打开 OpenAvatar Studio，预设、导入和模型连接才会正常工作。</span>";
  document.body.prepend(node);
  const status = $("#modelStatus");
  if (status) {
    status.textContent = "请通过启动器打开";
    status.className = "status-pill offline";
  }
}

function showView(id) {
  $$(".view").forEach(node => node.classList.add("hidden"));
  $(id).classList.remove("hidden");
}

function closeAuxiliaryDialogs() {
  ["#onboardingDialog", "#diagnosticsDialog", "#privacyDialog", "#packageDialog", "#packageExportDialog", "#capabilitiesDialog"].forEach(selector => {
    const dialog = $(selector);
    if (dialog?.open) dialog.close();
  });
}

function closeMobileMenu() {
  $(".top-actions")?.classList.remove("open");
}

function setSettingsTab(tabId) {
  $$(".settings-tabs button").forEach(node => node.classList.toggle("active", node.dataset.settingsTab === tabId));
  $$(".settings-section").forEach(node => node.classList.toggle("active", node.id === tabId));
}

function goStep(step) {
  state.step = step;
  $$(".step-panel").forEach(node => node.classList.add("hidden"));
  $(`#step${step}`).classList.remove("hidden");
  $$(".step").forEach(node => node.classList.toggle("active", Number(node.dataset.step) === step));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setCreationMode(mode) {
  state.creationMode = mode === "fictional" ? "fictional" : "real";
  const fictional = state.creationMode === "fictional";
  $("#identityForm [name=creation_mode]").value = state.creationMode;
  $("#identityForm [name=subject_kind]").value = fictional ? "fictional" : "self";
  $("#step1Title").innerHTML = fictional ? "虚构身份<small>原创角色档案</small>" : "真实身份<small>文本、声音、视觉</small>";
  $("#wizardTitle").textContent = fictional ? "创建一个原创数字人" : "从真实素材创建数字人";
  $("#wizardLead").textContent = fictional
    ? "普通用户默认通过问答生成设定；高级用户可以导入文档。里世界可以很大，也可以只先填写必须模块。"
    : "真实路线必须有文字或聊天记录来构建人格，再用音频构建声音；音频不能单独生成人物简介。";
  $("#identityForm [name=purpose]").placeholder = fictional
    ? "例如：创建一个原创虚构角色，用设定文件定义人格、世界观和说话方式"
    : "例如：记录自己的表达方式，创建一个可长期陪伴的数字分身";
  $("#step2Hint").textContent = fictional ? "问答、文档、视觉、声音" : "聊天、截图、声音、照片";
  $("#importLead").textContent = fictional
    ? "默认用问答一步步生成原创设定；高级用户也可以导入 Markdown、JSON、YAML 角色卡。"
    : "不必一次准备齐全。原始文件保存在本机；只有选择云端API并确认后，完成分析所需的内容才会发送给用户指定的服务商。";
  $("#realUploadGrid").classList.toggle("hidden", fictional);
  $("#fictionalUploadGrid").classList.toggle("hidden", !fictional);
  $("#fictionalPathSwitch").classList.toggle("hidden", !fictional);
  setFictionalFlow(state.fictionalFlow);
}

function setFictionalFlow(flow) {
  state.fictionalFlow = flow === "template" ? "template" : "guided";
  const fictional = state.creationMode === "fictional";
  $("#guidedBuilderPanel").classList.toggle("hidden", !fictional || state.fictionalFlow !== "guided");
  $("#templateDownloadCard").classList.toggle("hidden", !fictional || state.fictionalFlow !== "template");
  $$(".template-only").forEach(node => node.classList.toggle("hidden", !fictional || state.fictionalFlow !== "template"));
  $$("#fictionalPathSwitch button").forEach(node => node.classList.toggle("active", node.dataset.flow === state.fictionalFlow));
}

async function loadHealth() {
  try {
    const health = await api("/api/health");
    const node = $("#modelStatus");
    const modeName = health.runtime_mode === "cloud" ? ui("云端 API", "Cloud API") : ui("本地模型", "Local model");
    node.textContent = health.provider_available
      ? `${modeName}${ui("已配置", " ready")} · ${health.model}`
      : `${modeName}${ui("尚未就绪", " not ready")}`;
    node.className = `status-pill ${health.provider_available ? "online" : "offline"}`;
  } catch (error) { toast(error.message, true); }
}

async function loadOnboarding() {
  const onboarding = await api("/api/onboarding");
  if (!onboarding.completed) $("#onboardingDialog").showModal();
}

async function openDiagnostics() {
  $("#diagnosticsSummary").innerHTML = `<span class="diagnostic-loading">正在检查本地系统…</span>`;
  $("#diagnosticsList").innerHTML = "";
  if (!$("#diagnosticsDialog").open) $("#diagnosticsDialog").showModal();
  const report = await api("/api/diagnostics");
  const statusText = report.status === "pass" ? "状态良好" : report.status === "warn" ? "需要注意" : "需要处理";
  $("#diagnosticsSummary").innerHTML = `<article class="${escapeHtml(report.status)}"><b>${escapeHtml(statusText)}</b><span>${report.summary.pass} 项通过 · ${report.summary.warn} 项提醒 · ${report.summary.fail} 项失败</span><small>数据目录：${escapeHtml(report.environment.data_dir)}</small></article>`;
  $("#diagnosticsList").innerHTML = report.checks.map(item => `<article class="diagnostic-item ${escapeHtml(item.status)}">
    <b>${escapeHtml(item.name)}</b><span>${escapeHtml(item.detail)}</span>${item.action ? `<small>${escapeHtml(item.action)}</small>` : ""}
  </article>`).join("");
}

async function openCapabilities() {
  $("#capabilityList").innerHTML = `<span class="diagnostic-loading">正在读取能力状态…</span>`;
  if (!$("#capabilitiesDialog").open) $("#capabilitiesDialog").showModal();
  const report = await api("/api/capabilities");
  $("#capabilityList").innerHTML = report.items.map(item => `<article class="capability-item ${escapeHtml(item.running_at)}">
    <div><b>${escapeHtml(item.name)}</b><span>${escapeHtml(item.status)} · ${escapeHtml(item.running_at)}</span></div>
    <p><strong>${escapeHtml(item.provider)}</strong>${escapeHtml(item.sends)}</p>
    <small>${escapeHtml(item.cost)}${item.consent ? " · 已确认边界" : " · 需要用户留意边界"}</small>
  </article>`).join("");
}

function renderPackagePreview(info) {
  const typeName = { self: "我自己", authorized_person: "授权真人", fictional: "虚构人物" }[info.subject_kind] || info.subject_kind;
  const hint = info.model_connection_hint || {};
  const language = info.language_profile || {};
  const region = language.world_region_rules || {};
  $("#packagePreview").innerHTML = `<article>
    <b>${escapeHtml(info.name || "未命名人物包")}</b>
    <span>${escapeHtml(typeName)} · v${escapeHtml(info.version)} · ${info.file_count} 个文件 · ${info.asset_count} 个素材文件</span>
    <p>${escapeHtml(info.persona_summary || "人物包没有摘要，导入后可重新运行 Builder。")}</p>
  </article>
  <article><b>语言与世界</b><span>${escapeHtml(language.avatar_primary_language || info.avatar_primary_language || "未声明")} · ${escapeHtml(region.name_zh || info.world_region || "未声明")}</span><small>人物包会迁移数字人语言和世界地区；不会迁移使用者自己的界面语言。</small></article>
  <article><b>模型连接</b><span>${hint.provider_name ? `${escapeHtml(hint.provider_name)} · ${escapeHtml(hint.model || "")}` : "没有模型连接提示"}</span><small>不会导入 API Key，导入后需要重新绑定自己的连接。</small></article>
  <article class="${info.contains_api_keys ? "fail" : "pass"}"><b>密钥检查</b><span>${info.contains_api_keys ? "清单声明可能包含密钥，系统不会导入密钥。" : "清单声明不包含 API Key。"}</span></article>
  ${info.warnings?.length ? `<article class="warn"><b>提醒</b>${info.warnings.map(item => `<span>${escapeHtml(item)}</span>`).join("")}</article>` : ""}
  <article><b>包含内容</b><span>${(info.included_sections || []).map(item => escapeHtml(item)).join(" · ")}</span></article>`;
}

async function loadAvatars() {
  state.avatars = await api("/api/avatars");
  $("#avatarCount").textContent = `${state.avatars.length} ${t("home.countUnit", "个项目")}`;
  const grid = $("#avatarGrid");
  if (!state.avatars.length) {
    grid.innerHTML = `<div class="empty-card empty-home">
      <span data-i18n="home.emptyKicker">FIRST RUN</span><b data-i18n="home.emptyTitle">还没有数字人</b><p data-i18n="home.emptyText">选择真实素材或虚构设定路线，创建你的第一个数字人。</p>
      <div><button class="secondary" data-action="new-real-avatar" data-i18n="home.emptyReal">真实素材路线</button><button class="secondary" data-action="new-fictional-avatar" data-i18n="home.emptyFictional">虚构设定路线</button></div>
    </div>`;
    applyI18n();
    return;
  }
  grid.innerHTML = state.avatars.map(item => `<article class="avatar-card" data-avatar="${item.id}">
    <div class="orb">${escapeHtml(item.name.slice(0, 1).toUpperCase())}</div><h3>${escapeHtml(item.name)}</h3>
    <p>${escapeHtml(item.purpose || ui("一个保存在本机的数字人", "A locally stored avatar"))}</p><div class="avatar-meta"><span>${escapeHtml(item.relationship)}</span><span>${item.proactive_enabled ? ui("主动联系已开启", "Proactive contact on") : ui("主动联系关闭", "Proactive contact off")}</span></div>
  </article>`).join("");
}

function escapeHtml(value = "") {
  const node = document.createElement("div"); node.textContent = String(value); return node.innerHTML;
}

async function openAvatar(id) {
  state.currentId = id;
  state.current = await api(`/api/avatars/${id}`);
  setCreationMode(state.current.subject_kind === "fictional" ? "fictional" : "real");
  state.previewMode = !state.current.readiness?.can_start_official;
  $("#studioName").textContent = state.current.name;
  $("#studioPurpose").textContent = state.current.purpose || state.current.relationship;
  $("#profileInitial").textContent = state.current.name.slice(0, 1).toUpperCase();
  $("#proactiveToggle").checked = state.current.proactive_enabled;
  $("#proactiveInterval").value = state.current.proactive_interval_minutes;
  renderReadinessBanner();
  renderProfile();
  await loadMessages();
  selectTab("chat");
  showView("#studioView");
}

