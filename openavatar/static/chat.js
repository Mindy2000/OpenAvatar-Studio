async function streamChat(message, onEvent) {
  const controller = new AbortController();
  const response = await fetch(`/api/avatars/${state.currentId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, preview_mode: state.previewMode }),
    signal: controller.signal,
  });
  if (!response.ok) {
    let detail = tr`请求失败（${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(systemText(typeof detail === "string" ? detail : JSON.stringify(detail)));
  }
  const runId = response.headers.get("X-Run-Id") || "";
  state.activeChat = { controller, runId };
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  while (true) {
    const { value, done } = await reader.read();
    pending += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    if (done) break;
  }
  if (pending.trim()) onEvent(JSON.parse(pending));
}

async function cancelActiveChat() {
  const active = state.activeChat;
  if (!active) return;
  if (active.runId) {
    try { await api(`/api/runtime/runs/${encodeURIComponent(active.runId)}/cancel`, { method: "POST" }); } catch (_) {}
  }
  active.controller.abort();
  state.activeChat = null;
}

document.addEventListener("click", async event => {
  if (event.target.closest("[data-action]")?.dataset.action !== "cancel-chat") return;
  await cancelActiveChat();
  const node = event.target.closest(".message");
  const text = node?.querySelector("[data-stream-text]");
  if (text) text.textContent += ui("（已停止）", " (stopped)");
});

$("#chatForm").addEventListener("submit", async event => {
  event.preventDefault();
  const textarea = event.currentTarget.elements.message;
  const message = textarea.value.trim();
  if (!message) return;
  if (state.activeChat) await cancelActiveChat();
  textarea.value = "";
  const list = $("#messageList");
  if ($(".empty-chat", list)) list.innerHTML = "";
  const messageId = `stream-${Date.now()}`;
  list.insertAdjacentHTML(
    "beforeend",
    tr`<div class="message user">${escapeHtml(message)}</div><div class="message assistant" id="${messageId}"><span data-stream-text>正在连接模型…</span><button type="button" class="ghost" data-action="cancel-chat">停止</button></div>`,
  );
  list.scrollTop = list.scrollHeight;
  const node = $(`#${messageId}`);
  const textNode = node.querySelector("[data-stream-text]");
  let reply = "";
  try {
    await streamChat(message, item => {
      if (item.type === "start") textNode.textContent = "";
      if (item.type === "delta") {
        reply += item.text;
        textNode.textContent = reply;
        list.scrollTop = list.scrollHeight;
      }
      if (item.type === "error") throw new Error(systemText(item.error) || tr("模型流式回复失败"));
      if (item.type === "done") {
        node.innerHTML = tr`<span>${escapeHtml(item.reply)}</span><button class="message-audio" data-action="speak-message" title="使用复刻声音播放">♫</button>`;
      }
    });
  } catch (error) {
    if (error.name !== "AbortError") {
      node.remove();
      toast(error.message, true);
    }
  } finally {
    state.activeChat = null;
    node.removeAttribute("id");
  }
  list.scrollTop = list.scrollHeight;
});
