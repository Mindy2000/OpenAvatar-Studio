function selectTab(tab) {
  $$(".studio-sidebar nav button").forEach(node => node.classList.toggle("active", node.dataset.tab === tab));
  $$(".tab-panel").forEach(node => node.classList.add("hidden"));
  $(`#${tab}Tab`).classList.remove("hidden");
  if (tab === "training") loadTrainingJobs().catch(error => toast(error.message, true));
  if (tab === "chat") loadVideoCallStatus().catch(error => toast(error.message, true));
  if (tab === "history") loadHistoryRecords().catch(error => toast(error.message, true));
  if (tab === "timeline") loadLifeArchive().catch(error => toast(error.message, true));
  if (tab === "profile") loadEvidence().catch(error => toast(error.message, true));
  if (tab === "settings") loadAvatarModelSettings().catch(error => toast(error.message, true));
}

async function loadVideoCallStatus() {
  if (!state.currentId) return;
  const status = await api(`/api/avatars/${state.currentId}/video-call/status`);
  state.videoCallStatus = status;
  const available = status.available;
  $("#videoCallStatus").textContent = available
    ? "North/Atlas 已就绪。开始前会再次确认费用和数据传输。"
    : status.reason || "尚未配置实时视频通话";
  $("#videoCallPanel").classList.toggle("ready", Boolean(available));
  $("#videoCallDetails").innerHTML = `<span>${escapeHtml(status.provider)} · ${escapeHtml(status.transport || "livekit")}</span>
    <span>${status.hasCanonicalOrApprovedFace ? "已有 canonical/approved 身份图" : status.hasFaceUrl ? "使用 North Face URL" : "缺少身份参考图"}</span>
    <span>${status.settings?.scene_background_enabled ? "背景开启" : "背景关闭"} · ${status.settings?.camera_flip_enabled ? "翻转开启" : "翻转关闭"}</span>`;
}

async function loadLiveKitClient() {
  if (window.LivekitClient || window.LiveKitClient || window.LiveKit) return window.LivekitClient || window.LiveKitClient || window.LiveKit;
  try {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/livekit-client@2.15.7/dist/livekit-client.umd.min.js";
      script.integrity = "sha384-Xi7KEoauIhfuZTBufx2TYpgvKtb2BImoyPSFMmvAx8RZYS2epgzAq5bRwMca+J1f";
      script.crossOrigin = "anonymous";
      script.async = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
    const client = window.LivekitClient || window.LiveKitClient || window.LiveKit;
    if (client) return client;
  } catch (_) {}
  throw new Error("LiveKit SDK 加载失败，请检查网络或桌面应用的安全设置");
}

function liveKitStage() {
  return $("#videoLiveKitStage");
}

function setLiveKitStatus(message, error = false) {
  const node = $("#videoLiveKitStatus");
  if (node) {
    node.textContent = message;
    node.classList.toggle("error", error);
  }
}

function attachLiveKitTrack(track) {
  const stage = liveKitStage();
  if (!stage) return;
  const kind = track?.kind || track?.mediaStreamTrack?.kind || "";
  if (!["video", "audio"].includes(kind)) return;
  let media = null;
  if (typeof track.attach === "function") {
    media = track.attach();
  } else if (track.mediaStreamTrack) {
    media = document.createElement(kind);
    media.srcObject = new MediaStream([track.mediaStreamTrack]);
  }
  if (!media) return;
  media.autoplay = true;
  media.playsInline = true;
  media.controls = false;
  media.dataset.livekitTrack = kind;
  if (kind === "audio") media.style.display = "none";
  if (kind === "video") {
    stage.querySelectorAll("video[data-livekit-track='video']").forEach(node => node.remove());
    stage.classList.add("connected");
  }
  stage.appendChild(media);
  media.play?.().catch(() => null);
}

async function ensureLiveKitAudioTrack() {
  if (!state.livekitRoom || state.livekitAudioDest) return;
  if (state.livekitAudioPromise) return state.livekitAudioPromise;
  state.livekitAudioPromise = (async () => {
  const context = state.livekitAudioContext || new (window.AudioContext || window.webkitAudioContext)();
  state.livekitAudioContext = context;
  const client = await loadLiveKitClient();
  const dest = context.createMediaStreamDestination();
  const silence = context.createConstantSource ? context.createConstantSource() : null;
  if (silence) {
    const gain = context.createGain();
    gain.gain.value = 0;
    silence.connect(gain).connect(dest);
    silence.start();
  }
  const track = dest.stream.getAudioTracks()[0];
  if (!track) throw new Error("没有可发布的 LiveKit 音频轨道");
  await state.livekitRoom.localParticipant.publishTrack(track, {
    name: "openavatar-tts",
    source: client.Track?.Source?.Microphone || "microphone",
  });
  state.livekitAudioDest = dest;
  state.livekitSilenceSource = silence;
  state.livekitPublishedTrack = track;
  setLiveKitStatus("LiveKit 已连接，复刻语音会同步推入头像音轨");
  })();
  try { await state.livekitAudioPromise; } finally { state.livekitAudioPromise = null; }
}

