async function openImportReview(importId) {
  const avatarId = state.currentId;
  let preview = await api(`/api/avatars/${avatarId}/imports/${importId}/preview`);
  // Manual image text is saved as a whole, so show every supported OCR row together.
  if (preview.import.category === 'image' && preview.total > preview.rows.length) preview = await api(`/api/avatars/${avatarId}/imports/${importId}/preview?limit=2000`);
  if (state.currentId !== avatarId) return;
  state.currentImport = { id: importId, avatarId, preview, reviewed: new Set(), excluded: new Set(), speakers: null };
  renderImportReview();
  $("#reviewDialog").showModal();
}

function saveImportReviewSelection() {
  const current = state.currentImport;
  for (const node of $$('#reviewRows input[data-row-id]')) {
    const id = Number(node.dataset.rowId);
    current.reviewed.add(id);
    if (node.checked) current.excluded.delete(id); else current.excluded.add(id);
  }
  current.speakers = $$('#speakerChoices input:checked').map(node => node.value);
}

async function changeImportReviewPage(offset) {
  const current = state.currentImport;
  saveImportReviewSelection();
  const preview = await api(`/api/avatars/${current.avatarId}/imports/${current.id}/preview?offset=${offset}`);
  if (state.currentImport !== current || state.currentId !== current.avatarId) return;
  current.preview = preview;
  renderImportReview();
}

async function saveImportImageText() {
  const current = state.currentImport;
  if (!current || current.avatarId !== state.currentId) return;
  const text = $('#manualImageText').value;
  let preview = await api(`/api/avatars/${current.avatarId}/imports/${current.id}/text`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text})});
  if (state.currentImport !== current || state.currentId !== current.avatarId) return;
  if (preview.total > preview.rows.length) preview = await api(`/api/avatars/${current.avatarId}/imports/${current.id}/preview?limit=2000`);
  if (state.currentImport !== current || state.currentId !== current.avatarId) return;
  current.preview = preview;
  current.reviewed = new Set(); current.excluded = new Set();
  renderImportReview();
}

function renderImportReview() {
  const { preview } = state.currentImport;
  const current = state.currentImport;
  preview.rows.forEach(row => current.reviewed.add(row.id));
  const fictional = preview.import.category === "fictional";
  const editableImage = preview.import.category === "image" && preview.import.status !== "confirmed";
  $('[data-action="confirm-import"]').disabled = editableImage && preview.total === 0;
  $("#manualImageTextPanel").classList.toggle("hidden", !editableImage);
  $("#manualImageTextPanel").innerHTML = editableImage ? `<label>${ui("补录或校正图片文字", "Add or correct image text")}<textarea id="manualImageText" rows="5">${escapeHtml(preview.rows.map(row => row.content).join("\n"))}</textarea></label><button type="button" class="secondary" data-action="save-image-text">${ui("保存图片文字", "Save image text")}</button>` : "";
  $("#reviewDialogTitle").textContent = fictional ? tr("预览并确认角色设定") : tr("确认说话人与内容");
  $("#reviewDialogLead").textContent = fictional ? tr("文件尚未写入人物档案。检查解析结果，并选择合并或覆盖后再确认。") : tr("选择哪些名字代表数字人原型，并取消勾选不希望用于人格与记忆的内容。");
  $("#fictionalApplyModeLabel").classList.toggle("hidden", !fictional);
  $("#speakerChoices").classList.toggle("hidden", fictional);
  $("#speakerChoices").innerHTML = preview.speakers.map((item, index) => `<label class="speaker-choice"><input type="checkbox" value="${escapeHtml(item.speaker)}" ${(current.speakers ? current.speakers.includes(item.speaker) : index === 0 && item.speaker) ? "checked" : ""}><span>${escapeHtml(item.speaker || tr("未标记说话人"))} · ${item.count}</span></label>`).join("") || tr("<small>没有识别到明确的说话人，可直接检查内容。</small>");
  $("#reviewRows").innerHTML = preview.rows.map(row => `<label class="review-row"><input type="checkbox" data-row-id="${row.id}" ${current.excluded.has(row.id) ? '' : 'checked'}><b>${escapeHtml(row.speaker || tr("未知"))}</b><span>${escapeHtml(row.content)}</span></label>`).join("");
  $("#reviewCount").textContent = ui(`共 ${preview.total} 条，已查看 ${current.reviewed.size} 条；仅确认已查看且勾选的内容。`, `${preview.total} rows; ${current.reviewed.size} reviewed. Only reviewed, selected rows will be imported.`);
  if (!editableImage && preview.total > preview.limit) {
    for (const [label, offset, disabled] of [[ui('上一页','Previous'), Math.max(0, preview.offset - preview.limit), preview.offset === 0], [ui('下一页','Next'), preview.offset + preview.limit, !preview.truncated]]) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = label; button.disabled = disabled;
      button.addEventListener('click', () => changeImportReviewPage(offset).catch(error => toast(error.message)));
      $('#reviewCount').append(' ', button);
    }
  }
}
