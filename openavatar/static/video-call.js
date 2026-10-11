function selectTab(tab) {
  if (tab !== "chat") void stopConversationMedia();
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
  const avatarId=state.currentId;
  const status = await api(`/api/avatars/${avatarId}/video-call/status`);
  if(state.currentId!==avatarId)return;
  state.videoCallStatus = status;
  const available = status.available;
  $("#videoCallStatus").textContent = available
    ? tr("North/Atlas 已就绪。开始前会再次确认费用和数据传输。")
    : systemText(status.reason) || tr("尚未配置实时视频通话");
  $("#videoCallPanel").classList.toggle("ready", Boolean(available));
  $("#videoCallDetails").innerHTML = `<span>${escapeHtml(status.provider)} · ${escapeHtml(status.transport || "livekit")}</span>
    <span>${status.hasCanonicalOrApprovedFace ? tr("已有 canonical/approved 身份图") : status.hasFaceUrl ? tr("使用 North Face URL") : tr("缺少身份参考图")}</span>
    <span>${status.settings?.scene_background_enabled ? tr("背景开启") : tr("背景关闭")} · ${status.settings?.camera_flip_enabled ? tr("翻转开启") : tr("翻转关闭")}</span>`;
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
  throw new Error(tr("LiveKit SDK 加载失败，请检查网络或桌面应用的安全设置"));
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

let videoSession = null, videoTurn = null, speechRequest = null, speechGeneration = 0;
const pendingVideoReleases = new Map();
function videoSessionCurrent(session) {
  return !!session && videoSession===session && !session.cancelled && state.currentId===session.avatarId && !!state.previewMode===session.preview;
}
function requireVideoSession(session) {
  if(!videoSessionCurrent(session))throw new DOMException("Call ended", "AbortError");
}
function stopSpeechPlayback() {
  ++speechGeneration;
  speechRequest?.controller.abort();speechRequest=null;
  try {state.currentSpeechSource?.stop?.();} catch(_) {}
  state.currentSpeechSource=null;
  if(state.currentSpeechAudio){state.currentSpeechAudio.pause?.();state.currentSpeechAudio.src="";state.currentSpeechAudio=null;}
  if(state.currentSpeechURL){URL.revokeObjectURL(state.currentSpeechURL);state.currentSpeechURL=null;}
}
async function ensureLiveKitAudioTrack(session=videoSession) {
  requireVideoSession(session);
  const room=state.livekitRoom;
  if(!room||state.livekitAudioDest)return;
  if(session.audioPromise)return session.audioPromise;
  const promise=(async()=>{
    const client=await loadLiveKitClient();requireVideoSession(session);
    const context=state.livekitAudioContext||new (window.AudioContext||window.webkitAudioContext)();
    state.livekitAudioContext=context;
    const dest=context.createMediaStreamDestination();
    const silence=context.createConstantSource?context.createConstantSource():null;
    if(silence){const gain=context.createGain();gain.gain.value=0;silence.connect(gain).connect(dest);silence.start();}
    const track=dest.stream.getAudioTracks()[0];
    if(!track)throw new Error(tr("没有可发布的 LiveKit 音频轨道"));
    state.livekitAudioDest=dest;state.livekitSilenceSource=silence;state.livekitPublishedTrack=track;
    await room.localParticipant.publishTrack(track,{name:"openavatar-tts",source:client.Track?.Source?.Microphone||"microphone"});
    if(!videoSessionCurrent(session)){track.stop();try{silence?.stop();}catch(_){}throw new DOMException("Call ended","AbortError");}
    setLiveKitStatus(tr("LiveKit 已连接，复刻语音会同步推入头像音轨"));
  })();
  session.audioPromise=promise;
  try{await promise;}finally{if(session.audioPromise===promise)session.audioPromise=null;}
}
async function prepareUserMedia(session=videoSession) {
  requireVideoSession(session);
  if(!navigator.mediaDevices?.getUserMedia)return null;
  let stream;
  try{stream=await navigator.mediaDevices.getUserMedia({audio:true,video:true});}
  catch(_){requireVideoSession(session);try{stream=await navigator.mediaDevices.getUserMedia({audio:true,video:false});}catch(_){stream=null;}}
  if(!videoSessionCurrent(session)){stream?.getTracks().forEach(t=>t.stop());throw new DOMException("Call ended","AbortError");}
  state.userMedia=stream;
  state.callCameraEnabled=Boolean(stream?.getVideoTracks().length);
  state.callMicrophoneEnabled=Boolean(stream?.getAudioTracks().length);
  const cameraButton=$("[data-action='toggle-call-camera']"),microphoneButton=$("[data-action='toggle-call-microphone']");
  cameraButton?.setAttribute("aria-pressed",String(state.callCameraEnabled));
  microphoneButton?.setAttribute("aria-pressed",String(state.callMicrophoneEnabled));
  if(cameraButton)cameraButton.textContent=state.callCameraEnabled?tr("关闭摄像头"):tr("开启摄像头");
  if(microphoneButton)microphoneButton.textContent=state.callMicrophoneEnabled?tr("静音"):tr("取消静音");
  const preview=$("#localCameraPreview");
  if(preview&&stream?.getVideoTracks().length){preview.srcObject=stream;preview.classList.remove("hidden");}
  return stream;
}
async function publishUserMedia(session=videoSession) {
  requireVideoSession(session);
  const room=state.livekitRoom,stream=state.userMedia;
  if(!room||!stream)return;
  const client=await loadLiveKitClient();requireVideoSession(session);
  for(const track of stream.getTracks()){
    requireVideoSession(session);
    await room.localParticipant.publishTrack(track,{name:track.kind==="video"?"openavatar-user-camera":"openavatar-user-microphone",source:track.kind==="video"?(client.Track?.Source?.Camera||"camera"):(client.Track?.Source?.Microphone||"microphone")});
    if(!videoSessionCurrent(session)){track.stop();throw new DOMException("Call ended","AbortError");}
  }
}
async function connectNorthLiveKit(livekit,session=videoSession) {
  requireVideoSession(session);
  if(!livekit?.url||!livekit?.token)throw new Error(tr("North 没有返回完整的 LiveKit URL/token"));
  setLiveKitStatus(tr("正在连接 LiveKit 房间…"));
  const client=await loadLiveKitClient();requireVideoSession(session);
  const room=new client.Room({adaptiveStream:true,dynacast:true}),events=client.RoomEvent||{};
  session.room=room;state.livekitRoom=room;
  room.on?.(events.TrackSubscribed||"trackSubscribed",track=>{if(videoSessionCurrent(session)){attachLiveKitTrack(track);setLiveKitStatus(tr("实时头像画面已接入"));}});
  room.on?.(events.TrackUnsubscribed||"trackUnsubscribed",track=>{if(videoSessionCurrent(session)&&track?.kind==="video")liveKitStage()?.querySelectorAll("video[data-livekit-track='video']").forEach(n=>n.remove());});
  room.on?.(events.Disconnected||"disconnected",()=>{if(videoSessionCurrent(session))setLiveKitStatus(tr("LiveKit 连接已断开"),true);});
  await room.connect(livekit.url,livekit.token,{autoSubscribe:true});
  if(!videoSessionCurrent(session)){await room.disconnect();throw new DOMException("Call ended","AbortError");}
  state.livekit=livekit;
  await ensureLiveKitAudioTrack(session);await publishUserMedia(session);
}
function disconnectNorthLiveKit() {
  stopSpeechPlayback();
  try{state.livekitPublishedTrack?.stop?.();}catch(_){}
  try{state.livekitSilenceSource?.stop?.();}catch(_){}
  try{state.livekitRoom?.disconnect?.()?.catch?.(()=>null);}catch(_){}
  try{state.speechRecognition?.abort?.();}catch(_){}
  state.userMedia?.getTracks().forEach(track=>{try{track.stop();}catch(_){}});
  try{state.livekitAudioContext?.close?.()?.catch?.(()=>null);}catch(_){}
  for(const key of ["livekit","livekitRoom","livekitAudioContext","livekitAudioDest","livekitAudioPromise","livekitSilenceSource","livekitPublishedTrack","userMedia","speechRecognition"])state[key]=null;
  state.callCameraEnabled=false;state.callMicrophoneEnabled=false;
  const preview=$("#localCameraPreview");if(preview){preview.srcObject=null;preview.classList.add("hidden");}
  $("#videoCallControls")?.classList.add("hidden");
  liveKitStage()?.querySelectorAll("[data-livekit-track]").forEach(node=>node.remove());liveKitStage()?.classList.remove("connected");
}
async function releaseVideoSession(session) {
  if(!session?.call?.id)return;
  const key=`${session.avatarId}:${session.call.id}`;
  if(session.releasePromise)return session.releasePromise;
  pendingVideoReleases.set(key,session);
  const promise=api(`/api/avatars/${session.avatarId}/calls/${session.call.id}/end`,{method:"POST"}).then(result=>{
    pendingVideoReleases.delete(key);return result;
  }).catch(error=>{
    toast(ui("本机设备已关闭，远程视频会话释放失败。请点击结束通话重试，并检查服务商会话。","Local devices stopped. Remote cleanup failed. Retry End call and check the provider session."),true);
    if(state.currentId===session.avatarId&&!videoSession){
      $("#videoCallStatus").textContent=ui("远程会话释放失败，请再次点击结束通话重试。","Remote session cleanup failed. Click End call again to retry.");
      $("#videoCallDetails").innerHTML=`<button type="button" data-action="end-video-call">${ui("重试结束通话","Retry ending call")}</button>`;
    }
    throw error;
  }).finally(()=>{session.releasePromise=null;});
  session.releasePromise=promise;return promise;
}
async function endVideoCall() {
  const endingAvatar=state.currentId;
  const session=videoSession||(state.videoCall?{avatarId:state.currentId,call:state.videoCall}:null);
  if(session)session.cancelled=true;
  videoSession=null;state.videoCallStarting=false;state.videoCall=null;
  videoTurn?.controller.abort();videoTurn=null;
  disconnectNorthLiveKit();
  $("#videoCallStatus").textContent=tr("本机摄像头和麦克风已关闭。");
  const releases=[...pendingVideoReleases.values()];if(session&&!releases.includes(session))releases.push(session);
  const results=await Promise.allSettled(releases.map(releaseVideoSession));
  if(state.currentId===endingAvatar&&!videoSession&&results.every(x=>x.status==="fulfilled"))$("#videoCallStatus").textContent=tr("实时视频通话已结束。");
}
async function stopConversationMedia() {
  if(typeof endVoiceCall==="function")void endVoiceCall();
  if(typeof cancelVoiceMessage==="function")cancelVoiceMessage();
  await endVideoCall();
}
async function playSpeechBlob(blob,valid=()=>true) {
  stopSpeechPlayback();const generation=speechGeneration;
  const current=()=>generation===speechGeneration&&valid();
  if(!current())return;
  if(state.livekitRoom){
    const session=videoSession,context=state.livekitAudioContext;
    await context.resume?.();await ensureLiveKitAudioTrack(session);
    const buffer=await blob.arrayBuffer();if(!current())return;
    const decoded=await context.decodeAudioData(buffer.slice(0));if(!current())return;
    const source=context.createBufferSource();source.buffer=decoded;source.connect(context.destination);
    if(state.livekitAudioDest)source.connect(state.livekitAudioDest);
    state.currentSpeechSource=source;source.addEventListener?.("ended",()=>{if(state.currentSpeechSource===source)state.currentSpeechSource=null;},{once:true});source.start();return;
  }
  const url=URL.createObjectURL(blob),audio=new Audio(url);state.currentSpeechURL=url;state.currentSpeechAudio=audio;
  const done=()=>{URL.revokeObjectURL(url);if(state.currentSpeechAudio===audio){state.currentSpeechAudio=null;state.currentSpeechURL=null;}};
  audio.addEventListener("ended",done,{once:true});audio.addEventListener("error",done,{once:true});
  try{await audio.play();}catch(error){done();if(current())throw error;}
}
async function speakChatMessage(node) {
  if(speechRequest)return;
  if(state.videoCall||state.videoCallStarting||(typeof activeVoiceCall!=="undefined"&&activeVoiceCall?.active)){toast(tr("请先结束当前通话，再播放消息。"));return;}
  const avatarId=state.currentId,preview=!!state.previewMode,text=node.querySelector("span").textContent;
  if(!confirm(tr("使用所选声音播放会调用云端 TTS 并可能产生费用。继续吗？")))return;
  stopSpeechPlayback();
  const request={controller:new AbortController(),generation:speechGeneration};speechRequest=request;
  const valid=()=>request.generation===speechGeneration&&state.currentId===avatarId&&!!state.previewMode===preview;
  const button=node.querySelector('[data-action="speak-message"]');if(button)button.disabled=true;
  try{
    const response=await fetch(`/api/avatars/${avatarId}/speech`,{method:"POST",signal:request.controller.signal,headers:{"Content-Type":"application/json"},body:JSON.stringify({text,confirm_billable_call:true})});
    if(!valid())return;
    if(!response.ok){let detail=tr("语音生成失败");try{detail=(await response.json()).detail||detail;}catch(_){}throw new Error(systemText(detail));}
    const blob=await response.blob();if(!valid())return;
    // Release the request before the playback manager takes ownership.
    if(speechRequest===request)speechRequest=null;
    const playback=playSpeechBlob(blob,()=>state.currentId===avatarId&&!!state.previewMode===preview);
    request.generation=speechGeneration;await playback;
  }catch(error){if(error.name!=="AbortError"&&valid())throw error;}
  finally{if(speechRequest===request)speechRequest=null;if(button)button.disabled=false;}
}

function renderActiveVideoCall() {
  const call = state.videoCall;
  if (!call?.video_call) return;
  const video = call.video_call;
  $("#videoCallDetails").innerHTML = tr`<span>North session: ${escapeHtml(video.northSessionId || "")}</span>
    <span>LiveKit: ${escapeHtml(video.livekit?.room || "room pending")}</span>
    <span>计费：${Number(video.budget?.pricePerSecond || 0).toFixed(5)} / 秒</span>
    <small id="videoLiveKitStatus">正在等待 LiveKit 连接…</small>`;
}

async function startVideoCall() {
  if(!state.currentId||state.videoCallStarting||state.videoCall)return;
  if(pendingVideoReleases.size){await endVideoCall();if(pendingVideoReleases.size)return;}
  if(!confirm(ui("视频通话会向 North/LiveKit 发送身份参考图或 Face URL，以及你允许开启的摄像头和麦克风内容，并可能按时长收费。确认开始？","Video calls send identity and enabled camera/microphone streams to North/LiveKit and may incur charges. Start?")))return;
  if(typeof endVoiceCall==="function")void endVoiceCall();stopSpeechPlayback();
  const session={avatarId:state.currentId,preview:!!state.previewMode,cancelled:false,call:null};videoSession=session;state.videoCallStarting=true;
  try{
    await prepareUserMedia(session);requireVideoSession(session);
    // Do not abort creation: a late successful remote session must be explicitly released.
    session.call=await api(`/api/avatars/${session.avatarId}/calls`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mode:"video",provider:"north",user_camera_enabled:state.callCameraEnabled,confirm_billable_call:true})});
    requireVideoSession(session);state.videoCall=session.call;
    renderActiveVideoCall();await connectNorthLiveKit(session.call.video_call?.livekit,session);requireVideoSession(session);
    $("#videoCallControls").classList.remove("hidden");toast(tr("North 实时视频通话已创建"));
  }catch(error){
    if(videoSession===session){session.cancelled=true;videoSession=null;state.videoCall=null;disconnectNorthLiveKit();$("#videoCallStatus").textContent=tr("通话未能开始，本机摄像头和麦克风已关闭。");}
    if(session.call?.id)await releaseVideoSession(session).catch(()=>null);
    if(error.name!=="AbortError")throw error;
  }finally{if(!videoSession||videoSession===session)state.videoCallStarting=false;}
}
async function sendVideoTurn() {
  const input=$("#videoTranscriptInput"),message=input.value.trim(),session=videoSession;
  if(!message||!videoSessionCurrent(session)||!session.call?.id||videoTurn)return;
  const turn={controller:new AbortController()},avatarId=session.avatarId,callId=session.call.id;videoTurn=turn;
  const valid=()=>videoTurn===turn&&videoSessionCurrent(session)&&state.videoCall?.id===callId;
  const options=body=>({method:"POST",signal:turn.controller.signal,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  input.value="";$("#videoTurnStatus").textContent=tr("数字人正在理解并回复…");const started=performance.now();
  try{
    const result=await api(`/api/avatars/${avatarId}/chat`,options({message,preview_mode:session.preview}));if(!valid())return;
    await api(`/api/avatars/${avatarId}/calls/${callId}/turns`,options({user_transcript:message,assistant_text:result.reply,llm_latency_ms:Math.round(performance.now()-started),metadata:{source:"live_ui"}}));if(!valid())return;
    $("#videoTurnStatus").textContent=result.reply;
    const response=await fetch(`/api/avatars/${avatarId}/speech`,options({text:result.reply,confirm_billable_call:true}));if(!valid())return;
    if(response.ok){const blob=await response.blob();if(valid())await playSpeechBlob(blob,valid);}
    else $("#videoTurnStatus").textContent=tr`${result.reply}（当前没有可用的复刻声音，已保留文字回复）`;
  }catch(error){if(error.name!=="AbortError"&&valid())throw error;}
  finally{if(videoTurn===turn)videoTurn=null;}
}

window.addEventListener("pagehide",()=>{
  const session=videoSession;if(session)session.cancelled=true;
  if(session?.call?.id)pendingVideoReleases.set(`${session.avatarId}:${session.call.id}`,session);
  videoSession=null;state.videoCall=null;state.videoCallStarting=false;videoTurn?.controller.abort();videoTurn=null;disconnectNorthLiveKit();
  for(const item of pendingVideoReleases.values())fetch(`/api/avatars/${item.avatarId}/calls/${item.call.id}/end`,{method:"POST",keepalive:true}).catch(()=>null);
});

function listenVideoTurn() {
  const session=videoSession;if(!videoSessionCurrent(session))return;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) throw new Error(tr("当前浏览器不支持语音识别，请直接输入文字"));
  if (!confirm(ui("此功能使用浏览器自带语音识别，不使用你在本系统配置的语音 API Key。浏览器可能把麦克风音频发送到其在线识别服务，不能保证离线处理。是否继续？也可以取消并输入文字。", "This uses your browser's speech recognition, not the voice API key configured in this app. The browser may send microphone audio to its online recognition service; offline processing is not guaranteed. Continue, or cancel and type instead?"))) return;
  try { state.speechRecognition?.abort?.(); } catch (_) {}
  try { state.currentSpeechSource?.stop?.(); } catch (_) {}
  const recognition = new Recognition();
  recognition.lang = state.current?.avatar_primary_language === "en-US" ? "en-US" : "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = event => {
    if(!videoSessionCurrent(session))return;
    $("#videoTranscriptInput").value = [...event.results].map(result => result[0].transcript).join("");
  };
  recognition.onend = () => { if(!videoSessionCurrent(session))return; $("#videoTurnStatus").textContent = tr("语音识别结束，请检查文字后发送。"); };
  recognition.onerror = event => { if(!videoSessionCurrent(session))return; $("#videoTurnStatus").textContent = tr`语音识别不可用：${event.error}`; };
  state.speechRecognition = recognition;
  recognition.start();
  $("#videoTurnStatus").textContent = tr("正在听，请自然说话…");
}

