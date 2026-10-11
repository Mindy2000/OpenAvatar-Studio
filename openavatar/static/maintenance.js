async function openMaintenance() {
  const avatarId = state.currentId;
  const base = `/api/avatars/${avatarId}`;
  const [memories, revisions, world, backups] = await Promise.all([api(`${base}/memories?limit=500`), api(`${base}/memory-revisions`), api(`${base}/world`), api('/api/system/backups')]);
  if (state.currentId !== avatarId) return;
  state.maintenanceMemories = {avatarId, items: memories};
  const mergeable = memories.filter(m => !["merged_duplicate", "rejected"].includes(m.kind));
  const options = mergeable.map(m => `<option value="${m.id}">#${m.id} · ${escapeHtml(m.content.slice(0, 80))}</option>`).join("");
  const button = (action, label, attrs = '') => `<button type="button" class="secondary" data-action="maintenance-${action}" ${attrs}>${escapeHtml(label)}</button>`;
  $('#maintenanceContent').innerHTML = `<h2>${ui('数据维护', 'Data maintenance')}</h2>
    <h3>${ui('记忆编辑', 'Edit memories')}</h3><p>${ui('修改记忆不会改写导入的原始文件。', 'Editing memories does not rewrite imported source files.')}</p>
    ${memories.map(m => `<article class="approval-item"><b>${escapeHtml(m.speaker)} · #${m.id}</b><p>${escapeHtml(m.content)}</p>${button('edit-memory',ui('修改记忆','Edit memory'),`data-id="${m.id}"`)}${button('review-memory',ui('批准记忆','Approve memory'),`data-id="${m.id}"`)}</article>`).join('') || `<p>${ui('暂无记忆','No memories')}</p>`}
    <h3>${ui('合并重复记忆', 'Merge duplicate memories')}</h3>
    <p>${ui('选择要保留的记忆和重复记忆。两段内容会合并保留，重复项退出正常使用，原始资料不变。', 'Choose the memory to keep and its duplicate. Both texts are retained in the kept memory; the duplicate is retired and source files remain unchanged.')}</p>
    ${mergeable.length > 1 ? `<label>${ui('保留记忆','Keep memory')}<select id="memoryMergePrimary">${options}</select></label><label>${ui('重复记忆','Duplicate memory')}<select id="memoryMergeDuplicate">${options}</select></label>${button('merge',ui('检查并合并','Review and merge'))}` : `<p>${ui('至少需要两条可用记忆。','At least two active memories are required.')}</p>`}
    <h3>${ui('记忆修订记录', 'Memory revision history')}</h3>
    <p>${ui('显示最近100条修订，包括修改前后内容和合并记录。','Shows the latest 100 revisions, including before/after content and merges.')}</p>
    <div id="memoryRevisionList">${revisions.map(r => `<details class="approval-item"><summary>#${r.memory_id} · ${escapeHtml(({edit:ui('修改','Edit'),approve:ui('批准','Approve'),downgrade:ui('降权','Downgrade'),reject:ui('拒绝','Reject'),merge:ui('合并','Merge'),merged_duplicate:ui('标记重复','Retire duplicate')})[r.action] || r.action)} · ${escapeHtml(new Date(r.created_at * 1000).toLocaleString())}</summary><b>${ui('修改前','Before')}</b><p style="white-space:pre-wrap">${escapeHtml(r.before?.content || '')}</p><b>${ui('修改后','After')}</b><p style="white-space:pre-wrap">${escapeHtml(r.after?.content || '')}</p><small>${escapeHtml(r.note || '')}</small></details>`).join('') || `<p>${ui('暂无修订记录','No revisions yet')}</p>`}</div>
    <h3>${ui('世界冲突', 'World conflicts')}</h3>${button('scan',ui('检查世界冲突','Check world conflicts'))}
    ${(world.runtime?.conflicts || []).filter(c => c.status === 'open').map(c => `<article class="approval-item"><b>${escapeHtml(c.fact_key)}</b><p>${escapeHtml(c.reason)}</p><p>${ui('现有值','Existing')}: ${escapeHtml(c.existing_value_json || '')}</p><p>${ui('候选值','Candidate')}: ${escapeHtml(c.candidate_value_json || '')}</p>${button('conflict',ui('保留现有值','Keep existing'),`data-id="${c.id}" data-choice="keep_existing"`)}${button('conflict',ui('候选值送审','Propose candidate'),`data-id="${c.id}" data-choice="accept_candidate"`)}${button('conflict',ui('忽略冲突','Dismiss conflict'),`data-id="${c.id}" data-choice="dismiss"`)}</article>`).join('') || `<p>${ui('没有待处理的世界冲突','No open world conflicts')}</p>`}
    <h3>${ui('数据库备份与恢复', 'Database backup and restore')}</h3><p>${ui('范围是当前数据目录的全部人物。恢复会覆盖当前数据库，恢复前自动创建安全备份；素材文件和系统凭据不由数据库恢复替换。','Applies to all avatars in this data directory. Restoring replaces the database and first creates a safety backup; media files and system credentials are not replaced.')}</p>
    ${button('backup',ui('创建数据库备份','Create database backup'))}
    ${backups.items.map(b => `<article class="approval-item"><b>${escapeHtml(b.filename)}</b><small>${b.size_bytes} bytes</small>${button('restore',ui('恢复此备份','Restore this backup'),`data-file="${escapeHtml(b.filename)}"`)}</article>`).join('')}`;
  if (!$('#maintenanceDialog').open) $('#maintenanceDialog').showModal();
}
async function handleMaintenance(action, node) {
  const base = `/api/avatars/${state.currentId}`;
  const post = (path, payload = {}) => api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  if (action === 'open-maintenance') return openMaintenance();
  if (action === 'maintenance-edit-memory') {
    const rows = state.maintenanceMemories?.avatarId === state.currentId ? state.maintenanceMemories.items : [];
    const item = rows.find(m => String(m.id) === node.dataset.id);
    if (!item) throw new Error(ui('记忆已不存在，请刷新。','Memory no longer exists; refresh.'));
    const content = prompt(ui('修改记忆内容','Edit memory content'),item.content); if (content === null) return;
    await api(`${base}/memories/${item.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,note:'Manual memory edit'})});
  }
  if (action === 'maintenance-merge') {
    const primaryId = Number($('#memoryMergePrimary').value), duplicateId = Number($('#memoryMergeDuplicate').value);
    if (primaryId === duplicateId) throw new Error(ui('请选择两条不同的记忆。','Choose two different memories.'));
    const rows = await api(`${base}/memories?limit=500`);
    const primary = rows.find(m => m.id === primaryId), duplicate = rows.find(m => m.id === duplicateId);
    if (!primary || !duplicate) throw new Error(ui('记忆已变化，请刷新。','Memories changed; refresh.'));
    if (!confirm(`${ui('将合并以下两条记忆，重复项退出正常使用：','Merge these memories and retire the duplicate:')}\n\n#${primaryId}: ${primary.content}\n\n#${duplicateId}: ${duplicate.content}`)) return;
    node.disabled = true;
    try { await post(`${base}/memories/merge`, {primary_id: primaryId, duplicate_id: duplicateId}); }
    finally { node.disabled = false; }
  }
  if (action === 'maintenance-review-memory') await post(`${base}/memories/${node.dataset.id}/review`,{action:'approve'});
  if (action === 'maintenance-scan') await post(`${base}/world/consistency`);
  if (action === 'maintenance-conflict') await post(`${base}/world/conflicts/${node.dataset.id}/review`,{action:node.dataset.choice});
  if (action === 'maintenance-backup') await post('/api/system/backup');
  if (action === 'maintenance-restore') {
    const confirmation = prompt(ui('将恢复整个数据库。请输入 RESTORE OPENAVATAR DATABASE 确认：','Restore the entire database. Type RESTORE OPENAVATAR DATABASE to confirm:')); if (confirmation === null) return;
    await post(`/api/system/backups/${encodeURIComponent(node.dataset.file)}/restore?confirmation=${encodeURIComponent(confirmation)}`);
    $('#maintenanceDialog').close(); state.currentId=null; state.current=null; await loadAvatars(); showView('#homeView'); toast(ui('数据库已恢复，恢复前安全备份已保存。','Database restored; a safety backup was saved.')); return;
  }
  return openMaintenance();
}