async function prepareUserMedia() {
  if (!navigator.mediaDevices?.getUserMedia) return null;
  try {
    state.userMedia = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  } catch (_) {
    try { state.userMedia = await navigator.mediaDevices.getUserMedia({ audio: true, video: false }); } catch (_) { state.userMedia = null; }
  }
  state.callCameraEnabled = Boolean(state.userMedia?.getVideoTracks().length);
  state.callMicrophoneEnabled = Boolean(state.userMedia?.getAudioTracks().length);
  const cameraButton = $("[data-action='toggle-call-camera']");
  const microphoneButton = $("[data-action='toggle-call-microphone']");
  cameraButton?.setAttribute("aria-pressed", String(state.callCameraEnabled));
  microphoneButton?.setAttribute("aria-pressed", String(state.callMicrophoneEnabled));
  if (cameraButton) cameraButton.textContent = state.callCameraEnabled ? "关闭摄像头" : "开启摄像头";
  if (microphoneButton) microphoneButton.textContent = state.callMicrophoneEnabled ? "静音" : "取消静音";
  const preview = $("#localCameraPreview");
  if (preview && state.userMedia?.getVideoTracks().length) {
    preview.srcObject = state.userMedia;
    preview.classList.remove("hidden");
  }
  return state.userMedia;
}

async function publishUserMedia() {
  if (!state.livekitRoom || !state.userMedia) return;
  const client = await loadLiveKitClient();
  for (const track of state.userMedia.getTracks()) {
    await state.livekitRoom.localParticipant.publishTrack(track, {
      name: track.kind === "video" ? "openavatar-user-camera" : "openavatar-user-microphone",
      source: track.kind === "video" ? (client.Track?.Source?.Camera || "camera") : (client.Track?.Source?.Microphone || "microphone"),
    });
  }
}

async function connectNorthLiveKit(livekit) {
  if (!livekit?.url || !livekit?.token) throw new Error("North 没有返回完整的 LiveKit URL/token");
  if (state.livekitRoom) return;
  setLiveKitStatus("正在连接 LiveKit 房间…");
  const client = await loadLiveKitClient();
  const Room = client.Room;
  const RoomEvent = client.RoomEvent || {};
  const room = new Room({ adaptiveStream: true, dynacast: true });
  room.on?.(RoomEvent.TrackSubscribed || "trackSubscribed", track => {
    attachLiveKitTrack(track);
    setLiveKitStatus(track?.kind === "video" ? "实时头像画面已接入" : "LiveKit 音频轨道已接入");
  });
  room.on?.(RoomEvent.TrackUnsubscribed || "trackUnsubscribed", track => {
    if ((track?.kind || "") === "video") liveKitStage()?.querySelectorAll("video[data-livekit-track='video']").forEach(node => node.remove());
  });
  room.on?.(RoomEvent.Disconnected || "disconnected", () => setLiveKitStatus("LiveKit 连接已断开", true));
  await room.connect(livekit.url, livekit.token, { autoSubscribe: true });
  state.livekit = livekit;
  state.livekitRoom = room;
  await ensureLiveKitAudioTrack();
  await publishUserMedia();
}

function disconnectNorthLiveKit() {
  try { state.livekitPublishedTrack?.stop?.(); } catch (_) {}
  try { state.livekitSilenceSource?.stop?.(); } catch (_) {}
  try { state.livekitRoom?.disconnect?.()?.catch?.(() => null); } catch (_) {}
  try { state.speechRecognition?.stop?.(); } catch (_) {}
  state.userMedia?.getTracks().forEach(track => { try { track.stop(); } catch (_) {} });
  state.livekit = null;
  state.livekitRoom = null;
  state.livekitAudioDest = null;
  state.livekitAudioPromise = null;
  state.livekitSilenceSource = null;
  state.livekitPublishedTrack = null;
  state.userMedia = null;
  state.speechRecognition = null;
  state.callCameraEnabled = false;
  state.callMicrophoneEnabled = false;
  const preview = $("#localCameraPreview");
  if (preview) { preview.srcObject = null; preview.classList.add("hidden"); }
  $("#videoCallControls")?.classList.add("hidden");
  liveKitStage()?.querySelectorAll("[data-livekit-track]").forEach(node => node.remove());
  liveKitStage()?.classList.remove("connected");
}

async function playSpeechBlob(blob) {
  if (state.livekitRoom) {
    const context = state.livekitAudioContext || new (window.AudioContext || window.webkitAudioContext)();
    state.livekitAudioContext = context;
    await context.resume?.();
    await ensureLiveKitAudioTrack();
    const arrayBuffer = await blob.arrayBuffer();
    const decoded = await context.decodeAudioData(arrayBuffer.slice(0));
    const source = context.createBufferSource();
    source.buffer = decoded;
    source.connect(context.destination);
    if (state.livekitAudioDest) source.connect(state.livekitAudioDest);
    state.currentSpeechSource = source;
    source.addEventListener?.("ended", () => { if (state.currentSpeechSource === source) state.currentSpeechSource = null; }, { once: true });
    source.start();
    return;
  }
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
  await audio.play();
}

