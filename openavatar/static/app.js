document.addEventListener("click", async event => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  const avatar = event.target.closest("[data-avatar]")?.dataset.avatar;

  const step = event.target.closest("[data-step-go]")?.dataset.stepGo;
  const tab = event.target.closest("[data-tab]")?.dataset.tab;
  const historyKind = event.target.closest("[data-history-kind]")?.dataset.historyKind;
  const timelineKind = event.target.closest("[data-timeline-kind]")?.dataset.timelineKind;
  try {
    if (avatar) return openAvatar(avatar);
    if (step) return goStep(Number(step));
    if (tab) return selectTab(tab);
    if (historyKind) {
      state.historyKind = historyKind;
      $$('[data-history-kind]').forEach(node => node.classList.toggle("active", node.dataset.historyKind === historyKind));
      return loadHistoryRecords();
    }
    if (timelineKind) {
      state.timelineKind = timelineKind;
      $$('[data-timeline-kind]').forEach(node => node.classList.toggle("active", node.dataset.timelineKind === timelineKind));
      return loadLifeArchive();
    }
    if (action && action !== "toggle-mobile-menu") closeMobileMenu();
    if (action === "toggle-mobile-menu") return $(".top-actions")?.classList.toggle("open");
    if (action === "settings-tab") return setSettingsTab(event.target.closest("[data-settings-tab]").dataset.settingsTab);
    if (action === "home") { await loadAvatars(); showView("#homeView"); }
    if (action === "open-onboarding") $("#onboardingDialog").showModal();
    if (action === "complete-onboarding") {
      await api("/api/onboarding", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ completed: true }) });
      $("#onboardingDialog").close();
      toast("新手向导已完成，之后可以从顶部再次打开");
    }
    if (action === "open-diagnostics") await openDiagnostics();
    if (action === "dismiss-error") $("#errorTray").classList.add("hidden");
    if (action === "search-history") await loadHistoryRecords();
    if (action === "correct-history") {
      const memoryId = Number(event.target.closest("[data-memory-id]").dataset.memoryId);
      const result = await api(`/api/avatars/${state.currentId}/history?layer=historical&limit=1000`);
      const item = result.items.find(row => Number(row.id) === memoryId);
      if (!item) throw new Error(ui("找不到这条永久历史", "Permanent history record not found"));
      const content = prompt(ui("校正显示文字。原始导入内容不会被覆盖。", "Correct the display text. The original import will not be overwritten."), item.content);
      if (content === null) return;
      const speaker = prompt(ui("校正说话人（可保持不变）", "Correct the speaker (or keep unchanged)"), item.speaker);
      if (speaker === null) return;
      await api(`/api/avatars/${state.currentId}/history/${memoryId}/correction`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, speaker, note: ui("用户手工校正", "Manual user correction") }) });
      await loadHistoryRecords(); toast(ui("显示校正已保存，原始资料保持不变", "Display correction saved; original source preserved"));
    }
    if (action === "timeline-edit") await prepareTimelineChange("edit", Number(event.target.closest("[data-message-id]").dataset.messageId));
    if (action === "timeline-delete") await prepareTimelineChange("delete", Number(event.target.closest("[data-message-id]").dataset.messageId));
    if (action === "timeline-restore") {
      if (!confirm(ui("恢复后，当前时间线会进入封存区。继续吗？", "The current timeline will be archived after restoration. Continue?"))) return;
      const branchId = event.target.closest("[data-branch-id]").dataset.branchId;
      await api(`/api/avatars/${state.currentId}/timeline/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ branch_id: branchId }) });
      await Promise.all([loadLifeArchive(), loadMessages()]); toast(ui("时间线已经互换", "Timelines swapped"));
    }
    if (action === "timeline-purge") {
      if (!confirm(ui("系统会先自动备份数据库，再永久删除这个封存版本。继续吗？", "The database will be backed up before this archived version is permanently deleted. Continue?"))) return;
      const branchId = event.target.closest("[data-branch-id]").dataset.branchId;
      const result = await api(`/api/avatars/${state.currentId}/timeline/delete-branch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ branch_id: branchId }) });
      await loadLifeArchive(); toast(ui(`已永久删除；备份位于 ${result.backup_path}`, `Deleted permanently; backup: ${result.backup_path}`));
    }
    if (action === "timeline-approve-media") {
      if (!confirm(ui("确认允许数字人以后重新使用这项媒体？", "Allow the avatar to reuse this media later?"))) return;
      const candidateId = Number(event.target.closest("[data-candidate-id]").dataset.candidateId);
      await api(`/api/avatars/${state.currentId}/timeline/media-candidates/${candidateId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved", confirmed: true }) });
      await loadLifeArchive(); toast(ui("复用权限已保存", "Reuse permission saved"));
    }
    if (action === "refresh-diagnostics") await openDiagnostics();
    if (action === "open-capabilities") await openCapabilities();
    if (action === "refresh-capabilities") await openCapabilities();
    if (action === "open-privacy") {
      if ($("#onboardingDialog").open) $("#onboardingDialog").close();
      if (!$("#privacyDialog").open) $("#privacyDialog").showModal();
    }
    if (action === "close-privacy") $("#privacyDialog").close();
    if (action === "cancel-package-import") {
      state.pendingPackageFile = null;
      $("#packageDialog").close();
      $("#packageInput").value = "";
    }
    if (action === "confirm-package-import") {
      if (!state.pendingPackageFile) throw new Error("请先选择人物包文件");
      const file = state.pendingPackageFile;
      const result = await api("/api/packages/import", { method: "POST", headers: { "Content-Type": "application/zip", "X-File-Name": encodeURIComponent(file.name), "X-Rights-Confirmed": "true" }, body: file });
      state.pendingPackageFile = null;
      $("#packageDialog").close();
      $("#packageInput").value = "";
      await loadAvatars();
      toast(`已导入数字人：${result.name}`);
      await openAvatar(result.id);
    }
    if (action === "new-real-avatar" || action === "new-avatar") { state.currentId = null; $("#identityForm").reset(); $("#uploadList").innerHTML = ""; setCreationMode("real"); showView("#wizardView"); goStep(1); }
    if (action === "new-fictional-avatar") { state.currentId = null; $("#identityForm").reset(); $("#uploadList").innerHTML = ""; state.fictionalFlow = "guided"; setCreationMode("fictional"); showView("#wizardView"); goStep(1); }
    if (action === "set-fictional-flow") {
      setFictionalFlow(event.target.closest("[data-flow]").dataset.flow);
      if (state.fictionalFlow === "guided" && state.currentId) await loadGuidedBuilder();
    }
    if (action === "open-existing") { $("#avatarGrid").scrollIntoView({ behavior: "smooth" }); }
    if (action === "open-settings") await openSettings();
    if (action === "set-interface-language") {
      const button = event.target.closest("[data-language]");
      if (button?.dataset.language) await setInterfaceLanguage(button.dataset.language);
    }
    if (action === "open-current") await openAvatar(state.currentId);
    if (action === "skip-guided-question") {
      const active = (state.guided?.questions || []).filter(row => row.enabled);
      if (!active.length) return;
      state.guidedIndex = Math.min(active.length - 1, state.guidedIndex + 1);
      renderGuidedBuilder();
    }
    if (action === "save-guided-answer") {
      const active = (state.guided?.questions || []).filter(row => row.enabled);
      const item = active[state.guidedIndex] || state.guided?.next_question;
      if (!item) throw new Error("没有需要回答的问题");
      const answer = $("#guidedAnswer").value.trim();
      if (!answer) throw new Error("请先写一点设定");
      state.guided = await api(`/api/avatars/${state.currentId}/guided-builder/answers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_key: item.key, answer }) });
      const nextIndex = state.guided.questions.filter(row => row.enabled).findIndex(row => !row.answered);
      state.guidedIndex = nextIndex >= 0 ? nextIndex : state.guidedIndex;
      renderGuidedBuilder();
      toast("这一项已进入设定证据库");
    }
    if (action === "choose-ai") {
      if (!state.currentId) throw new Error("请先创建人物档案");
      state.current = await api(`/api/avatars/${state.currentId}`);
      const required = state.current.readiness?.checks || [];
      if (state.creationMode === "real") {
        const textReady = required.find(item => item.name === "文本人格素材")?.passed;
        const audioReady = required.find(item => item.name === "声音样本")?.passed;
        if (!textReady || !audioReady) throw new Error("真实路线需要先确认文字/聊天内容，并上传至少一段声音样本。完成后才能选择 AI。");
      } else {
        const pendingSetting = state.current.imports?.some(item => item.category === "fictional" && item.status === "needs_review");
        if (pendingSetting) throw new Error("请先预览并确认刚刚导入的设定文件。");
      }
      await loadModelConnections();
      goStep(3);
    }
    if (action === "review-import") await openImportReview(Number(event.target.closest("[data-import-id]").dataset.importId));
    if (action === "close-review") $("#reviewDialog").close();
    if (action === "confirm-import") {
      const avatarSpeakers = $$("#speakerChoices input:checked").map(node => node.value);
      const excluded = $$("#reviewRows input:not(:checked)").map(node => Number(node.dataset.rowId));
      const result = await api(`/api/avatars/${state.currentId}/imports/${state.currentImport.id}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ avatar_speakers: avatarSpeakers, excluded_row_ids: excluded, apply_mode: $("#fictionalApplyMode").value }) });
      $("#reviewDialog").close();
      const status = $(`[data-upload-import="${state.currentImport.id}"] .upload-status`);
      if (status) status.textContent = result.note;
      state.current = await api(`/api/avatars/${state.currentId}`);
      renderProfile();
      toast("资料已经确认，可以用于人格构建");
    }
    if (action === "cancel-job") {
      const jobId = event.target.closest("[data-job-id]").dataset.jobId;
      await api(`/api/avatars/${state.currentId}/training-jobs/${jobId}/cancel`, { method: "POST" });
      await loadTrainingJobs(); toast("已请求取消构建任务");
    }
    if (action === "retry-job") {
      const jobId = event.target.closest("[data-job-id]").dataset.jobId;
      await api(`/api/avatars/${state.currentId}/training-jobs/${jobId}/retry`, { method: "POST" });
      await loadTrainingJobs(); toast("任务已经重新进入队列");
    }
    if (action === "run-cloud-job") {
      const jobId = event.target.closest("[data-job-id]").dataset.jobId;
      if (!confirm("这会把该数字人的授权素材发送给已配置的云端服务商，并可能产生 API 费用。视频任务会异步生成，需要之后检查结果。继续吗？")) return;
      await api(`/api/avatars/${state.currentId}/training-jobs/${jobId}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_billable_call: true }) });
      await loadTrainingJobs(); toast("云端任务已更新");
    }
    if (action === "speak-message") {
      const text = event.target.closest(".message").querySelector("span").textContent;
      if (!confirm("使用复刻声音播放会调用云端 TTS 并可能产生费用。继续吗？")) return;
      const response = await fetch(`/api/avatars/${state.currentId}/speech`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, confirm_billable_call: true }) });
      if (!response.ok) { let detail = "语音生成失败"; try { detail = (await response.json()).detail || detail; } catch (_) {} throw new Error(detail); }
      await playSpeechBlob(await response.blob());
    }
    if (action === "evaluate-avatar") {
      const result = await api(`/api/avatars/${state.currentId}/evaluate`, { method: "POST" });
      $("#evaluationResult").innerHTML = `<div class="evaluation-card"><div class="evaluation-score"><b>${result.score}</b><span>关键盲测</span></div><div>${(result.samples || []).map(sample => `<p><strong>${escapeHtml(sample.title)}</strong><small>${escapeHtml(sample.expected_signal)}</small></p>`).join("")}${result.checks.map(check => `<p class="${check.passed ? "passed" : "pending"}">${check.passed ? "✓" : "○"} ${escapeHtml(check.name)} <small>${escapeHtml(check.passed ? String(check.value ?? "") : check.recommendation)}</small></p>`).join("")}</div></div>`;
      await loadTrainingJobs(); toast("就绪度评估已完成");
    }
    if (action === "run-build-checks") {
      const result = await api(`/api/avatars/${state.currentId}/checks`);
      $("#evaluationResult").innerHTML = `<div class="evaluation-card"><div class="evaluation-score"><b>${result.score}</b><span>构建检查</span></div><div>${result.checks.map(check => `<p class="${check.passed ? "passed" : "pending"}">${check.passed ? "✓" : "○"} ${escapeHtml(check.name)} <small>${escapeHtml(check.passed ? (check.level || check.severity) : check.recommendation)}</small></p>`).join("")}</div></div>`;
      await loadBuildPanels();
    }
    if (action === "approve-video-review") {
      if (!confirm("请先播放并检查人物、服装、物品和场景。确认这段视频可以使用吗？")) return;
      const runId = event.target.closest("[data-run-id]").dataset.runId;
      await api(`/api/avatars/${state.currentId}/continuity/runs/${runId}/approve`, { method: "POST" });
      await loadTrainingJobs();
      toast("视频已通过人工确认并加入历史参考库");
    }
    if (action === "run-builder") {
      const result = await api(`/api/avatars/${state.currentId}/build`, { method: "POST" });
      $("#evaluationResult").innerHTML = `<div class="evaluation-card"><div class="evaluation-score"><b>${result.score}</b><span>Builder</span></div><div>${result.checks.map(check => `<p class="${check.passed ? "passed" : "pending"}">${check.passed ? "✓" : "○"} ${escapeHtml(check.name)} <small>${escapeHtml(check.passed ? (check.level || check.severity) : check.recommendation)}</small></p>`).join("")}</div></div>`;
      state.current = await api(`/api/avatars/${state.currentId}`);
      renderReadinessBanner();
      renderProfile();
      await loadTrainingJobs();
      toast("统一 Builder 已运行");
    }
    if (action === "advance-world") {
      const result = await api(`/api/avatars/${state.currentId}/world/advance`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seconds: 3600, force_minor_event: true }) });
      await loadTrainingJobs();
      toast(result.advanced ? "里世界已推进一小时" : result.reason || "里世界未推进");
    }
    if (action === "rollback-world") {
      const result = await api(`/api/avatars/${state.currentId}/world/rollback`, { method: "POST" });
      await loadTrainingJobs();
      toast(result.rolled_back ? "已回滚最近一次世界事件" : result.reason || "没有可回滚事件");
    }
    if (action === "rebuild-memory-graph") {
      await api(`/api/avatars/${state.currentId}/memory-graph/rebuild`, { method: "POST" });
      await loadTrainingJobs();
      toast("记忆图谱已重建");
    }
    if (action === "rebuild-persona-core") {
      await api(`/api/avatars/${state.currentId}/persona-core/rebuild`, { method: "POST" });
      await loadTrainingJobs();
      toast("Persona Core 已重建");
    }
    if (action === "review-world-proposal") {
      const proposalId = event.target.closest("[data-proposal-id]").dataset.proposalId;
      const reviewAction = event.target.closest("[data-review-action]").dataset.reviewAction;
      await api(`/api/avatars/${state.currentId}/world/proposals/${proposalId}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: reviewAction, note: "构建中心审批" }) });
      await loadTrainingJobs(); toast(reviewAction === "approve" ? "世界事实已批准" : "世界事实已拒绝");
    }
    if (action === "update-visual-asset") {
      const node = event.target.closest("[data-asset-id]");
      await api(`/api/avatars/${state.currentId}/visual-assets/${node.dataset.assetId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: node.dataset.status, note: "构建中心视觉审批" }) });
      await loadTrainingJobs(); toast("视觉审批状态已更新");
    }
    if (action === "organize-visual-assets") {
      const result = await api(`/api/avatars/${state.currentId}/visual-asset-sets/organize`, { method: "POST" });
      await loadTrainingJobs();
      toast(result.organized ? `已整理 ${result.organized} 张素材` : "现有素材已经整理完成");
    }
    if (action === "classify-visual-asset") {
      const node = event.target.closest("[data-asset-id]");
      const names = { identity: "人物身份", wardrobe: "服装", prop: "物品", scene: "场景" };
      const setType = node.dataset.setType;
      state.pendingVisualClassification = { assetId: Number(node.dataset.assetId), assetStatus: node.dataset.assetStatus, setType };
      $("#visualClassifyTitle").textContent = `整理为${names[setType]}素材包`;
      $("#visualSetLabel").value = `默认${names[setType]}`;
      $("#visualSetRules").value = "";
      $("#visualClassifyDialog").showModal();
    }
    if (action === "cancel-visual-classify") {
      state.pendingVisualClassification = null;
      $("#visualClassifyDialog").close();
    }
    if (action === "confirm-visual-classify") {
      const pending = state.pendingVisualClassification;
      if (!pending) return;
      const names = { identity: "人物身份", wardrobe: "服装", prop: "物品", scene: "场景" };
      const setType = pending.setType;
      const label = $("#visualSetLabel").value.trim();
      if (!label) throw new Error("请填写素材包名称");
      const ruleText = $("#visualSetRules").value;
      const invariants = ruleText.split(/[,，]/).map(item => item.trim()).filter(Boolean);
      const assetSet = await api(`/api/avatars/${state.currentId}/visual-asset-sets`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set_type: setType, label, invariants, status: pending.assetStatus === "canonical" ? "canonical" : "approved" }),
      });
      await api(`/api/avatars/${state.currentId}/visual-asset-sets/${assetSet.id}/items`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visual_asset_id: pending.assetId, role: setType === "scene" ? "first_frame" : "reference", status: pending.assetStatus }),
      });
      if (setType === "scene") {
        await api(`/api/avatars/${state.currentId}/scene-profiles`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name: label, semantic_key: assetSet.semantic_key, stable_features: invariants, status: "approved", route: "image_grounded" }),
        });
      }
      state.pendingVisualClassification = null;
      $("#visualClassifyDialog").close();
      await loadTrainingJobs();
      toast(`已加入${names[setType]}一致性素材包`);
    }
    if (action === "select-voice-profile") {
      const profileId = event.target.closest("[data-profile-id]").dataset.profileId;
      await api(`/api/avatars/${state.currentId}/voice-profiles/${profileId}/select`, { method: "POST" });
      await loadTrainingJobs(); toast("声音方案已选择");
    }
    if (action === "enable-preview") {
      state.previewMode = true;
      renderReadinessBanner();
      await loadMessages();
      toast("已开启预览测试模式");
    }
    if (action === "continue-import") {
      setCreationMode(state.current?.subject_kind === "fictional" ? "fictional" : "real");
      showView("#wizardView"); goStep(2);
      if (state.creationMode === "fictional") await loadGuidedBuilder();
    }
    if (action === "run-transcription") {
      const transcriptionId = event.target.closest("[data-transcription-id]").dataset.transcriptionId;
      if (!confirm("这会把授权音频发送给当前 ASR 服务，并可能产生费用。继续吗？")) return;
      await api(`/api/avatars/${state.currentId}/voice-transcriptions/${transcriptionId}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_billable_call: true }) });
      await loadTrainingJobs(); toast("自动转写完成，请检查后确认");
    }
    if (action === "confirm-transcription") {
      const transcriptionId = event.target.closest("[data-transcription-id]").dataset.transcriptionId;
      const text = $(`[data-transcription-text="${transcriptionId}"]`).value.trim();
      if (!text) throw new Error("请先填写转写文本");
      await api(`/api/avatars/${state.currentId}/voice-transcriptions/${transcriptionId}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ transcript: text, use_as_memory: true }) });
      await loadTrainingJobs(); toast("声音转写已进入证据库");
    }
    if (action === "save-model-route") {
      const role = event.target.closest("[data-route]").dataset.route;
      const provider = $(`[data-route="${role}"][data-route-field="provider"]`).value;
      const primaryModel = $(`[data-route="${role}"][data-route-field="primary_model"]`).value;
      await api(`/api/settings/model-routes/${encodeURIComponent(role)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role, provider, primary_model: primaryModel, fallback_models: [], latency_class: "background", cost_class: "cheap" }) });
      await loadBuildPanels(); toast("模型路由已保存");
    }
    if (action === "download-templates") {
      const templates = await api("/api/templates/character");
      const blob = new Blob([templates.avatar_md + "\n\n--- character.yaml ---\n" + templates.character_yaml], { type: "text/plain;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob); link.download = "openavatar-character-templates.txt"; link.click(); URL.revokeObjectURL(link.href);
      toast("设定模板已生成");
    }
    if (action === "refresh-connections") {
      await loadModelConnections();
      toast("模型连接列表已刷新");
    }
    if (action === "edit-model-connection") {
      const id = event.target.closest("[data-connection-id]").dataset.connectionId;
      fillConnectionEditor(state.modelConnections.find(item => item.id === id));
    }
    if (action === "select-model-connection") {
      const id = event.target.closest("[data-connection-id]").dataset.connectionId;
      await api(`/api/model-connections/${encodeURIComponent(id)}/select`, { method: "POST" });
      await loadModelConnections();
      toast("默认模型连接已切换");
    }
    if (action === "delete-model-connection") {
      const id = event.target.closest("[data-connection-id]").dataset.connectionId;
      const item = state.modelConnections.find(row => row.id === id);
      if (!confirm(`删除模型连接“${item?.display_name || id}”？使用它的数字人会改为继承默认连接。`)) return;
      await api(`/api/model-connections/${encodeURIComponent(id)}`, { method: "DELETE" });
      fillConnectionEditor();
      await loadModelConnections();
      toast("模型连接已删除");
    }
    if (action === "test-model-connection") {
      const result = await api("/api/model-connections/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...connectionPayload(), connection_id: $("#settingsDialog").dataset.editConnectionId || "" }) });
      $("#dialogModelResult").textContent = result.message;
      toast(result.ok ? "连接检查通过" : "连接检查未通过", !result.ok);
    }
    if (action === "save-model-connection") {
      await saveModelConnection($("#dialogModelResult"));
      toast("模型连接已保存，API Key 不会回显");
    }
    if (action === "edit-provider-connection") {
      const id = event.target.closest("[data-provider-id]").dataset.providerId;
      renderProviderEditor(state.providerHub.connections.find(item => item.id === id));
    }
    if (action === "delete-provider-connection") {
      const id = event.target.closest("[data-provider-id]").dataset.providerId;
      const item = state.providerHub.connections.find(row => row.id === id);
      if (!confirm(`删除服务连接“${item?.display_name || id}”？引用它的能力路由也会被清除。`)) return;
      await api(`/api/provider-connections/${encodeURIComponent(id)}`, { method: "DELETE" });
      $("#settingsDialog").dataset.editProviderId = "";
      await loadProviderHub(); toast("服务连接已删除");
    }
    if (action === "save-provider-connection") {
      const id = $("#settingsDialog").dataset.editProviderId || "";
      const result = await api(id ? `/api/provider-connections/${encodeURIComponent(id)}` : "/api/provider-connections", { method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(providerPayload()) });
      $("#providerApiKey").value = "";
      $("#settingsDialog").dataset.editProviderId = result.id;
      $("#providerResult").textContent = `服务已保存：${result.display_name}`;
      await loadProviderHub(); await loadHealth(); toast("服务已保存，API Key 不会回显");
    }
    if (action === "test-provider-connection") {
      let id = event.target.closest("[data-provider-id]")?.dataset.providerId || $("#settingsDialog").dataset.editProviderId || "";
      if (!id) {
        const created = await api("/api/provider-connections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(providerPayload()) });
        id = created.id; $("#settingsDialog").dataset.editProviderId = id; $("#providerApiKey").value = "";
      }
      const result = await api(`/api/provider-connections/${encodeURIComponent(id)}/test`, { method: "POST" });
      $("#providerResult").textContent = `${result.message}${result.models?.length ? `：${result.models.slice(0, 8).join("、")}` : ""}`;
      await loadProviderHub(); toast(result.ok ? "服务连接测试通过" : "服务连接测试未通过", !result.ok);
    }
    if (action === "save-capability-route") {
      const capability = event.target.closest("[data-capability]").dataset.capability;
      const primary = $(`[data-cap-route-primary="${capability}"]`).value;
      const fallback = $(`[data-cap-route-fallback="${capability}"]`).value;
      const scope = $("#capabilityRouteScope").value === "avatar" && state.currentId ? "avatar" : "global";
      await api("/api/capability-routes", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope_type: scope, avatar_id: scope === "avatar" ? state.currentId : "", capability, primary_connection_id: primary, fallback_connection_ids: fallback && fallback !== primary ? [fallback] : [], model: $(`[data-cap-route-model="${capability}"]`).value, config: {} }) });
      await loadProviderHub(); await loadHealth(); toast(`${providerCapabilityLabels[capability] || capability}路由已生效`);
    }
    if (action === "edit-ocr-connection") {
      const id = event.target.closest("[data-ocr-id]").dataset.ocrId;
      fillOcrEditor(state.ocrConnections.find(item => item.id === id));
    }
    if (action === "select-ocr-connection") {
      const id = event.target.closest("[data-ocr-id]").dataset.ocrId;
      await api(`/api/ocr-connections/${encodeURIComponent(id)}/select`, { method: "POST" });
      await loadOcrConnections();
      toast("默认 OCR 已切换");
    }
    if (action === "delete-ocr-connection") {
      const id = event.target.closest("[data-ocr-id]").dataset.ocrId;
      const item = state.ocrConnections.find(row => row.id === id);
      if (!confirm(`删除 OCR 连接“${item?.display_name || id}”？截图识别会回到自动检测/手动补文字。`)) return;
      await api(`/api/ocr-connections/${encodeURIComponent(id)}`, { method: "DELETE" });
      fillOcrEditor();
      await loadOcrConnections();
      toast("OCR 连接已删除");
    }
    if (action === "test-ocr-connection") {
      const result = await api("/api/ocr-connections/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...ocrPayload(), connection_id: $("#settingsDialog").dataset.editOcrId || "" }) });
      $("#ocrResult").textContent = result.message;
      toast(result.ok ? "OCR 配置检查通过" : "OCR 配置未通过", !result.ok);
    }
    if (action === "save-ocr-connection") {
      const id = $("#settingsDialog").dataset.editOcrId || "";
      const result = await api(id ? `/api/ocr-connections/${encodeURIComponent(id)}` : "/api/ocr-connections", {
        method: id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ocrPayload()),
      });
      $("#ocrApiKey").value = "";
      $("#ocrResult").textContent = `OCR 已保存：${result.display_name}`;
      await loadOcrConnections();
      toast("OCR 已保存，Key 不会回显");
    }
    if (action === "save-media-settings") {
      if ($("#dialogAliyunKey").value || $("#dialogNorthKey").value || $("#dialogMediaConsent").checked) await api("/api/settings/cloud-services", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        aliyun_api_key: $("#dialogAliyunKey").value,
        north_api_key: $("#dialogNorthKey").value,
        voice_clone_model: $("#dialogVoiceCloneModel").value,
        voice_target_model: $("#dialogVoiceTargetModel").value,
        voice_tts_model: $("#dialogVoiceTargetModel").value,
        image_reference_model: $("#dialogImageModel").value,
        north_api_url: $("#dialogNorthApiUrl").value,
        north_face_url: $("#dialogNorthFaceUrl").value,
        north_idle_timeout: Number($("#dialogNorthIdleTimeout").value),
        north_price_per_second: Number($("#dialogNorthPrice").value),
        video_call_enabled: $("#dialogVideoCallEnabled").checked,
        scene_background_enabled: $("#dialogVideoScene").checked,
        camera_flip_enabled: $("#dialogVideoFlip").checked,
        vision_feedback_enabled: $("#dialogVideoVision").checked,
        smart_interrupt_enabled: $("#dialogVideoInterrupt").checked,
        cloud_data_consent: $("#dialogMediaConsent").checked,
      }) });
      $("#dialogAliyunKey").value = "";
      $("#dialogNorthKey").value = "";
      toast("声音、形象与 North 视频通话设置已保存");
    }
    if (action === "refresh-video-call") {
      await loadVideoCallStatus();
      toast("实时视频状态已刷新");
    }
    if (action === "start-video-call") {
      await startVideoCall();
    }
    if (action === "listen-video-turn") listenVideoTurn();
    if (action === "send-video-turn") await sendVideoTurn();
    if (action === "toggle-call-camera") {
      const tracks = state.userMedia?.getVideoTracks() || [];
      state.callCameraEnabled = !state.callCameraEnabled;
      tracks.forEach(track => { track.enabled = state.callCameraEnabled; });
      const button = event.target.closest("button");
      button.textContent = state.callCameraEnabled ? "关闭摄像头" : "开启摄像头";
      button.setAttribute("aria-pressed", String(state.callCameraEnabled));
    }
    if (action === "toggle-call-microphone") {
      const tracks = state.userMedia?.getAudioTracks() || [];
      state.callMicrophoneEnabled = !state.callMicrophoneEnabled;
      tracks.forEach(track => { track.enabled = state.callMicrophoneEnabled; });
      const button = event.target.closest("button");
      button.textContent = state.callMicrophoneEnabled ? "静音" : "取消静音";
      button.setAttribute("aria-pressed", String(state.callMicrophoneEnabled));
    }
    if (action === "end-video-call") {
      if (!state.videoCall?.id) throw new Error("当前没有正在记录的视频通话");
      const ended = await api(`/api/avatars/${state.currentId}/calls/${state.videoCall.id}/end`, { method: "POST" });
      disconnectNorthLiveKit();
      state.videoCall = null;
      $("#videoCallStatus").textContent = "实时视频通话已结束，North session 已请求释放。";
      $("#videoCallDetails").innerHTML = `<span>${escapeHtml(ended.summary || "通话已结束")}</span>`;
      toast("视频通话已结束");
    }
    if (action === "prepare-video-background") {
      const result = await api(`/api/avatars/${state.currentId}/video-call/prepare-background`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "scene", prompt: "" }) });
      $("#videoCallDetails").innerHTML = `<span>背景协议已准备</span><small>${escapeHtml(result.rule || result.reason || "")}</small>`;
      toast(result.ok ? "通话背景已准备" : "通话背景不可用", !result.ok);
    }
    if (action === "prepare-video-flip") {
      const result = await api(`/api/avatars/${state.currentId}/video-call/flip-video`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "flipped", prompt: "" }) });
      $("#videoCallDetails").innerHTML = `<span>翻转镜头任务：${escapeHtml(result.taskId || "")}</span><small>${escapeHtml(result.note || result.reason || "")}</small>`;
      toast(result.ok ? "翻转镜头任务已记录" : "翻转镜头不可用", !result.ok);
    }
    if (action === "save-proactive") {
      state.current = await api(`/api/avatars/${state.currentId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proactive_enabled: $("#proactiveToggle").checked, proactive_interval_minutes: Number($("#proactiveInterval").value) }) });
      await api(`/api/avatars/${state.currentId}/proactive-rules`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        daily_max: Number($("#proactiveDailyMax").value),
        allowed_windows: parseWindows($("#proactiveWindows").value),
        quiet_hours: parseQuiet($("#proactiveQuiet").value),
        topic_scope: String($("#proactiveTopics").value || "").split(",").map(item => item.trim()).filter(Boolean),
        use_long_term_memory: $("#proactiveUseMemory").checked,
        allow_world_event_advancement: $("#proactiveAdvanceWorld").checked,
        tone: $("#proactiveTone").value,
        cooldown_after_user_reply_minutes: Number($("#proactiveCooldown").value),
      }) });
      if (state.current.proactive_enabled && "Notification" in window && Notification.permission === "default") {
        await Notification.requestPermission();
      }
      toast(state.current.proactive_enabled ? "主动联系已开启，将调用当前模型" : "主动联系已关闭");
    }
    if (action === "save-avatar-model-settings") {
      const useConnection = $("#avatarModelMode").value === "connection";
      const connection = state.modelConnections.find(item => item.id === $("#avatarConnectionSelect").value);
      await api(`/api/avatars/${state.currentId}/settings/model`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        mode: useConnection ? (connection?.connection_type === "cloud_openai" ? "cloud" : "local") : "inherit",
        connection_id: useConnection ? $("#avatarConnectionSelect").value : "",
      }) });
      await loadAvatarModelSettings();
      await loadHealth();
      toast("这个数字人的模型设置已保存");
    }
    if (action === "export-avatar") $("#packageExportDialog").showModal();
    if (action === "cancel-package-export") $("#packageExportDialog").close();
    if (action === "confirm-package-export") {
      const query = new URLSearchParams({
        include_conversations: $("#exportConversations").checked,
        include_audio: $("#exportAudio").checked,
        include_images: $("#exportImages").checked,
        include_video: $("#exportVideo").checked,
        include_call_history: $("#exportCalls").checked,
      });
      const response = await fetch(`/api/avatars/${state.currentId}/export?${query}`, { method: "POST" });
      if (!response.ok) throw new Error("导出失败");
      const blob = await response.blob(); const link = document.createElement("a");
      link.href = URL.createObjectURL(blob); link.download = `${state.current.name}.openavatar.zip`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 10000);
      $("#packageExportDialog").close();
      toast(ui("人物包已导出；专用 API Key 字段未导出。分享前请检查聊天、图片等内容是否含私人信息。", "Package exported without dedicated API key fields. Check conversations, images and other content for private information before sharing."));
    }
    if (action === "delete-avatar") {
      const confirmation = prompt(ui(`将删除“${state.current.name}”在当前数据目录中的人物记录和素材。已导出文件、历史备份、其他数据目录、云端副本和服务凭据不会删除。请输入人物名称确认：`, `Delete the records and assets for “${state.current.name}” in the current data directory? Exports, backups, other data directories, cloud copies and service credentials will remain. Enter the avatar name to confirm:`));
      if (confirmation === null) return;
      await api(`/api/avatars/${state.currentId}?confirmation=${encodeURIComponent(confirmation)}`, { method: "DELETE" });
      state.currentId = null; await loadAvatars(); showView("#homeView"); toast(ui("当前人物记录与素材已删除；备份、导出及其他副本仍保留。", "Current avatar records and assets deleted; backups, exports and other copies remain."));
    }
  } catch (error) { toast(error.message, true); }
});

