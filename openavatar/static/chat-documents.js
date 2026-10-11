/* Explicit file questions: uploads and ordinary chat never implicitly read a file. */
function renderChatDocumentControls(row) {
  if (row.role !== 'user' || row.message_kind !== 'file') return '';
  const supported = /\.(txt|md|csv|pdf)$/i.test(row.attachment?.name || '');
  if (!supported) return `<small>${ui('此格式仅供下载；可阅读 TXT、MD、CSV、PDF。','Download only; reading supports TXT, MD, CSV and PDF.')}</small>`;
  const read = ['done', 'read'].includes(row.attachment?.document?.status);
  return `<div><button type="button" class="secondary" data-read-document="${Number(row.id)}">${read ? ui('继续问此文件','Ask about this file') : ui('阅读此文件','Read this file')}</button></div>`;
}
function renderChatDocumentSource(row) {
  const source = row.attachment?.document_source;
  if (!source || !Number.isSafeInteger(source.message_id) || source.message_id <= 0) return '';
  return `<div><button type="button" class="secondary" data-read-document="${source.message_id}">${ui('文件来源：','File source: ')}${escapeHtml(source.name || '')}</button></div>`;
}

const chatDocumentErrors = {
  document_unsupported: 'Only TXT, MD, CSV and PDFs with a text layer are supported.',
  document_missing: 'This file is missing or does not belong to this avatar.',
  document_too_large: 'Reading limit: 2 MB for text files and 10 MB for PDFs. Split the file and try again.',
  document_too_many_pages: 'This PDF exceeds the 20-page limit. Nothing was sent to the chat service. Split the file first.',
  document_too_many_characters: 'The text exceeds 20,000 characters. Nothing was sent to the chat service. Split the file first.',
  document_encrypted: 'This PDF is encrypted. Provide an unencrypted copy you are entitled to use.',
  document_no_text: 'No readable text was found. Scanned or image-only PDFs need OCR first. No cloud service was called.',
  document_invalid_text: 'Unsupported text encoding or binary content. Save the file as UTF-8 text and try again.',
  document_invalid_pdf: 'The PDF is damaged or its text layer cannot be read. Check the file and try again.',
  document_pdf_limit: 'PDF parsing reached its resource limit. Nothing was sent to the chat service. Simplify or split the file.',
  document_pdf_timeout: 'PDF parsing timed out and was stopped. Nothing was sent to the chat service. Split the file first.',
  document_consent: 'Confirm that extracted text may be sent to the current chat service and may incur charges.',
  document_busy: 'Another file question is being processed. Please wait; there is no automatic retry.',
  document_request_reused: 'This request ID was used for another question or file version. Confirm and send again.',
  document_already_attempted: 'This request already completed or failed. No new call was made. To retry, confirm and send again.',
  document_conversation_changed: 'This file or conversation was edited, rewound or stopped. The reply was not added to chat; a service call that already started may still incur charges. Select the file again.',
  document_provider_failed: 'The file question failed. No retry or provider switch was made. Check the connection, then confirm and try again.'
};
let chatDocumentDialog = null;
let activeChatDocument = null;
async function chatDocumentRequest(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'object' && detail?.code ? ui(detail.message, chatDocumentErrors[detail.code] || detail.message) : tr(typeof detail === 'string' ? detail : ui('文件提问失败','File question failed'));
    const error = new Error(message); error.documentDetail = detail; throw error;
  }
  return body;
}
function makeChatDocumentDialog() {
  if (chatDocumentDialog) chatDocumentDialog.remove();
  const dialog = document.createElement('dialog');
  dialog.id = 'chatDocumentDialog';
  dialog.className = 'chat-attachment-dialog';
  dialog.innerHTML = `<form id="chatDocumentForm">
    <div class="chat-dialog-heading"><h2 id="chatDocumentTitle"></h2><button type="button" id="closeChatDocument" aria-label="${ui('关闭','Close')}">×</button></div>
    <p id="chatDocumentScope" class="chat-dialog-note">${ui('仅阅读所选文件的文字。上传不会自动分析；普通聊天不会自动附带此文件。后续请在此窗口明确提问。','Only text from the selected file is read. Uploading does not analyze it, and ordinary chat does not automatically include it. Ask follow-up questions here explicitly.')}</p>
    <p id="chatDocumentLimits" class="chat-dialog-note">${ui('支持 TXT、MD、CSV 和有文本层的 PDF。最多 20,000 字符；文本 2 MB，PDF 10 MB／20 页。PDF 图片不会识别。','Supports TXT, MD, CSV and PDFs with a text layer. Up to 20,000 characters; text files up to 2 MB, PDFs up to 10 MB / 20 pages. Images in PDFs are not recognized.')}</p>
    <label><span id="chatDocumentQuestionLabel">${ui('关于此文件的问题（留空则概括）','Question about this file (leave blank for a summary)')}</span><textarea id="chatDocumentQuestion" maxlength="1000" rows="3"></textarea></label>
    <label><input id="chatDocumentConsent" type="checkbox" required> <span id="chatDocumentConsentLabel">${ui('同意将提取的文件文本、问题及当前对话上下文发给当前对话服务，可能产生费用。每次回复最多80字。','I agree to send extracted text, my question and current conversation context to the current chat service. Charges may apply. Replies are limited to 80 characters.')}</span></label>
    <p id="chatDocumentError" class="chat-inline-error" role="alert"></p>
    <div id="chatDocumentResult" role="status"></div>
    <div class="chat-dialog-actions"><button type="button" id="cancelChatDocument">${ui('关闭','Close')}</button><button type="submit" id="sendChatDocument" class="chat-send">${ui('确认阅读并提问','Confirm and ask')}</button></div>
  </form>`;
  document.body.append(dialog);
  chatDocumentDialog = dialog;
  dialog.querySelector('#closeChatDocument').onclick = () => dialog.close();
  dialog.querySelector('#cancelChatDocument').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { activeChatDocument = null; });
  dialog.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault();
    const selected = activeChatDocument;
    if (!selected || selected.busy) return;
    const error = dialog.querySelector('#chatDocumentError');
    if (state.currentId !== selected.avatarId || !!state.previewMode !== selected.preview) {
      error.textContent = ui('人物或时间线已切换，请关闭后重新选择文件。','The avatar or timeline changed. Close this window and select the file again.');
      return;
    }
    const consent = dialog.querySelector('#chatDocumentConsent');
    if (!consent.checked) return;
    selected.busy = true;
    const button = dialog.querySelector('#sendChatDocument');
    button.disabled = true;
    button.textContent = ui('正在阅读…','Reading…');
    error.textContent = ''; selected.error = null; selected.result = null;
    dialog.querySelector('#chatDocumentResult').textContent = '';
    try {
      // A fresh ID is created only for a deliberate click. Fetch never retries automatically.
      const result = await chatDocumentRequest(`${selected.url}/read`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: dialog.querySelector('#chatDocumentQuestion').value.trim(),
          preview_mode: selected.preview, confirm_billable_call: true, request_id: crypto.randomUUID()})
      });
      if (activeChatDocument !== selected) return;
      selected.result = result;
      refreshChatDocumentLanguage();
      dialog.querySelector('#chatDocumentQuestion').value = '';
      consent.checked = false;
    } catch (problem) {
      if (activeChatDocument === selected) { selected.error = problem; error.textContent = problem.message; }
    } finally {
      selected.busy = false;
      button.disabled = false;
      button.textContent = ui('确认阅读并提问','Confirm and ask');
      if (state.currentId === selected.avatarId && !!state.previewMode === selected.preview) {
        delete $('#messageList').dataset.signature;
        await loadMessages();
      }
    }
  });
  return dialog;
}
async function openChatDocument(messageId) {
  if (!state.currentId || activeChatDocument?.busy) return;
  const selected = {avatarId: state.currentId, preview: !!state.previewMode, messageId, busy: false};
  selected.url = `/api/avatars/${selected.avatarId}/messages/${messageId}/document`;
  const dialog = makeChatDocumentDialog();
  activeChatDocument = selected;
  dialog.querySelector('#chatDocumentTitle').textContent = ui('阅读此文件','Read this file');
  dialog.querySelector('#sendChatDocument').disabled = true;
  dialog.showModal();
  try {
    const status = await chatDocumentRequest(`${selected.url}?preview_mode=${selected.preview}`);
    if (activeChatDocument !== selected) return;
    selected.name = status.name;
    dialog.querySelector('#chatDocumentTitle').textContent = `${ui('文件：','File: ')}${status.name}`;
    dialog.querySelector('#sendChatDocument').disabled = !status.supported;
    if (!status.supported) dialog.querySelector('#chatDocumentError').textContent = ui('此文件格式仅供下载。','This format is available for download only.');
  } catch (problem) {
    if (activeChatDocument === selected) { selected.error = problem; dialog.querySelector('#chatDocumentError').textContent = problem.message; }
  }
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-read-document]');
  if (button) openChatDocument(Number(button.dataset.readDocument));
});

