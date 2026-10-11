// A local configuration checklist. Connection editing and avatar creation stay in
// their existing screens; this module never tests a provider or submits AI work.
let setupGuideReport = null;
let setupGuideInitialized = false;
let setupGuideReturning = false;
let setupGuideGeneration = 0;

const setupIssueLabels = {
  route_missing: ["还没有选择服务和模型", "Choose a service and model"],
  connection_missing: ["所选连接不存在，请重新选择", "The selected connection is missing; choose another"],
  connection_disabled: ["服务连接已停用", "The connection is disabled"],
  capability_disabled: ["连接尚未开启这项能力", "This capability is disabled on the connection"],
  adapter_unsupported: ["这类服务暂不支持语音合成，请改用已支持的连接", "Speech synthesis is not supported for this provider type; choose a supported connection"],
  consent_missing: ["缺少所需数据授权", "Required data consent is missing"],
  model_missing: ["还没有填写模型名称", "A model name is missing"],
  address_invalid: ["服务地址不可用，请检查设置", "The service address needs correction"],
  credentials_missing: ["尚未保存可用密钥", "No saved credential is available"],
  credentials_unavailable: ["暂时无法检查凭据库", "The credential store could not be checked"],
  budget_exhausted: ["已达到当前日或月估算预算", "The current daily or monthly estimated budget is exhausted"],
  budget_invalid: ["预算设置无效，请检查金额", "Budget settings are invalid; check the amounts"],
  connection_unavailable: ["连接条件尚未满足", "Connection requirements are not met"],
  legacy_test_required: ["旧版连接需要有效的测试记录，请在设置中确认", "The legacy connection needs a valid test record; review it in settings"],
};

function ensureSetupGuide() {
  let dialog = document.querySelector('#setupGuideDialog');
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.id = 'setupGuideDialog';
  dialog.setAttribute('aria-labelledby', 'setupGuideTitle');
  document.body.append(dialog);
  dialog.addEventListener('cancel', event => { event.preventDefault(); dismissSetupGuide(); });
  dialog.addEventListener('click', async event => {
    const button = event.target.closest('[data-setup-action]');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      const action = button.dataset.setupAction;
      if (action === 'dismiss') await dismissSetupGuide();
      if (action === 'refresh') await refreshSetupGuide();
      if (action === 'configure') await configureSetupCapability(button.dataset.capability);
      if (action === 'create') {
        dialog.close();
        const trigger = document.querySelector(`[data-action="${button.dataset.creationAction}"]`);
        if (!trigger) throw new Error(ui('创建入口暂不可用，请从首页创建', 'Creation is unavailable here; use the home page'));
        trigger.click(); // The existing form still collects identity and rights.
      }
      if (action === 'avatar' && setupGuideReport?.avatar) {
        dialog.close();
        await openAvatar(setupGuideReport.avatar.id);
        await selectTab(setupGuideReport.required?.ready ? 'chat' : 'training');
      }
    } catch (error) {
      if (!dialog.open) dialog.showModal();
      const node = document.querySelector('#setupGuideError');
      if (node) node.textContent = error.message;
    } finally { button.disabled = false; }
  });
  return dialog;
}

function setupCapabilityCard(capability, optional = false) {
  const item = setupGuideReport?.capabilities?.[capability];
  if (!item) return '';
  const titles = {chat: ['对话', 'Chat'], tts: ['声音', 'Voice'], vision: ['看图', 'Images']};
  const label = item.ready ? ui('本机配置已就绪', 'Locally configured') : optional && item.issues.includes('route_missing') ? ui('可稍后开启', 'Optional; add later') : ui('还需配置', 'Needs configuration');
  const issues = item.issues.map(code => `<li>${escapeHtml(ui(...(setupIssueLabels[code] || setupIssueLabels.connection_unavailable)))}</li>`).join('');
  const selected = item.display_name ? `<p class="setup-guide-detail">${escapeHtml(item.display_name)}${item.model ? ` · ${escapeHtml(item.model)}` : ''}${item.using_fallback ? ` · ${ui('使用备用连接', 'Using fallback')}` : ''}</p>` : '';
  return `<div class="setup-guide-capability"><h4>${escapeHtml(ui(...titles[capability]))}</h4><span class="setup-guide-state ${item.ready ? 'ready' : ''}">${label}</span>${selected}${issues ? `<ul>${issues}</ul>` : ''}<button type="button" class="secondary" data-setup-action="configure" data-capability="${capability}">${item.ready ? ui('查看设置', 'Review settings') : ui('去配置', 'Configure')}</button></div>`;
}

