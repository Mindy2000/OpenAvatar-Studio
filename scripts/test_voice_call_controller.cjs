/* Local controller unit checks: no browser, microphone, network or cloud call. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../openavatar/static/voice-call.js'), 'utf8').split('let activeVoiceCall = null;')[0];
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const requests = [], audios = [], revoked = [], sent = [], statuses = [];
  let serial = 0;
  class FakeAudio {
    constructor(url) { this.url = url; audios.push(this); }
    play() { this.played = true; return Promise.resolve(); }
    pause() { this.paused = true; }
    removeAttribute() {}
    finish() { this.onended?.(); }
  }
  const context = vm.createContext({
    window:{}, tr:(value, ...args) => Array.isArray(value) ? value.reduce((s, x, i) => s + x + (args[i] ?? ''), '') : value,
    WebSocket:{OPEN:1}, Audio:FakeAudio, AbortController, Number, Set,
    URL:{createObjectURL:() => `blob:${++serial}`, revokeObjectURL:value => revoked.push(value)},
    fetch:(url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    setTimeout, clearTimeout, setInterval, clearInterval,
  });
  vm.runInContext(source + '\nglobalThis.Controller = VoiceCallController;', context);
  const controller = new context.Controller({avatarId:'test', status:x => statuses.push(x), transcript:() => {}, changed:() => {}});
  Object.assign(controller, {active:true, ready:true, callId:1, callToken:'test-session-token', socket:{readyState:1, send:data => sent.push(JSON.parse(data)), close() {}}});
  function turn(id = 'run') {
    controller.submit('继续');
    controller.receive({type:'user.committed', run_id:id, client_turn_id:controller.pendingTurn});
  }
  function segment(n, run = 'run') { controller.receive({type:'assistant.segment', run_id:run, segment_id:n, text:'句子。'}); }
  function done(run = 'run') { controller.receive({type:'assistant.done', run_id:run, reply:'完成。'}); }
  function respond(n) { requests[n].resolve({ok:true, blob:async () => ({})}); }
  return {controller, requests, audios, revoked, sent, statuses, turn, segment, done, respond,
    recognitionLanguage:context.voiceRecognitionLanguage};
}
(async () => {
  {
    const f = fixture();
    for (const value of ['en-US', 'en', 'English', 'en-GB', 'en_US']) {
      assert.equal(f.recognitionLanguage(value), 'en-US', 'English avatars use English recognition');
    }
    for (const value of ['zh-CN', 'bilingual', 'custom', undefined]) {
      assert.equal(f.recognitionLanguage(value), 'zh-CN', 'existing default stays Chinese');
    }
    f.controller.end();
  }
  {
    const f = fixture(); f.turn(); f.segment(0); f.segment(1); f.segment(0);
    assert.equal(f.requests.length, 1, 'sequential synthesis, deduplicated first segment');
    f.respond(0); await tick();
    assert.equal(f.audios.length, 1, 'first sentence plays before assistant.done');
    assert.equal(f.requests.length, 2, 'next synthesis starts while first audio plays');
    f.respond(1); await tick(); f.done();
    assert.equal(f.audios.length, 1, 'no overlapping playback');
    f.audios[0].finish(); await tick();
    assert.equal(f.audios.length, 2);
    assert.equal(f.controller.runId, 'run', 'keep turn active until last audio finishes');
    f.audios[1].finish();
    assert.equal(f.controller.runId, null);
    assert.equal(f.sent.filter(x => x.type === 'call.played').length, 1);
    for (let n = 0; n < 5; n++) f.turn(`run${n}`);
    assert.equal(f.controller.active, true, 'more than three rounds stays active');
    f.controller.end();
  }
  {
    const f = fixture(); f.turn(); f.segment(0); f.segment(1);
    const oldSignal = f.requests[0].options.signal;
    f.controller.interrupt();
    assert.equal(oldSignal.aborted, true);
    f.turn('new'); f.segment(0, 'new');
    f.respond(0); await tick();
    assert.equal(f.audios.length, 0, 'old response cannot play after interrupt');
    assert.equal(f.requests.length, 2, 'old queued second segment never requested');
    f.respond(1); await tick();
    assert.equal(f.audios.length, 1);
    f.controller.receive({type:'assistant.segment', run_id:'run', segment_id:2});
    assert.equal(f.requests.length, 2, 'ignore late segment from old run');
    f.controller.observeMicLevel(.1, 0); f.controller.observeMicLevel(.1, 130);
    assert.equal(f.audios[0].paused, true, 'local microphone activity stops playback');
    assert.equal(f.controller.audioQueue.length, 0);
    f.controller.end();
  }
  {
    const f = fixture(); f.turn(); f.segment(0); f.segment(1);
    f.requests[0].reject(new Error('simulated provider failure')); await tick();
    assert.equal(f.controller.active, false);
    assert.equal(f.requests.length, 1, 'no retry or next segment after failure');
  }
  {
    const f = fixture(); f.turn(); f.segment(3); f.segment(-1);
    assert.equal(f.requests.length, 0, 'at most three valid segments');
    f.controller.receive({type:'call.ended', reason:'time_limit', message:'finished'});
    assert.equal(f.controller.active, false, 'server deadline closes an idle call');
  }
  {
    const f = fixture();
    let stopped = 0, closed = 0, aborted = 0;
    f.controller.micStream = {getTracks:() => [{stop:() => stopped++}]};
    f.controller.micContext = {close:() => { closed++; return Promise.resolve(); }};
    f.controller.recognition = {abort:() => aborted++};
    f.controller.end();
    assert.equal(stopped, 1); assert.equal(closed, 1); assert.equal(aborted, 1);
    const fullSource = fs.readFileSync(path.join(__dirname, '../openavatar/static/voice-call.js'), 'utf8');
    assert.ok(fullSource.includes("window.addEventListener('beforeunload', endVoiceCall)"));
    assert.ok(!fullSource.includes("document.addEventListener('visibilitychange'"), 'switching tabs does not hang up');
  }
  console.log('Voice call controller: 6 local scenarios passed (language, ordered early speech, interruption, no retries, limits, cleanup).');
})().catch(error => { console.error(error); process.exitCode = 1; });
