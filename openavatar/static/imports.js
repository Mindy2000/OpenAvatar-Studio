async function openImportReview(importId) {
  const preview = await api(`/api/avatars/${state.currentId}/imports/${importId}/preview`);
  state.currentImport = { id: importId, preview };
  renderImportReview();
  $("#reviewDialog").showModal();
}

function renderImportReview() {
  const { preview } = state.currentImport;
  const fictional = preview.import.category === "fictional";
  $("#reviewDialogTitle").textContent = fictional ? tr("预览并确认角色设定") : tr("确认说话人与内容");
  $("#reviewDialogLead").textContent = fictional ? tr("文件尚未写入人物档案。检查解析结果，并选择合并或覆盖后再确认。") : tr("选择哪些名字代表数字人原型，并取消勾选不希望用于人格与记忆的内容。");
  $("#fictionalApplyModeLabel").classList.toggle("hidden", !fictional);
  $("#speakerChoices").classList.toggle("hidden", fictional);
  $("#speakerChoices").innerHTML = preview.speakers.map((item, index) => `<label class="speaker-choice"><input type="checkbox" value="${escapeHtml(item.speaker)}" ${index === 0 && item.speaker ? "checked" : ""}><span>${escapeHtml(item.speaker || tr("未标记说话人"))} · ${item.count}</span></label>`).join("") || tr("<small>没有识别到明确的说话人，可直接检查内容。</small>");
  $("#reviewRows").innerHTML = preview.rows.map(row => `<label class="review-row"><input type="checkbox" data-row-id="${row.id}" checked><b>${escapeHtml(row.speaker || tr("未知"))}</b><span>${escapeHtml(row.content)}</span></label>`).join("");
  $("#reviewCount").textContent = tr`共 ${preview.total} 条${preview.truncated ? tr("，当前显示前部分") : ""}`;
}
