const state = { avatars: [], currentId: null, current: null, step: 1, currentImport: null, creationMode: "real", fictionalFlow: "guided", guided: null, guidedIndex: 0, previewMode: false, historyKind: "official", timelineKind: "official", modelConnections: [], selectedConnectionId: "", ocrConnections: [], selectedOcrId: "", pendingPackageFile: null, pendingVisualClassification: null, interfaceLanguage: "zh-CN", messages: {}, worldOptions: null, videoCall: null, videoCallStatus: null, livekit: null, livekitRoom: null, livekitAudioContext: null, livekitAudioDest: null, livekitAudioPromise: null, livekitSilenceSource: null, userMedia: null, speechRecognition: null, currentSpeechSource: null, callCameraEnabled: false, callMicrophoneEnabled: false, lastProactiveMessageId: 0, lastNotificationId: Number(localStorage.getItem("openavatar.lastNotificationId") || 0), activeChat: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
// Capture only the original HTML, before any avatar or chat content is rendered.
const staticText = [];
const staticAttributes = [];
const staticWalker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
while (staticWalker.nextNode()) {
  const node = staticWalker.currentNode;
  if (!node.parentElement.closest("script, style, [data-i18n], [data-i18n-html]")) {
    staticText.push({ node, source: node.nodeValue, rendered: node.nodeValue });
  }
}
$$("[placeholder], [title], [aria-label], [alt], input[value]").forEach(node => {
  for (const attribute of ["placeholder", "title", "aria-label", "alt", "value"]) {
    if (node.hasAttribute(attribute)) staticAttributes.push({ node, attribute, source: node.getAttribute(attribute), rendered: node.getAttribute(attribute) });
  }
});
let translationPattern = null;

// Translate developer-authored strings only. Template substitutions are never translated.
// User names, chats, documents and other content must not be passed to this function.
function tr(source, ...values) {
  if (Array.isArray(source) && Object.hasOwn(source, "raw")) {
    return source.map((part, i) => tr(part) + (i < values.length ? values[i] : "")).join("");
  }
  if (state.interfaceLanguage !== "en-US" || typeof source !== "string") return source;
  const dictionary = state.messages.literals || {};
  if (Object.hasOwn(dictionary, source)) return dictionary[source];
  return translationPattern ? source.replace(translationPattern, match => dictionary[match]) : source;
}

// System API messages use exact phrases or named templates. Dynamic values remain intact.
let systemTemplates = [];
function systemText(source) {
  if (state.interfaceLanguage !== "en-US" || typeof source !== "string") return source;
  const dictionary = state.messages.system || {};
  if (Object.hasOwn(dictionary, source)) return dictionary[source];
  if (Object.hasOwn(state.messages.literals || {}, source)) return state.messages.literals[source];
  for (const { pattern, keys, translated } of systemTemplates) {
    const match = source.match(pattern);
    if (match) return translated.replace(/\{(\d+)\}/g, (_, key) => match[keys.indexOf(key) + 1] ?? "");
  }
  return source;
}
function systemHtml(source) { return escapeHtml(systemText(source)); }

function captureFormState() {
  return $$("input, textarea, select").filter(node => node.type !== "file").map(node => {
    const attributes = [...node.attributes].filter(attr => attr.name === "id" || attr.name.startsWith("data-"));
    if (!attributes.length && node.type === "checkbox" && node.hasAttribute("value")) attributes.push(node.attributes.getNamedItem("value"));
    const scope = node.parentElement.closest("[id]");
    const selector = node.id ? `#${CSS.escape(node.id)}` : attributes.length
      ? `${scope ? `#${CSS.escape(scope.id)} ` : ""}${node.tagName}${attributes.map(attr => `[${attr.name}="${CSS.escape(attr.value)}"]`).join("")}` : null;
    return { node, selector, value: node.value, checked: node.checked };
  });
}
function restoreFormState(items) {
  for (const item of items) {
    const node = item.node.isConnected ? item.node : item.selector ? $(item.selector) : null;
    if (node) { node.value = item.value; node.checked = item.checked; }
  }
}

const isFilePreview = window.location.protocol === "file:";

async function api(path, options = {}) {
  if (isFilePreview) {
    throw new Error(tr("请通过 start.command、start.sh、start.bat 或桌面应用打开。直接打开 index.html 只能看到静态页面，不能使用预设和后端能力。"));
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = tr`请求失败（${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(systemText(typeof detail === "string" ? detail : JSON.stringify(detail)));
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function setSystemMessage(node, source) {
  if (!node) return;
  node.dataset.systemMessage = source || "";
  node.textContent = systemText(source || "");
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
    toast(`${systemText(item.title)}${item.body ? `: ${systemText(item.body)}` : ""}`);
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(systemText(item.title), { body: systemText(item.body) || tr("OpenAvatar 后台任务有新进展") });
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
  document.title = "OpenAvatar Studio";
  $$("[data-i18n]").forEach(node => { node.textContent = t(node.dataset.i18n, node.textContent); });
  $$("[data-i18n-html]").forEach(node => { node.innerHTML = t(node.dataset.i18nHtml, node.innerHTML); });
  staticText.forEach(item => {
    // Do not restore text subsequently replaced by a renderer or user content.
    if (item.node.isConnected && item.node.nodeValue === item.rendered) {
      item.rendered = tr(item.source);
      item.node.nodeValue = item.rendered;
    }
  });
  staticAttributes.forEach(item => {
    if (!item.node.isConnected) return;
    if (item.attribute === "value" && item.node.value !== item.rendered) return;
    item.rendered = tr(item.source);
    item.node.setAttribute(item.attribute, item.rendered);
    if (item.attribute === "value") item.node.value = item.rendered;
  });
  $$(".language-switch button").forEach(node => node.classList.toggle("active", node.dataset.language === state.interfaceLanguage));
  const count = $("#avatarCount");
  if (count) count.textContent = `${state.avatars.length} ${t("home.countUnit", "个项目")}`;
}

async function loadI18n(language = "") {
  if (isFilePreview) return;
  const preferred = language || localStorage.getItem("openavatar.interfaceLanguage") || "zh-CN";
  const payload = await api(`/api/i18n/${encodeURIComponent(preferred)}`);
  state.interfaceLanguage = payload.selected || payload.language || preferred;
  const selectedPayload = state.interfaceLanguage === payload.language ? payload : await api(`/api/i18n/${encodeURIComponent(state.interfaceLanguage)}`);
  state.messages = selectedPayload.messages || {};
  const phrases = Object.keys(state.messages.literals || {}).sort((a, b) => b.length - a.length);
  translationPattern = phrases.length ? new RegExp(phrases.map(value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g") : null;
  systemTemplates = Object.entries(state.messages.system || {}).filter(([source]) => /\{\d+\}/.test(source)).map(([source, translated]) => {
    const keys = [...source.matchAll(/\{(\d+)\}/g)].map(match => match[1]);
    const escaped = source.split(/\{\d+\}/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return { pattern: new RegExp("^" + escaped.join("([\\s\\S]*?)") + "$"), keys, translated };
  });
  localStorage.setItem("openavatar.interfaceLanguage", state.interfaceLanguage);
  applyI18n();
}

async function setInterfaceLanguage(language) {
  const result = await api("/api/settings/interface-language", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language }) });
  await loadI18n(result.language);
  const formState = captureFormState();
  try {
    await loadHealth(false);
    await loadAvatars();
    // Refresh system panels without resetting user-entered form values.
    const selectedOptions = ["#avatarLanguageSelect", "#avatarResponseModeSelect", "#worldRegionSelect", "#worldTypeSelect"].map(id => [id, $(id).value]);
    await loadWorldOptions();
    selectedOptions.forEach(([id, value]) => { $(id).value = value; });
    setCreationMode(state.creationMode);
    if (state.providerHub) {
      renderProviderConnections();
      renderCapabilityRoutes();
      renderProviderEditor(state.providerHub.connections.find(item => item.id === $("#settingsDialog").dataset.editProviderId) || null);
    }
    await loadModelConnections();
    await loadOcrConnections();
    if (state.current) {
      renderReadinessBanner();
      renderProfile();
      if (state.guided) {
        state.guided = await api(`/api/avatars/${state.currentId}/guided-builder`);
        renderGuidedBuilder();
      }
      await loadTrainingJobs();
      if (!state.activeChat) await loadMessages();
      else $$('[data-action="cancel-chat"]').forEach(node => { node.textContent = tr("停止"); });
      await loadHistoryRecords();
      await loadLifeArchive();
      await loadAvatarModelSettings();
      await loadVideoCallStatus();
      await loadEvidence();
    }
    if (state.lastEvaluation) renderEvaluation(state.lastEvaluation.result, state.lastEvaluation.kind);
    if (state.packageInfo) renderPackagePreview(state.packageInfo);
    if (state.currentImport) renderImportReview();
    if (state.videoCall) renderActiveVideoCall();
    $$("[data-system-message]").forEach(node => { node.textContent = systemText(node.dataset.systemMessage); });
  } finally { restoreFormState(formState); }
  toast(language === "en-US" ? "Interface language saved" : tr("界面语言已保存"));
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
  node.innerHTML = tr("<b>当前只是静态预览</b><span>请用 start.command、start.sh、start.bat 或桌面应用打开 OpenAvatar Studio，预设、导入和模型连接才会正常工作。</span>");
  document.body.prepend(node);
  const status = $("#modelStatus");
  if (status) {
    status.textContent = tr("请通过启动器打开");
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
  $("#step1Title").innerHTML = fictional ? tr("虚构身份<small>原创角色档案</small>") : tr("真实身份<small>文本、声音、视觉</small>");
  $("#wizardTitle").textContent = fictional ? tr("创建一个原创数字人") : tr("从真实素材创建数字人");
  $("#wizardLead").textContent = fictional
    ? tr("普通用户默认通过问答生成设定；高级用户可以导入文档。里世界可以很大，也可以只先填写必须模块。")
    : tr("真实路线必须有文字或聊天记录来构建人格，再用音频构建声音；音频不能单独生成人物简介。");
  $("#identityForm [name=purpose]").placeholder = fictional
    ? tr("例如：创建一个原创虚构角色，用设定文件定义人格、世界观和说话方式")
    : tr("例如：记录自己的表达方式，创建一个可长期陪伴的数字分身");
  $("#step2Hint").textContent = fictional ? tr("问答、文档、视觉、声音") : tr("聊天、截图、声音、照片");
  $("#importLead").textContent = fictional
    ? tr("默认用问答一步步生成原创设定；高级用户也可以导入 Markdown、JSON、YAML 角色卡。")
    : tr("不必一次准备齐全。原始文件保存在本机；只有选择云端API并确认后，完成分析所需的内容才会发送给用户指定的服务商。");
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

async function loadHealth(refresh = true) {
  try {
    const health = !refresh && state.lastHealth ? state.lastHealth : await api("/api/health");
    state.lastHealth = health;
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
  $("#diagnosticsSummary").innerHTML = tr`<span class="diagnostic-loading">正在检查本地系统…</span>`;
  $("#diagnosticsList").innerHTML = "";
  if (!$("#diagnosticsDialog").open) $("#diagnosticsDialog").showModal();
  const report = await api("/api/diagnostics");
  const statusText = report.status === "pass" ? tr("状态良好") : report.status === "warn" ? tr("需要注意") : tr("需要处理");
  $("#diagnosticsSummary").innerHTML = tr`<article class="${escapeHtml(report.status)}"><b>${escapeHtml(statusText)}</b><span>${report.summary.pass} 项通过 · ${report.summary.warn} 项提醒 · ${report.summary.fail} 项失败</span><small>数据目录：${escapeHtml(report.environment.data_dir)}</small></article>`;
  $("#diagnosticsList").innerHTML = report.checks.map(item => `<article class="diagnostic-item ${escapeHtml(item.status)}">
    <b>${systemHtml(item.name)}</b><span>${systemHtml(item.detail)}</span>${item.action ? `<small>${systemHtml(item.action)}</small>` : ""}
  </article>`).join("");
}

async function openCapabilities() {
  $("#capabilityList").innerHTML = tr`<span class="diagnostic-loading">正在读取能力状态…</span>`;
  if (!$("#capabilitiesDialog").open) $("#capabilitiesDialog").showModal();
  const report = await api("/api/capabilities");
  $("#capabilityList").innerHTML = report.items.map(item => `<article class="capability-item ${escapeHtml(item.running_at)}">
    <div><b>${systemHtml(item.name)}</b><span>${escapeHtml(item.status)} · ${escapeHtml(item.running_at)}</span></div>
    <p><strong>${escapeHtml(item.key === "ocr" && item.running_at === "cloud" ? item.provider : systemText(item.provider))}</strong>${systemHtml(item.sends)}</p>
    <small>${systemHtml(item.cost)}${item.consent ? tr(" · 已确认边界") : tr(" · 需要用户留意边界")}</small>
  </article>`).join("");
}

function renderPackagePreview(info) {
  state.packageInfo = info;
  const typeName = { self: tr("我自己"), authorized_person: tr("授权真人"), fictional: tr("虚构人物") }[info.subject_kind] || info.subject_kind;
  const hint = info.model_connection_hint || {};
  const language = info.language_profile || {};
  const region = language.world_region_rules || {};
  $("#packagePreview").innerHTML = tr`<article>
    <b>${escapeHtml(info.name || tr("未命名人物包"))}</b>
    <span>${escapeHtml(typeName)} · v${escapeHtml(info.version)} · ${info.file_count} 个文件 · ${info.asset_count} 个素材文件</span>
    <p>${escapeHtml(info.persona_summary || tr("人物包没有摘要，导入后可重新运行 Builder。"))}</p>
  </article>
  <article><b>语言与世界</b><span>${escapeHtml(language.avatar_primary_language || info.avatar_primary_language || tr("未声明"))} · ${escapeHtml(labelFor(region) || info.world_region || tr("未声明"))}</span><small>人物包会迁移数字人语言和世界地区；不会迁移使用者自己的界面语言。</small></article>
  <article><b>模型连接</b><span>${hint.provider_name ? `${escapeHtml(hint.provider_name)} · ${escapeHtml(hint.model || "")}` : tr("没有模型连接提示")}</span><small>不会导入 API Key，导入后需要重新绑定自己的连接。</small></article>
  <article class="${info.contains_api_keys ? "fail" : "pass"}"><b>密钥检查</b><span>${info.contains_api_keys ? tr("清单声明可能包含密钥，系统不会导入密钥。") : tr("清单声明不包含 API Key。")}</span></article>
  ${info.warnings?.length ? tr`<article class="warn"><b>提醒</b>${info.warnings.map(item => `<span>${systemHtml(item)}</span>`).join("")}</article>` : ""}
  <article><b>包含内容</b><span>${(info.included_sections || []).map(item => escapeHtml(item)).join(" · ")}</span></article>`;
}

async function loadAvatars() {
  state.avatars = await api("/api/avatars");
  $("#avatarCount").textContent = `${state.avatars.length} ${t("home.countUnit", tr("个项目"))}`;
  const grid = $("#avatarGrid");
  if (!state.avatars.length) {
    grid.innerHTML = tr`<div class="empty-card empty-home">
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
  state.lastEvaluation = null;
  state.currentImport = null;
  $("#evaluationResult").innerHTML = "";
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

