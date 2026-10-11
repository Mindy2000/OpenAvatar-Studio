/* Browser recognition sends transcripts to the text gateway; audio replies use
   the avatar's existing TTS route. It never starts a camera or a video session. */
function voiceRecognitionLanguage(primaryLanguage) {
  // Persisted avatar language is a locale (en-US), while older packages may
  // still carry en/English. UI language does not override the avatar's language.
  const language = String(primaryLanguage || '').trim().toLowerCase().replaceAll('_', '-');
  return language === 'english' || /^en(?:-|$)/.test(language) ? 'en-US' : 'zh-CN';
}
class VoiceCallController {
  constructor({avatarId, language = 'zh-CN', status, transcript, changed, maxMinutes = 10, estimatedBudgetCny = 5, limits = () => {}}) {
    Object.assign(this, {avatarId, language, status, transcript, changed, maxMinutes, estimatedBudgetCny, limits});
    this.active = false;
    this.muted = false;
    this.turns = 0;
    this.version = 0;
    this.speechQueue = [];
    this.audioQueue = [];
    this.seenSegments = new Set();
  }
  start() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) throw new Error(tr('当前浏览器不支持语音识别，请使用支持此功能的浏览器。'));
    if (!Number.isFinite(this.maxMinutes) || this.maxMinutes < 1 || this.maxMinutes > 120) throw new Error(tr('通话时长须在1至120分钟之间'));
    if (!Number.isFinite(this.estimatedBudgetCny) || this.estimatedBudgetCny < .01 || this.estimatedBudgetCny > 1000) throw new Error(tr('本次估算额度须在0.01至1000元之间'));
    this.active = true;
    this.recognition = new Recognition();
    const r = this.recognition;
    r.lang = this.language;
    r.continuous = true;
    r.interimResults = true;
    r.onstart = () => { if (this.active && !this.muted) this.status(tr('麦克风已开启，正在听…')); };
    r.onspeechstart = () => { if (this.active && !this.muted) this.interrupt(); };
    r.onresult = event => {
      if (!this.active || this.muted) return;
      const words = [];
      let hasSpeech = false;
      let hasInterim = false;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        hasSpeech ||= Boolean(event.results[i][0].transcript.trim());
        hasInterim ||= !event.results[i].isFinal;
        if (event.results[i].isFinal) words.push(event.results[i][0].transcript);
      }
      // Chrome may not emit speechstart again during continuous recognition.
      // Stop the old response on partial speech, before waiting for a final result.
      if (hasSpeech && (this.pendingTurn || this.runId || this.speechAbort || this.audio)) this.interrupt();
      if (hasInterim) clearTimeout(this.submitTimer);
      const text = words.join('').trim();
      if (text) this.pendingText = (this.pendingText || '') + text;
      if (hasInterim || !this.pendingText) return;
      clearTimeout(this.submitTimer);
      this.submitTimer = setTimeout(() => {
        const text = this.pendingText;
        this.pendingText = '';
        this.submit(text);
      }, 450);
    };
    r.onerror = event => {
      if (!this.active || event.error === 'aborted' || event.error === 'no-speech') return;
      this.end(tr`语音识别失败（${event.error}），通话已停止。请检查麦克风权限或网络。`);
    };
    r.onend = () => {
      if (this.active && !this.muted) this.restartTimer = setTimeout(() => this.listen(), 300);
    };
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const query = new URLSearchParams({voice:'true', max_minutes:this.maxMinutes, estimated_budget_cny:this.estimatedBudgetCny});
    this.socket = new WebSocket(`${scheme}//${location.host}/ws/avatars/${encodeURIComponent(this.avatarId)}/call?${query}`);
    this.socket.onmessage = event => {
      if (!this.active) return;
      try { this.receive(JSON.parse(event.data)); } catch (_) { this.end(tr('通话返回格式异常，已停止。')); }
    };
    this.socket.onerror = () => this.end(tr('通话连接失败，请检查本机应用。'));
    this.socket.onclose = () => { if (this.active) this.end(tr('通话连接已断开。')); if (typeof state !== 'undefined' && state.currentId === this.avatarId && typeof loadMessages === 'function') loadMessages().catch(()=>{}); };
    this.connectTimer = setTimeout(() => { if (!this.ready) this.end(tr('通话连接超时，请检查应用。')); }, 15000);
    this.changed(this);
    this.status(tr('正在连接，尚未开始录音…'));
  }
  listen() {
    if (!this.active || this.muted) return;
    try { this.recognition.start(); } catch (error) {
      if (error.name !== 'InvalidStateError') this.end(tr`无法开启麦克风：${error.message}`);
    }
  }
  send(value) {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(value));
  }
  async startMicMonitor() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext || !window.navigator?.mediaDevices?.getUserMedia) return;
    try {
      const stream = await window.navigator.mediaDevices.getUserMedia({audio:{
        echoCancellation:true, noiseSuppression:true, autoGainControl:true,
      }});
      if (!this.active) { stream.getTracks().forEach(track => track.stop()); return; }
      this.micStream = stream;
      stream.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
      const context = this.micContext = new AudioContext();
      this.micSource = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      this.micSource.connect(analyser);
      // Deliberately never connect the microphone to speakers.
      await context.resume();
      if (!this.active || context !== this.micContext) return;
      const samples = new Float32Array(analyser.fftSize);
      this.noiseFloor = 0.003;
      this.micTimer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        let energy = 0;
        for (const sample of samples) energy += sample * sample;
        this.observeMicLevel(Math.sqrt(energy / samples.length), performance.now());
      }, 20);
    } catch (_) {
      this.stopMicMonitor();
      if (this.active) this.status(tr('即时打断检测不可用；可点击“打断回复”，语音识别仍会继续。'));
    }
  }
  observeMicLevel(rms, now) {
    if (!this.active || this.muted) { this.voiceSince = null; return; }
    // Require sustained input above the ambient floor, ignoring short clicks.
    const threshold = Math.max(0.018, (this.noiseFloor || 0.003) * 3);
    if (rms < threshold) {
      this.voiceSince = null;
      if (rms < 0.015) this.noiseFloor = (this.noiseFloor || 0.003) * 0.95 + rms * 0.05;
      return;
    }
    if (!(this.pendingTurn || this.runId || this.speechAbort || this.audio)) {
      this.voiceSince = null;
      return;
    }
    if (this.voiceSince == null) this.voiceSince = now;
    if (now - this.voiceSince >= 120) {
      this.voiceSince = null;
      this.interrupt();
    }
  }
  stopMicMonitor() {
    clearInterval(this.micTimer);
    this.voiceSince = null;
    this.micSource?.disconnect();
    this.micSource = null;
    this.micStream?.getTracks().forEach(track => track.stop());
    this.micStream = null;
    const context = this.micContext;
    this.micContext = null;
    if (context) context.close().catch(() => {});
  }
  interrupt() {
    ++this.version;
    this.runId = null;
    this.pendingTurn = null;
    this.replyDone = false;
    this.speechQueue = [];
    this.audioQueue.forEach(item => URL.revokeObjectURL(item.url));
    this.audioQueue = [];
    this.seenSegments.clear();
    this.fetchingVersion = null;
    this.speechAbort?.abort();
    this.speechAbort = null;
    if (this.audio) { this.audio.pause(); this.audio.removeAttribute('src'); this.audio = null; }
    if (this.audioURL) { URL.revokeObjectURL(this.audioURL); this.audioURL = null; }
    this.send({type:'call.interrupt'});
    if (this.active) this.status(this.muted ? tr('麦克风已静音。') : tr('正在听，你可以继续说。'));
  }
  submit(text) {
    if (!this.active || this.muted || !text || !this.ready) return;
    this.interrupt();
    this.turns++;
    this.pendingTurn = String(this.version);
    this.transcript(tr`你：${text}`);
    this.status(tr('正在回复…'));
    this.send({type:'user.text', text, client_turn_id:this.pendingTurn});
  }
  receive(event) {
    if (event.type === 'call.started') {
      this.callId = event.call_id;
      this.callToken = event.token;
      this.ready = true;
      this.limits(event);
      clearTimeout(this.connectTimer);
      this.listen();
      this.startMicMonitor();
    } else if (event.type === 'call.usage') {
      this.limits(event);
    } else if (event.type === 'call.ended') {
      this.limits(event);
      this.end(tr(event.message || '语音通话已结束。'));
    } else if (event.type === 'user.committed' && event.client_turn_id === this.pendingTurn) {
      this.runId = event.run_id;
    } else if (event.type === 'assistant.segment' && this.runId && event.run_id === this.runId) {
      if (!Number.isInteger(event.segment_id) || event.segment_id < 0 || event.segment_id > 2 || this.seenSegments.has(event.segment_id)) return;
      this.seenSegments.add(event.segment_id);
      this.speechQueue.push({runId:event.run_id, segmentId:event.segment_id});
      this.fetchSpeech(this.version);
    } else if (event.type === 'assistant.done' && this.runId && event.run_id === this.runId) {
      this.transcript(tr`人物：${event.reply}`);
      this.replyDone = true;
      this.finishReplyIfReady();
    } else if (event.type === 'call.error' && (!event.run_id || event.run_id === this.runId)) {
      this.end(tr`通话已停止：${event.error}`);
    }
  }
  finishReplyIfReady() {
    if (!this.active || !this.replyDone || this.audio || this.audioQueue.length || this.speechQueue.length || this.fetchingVersion === this.version) return;
    this.send({type:'call.played', run_id:this.runId});
    this.runId = null;
    this.pendingTurn = null;
    this.replyDone = false;
    this.status(this.muted ? tr('麦克风已静音。') : tr('正在听，你可以继续说。'));
  }
  async fetchSpeech(version) {
    // One synthesis request at a time, independently of audio playback. While
    // sentence one plays, the next sentence can be prepared, never reordered.
    if (!this.active || version !== this.version || this.fetchingVersion === version) return;
    this.fetchingVersion = version;
    try {
      while (this.active && version === this.version && this.speechQueue.length) {
        const segment = this.speechQueue.shift();
        const controller = new AbortController();
        this.speechAbort = controller;
        if (!this.audio) this.status(tr('正在合成当前人物的声音…'));
        const response = await fetch(`/api/avatars/${encodeURIComponent(this.avatarId)}/calls/${this.callId}/speech`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({token:this.callToken, run_id:segment.runId, segment_id:segment.segmentId}), signal:controller.signal,
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || tr`声音请求失败（${response.status}）`);
        }
        const blob = await response.blob();
        if (!this.active || version !== this.version) return;
        this.speechAbort = null;
        this.audioQueue.push({url:URL.createObjectURL(blob), version});
        this.playNext();
      }
    } catch (error) {
      if (error.name !== 'AbortError' && this.active && version === this.version) this.end(tr`声音未播放：${error.message}`);
    } finally {
      if (version === this.version) {
        this.fetchingVersion = null;
        this.speechAbort = null;
        this.finishReplyIfReady();
      }
    }
  }
  async playNext() {
    if (!this.active || this.audio || !this.audioQueue.length) return;
    const {url, version} = this.audioQueue.shift();
    if (version !== this.version) { URL.revokeObjectURL(url); return; }
    this.audioURL = url;
    const audio = this.audio = new Audio(url);
    audio.onended = () => {
      if (!this.active || version !== this.version || this.audio !== audio) return;
      audio.removeAttribute('src');
      this.audio = null;
      this.audioURL = null;
      URL.revokeObjectURL(url);
      this.playNext();
      this.finishReplyIfReady();
    };
    audio.onerror = () => { if (this.active && version === this.version) this.end(tr('声音播放失败，通话已停止。')); };
    try {
      await audio.play();
      if (this.active && version === this.version) this.status(tr('正在说话；你可以直接开口或点击“打断回复”。'));
    } catch (error) {
      if (this.active && version === this.version) this.end(tr`声音未播放：${error.message}`);
    }
  }
  toggleMute() {
    if (!this.active) return;
    this.muted = !this.muted;
    this.voiceSince = null;
    this.micStream?.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
    if (this.muted) {
      clearTimeout(this.submitTimer);
      clearTimeout(this.restartTimer);
      this.pendingText = '';
      this.recognition.abort();
      this.status(tr('麦克风已静音。'));
    } else this.listen();
    this.changed(this);
  }
  end(message = tr('语音通话已结束。')) {
    this.active = false;
    this.stopMicMonitor();
    this.interrupt();
    for (const timer of ['submitTimer','restartTimer','limitTimer','connectTimer']) clearTimeout(this[timer]);
    this.pendingText = '';
    try { this.recognition?.abort(); } catch (_) {}
    this.send({type:'call.end'});
    this.socket?.close();
    this.changed(this);
    this.status(message);
  }
}