// Re-label an open dialog in place: preserve its draft, consent, result and in-flight request.
function refreshChatDocumentLanguage() {
  const dialog = chatDocumentDialog, selected = activeChatDocument;
  if (!dialog || !selected) return;
  dialog.querySelector('#chatDocumentTitle').textContent = selected.name ? `${ui('文件：','File: ')}${selected.name}` : ui('阅读此文件','Read this file');
  dialog.querySelector('#closeChatDocument').setAttribute('aria-label', ui('关闭','Close'));
  dialog.querySelector('#cancelChatDocument').textContent = ui('关闭','Close');
  dialog.querySelector('#sendChatDocument').textContent = selected.busy ? ui('正在阅读…','Reading…') : ui('确认阅读并提问','Confirm and ask');
  dialog.querySelector('#chatDocumentScope').textContent = ui('仅阅读所选文件的文字。上传不会自动分析；普通聊天不会自动附带此文件。后续请在此窗口明确提问。','Only text from the selected file is read. Uploading does not analyze it, and ordinary chat does not automatically include it. Ask follow-up questions here explicitly.');
  dialog.querySelector('#chatDocumentLimits').textContent = ui('支持 TXT、MD、CSV 和有文本层的 PDF。最多 20,000 字符；文本 2 MB，PDF 10 MB／20 页。PDF 图片不会识别。','Supports TXT, MD, CSV and PDFs with a text layer. Up to 20,000 characters; text files up to 2 MB, PDFs up to 10 MB / 20 pages. Images in PDFs are not recognized.');
  dialog.querySelector('#chatDocumentQuestionLabel').textContent = ui('关于此文件的问题（留空则概括）','Question about this file (leave blank for a summary)');
  dialog.querySelector('#chatDocumentConsentLabel').textContent = ui('同意将提取的文件文本、问题及当前对话上下文发给当前对话服务，可能产生费用。每次回复最多80字。','I agree to send extracted text, my question and current conversation context to the current chat service. Charges may apply. Replies are limited to 80 characters.');
  if (selected.error) {
    const detail = selected.error.documentDetail;
    dialog.querySelector('#chatDocumentError').textContent = detail?.code ? ui(detail.message, chatDocumentErrors[detail.code] || detail.message) : selected.error.message;
  }
  const result = selected.result;
  if (result) {
    const source = result.source;
    const facts = [result.reply, `${ui('文件来源：','File source: ')}${source.name}`, `${ui('提取字符：','Extracted characters: ')}${source.characters}`];
    if (source.text_layer_only) facts.push(ui('仅依据 PDF 文本层；未识别其中的图片。','Based only on the PDF text layer; images were not recognized.'));
    if (source.empty_pages?.length) facts.push(`${ui('这些页没有可读取文字：','Pages with no readable text: ')}${source.empty_pages.join(', ')}`);
    if (result.cached) facts.push(ui('已显示之前成功的结果，本次未再调用服务。','Showing a previous successful result; no new service call was made.'));
    dialog.querySelector('#chatDocumentResult').textContent = facts.join('\n\n');
  }
}