function renderSetupGuide() {
  const dialog = ensureSetupGuide();
  const report = setupGuideReport;
  let avatarContent = `<p>${ui('用原创设定或有权使用的资料创建人物，按向导完成必须项。', 'Create from original settings or authorized materials, then complete the required items.')}</p><button type="button" class="primary" data-setup-action="create" data-creation-action="new-fictional-avatar">${ui('创建虚构数字人', 'Create fictional avatar')}</button><button type="button" class="secondary" data-setup-action="create" data-creation-action="new-real-avatar">${ui('从真实素材创建', 'Create from real materials')}</button>`;
  if (report?.avatar) {
    const ready = report.required?.ready;
    avatarContent = `<p><strong>${escapeHtml(report.avatar.name)}</strong></p><span class="setup-guide-state ${ready ? 'ready' : ''}">${ready ? ui('必须项已完成', 'Required items complete') : ui('继续完成必须项', 'Complete required items')}</span><p>${ui('必须项', 'Required')} ${escapeHtml(report.required?.summary || '')}</p>${(report.required?.missing || []).length ? `<ul>${report.required.missing.map(item => `<li>${escapeHtml(systemText(item.name))}</li>`).join('')}</ul>` : ''}<button type="button" class="primary" data-setup-action="avatar">${ready ? ui('开始聊天', 'Start chatting') : ui('打开构建中心', 'Open Build Center')}</button>`;
  }
  dialog.innerHTML = `<div class="setup-guide-content"><div class="setup-guide-heading"><div><small>OPENAVATAR STUDIO</small><h2 id="setupGuideTitle">${ui('三步开始使用', 'Get started in three steps')}</h2></div><button type="button" class="secondary setup-guide-close" data-setup-action="dismiss" aria-label="${ui('关闭起步指南', 'Close setup guide')}">×</button></div><p class="setup-guide-lead">${ui('先让对话可用，再按需添加声音和看图。设置和创建都沿用原有页面。', 'Set up chat first, then add voice and images if needed. Use the existing settings and creation screens.')}</p>${report ? `<div class="setup-guide-steps"><section class="setup-guide-step"><h3>${ui('1 · 配置对话', '1 · Configure chat')}</h3>${setupCapabilityCard('chat')}<p class="setup-guide-detail">${ui('保存连接后，还要为对话选择服务和模型。', 'After saving a connection, select its service and model for Chat.')}</p></section><section class="setup-guide-step"><h3>${ui('2 · 声音和看图（可选）', '2 · Voice and images (optional)')}</h3>${setupCapabilityCard('tts', true)}${setupCapabilityCard('vision', true)}<p class="setup-guide-detail">${ui('声音还需要在人物构建中心选择音色；可以先只用文字。', 'For speech, also choose a voice in Build Center. You can start with text only.')}</p></section><section class="setup-guide-step"><h3>${ui('3 · 完成人物，开始聊天', '3 · Finish an avatar and chat')}</h3>${avatarContent}</section></div>` : `<p role="status">${ui('正在检查本机配置…', 'Checking local configuration…')}</p>`}<div id="setupGuideError" role="alert"></div><div class="setup-guide-footer"><button type="button" class="secondary" data-setup-action="refresh">${ui('刷新本机状态', 'Refresh local status')}</button><button type="button" class="secondary" data-setup-action="dismiss">${ui('先跳过，可从顶部再次打开', 'Skip for now; reopen from the top bar')}</button></div><p class="setup-guide-note">${ui('这里只检查保存的配置、数据授权、密钥是否存在和估算预算，不会自动测试服务或产生 AI 调用费用。配置就绪不等于实际回复已验证。', 'This checks saved configuration, consent, credential presence, and estimated budgets. It does not test services or make billable AI requests. Configuration readiness is not proof of a successful reply.')}</p></div>`;
}