let activeVoiceCall = null;
let voiceTimer = null;
let voiceStartedAt = 0;
function updateVoiceTimer() {
  const seconds = voiceStartedAt ? Math.floor((Date.now() - voiceStartedAt) / 1000) : 0;
  const value = tr`${String(Math.floor(seconds / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`;
  $('#voiceCallTimer').textContent = value;
  $('#voiceFloatingTimer').textContent = value;
}
function endVoiceCall() {
  activeVoiceCall?.end();
  activeVoiceCall = null;
  clearInterval(voiceTimer);
  $('#voiceCallDialog').close();
  $('#voiceCallFloating').hidden = true;
}
function voiceCallControls(call) {
  $('#voiceCallBeforeStart').hidden = true;
  $('#voiceCallActions').hidden = !call.active;
  $('#dismissVoiceCall').hidden = call.active;
  $('#voiceMuteLabel').textContent = call.muted ? tr('麦克风已关') : tr('麦克风已开');
  $('#muteVoiceCall').setAttribute('aria-pressed', String(call.muted));
  $('#voiceEntryStatus').textContent = call.active ? tr('正在通话 · 点击返回窗口') : tr('通话已结束');
  if (!call.active) {
    clearInterval(voiceTimer);
    $('#voiceCallFloating').hidden = true;
    $('#minimizeVoiceCall').hidden = true;
  }
}
async function openVoiceWindow() {
  if (!state.currentId) return;
  $("#callChoiceDialog")?.close();
  if (typeof cancelVoiceMessage === "function") cancelVoiceMessage();
  const dialog = $('#voiceCallDialog');
  $('#voiceCallFloating').hidden = true;
  if (!dialog.open) dialog.showModal();
  if (activeVoiceCall?.active) return;
  const avatarId = state.currentId;
  $('#voicePersonName').textContent = state.current.name;
  $('#voiceFloatingName').textContent = state.current.name;
  $('#voicePersonInitial').textContent = state.current.name.slice(0,1);
  $('#voicePersonInitial').hidden = false;
  const image = $('#voicePersonAvatar');
  image.hidden = true;
  image.removeAttribute('src');
  $('#voiceCallStatus').textContent = tr('准备好，就和我说说话吧');
  if ($('#voiceCallLimits')) $('#voiceCallLimits').textContent = '';
  $('#voiceCallBeforeStart').hidden = false;
  $('#voiceCallActions').hidden = true;
  $('#dismissVoiceCall').hidden = true;
  $('#minimizeVoiceCall').hidden = true;
  voiceStartedAt = 0;
  updateVoiceTimer();
  try {
    const assets = await api(`/api/avatars/${avatarId}/visual-assets`);
    if (state.currentId !== avatarId || !dialog.open) return;
    const asset = assets.find(x => x.status === 'canonical') || assets.find(x => x.status === 'approved' && !['scene_key_image','wardrobe','prop','scene'].includes(x.asset_kind));
    if (asset?.asset_url) {
      image.onload = () => { image.hidden = false; $('#voicePersonInitial').hidden = true; };
      image.onerror = () => { image.hidden = true; $('#voicePersonInitial').hidden = false; };
      image.src = asset.asset_url;
    }
  } catch (_) { /* Keep the name initial when no approved photo is available. */ }
}
$('#startVoiceCall').addEventListener('click', openVoiceWindow);
$('#connectVoiceCall').addEventListener('click', () => {
  if (!state.currentId || activeVoiceCall?.active) return;
  if (!state.current?.readiness?.can_start_official) { $('#voiceCallStatus').textContent = tr('请先在构建中心完成必须项。'); return; }
  if (state.videoCall?.id) { $('#voiceCallStatus').textContent = tr('请先结束视频通话。'); return; }
  const primary = state.current?.language_profile?.avatar_primary_language || '';
  activeVoiceCall = new VoiceCallController({
    maxMinutes:Number($('#voiceCallMaxMinutes')?.value ?? 10),
    estimatedBudgetCny:Number($('#voiceCallBudget')?.value ?? 5),
    limits: event => {
      const node = $('#voiceCallLimits');
      if (!node) return;
      const reserved = Number(event.estimated_reserved_cny || 0).toFixed(4);
      const budget = Number(event.estimated_budget_cny || 0).toFixed(2);
      const seconds = Math.ceil(event.remaining_seconds || 0);
      const warning = event.budget_warning ? tr('接近本次估算额度。') : event.time_warning ? tr('即将达到设定时长。') : '';
      node.textContent = tr`已预留估算 ¥${reserved} / ¥${budget} · 剩余 ${seconds} 秒` + (warning ? ` · ${warning}` : '');
    },
    avatarId:state.currentId, language:voiceRecognitionLanguage(primary),
    status: text => {
      $('#voiceCallStatus').textContent = text;
      if (activeVoiceCall?.ready && activeVoiceCall.active && !voiceStartedAt) {
        voiceStartedAt = Date.now();
        voiceTimer = setInterval(updateVoiceTimer, 1000);
      }
    },
    transcript: () => {}, changed:voiceCallControls,
  });
  $('#minimizeVoiceCall').hidden = false;
  try { activeVoiceCall.start(); } catch (error) { activeVoiceCall.end(error.message); }
});
$('#muteVoiceCall').addEventListener('click', () => activeVoiceCall?.toggleMute());
$('#interruptVoiceCall').addEventListener('click', () => activeVoiceCall?.interrupt());
$('#endVoiceCall').addEventListener('click', () => activeVoiceCall?.end());
$('#minimizeVoiceCall').addEventListener('click', () => {
  $('#voiceCallDialog').close();
  $('#voiceCallFloating').hidden = !activeVoiceCall?.active;
});
$('#voiceCallFloating').addEventListener('click', openVoiceWindow);
$('#closeVoiceWindow').addEventListener('click', endVoiceCall);
$('#dismissVoiceCall').addEventListener('click', endVoiceCall);
$('#voiceCallDialog').addEventListener('cancel', event => { event.preventDefault(); endVoiceCall(); });
window.addEventListener('beforeunload', endVoiceCall);