$("#identityForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    let customRegion = {};
    const customRaw = String(form.get("world_region_custom") || "").trim();
    if (customRaw) customRegion = JSON.parse(customRaw);
    const payload = {
      name: form.get("name"),
      purpose: form.get("purpose"),
      relationship: form.get("relationship"),
      subject_kind: form.get("subject_kind"),
      adult_subject: form.has("adult_subject"),
      consent_confirmed: form.has("consent_confirmed"),
      avatar_primary_language: form.get("avatar_primary_language") || "zh-CN",
      avatar_response_mode: form.get("avatar_response_mode") || "follow_user",
      world_region: form.get("world_region") || "mainland_china",
      world_type: form.get("world_type") || "realistic",
      world_region_custom: customRegion,
    };
    const avatar = await api("/api/avatars", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    state.currentId = avatar.id; state.current = avatar; goStep(2);
    if (state.creationMode === "fictional") await loadGuidedBuilder();
  } catch (error) {
    toast(error instanceof SyntaxError ? "自定义世界规则需要是 JSON 格式" : error.message, true);
  }
});

$$('.upload-card input[type="file"]').forEach(input => input.addEventListener("change", async event => {
  if (!state.currentId) return;
  for (const file of event.target.files) {
    const row = document.createElement("div"); row.className = "upload-item"; row.innerHTML = `<span>${escapeHtml(file.name)}</span><span class="upload-status">正在本地处理…</span>`; $("#uploadList").prepend(row);
    try {
      const result = await api(`/api/avatars/${state.currentId}/imports?category=${encodeURIComponent(event.target.dataset.category)}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) }, body: file });
      row.dataset.uploadImport = result.id; row.querySelector(".upload-status").textContent = result.note;
      if (result.status === "needs_review") row.insertAdjacentHTML("beforeend", `<button type="button" class="secondary" data-action="review-import" data-import-id="${result.id}">检查内容</button>`);
      state.current = await api(`/api/avatars/${state.currentId}`);
      renderProfile();
    }
    catch (error) { row.lastElementChild.textContent = error.message; row.lastElementChild.classList.add("upload-error"); }
  }
  event.target.value = "";
}));

$("#personaForm").addEventListener("submit", async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const payload = { summary: form.get("summary"), traits: String(form.get("traits")).split("\n").map(item => item.trim()).filter(Boolean), speaking_style: form.get("speaking_style"), boundaries: form.get("boundaries") };
  try { await api(`/api/avatars/${state.currentId}/persona`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); goStep(5); }
  catch (error) { toast(error.message, true); }
});

$("#modelForm").addEventListener("submit", async event => {
  event.preventDefault();
  const connectionId = $("#wizardConnectionSelect").value;
  try {
    if (!connectionId) throw new Error("请先新建一个模型连接");
    const connection = state.modelConnections.find(item => item.id === connectionId);
    await saveCurrentAvatarModelSettings({ mode: connection?.connection_type === "cloud_openai" ? "cloud" : "local", connection_id: connectionId }, $("#modelTestResult"));
    const result = await api(`/api/avatars/${state.currentId}/analyze`, { method: "POST" });
    $("#personaForm [name=summary]").value = result.summary || "";
    $("#personaForm [name=traits]").value = (result.traits || []).join("\n");
    $("#personaForm [name=speaking_style]").value = result.speaking_style || "";
    $("#personaForm [name=boundaries]").value = result.boundaries || "";
    $("#analysisMethod").textContent = result.method === "local_heuristic" ? "模型尚未就绪，已使用离线规则生成初步档案；可以修改后继续。" : `已使用当前模型连接分析，请检查后再保存。`;
    goStep(4);
  }
  catch (error) { toast(error.message, true); }
});

$("#wizardConnectionSelect").addEventListener("change", event => renderConnectionHint("#wizardConnectionHint", event.target.value));
$("#avatarConnectionSelect").addEventListener("change", event => renderConnectionHint("#avatarConnectionHint", event.target.value));
$("#connectionType").addEventListener("change", updateConnectionEditorHints);
$("#ocrType").addEventListener("change", updateOcrHints);
$("#providerKind").addEventListener("change", () => { $("#settingsDialog").dataset.editProviderId = ""; renderProviderEditor(); });
$("#capabilityRouteScope").addEventListener("change", renderCapabilityRoutes);

$("#worldModuleSelector").addEventListener("change", async event => {
  const input = event.target.closest("[data-module-key]");
  if (!input || !state.currentId) return;
  $("#guidedAnswer").disabled = true;
  try {
    state.guided = await api(`/api/avatars/${state.currentId}/guided-builder/modules/${encodeURIComponent(input.dataset.moduleKey)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: input.checked }),
    });
    state.guidedIndex = 0;
    renderGuidedBuilder();
    toast(input.checked ? "已启用这个里世界模块" : "已暂时跳过这个模块");
  } catch (error) {
    input.checked = !input.checked;
    $("#guidedAnswer").disabled = false;
    toast(error.message, true);
  }
});