async function refreshSetupGuide() {
  const generation = ++setupGuideGeneration;
  const query = state.currentId ? `?avatar_id=${encodeURIComponent(state.currentId)}` : '';
  try {
    const report = await api(`/api/setup/status${query}`);
    if (generation !== setupGuideGeneration) return setupGuideReport;
    setupGuideReport = report;
    if (document.querySelector('#setupGuideDialog')?.open) renderSetupGuide();
    return report;
  } catch (error) {
    if (generation === setupGuideGeneration) {
      const node = document.querySelector('#setupGuideError');
      if (node) node.textContent = ui('无法检查本机状态，请稍后刷新。', 'Could not check local status. Please refresh later.');
    }
    throw error;
  }
}

async function openSetupGuide() {
  const dialog = ensureSetupGuide();
  document.querySelector('#onboardingDialog')?.close();
  renderSetupGuide();
  if (!dialog.open) dialog.showModal();
  try { await refreshSetupGuide(); } catch (_) { /* The retry control remains available. */ }
}

async function dismissSetupGuide() {
  try {
    await api('/api/setup/dismiss', {method: 'PUT'});
    if (setupGuideReport) setupGuideReport.dismissed = true;
    setupGuideReturning = false;
    document.querySelector('#setupGuideDialog')?.close();
  } catch (_) {
    const node = document.querySelector('#setupGuideError');
    if (node) node.textContent = ui('未能保存跳过状态，请重试。', 'Could not save dismissal. Please retry.');
  }
}

async function configureSetupCapability(capability) {
  if (!['chat', 'tts', 'vision'].includes(capability)) return;
  const item = setupGuideReport?.capabilities?.[capability];
  document.querySelector('#setupGuideDialog')?.close();
  if (item?.scope === 'avatar' && setupGuideReport?.avatar && state.currentId !== setupGuideReport.avatar.id) {
    await openAvatar(setupGuideReport.avatar.id);
  }
  setupGuideReturning = true;
  await openSettings();
  if (!document.querySelector('#settingsDialog')?.open) return;
  if (item?.source === 'legacy') {
    setSettingsTab('modelSettingsPanel');
    document.querySelector('#dialogConnectionList')?.scrollIntoView({block: 'center'});
    return;
  }
  setSettingsTab('providerHubPanel');
  const scope = document.querySelector('#capabilityRouteScope');
  if (scope) scope.value = item?.scope === 'avatar' && state.currentId ? 'avatar' : 'global';
  renderCapabilityRoutes();
  const connection = state.providerHub?.connections.find(row => row.id === item?.connection_id);
  const connectionProblem = item?.issues?.some(code => !['route_missing', 'connection_missing'].includes(code));
  if (connectionProblem && connection) {
    renderProviderEditor(connection);
    document.querySelector('#providerDisplayName')?.scrollIntoView({block: 'center'});
    document.querySelector('#providerDisplayName')?.focus({preventScroll: true});
  } else if (!state.providerHub?.connections?.length) {
    document.querySelector('#providerDisplayName')?.scrollIntoView({block: 'center'});
    document.querySelector('#providerDisplayName')?.focus({preventScroll: true});
  } else {
    const target = document.querySelector(`[data-cap-route-primary="${capability}"]`);
    target?.scrollIntoView({block: 'center'});
    target?.focus({preventScroll: true});
  }
}

async function initializeSetupGuide() {
  if (setupGuideInitialized || isFilePreview) return;
  setupGuideInitialized = true;
  document.querySelector('#settingsDialog')?.addEventListener('close', async () => {
    if (!setupGuideReturning) return;
    setupGuideReturning = false;
    await openSetupGuide();
  });
  new MutationObserver(() => {
    if (document.querySelector('#setupGuideDialog')?.open) renderSetupGuide();
  }).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});
  try {
    const report = await refreshSetupGuide();
    if (report?.auto_show && !document.querySelector('dialog[open]')) await openSetupGuide();
  } catch (_) { /* An unavailable optional guide must not block application startup. */ }
}
