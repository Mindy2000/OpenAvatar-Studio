let chatMessageSerial = 0;

function ownsChatRequest(active) {
  return state.activeChat === active && !active.controller.signal.aborted
    && state.currentId === active.avatarId && !!state.previewMode === active.previewMode;
}

async function streamChat(active, message, onEvent, sourceMessageId = 0) {
  const response = await fetch(`/api/avatars/${encodeURIComponent(active.avatarId)}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, source_message_id: sourceMessageId, preview_mode: active.previewMode }),
    signal: active.controller.signal,
  });
  active.runId = response.headers.get("X-Run-Id") || "";
  if (!ownsChatRequest(active)) {
    void cancelActiveChat(active);
    throw new DOMException("Chat request is no longer current", "AbortError");
  }
  if (!response.ok) {
    let detail = tr`请求失败（${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(systemText(typeof detail === "string" ? detail : JSON.stringify(detail)));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  while (true) {
    const { value, done } = await reader.read();
    if (!ownsChatRequest(active)) {
      void cancelActiveChat(active);
      throw new DOMException("Chat request is no longer current", "AbortError");
    }
    pending += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    if (done) break;
  }
  if (pending.trim()) onEvent(JSON.parse(pending));
}

async function cancelActiveChat(active = state.activeChat) {
  if (!active) return;
  // Detach and stop locally before waiting for the cancellation endpoint.
  // An older request must never clear or cancel its replacement.
  if (state.activeChat === active) state.activeChat = null;
  active.controller.abort();
  if (active.runId) {
    try { await api(`/api/runtime/runs/${encodeURIComponent(active.runId)}/cancel`, { method: "POST" }); } catch (_) {}
  }
}

document.addEventListener("click", async event => {
  if (event.target.closest("[data-action]")?.dataset.action !== "cancel-chat") return;
  const node = event.target.closest(".message");
  const button = event.target.closest("[data-action]");
  const active = state.activeChat;
  if (!active || active.node !== node) { button.remove(); return; }
  button.disabled = true;
  await cancelActiveChat(active);
  button.remove();
  const text = node?.querySelector("[data-stream-text]");
  if (text) text.textContent += ui("（已停止）", " (stopped)");
});

async function sendTextMessage(message, sourceMessageId = 0) {
  const avatarId = state.currentId;
  const previewMode = !!state.previewMode;
  const textarea = $("#chatMessageInput");
  if (!message || !avatarId) return;
  if (state.activeChat) void cancelActiveChat();
  const active = {controller: new AbortController(), runId: "", avatarId, previewMode};
  state.activeChat = active;
  textarea.value = "";
  textarea.dispatchEvent(new Event("input"));
  const list = $("#messageList");
  if ($(".empty-chat", list)) list.innerHTML = "";
  const messageId = `stream-${++chatMessageSerial}`;
  list.insertAdjacentHTML(
    "beforeend",
    `${sourceMessageId ? "" : `<div class="message user"><span>${escapeHtml(message)}</span></div>`}<div class="message assistant" id="${messageId}"><span data-stream-text>正在连接模型…</span><button type="button" class="ghost" data-action="cancel-chat">停止</button></div>`,
  );
  list.scrollTop = list.scrollHeight;
  const node = $(`#${messageId}`);
  active.node = node;
  const textNode = node.querySelector("[data-stream-text]");
  let reply = "";
  try {
    await streamChat(active, message, item => {
      if (!ownsChatRequest(active)) return;
      if (item.type === "start") textNode.textContent = "";
      if (item.type === "delta") {
        reply += item.text;
        textNode.textContent = reply;
        list.scrollTop = list.scrollHeight;
      }
      if (item.type === "error") throw new Error(systemText(item.error) || tr("模型流式回复失败"));
      if (item.type === "done") {
        node.innerHTML = tr`<span>${escapeHtml(item.reply)}</span><button class="message-audio" data-action="speak-message" title="使用所选声音播放">♫</button>`;
      }
    }, sourceMessageId);
  } catch (error) {
    if (error.name !== "AbortError" && ownsChatRequest(active)) {
      node.remove();
      toast(error.message, true);
      if (!sourceMessageId) { textarea.value = message; textarea.dispatchEvent(new Event("input")); }
    }
  } finally {
    if (state.activeChat === active) state.activeChat = null;
    node.querySelector('[data-action="cancel-chat"]')?.remove();
    node.removeAttribute("id");
  }
  list.scrollTop = list.scrollHeight;
  if (!state.activeChat && state.currentId === avatarId && !!state.previewMode === previewMode) { delete list.dataset.signature; await loadMessages(); }
}
$("#chatForm").addEventListener("submit", async event => {
  event.preventDefault();
  await sendTextMessage($("#chatMessageInput").value.trim());
});