$("#packageInput").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    state.pendingPackageFile = file;
    const info = await api("/api/packages/inspect", { method: "POST", headers: { "Content-Type": "application/zip", "X-File-Name": encodeURIComponent(file.name) }, body: file });
    renderPackagePreview(info);
    $("#packageDialog").showModal();
  } catch (error) { toast(error.message, true); }
});

async function handleHashAction() {
  const hash = window.location.hash.replace("#", "");
  if (!hash) return;
  try {
    if (hash === "capabilities") await openCapabilities();
    if (hash === "diagnostics") await openDiagnostics();
    if (hash === "settings") await openSettings();
    window.history.replaceState(null, "", window.location.pathname);
  } catch (error) {
    toast(error.message, true);
  }
}

window.addEventListener("hashchange", handleHashAction);
window.addEventListener("pagehide", () => {
  if (state.videoCall?.id && state.currentId && navigator.sendBeacon) {
    navigator.sendBeacon(`/api/avatars/${state.currentId}/calls/${state.videoCall.id}/end`);
  }
  disconnectNorthLiveKit();
});
showFilePreviewNotice();
if (!isFilePreview) {
  (async function boot() {
    try {
      await loadI18n();
      await loadWorldOptions();
      await loadHealth();
      await loadAvatars();
      await loadOnboarding();
      await handleHashAction();
      window.setInterval(() => pollProactiveMessages().catch(() => null), 30000);
      window.setInterval(() => pollNotifications().catch(() => null), 15000);
    } catch (error) {
      toast(error.message, true);
    }
  })();
}
