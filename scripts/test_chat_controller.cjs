/* Local race checks: disposable DOM/fetch doubles, no browser or cloud calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../openavatar/static/chat.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const requests = [], cancellations = [], nodes = new Map(), listeners = {}, toasts = [], loads = [];
  const input = {value:'', dispatchEvent() {}};
  const list = {
    dataset:{}, scrollHeight:0, scrollTop:0,
    insertAdjacentHTML(_position, html) {
      const id = html.match(/id="(stream-\d+)"/)[1];
      const text = {textContent:''};
      const button = {removed:false, remove() { this.removed = true; }};
      const node = {text, button, removeAttribute() {}, remove() { this.removed = true; },
        querySelector(selector) { return selector === '[data-stream-text]' ? text : button; }};
      nodes.set('#' + id, node);
    },
  };
  const state = {currentId:'avatar-a', previewMode:false, activeChat:null};
  const context = vm.createContext({
    state, AbortController, DOMException, TextDecoder, Uint8Array, Event,
    document:{addEventListener:(name, callback) => { listeners[name] = callback; }},
    $:selector => selector === '#chatMessageInput' ? input : selector === '#messageList' ? list
      : selector === '#chatForm' ? {addEventListener() {}} : selector === '.empty-chat' ? null : nodes.get(selector),
    fetch:(url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject, reads:[]})),
    api:async (url, options) => { cancellations.push({url, options}); return {}; },
    loadMessages:async () => { loads.push(state.currentId); },
    toast:(...args) => toasts.push(args), escapeHtml:value => value, systemText:value => value,
    ui:(_zh, en) => en,
    tr:(value, ...args) => Array.isArray(value) ? value.reduce((s, x, i) => s + x + (args[i] ?? ''), '') : value,
  });
  vm.runInContext(source, context);
  function respond(index, runId) {
    const request = requests[index];
    request.resolve({ok:true, headers:{get:() => runId},
      body:{getReader:() => ({read:() => new Promise(resolve => request.reads.push(resolve))})}});
  }
  async function complete(index) {
    requests[index].reads.shift()({value:new TextEncoder().encode('{"type":"done","reply":"Done"}\n'),done:false});
    await tick();
    requests[index].reads.shift()({done:true});
  }
  return {state, context, requests, cancellations, nodes, listeners, toasts, input, loads, respond, complete};
}

(async () => {
  {
    const f = fixture();
    const sending = f.context.sendTextMessage('First');
    assert.ok(f.state.activeChat, 'register the request before waiting for response headers');
    await f.context.cancelActiveChat();
    assert.equal(f.requests[0].options.signal.aborted, true, 'stop aborts a pending first response immediately');
    assert.equal(f.state.activeChat, null);
    f.respond(0, 'late-run');
    await sending;
    assert.equal(f.state.activeChat, null, 'late headers cannot revive a stopped request');
    assert.ok(f.cancellations.some(item => item.url.endsWith('/late-run/cancel')));
    assert.deepEqual(f.toasts, []);
  }
  {
    const f = fixture();
    const first = f.context.sendTextMessage('First');
    const firstNode = [...f.nodes.values()][0];
    const second = f.context.sendTextMessage('Second');
    const latest = f.state.activeChat;
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[0].options.signal.aborted, true, 'new submission stops the older request');
    assert.equal(f.nodes.size, 2, 'rapid sends have separate message elements');
    f.respond(1, 'new-run'); await tick();
    await f.listeners.click({target:{closest:selector => selector === '.message' ? firstNode
      : selector === '[data-action]' ? Object.assign(firstNode.button, {dataset:{action:'cancel-chat'}}) : null}});
    assert.equal(f.state.activeChat, latest, 'an old stop button cannot cancel the new request');
    f.respond(0, 'old-run'); await first;
    assert.equal(f.state.activeChat, latest, 'old response and finally cannot replace or clear the new request');
    assert.equal(latest.runId, 'new-run');
    assert.deepEqual(f.loads, [], 'old cleanup cannot replace a live stream with stored messages');
    await f.complete(1); await second;
    assert.equal(f.state.activeChat, null);
    assert.deepEqual(f.loads, ['avatar-a']);
  }
  {
    const f = fixture();
    let finishCancellation;
    f.context.api = () => new Promise(resolve => { finishCancellation = resolve; });
    const sending = f.context.sendTextMessage('First');
    f.respond(0, 'blocked-cancel'); await tick();
    const cancellation = f.context.cancelActiveChat();
    assert.equal(f.requests[0].options.signal.aborted, true, 'local stop never waits for the server cancellation response');
    assert.equal(f.state.activeChat, null);
    finishCancellation({}); await cancellation;
    f.context.api = async () => ({});
    f.requests[0].reads.shift()({done:true}); await sending;
  }
  {
    const f = fixture();
    const first = f.context.sendTextMessage('Only avatar A');
    f.state.currentId = 'avatar-b'; f.state.previewMode = true;
    assert.equal(f.requests[0].url, '/api/avatars/avatar-a/chat/stream');
    assert.equal(JSON.parse(f.requests[0].options.body).preview_mode, false);
    f.respond(0, 'old-avatar-run'); await first;
    assert.equal(f.requests[0].options.signal.aborted, true);
    assert.deepEqual(f.loads, [], 'old avatar response cannot refresh the new avatar');
    assert.deepEqual(f.toasts, []);
    const second = f.context.sendTextMessage('Only preview B');
    assert.equal(f.requests[1].url, '/api/avatars/avatar-b/chat/stream');
    assert.equal(JSON.parse(f.requests[1].options.body).preview_mode, true);
    f.respond(1, 'preview-run'); await tick();
    await f.complete(1); await second;
    assert.deepEqual(f.loads, ['avatar-b']);
  }
  {
    const f = fixture();
    const first = f.context.sendTextMessage('Old');
    const second = f.context.sendTextMessage('New');
    const latest = f.state.activeChat;
    f.requests[0].reject(new Error('late old failure')); await first;
    assert.equal(f.state.activeChat, latest);
    assert.equal(f.input.value, '', 'old failure does not restore obsolete input');
    assert.deepEqual(f.toasts, []);
    assert.deepEqual(f.loads, []);
    f.respond(1, 'new-run'); await tick();
    await f.complete(1); await second;
  }
  console.log('Chat controller: 5 local scenarios passed (pending stop, replacement ownership, immediate abort, avatar/preview scope, stale failure).');
})().catch(error => { console.error(error); process.exitCode = 1; });