function renderActiveVideoCall() {
  const call = state.videoCall;
  if (!call?.video_call) return;
  const video = call.video_call;
  $("#videoCallDetails").innerHTML = `<span>North session: ${escapeHtml(video.northSessionId || "")}</span>
    <span>LiveKit: ${escapeHtml(video.livekit?.room || "room pending")}</span>
    <span>计费：${Number(video.budget?.pricePerSecond || 0).toFixed(5)} / 秒</span>
    <small id="videoLiveKitStatus">正在等待 LiveKit 连接…</small>`;
}

async function startVideoCall() {
  if (!state.currentId || state.videoCallStarting || state.videoCall) return;
  if (!confirm(ui("视频通话会向 North/LiveKit 发送身份参考图或 Face URL，以及你允许开启的摄像头和麦克风内容，并可能按时长收费。确认开始？", "Video calls send the identity reference or Face URL and enabled camera/microphone streams to North/LiveKit, and may incur time-based charges. Start?"))) return;
  const avatarId = state.currentId;
  let call = null;
  state.videoCallStarting = true;
  try {
    await prepareUserMedia();
    call = await api(`/api/avatars/${avatarId}/calls`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "video", provider: "north", user_camera_enabled: state.callCameraEnabled, confirm_billable_call: true }),
    });
    state.videoCall = call;
    $("#videoCallStatus").textContent = "实时视频通话已创建，North/LiveKit 房间已返回。";
    renderActiveVideoCall();
    await connectNorthLiveKit(call.video_call?.livekit);
    $("#videoCallControls").classList.remove("hidden");
    toast("North 实时视频通话已创建");
  } catch (error) {
    // Release local devices immediately, even if the remote cleanup request stalls.
    disconnectNorthLiveKit();
    state.videoCall = null;
    $("#videoCallStatus").textContent = ui("通话未能开始，摄像头和麦克风已关闭。", "Call could not start. Camera and microphone have been stopped.");
    if (call?.id) {
      try {
        await api(`/api/avatars/${avatarId}/calls/${call.id}/end`, { method: "POST" });
      } catch (_) {
        $("#videoCallStatus").textContent = ui("本机摄像头和麦克风已关闭，但远程会话释放失败。请到服务商处检查会话与费用。", "Local camera and microphone are stopped, but remote session cleanup failed. Check the session and billing with your provider.");
      }
    }
    throw error;
  } finally {
    state.videoCallStarting = false;
  }
}

async function sendVideoTurn() {
  const input = $("#videoTranscriptInput");
  const message = input.value.trim();
  if (!message || !state.videoCall?.id) return;
  input.value = "";
  $("#videoTurnStatus").textContent = "数字人正在理解并回复…";
  const started = performance.now();
  const result = await api(`/api/avatars/${state.currentId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, preview_mode: state.previewMode }),
  });
  const llmLatency = Math.round(performance.now() - started);
  await api(`/api/avatars/${state.currentId}/calls/${state.videoCall.id}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_transcript: message, assistant_text: result.reply, llm_latency_ms: llmLatency, metadata: { source: "live_ui" } }),
  });
  $("#videoTurnStatus").textContent = result.reply;
  const response = await fetch(`/api/avatars/${state.currentId}/speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: result.reply, confirm_billable_call: true }),
  });
  if (response.ok) await playSpeechBlob(await response.blob());
  else $("#videoTurnStatus").textContent = `${result.reply}（当前没有可用的复刻声音，已保留文字回复）`;
}

function listenVideoTurn() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) throw new Error("当前浏览器不支持语音识别，请直接输入文字");
  if (!confirm(ui("此功能使用浏览器自带语音识别，不使用你在本系统配置的语音 API Key。浏览器可能把麦克风音频发送到其在线识别服务，不能保证离线处理。是否继续？也可以取消并输入文字。", "This uses your browser's speech recognition, not the voice API key configured in this app. The browser may send microphone audio to its online recognition service; offline processing is not guaranteed. Continue, or cancel and type instead?"))) return;
  try { state.speechRecognition?.abort?.(); } catch (_) {}
  try { state.currentSpeechSource?.stop?.(); } catch (_) {}
  const recognition = new Recognition();
  recognition.lang = state.current?.avatar_primary_language === "en-US" ? "en-US" : "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = event => {
    $("#videoTranscriptInput").value = [...event.results].map(result => result[0].transcript).join("");
  };
  recognition.onend = () => { $("#videoTurnStatus").textContent = "语音识别结束，请检查文字后发送。"; };
  recognition.onerror = event => { $("#videoTurnStatus").textContent = `语音识别不可用：${event.error}`; };
  state.speechRecognition = recognition;
  recognition.start();
  $("#videoTurnStatus").textContent = "正在听，请自然说话…";
}


