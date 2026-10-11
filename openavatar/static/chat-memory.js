/* User-confirmed notes; opening or saving this dialog never calls a model. */
let chatMemoryDraft = null;

function renderChatMemoryAction(row) {
  if (!['text', 'audio'].includes(row.message_kind || 'text') || !['user', 'assistant'].includes(row.role)) return '';
  if (row.message_kind === 'audio' && row.content.startsWith('[语音]')) return '';
  const label = row.remembered ? ui('已记住', 'Remembered') : row.context_excluded ? ui('已停用', 'Not used') : ui('记忆', 'Memory');
  return `<button type="button" data-chat-memory="${Number(row.id)}" title="${ui('记住、纠正或不再使用', 'Remember, correct, or stop using')}">${label}</button>`;
}

function chatMemoryDialog() {
  let dialog = $('#chatMemoryDialog');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'chatMemoryDialog'; dialog.className = 'chat-attachment-dialog';
    document.body.append(dialog);
    dialog.addEventListener('close', () => { chatMemoryDraft = null; });
  }
  return dialog;
}

function renderChatMemoryDialog() {
  const draft = chatMemoryDraft; if (!draft) return;
  const dialog = chatMemoryDialog();
  const saved = draft.info.remembered;
  dialog.innerHTML = `<form id="chatMemoryForm">
    <div class="chat-dialog-heading"><h2>${ui('这条消息的记忆', 'Memory for this message')}</h2><button type="button" data-memory-close aria-label="${ui('关闭', 'Close')}">×</button></div>
    <p class="chat-dialog-note">${ui('只在你确认后保存，不会调用模型。原消息会保留。', 'Saved only after your confirmation, without a model call. The original message remains.')}</p>
    <details><summary>${ui('查看原消息', 'View original message')}</summary><p class="memory-original">${escapeHtml(draft.info.original_content)}</p></details>
    <p>${saved ? ui('当前已记住；可以纠正或停用。', 'Remembered. You can correct it or stop using it.') : draft.info.context_excluded ? ui('原消息已从后续对话上下文停用。', 'The original message is excluded from future conversation context.') : ui('还没有将这条消息保存为记忆。', 'This message has not been saved as a memory.')}</p>
    ${draft.info.merged_dependents ? `<p class="chat-dialog-note">${ui('此条曾被合并进其它记忆。修改或停用时，包含它的合并记忆也会停用；原聊天均会保留。', 'This note was merged into other memories. Changing or stopping it also deactivates those merged memories; original chats remain.')}</p>` : ''}
    <label>${ui('希望记住的内容', 'What to remember')}<textarea id="chatMemoryContent" rows="4" maxlength="1000">${escapeHtml(draft.text)}</textarea></label>
    <p class="chat-dialog-note">${ui('纠正或停用会排除原消息及同轮回复的上下文。不会删除聊天记录、独立保存的其它资料，或收回已发送的请求。', 'Correcting or stopping use excludes the original message and its same-turn reply from context. This does not delete chat history or separately saved material, or recall requests already sent.')}</p>
    <div id="chatMemoryError" role="alert" class="chat-inline-error"></div>
    <div class="chat-dialog-actions memory-actions">
      <button type="button" class="secondary" data-memory-save="forget">${ui('以后别再使用', 'Stop using this')}</button>
      <button type="button" class="secondary" data-memory-save="correct">${ui('纠正并记住', 'Correct and remember')}</button>
      <button type="submit" class="chat-send">${saved ? ui('保存记忆', 'Save memory') : ui('记住这条', 'Remember this')}</button>
    </div></form>`;
  $('#chatMemoryContent').oninput = event => { if (chatMemoryDraft === draft) draft.text = event.target.value; };
  dialog.querySelector('[data-memory-close]').onclick = () => dialog.close();
  $('#chatMemoryForm').onsubmit = event => { event.preventDefault(); saveChatMemory(saved ? 'correct' : 'remember'); };
  dialog.querySelectorAll('[data-memory-save]').forEach(button => { button.onclick = () => saveChatMemory(button.dataset.memorySave); });
}

async function openChatMemory(messageId) {
  const avatarId = state.currentId, preview = !!state.previewMode;
  const info = await api(`/api/avatars/${avatarId}/messages/${messageId}/memory?preview_mode=${preview}`);
  if (state.currentId !== avatarId || !!state.previewMode !== preview) return;
  chatMemoryDraft = {avatarId, messageId, preview, info, text: info.remembered ? info.memory.content : info.original_content};
  renderChatMemoryDialog(); chatMemoryDialog().showModal();
}

async function saveChatMemory(action) {
  const draft = chatMemoryDraft; if (!draft || state.currentId !== draft.avatarId || !!state.previewMode !== draft.preview) return;
  const dialog = chatMemoryDialog(), buttons = dialog.querySelectorAll('button');
  buttons.forEach(button => { button.disabled = true; });
  try {
    if (action !== 'forget' && !draft.text.trim()) throw new Error(ui('请填写要记住的内容', 'Enter what to remember'));
    await api(`/api/avatars/${draft.avatarId}/messages/${draft.messageId}/memory`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({action, content: draft.text.trim(), confirmed: true, preview_mode: draft.preview}),
    });
    dialog.close();
    if (state.currentId === draft.avatarId) await loadMessages();
    toast(action === 'forget' ? ui('已停用这条消息的记忆与上下文', 'Memory and context use stopped for this message') : ui('已保存你确认的记忆', 'Your confirmed memory was saved'));
  } catch (error) { $('#chatMemoryError').textContent = error.message; }
  finally { buttons.forEach(button => { button.disabled = false; }); }
}

function refreshChatMemoryLanguage() {
  if ($('#chatMemoryDialog')?.open) renderChatMemoryDialog();
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-chat-memory]');
  if (button) openChatMemory(Number(button.dataset.chatMemory)).catch(error => toast(error.message, true));
});
