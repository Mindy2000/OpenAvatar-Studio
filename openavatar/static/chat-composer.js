/* One conversation composer: text, voice notes, local media and calls. */
const chatIcons = {
  mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
  keyboard:'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M5 9h2m2 0h2m2 0h2m2 0h2M5 12h2m2 0h2m2 0h2m2 0h2M7 16h10"/>',
  smile:'<circle cx="12" cy="12" r="9"/><path d="M8 14c2 3 6 3 8 0M8 8v2m8-2v2"/>',
  plus:'<circle cx="12" cy="12" r="9"/><path d="M12 7v10M7 12h10"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',
  camera:'<path d="M3 7h4l2-3h6l2 3h4v14H3z"/><circle cx="12" cy="13" r="4"/>',
  phone:'<path d="M5 3h4l2 5-3 2c2 3 3 4 6 6l2-3 5 2v4c0 3-7 1-12-4S2 3 5 3z"/>',
  file:'<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8M8 16h6"/>',
  pin:'<path d="M19 9c0 5-7 12-7 12S5 14 5 9a7 7 0 0 1 14 0z"/><circle cx="12" cy="9" r="2"/>',
  star:'<path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/>'
};
function chatIcon(name) { return tr`<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${chatIcons[name] || chatIcons.file}</svg>`; }
$$('[data-icon]').forEach(node => node.innerHTML = chatIcon(node.dataset.icon));
const chatMediaKinds = new Set(['image','video','audio','file']);
function renderChatMessage(row) {
  const meta = row.attachment || {};
  // Only the local attachment route is embeddable; arbitrary URLs never become HTML.
  const media = /^\/api\/avatars\/[a-zA-Z0-9_-]+\/messages\/\d+\/file$/.test(row.media_url || '') ? row.media_url : '';
  const name = escapeHtml(meta.name || tr('附件')).replaceAll('"', '&quot;');
  let content = tr`<span>${escapeHtml(row.content)}</span>`;
  if (row.message_kind === 'image' && media) content = tr`<a href="${media}" target="_blank" rel="noopener"><img class="chat-message-image" src="${media}" alt="${name}" loading="lazy"></a><div class="image-understanding-status">${meta.vision?.status==='done' ? tr('已看过这张图片') : `<button type="button" class="secondary" data-understand-image="${Number(row.id)}">${meta.vision?.status==='failed'?tr('重试看图'):tr('让她看图')}</button>`}</div>`;
  if (row.message_kind === 'video' && media) content = tr`<video class="chat-message-video" controls preload="metadata" src="${media}"></video>`;
  if (row.message_kind === 'audio' && media) content = tr`<div class="voice-note-label">${chatIcon('mic')} 语音消息 · ${Math.ceil(meta.duration || 0)}秒</div><audio controls preload="metadata" src="${media}"></audio>${row.content.startsWith('[语音]') ? '' : `<p class="voice-note-text">${escapeHtml(row.content)}</p>`}`;
  if (row.message_kind === 'file' && media) content = tr`<a class="chat-file-card" href="${media}?download=true" download>${chatIcon('file')}<span><b>${name}</b><small>${formatChatSize(meta.size)} · 点击下载</small></span></a>`;
  if (typeof renderChatDocumentControls === 'function') content += renderChatDocumentControls(row);
  if (typeof renderChatDocumentSource === 'function') content += renderChatDocumentSource(row);
  if (row.message_kind === 'location') content = tr`<div class="chat-location-card">${chatIcon('pin')}<span><b>${name}</b><small>${escapeHtml(meta.address || tr('分享的地点'))}</small></span></div>`;
  if (row.message_kind === 'call') return tr`<div class="chat-call-record">${chatIcon('phone')} ${Number.isFinite(meta.duration) ? tr`语音通话 ${String(Math.floor(meta.duration/60)).padStart(2,'0')}:${String(meta.duration%60).padStart(2,'0')}` : escapeHtml(row.content)}</div>`;
  return tr`<div class="message ${row.role === 'user' ? 'user' : 'assistant'} ${row.channel === 'proactive' ? 'proactive' : ''}" data-message-id="${Number(row.id)}">${content}<div class="message-tools">${typeof renderChatMemoryAction === 'function' ? renderChatMemoryAction(row) : ''}<button type="button" data-chat-favorite="${Number(row.id)}" data-starred="${!!row.starred}" aria-label="${row.starred ? tr('取消收藏') : tr('收藏消息')}" title="${row.starred ? tr('取消收藏') : tr('收藏消息')}">${row.starred ? '★' : '☆'}</button>${row.role === 'assistant' && !chatMediaKinds.has(row.message_kind) ? tr('<button type="button" class="message-audio" data-action="speak-message" title="使用所选声音播放">♫</button>') : ''}</div></div>`;
}
function formatChatSize(bytes=0) { return bytes > 1048576 ? `${(bytes/1048576).toFixed(1)} MB` : `${Math.max(1,Math.round(bytes/1024))} KB`; }
function closeComposerPanels() {
  $('#chatMorePanel').hidden = true; $('#chatEmojiPanel').hidden = true;
  $('#toggleChatMore').setAttribute('aria-expanded','false'); $('#toggleEmoji').setAttribute('aria-expanded','false');
}
function toggleComposerPanel(id, button) {
  const opening = $(id).hidden; closeComposerPanels(); $(id).hidden = !opening;
  $(button).setAttribute('aria-expanded',String(opening));
}
$('#toggleChatMore').onclick = () => toggleComposerPanel('#chatMorePanel','#toggleChatMore');
$('#toggleEmoji').onclick = () => toggleComposerPanel('#chatEmojiPanel','#toggleEmoji');
$('#chatEmojiPanel').innerHTML = ['😀','😊','🥰','😘','🤗','🥺','😂','😴','❤️','🌷','🌻','☀️','☕','🍰','👍','👋','🎉','✨','🌙','📚'].map(x=>`<button type="button" data-chat-emoji="${x}" aria-label="${x}">${x}</button>`).join('');
$('#chatMessageInput').addEventListener('input',()=> { $('#sendChatText').hidden = !$('#chatMessageInput').value.trim(); });
$('#chatMessageInput').addEventListener('keydown',event=> { if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#chatForm').requestSubmit();} });
$('#chatMessageInput').addEventListener('focus',closeComposerPanels);
$('#chatMore').onclick=()=> { $('[data-tab="settings"]').click(); };
async function refreshChatHeader() {
  const id = state.currentId, avatar = state.current;
  $('#chatPersonName').textContent = avatar.name;
  $('#chatAvatar').textContent = avatar.name.slice(0,1);
  try {
    const assets = await api(`/api/avatars/${id}/visual-assets`);
    if(state.currentId!==id) return;
    const selected = assets.find(x=>x.status==='canonical');
    if(selected?.asset_url) { const image = document.createElement('img'); image.alt=avatar.name; image.src=selected.asset_url; $('#chatAvatar').replaceChildren(image); }
  } catch (_) {}
}
let pendingChatAttachment=null, attachmentObjectURL='', chatCameraStream=null, chatCaptureGeneration=0, composerGeneration=0;
function clearChatAttachment() {
  if(attachmentObjectURL) URL.revokeObjectURL(attachmentObjectURL);
  attachmentObjectURL='';pendingChatAttachment=null;$('#attachmentPreview').replaceChildren();
}
function previewChatAttachment(file,kind,options={}) {
  clearChatAttachment();
  pendingChatAttachment={generation:composerGeneration,file,kind,avatarId:state.currentId,preview:state.previewMode,key:crypto.randomUUID(),...options};
  attachmentObjectURL=URL.createObjectURL(file);
  $('#attachmentTitle').textContent=kind==='audio'?tr('发送语音消息'):tr('发送附件');
  const node=document.createElement(kind==='image'?'img':kind==='video'?'video':kind==='audio'?'audio':'div');
  if(kind==='file') {node.className='attachment-file-name';node.textContent=`${file.name} · ${formatChatSize(file.size)}`;} else {node.src=attachmentObjectURL;if(kind!=='image')node.controls=true;node.alt=file.name;}
  $('#attachmentPreview').append(node);
  $('#voiceTranscriptLabel').hidden=kind!=='audio';$('#voiceMessageTranscript').value=options.transcript||'';
  $('#attachmentNote').textContent=kind==='audio'?tr('录音保存在聊天中。有识别文字时，发送后会按该文字请求人物回复，使用已配置的对话服务。没有文字时只发送录音。'):tr('发送后保存在本机聊天记录中；图片和文件内容不会自动上传给AI解读。');
  if(kind==='image') {
    $('#attachmentNote').textContent=tr('图片发送后会交给已配置的看图服务读取并回复，可能产生费用。');
    const draft=pendingChatAttachment;
    api(`/api/avatars/${draft.avatarId}/image-understanding`).then(info=>{
      if(pendingChatAttachment!==draft)return;
      $('#attachmentNote').textContent=info.ready ? tr`图片会交给${info.provider}读取并回复，可能产生费用。` : tr('当前尚未接通看图服务：发送后仅保存照片，可配置后点击“让她看图”。');
    }).catch(()=>{});
  }
  $('#attachmentError').textContent='';$('#sendChatAttachment').disabled=false;$('#sendChatAttachment').textContent=tr('发送');
  closeComposerPanels();$('#chatAttachmentDialog').showModal();
}
$('#chatMediaPicker').onchange=event=>{const f=event.target.files[0];if(f)previewChatAttachment(f,f.type.startsWith('video/')?'video':'image');event.target.value='';};
$('#chatFilePicker').onchange=event=>{const f=event.target.files[0];if(f)previewChatAttachment(f,'file');event.target.value='';};
$('#sendChatAttachment').onclick=async()=>{
  const draft=pendingChatAttachment;if(!draft||draft.sending||draft.avatarId!==state.currentId||!!draft.preview!==!!state.previewMode)return;
  draft.sending=true;const transcript=$('#voiceMessageTranscript').value.trim();
  const belongs=()=>draft.generation===composerGeneration&&state.currentId===draft.avatarId&&!!state.previewMode===!!draft.preview;
  const ownsDraft=()=>pendingChatAttachment===draft;
  const button=$('#sendChatAttachment');button.disabled=true;button.textContent=tr('发送中…');$('#attachmentError').textContent='';
  try {
    const query=new URLSearchParams({kind:draft.kind,preview_mode:String(!!draft.preview),duration:String(draft.duration||0),client_key:draft.key});
    const response=await fetch(`/api/avatars/${draft.avatarId}/messages/attachment?${query}`,{method:'POST',headers:{'X-File-Name':encodeURIComponent(draft.file.name),'Content-Type':draft.file.type||'application/octet-stream'},body:draft.file});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||tr('附件发送失败'));
    if(!ownsDraft()||!belongs())return;
    $('#chatAttachmentDialog').close();
    await loadMessages();
    if(!belongs()||pendingChatAttachment)return;
    if(draft.kind==='audio'&&transcript) await sendTextMessage(transcript,result.id);
    if(draft.kind==='image') await understandChatImage(result.id,draft.avatarId,!!draft.preview);
  } catch(error) {if(ownsDraft()&&belongs()){$('#attachmentError').textContent=error.message;button.textContent=tr('重试发送');}}
  finally {draft.sending=false;if(ownsDraft())button.disabled=false;}
};
function syncChatCameraMirror() { $('#chatCameraPreview').classList.toggle('camera-mirrored', $('#chatCameraMirror').checked); }
$('#chatCameraMirror').onchange=syncChatCameraMirror;
function stopChatCamera() { ++chatCaptureGeneration; chatCameraStream?.getTracks().forEach(t=>t.stop());chatCameraStream=null;$('#chatCameraPreview').srcObject=null; }
async function openChatCamera() {
  closeComposerPanels();syncChatCameraMirror();$('#chatCameraDialog').showModal();$('#captureChatPhoto').disabled=true;
  $('#cameraStatus').textContent=tr('正在请求摄像头权限…');const generation=++chatCaptureGeneration;
  try {
    const stream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    if(generation!==chatCaptureGeneration||!$('#chatCameraDialog').open){stream.getTracks().forEach(t=>t.stop());return;}
    chatCameraStream=stream;$('#chatCameraPreview').srcObject=stream;
    $('#chatCameraPreview').onloadedmetadata=()=>{$('#captureChatPhoto').disabled=false;};
    $('#cameraStatus').textContent=tr('只在本机预览，拍好后确认发送。');
  } catch(error){$('#cameraStatus').textContent=tr('无法打开摄像头，请检查权限，也可以从“图片 / 视频”选择文件。');}
}
$('#captureChatPhoto').onclick=()=> {
  const video=$('#chatCameraPreview');if(!video.videoWidth)return;
  const avatarId=state.currentId,canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;
  const context=canvas.getContext('2d');
  if($('#chatCameraMirror').checked) { context.translate(canvas.width,0);context.scale(-1,1); }
  context.drawImage(video,0,0);
  canvas.toBlob(blob=>{if(!blob||state.currentId!==avatarId||!$('#chatCameraDialog').open)return;$('#chatCameraDialog').close();previewChatAttachment(new File([blob],`照片-${Date.now()}.jpg`,{type:'image/jpeg'}),'image');},'image/jpeg',0.9);
};
$('#chatCameraDialog').addEventListener('close',stopChatCamera);
$('#chatAttachmentDialog').addEventListener('close',clearChatAttachment);
$('#chatLocationForm').onsubmit=async event=>{
  event.preventDefault();const form=event.currentTarget,id=state.currentId,button=form.querySelector('button.chat-send');button.disabled=true;
  try { await api(`/api/avatars/${id}/messages/location`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:form.elements.place.value,address:form.elements.address.value,preview_mode:!!state.previewMode,client_key:form.dataset.sendKey})});$('#chatLocationDialog').close();if(state.currentId===id)await loadMessages();}
  catch(error){form.querySelector('[role="alert"]').textContent=error.message;}finally{button.disabled=false;}
};
async function openChatFavorites() {
  const id=state.currentId;$('#chatFavoritesDialog').showModal();$('#chatFavoritesList').textContent=tr('正在加载…');
  try {const rows=await api(`/api/avatars/${id}/favorites`);if(state.currentId!==id)return;
    $('#chatFavoritesList').innerHTML=rows.length?rows.map(row=>tr`<article class="favorite-item">${renderChatMessage(row)}<button type="button" data-chat-resend="${row.id}" class="chat-send">发送到聊天</button></article>`).join(''):tr('还没有收藏。点击消息旁的 ☆ 可以收藏文字、图片、文件和语音。');
  }catch(error){$('#chatFavoritesList').textContent=error.message;}
}
const imageUnderstandingInFlight = new Set();
async function understandChatImage(messageId,avatarId=state.currentId,preview=!!state.previewMode) {
  const key=`${avatarId}:${messageId}`;
  if(imageUnderstandingInFlight.has(key))return;
  imageUnderstandingInFlight.add(key);
  const buttons=Array.from(document.querySelectorAll(`[data-understand-image="${messageId}"]`));
  buttons.forEach(b=>{b.disabled=true;b.textContent=tr('正在看图…');});
  try {
    await api(`/api/avatars/${avatarId}/messages/${messageId}/understand`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm_billable_call:true,preview_mode:preview})});
  } catch(error) { toast(error.message,true); }
  finally {
    imageUnderstandingInFlight.delete(key);
    if(state.currentId===avatarId) { delete $('#messageList').dataset.signature;await loadMessages(); }
    buttons.forEach(b=>{b.disabled=false;b.textContent=tr('重试看图');});
  }
}
document.addEventListener('click',async event=>{
  const imageButton=event.target.closest('[data-understand-image]');if(imageButton){await understandChatImage(Number(imageButton.dataset.understandImage));return;}
  const close=event.target.closest('[data-close-chat-dialog]');if(close){close.closest('dialog').close();return;}
  const emoji=event.target.closest('[data-chat-emoji]');if(emoji){if(voiceNoteMode)$('#toggleVoiceMessage').onclick();const input=$('#chatMessageInput');input.value+=emoji.dataset.chatEmoji;input.dispatchEvent(new Event('input'));return;}
  const tool=event.target.closest('[data-chat-tool]')?.dataset.chatTool;
  if(tool==='image')$('#chatMediaPicker').click();
  if(tool==='file')$('#chatFilePicker').click();
  if(tool==='camera')openChatCamera();
  if(tool==='call'){cancelVoiceMessage();closeComposerPanels();$('#callChoiceDialog').showModal();}
  if(tool==='favorites'){closeComposerPanels();openChatFavorites();}
  if(tool==='location'){closeComposerPanels();$('#chatLocationForm').reset();$('#chatLocationForm').dataset.sendKey=crypto.randomUUID();$('#chatLocationForm [role="alert"]').textContent='';$('#chatLocationDialog').showModal();}
  const favorite=event.target.closest('[data-chat-favorite]');
  if(favorite){favorite.disabled=true;try{await api(`/api/avatars/${state.currentId}/messages/${favorite.dataset.chatFavorite}/favorite`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({starred:favorite.dataset.starred!=='true'})});await loadMessages();if($('#chatFavoritesDialog').open)await openChatFavorites();}catch(error){toast(error.message,true);}finally{favorite.disabled=false;}}
  const resend=event.target.closest('[data-chat-resend]');
  if(resend){resend.disabled=true;const id=state.currentId;try{await api(`/api/avatars/${id}/messages/${resend.dataset.chatResend}/resend`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:tr('收藏'),client_key:resend.dataset.sendKey||(resend.dataset.sendKey=crypto.randomUUID()),preview_mode:!!state.previewMode})});$('#chatFavoritesDialog').close();if(state.currentId===id)await loadMessages();}catch(error){toast(error.message,true);}finally{resend.disabled=false;}}
});
$('#chooseVideoCall').onclick=()=>{cancelVoiceMessage();$('#callChoiceDialog').close();$('#chatVideoDialog').showModal();};
$('#chatVideoDialog').addEventListener('close',()=>{if(state.videoCallStarting)void endVideoCall();});
$('#chatVideoDialog').addEventListener('cancel',event=>{if(state.videoCall?.id){event.preventDefault();toast(tr('请先结束视频通话，再关闭窗口。'));}});
// Avoid silently discarding an active video call when the close button is clicked.
$('#chatVideoDialog [data-close-chat-dialog]').removeAttribute('data-close-chat-dialog');
$('#chatVideoDialog .chat-dialog-heading button').onclick=()=>{if(state.videoCall?.id)toast(tr('请先结束视频通话，再关闭窗口。'));else $('#chatVideoDialog').close();};
let voiceNote=null,voiceNoteGeneration=0,voiceNoteMode=false,voiceSending=false;
function voiceNoteNotice(text) {$('#composerNotice').textContent=text;$('#composerNotice').hidden=!text;}
$('#toggleVoiceMessage').onclick=()=>{
  cancelVoiceMessage();voiceNoteMode=!voiceNoteMode;closeComposerPanels();
  $('#chatMessageInput').hidden=voiceNoteMode;$('#holdVoiceMessage').hidden=!voiceNoteMode;
  $('#toggleVoiceMessage').innerHTML=chatIcon(voiceNoteMode?'keyboard':'mic');$('#toggleVoiceMessage').setAttribute('aria-pressed',String(voiceNoteMode));$('#toggleVoiceMessage').setAttribute('aria-label',voiceNoteMode?tr('切换到文字输入'):tr('切换到语音消息'));
  const explained = localStorage.getItem('voice-note-direct-explained');
  voiceNoteNotice(voiceNoteMode?(explained?tr('按住说话，松开发送，上滑取消。'):tr('按住说话，松开发送，上滑取消。识别可能使用浏览器服务，发送后按识别文字请求人物回复，可能产生对话费用。')):'');
  if(voiceNoteMode) localStorage.setItem('voice-note-direct-explained','1');
};
function cancelVoiceMessage() {++voiceNoteGeneration;voiceSending=false;if(voiceNote){voiceNote.cancelled=true;clearTimeout(voiceNote.timer);voiceNote.recognition?.abort();if(voiceNote.recorder?.state==='recording')voiceNote.recorder.stop();voiceNote.stream?.getTracks().forEach(t=>t.stop());voiceNote=null;}$('#holdVoiceMessage').classList.remove('recording','cancelling');$('#holdVoiceMessage').textContent=tr('按住说话');}
async function startVoiceMessage(event) {
  if(event.button && event.button!==0)return;event.preventDefault();
  if(voiceSending){voiceNoteNotice(tr('上一条语音正在发送…'));return;}
  if(activeVoiceCall?.active||state.videoCall?.id){voiceNoteNotice(tr('请先结束当前通话，再录制语音消息。'));return;}
  cancelVoiceMessage();if(event.pointerId!==undefined)event.currentTarget.setPointerCapture(event.pointerId);const generation=voiceNoteGeneration;
  const note={generation,avatarId:state.currentId,started:Date.now(),chunks:[],transcript:'',startY:event.clientY,cancelled:false,preview:!!state.previewMode,key:crypto.randomUUID()};voiceNote=note;
  $('#holdVoiceMessage').textContent=tr('正在开启麦克风…');
  try {
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw new Error(tr('当前浏览器不支持录音，请使用 Chrome。'));
    note.stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(generation!==voiceNoteGeneration||note.cancelled){note.stream.getTracks().forEach(t=>t.stop());return;}
    const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(x=>MediaRecorder.isTypeSupported(x));
    note.recorder=new MediaRecorder(note.stream,mime?{mimeType:mime}:{});note.started=Date.now();
    note.recorder.ondataavailable=e=>{if(e.data.size)note.chunks.push(e.data);};
    note.recorder.onstop=async()=>{
      note.stream.getTracks().forEach(t=>t.stop());try{note.recognition?.stop();}catch(_){}clearTimeout(note.timer);
      if(note.cancelled||generation!==voiceNoteGeneration||state.currentId!==note.avatarId||!note.chunks.length){if(generation===voiceNoteGeneration)voiceSending=false;return;}
      const type=note.recorder.mimeType,extension=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';
      const blob=new Blob(note.chunks,{type});
      voiceSending=true;
      if(note.recognitionDone) await Promise.race([note.recognitionDone,new Promise(resolve=>setTimeout(resolve,1000))]);
      note.recognition?.abort();
      if(generation!==voiceNoteGeneration||state.currentId!==note.avatarId){if(generation===voiceNoteGeneration)voiceSending=false;return;}
      note.file=new File([blob],`语音-${Date.now()}.${extension}`,{type});
      await sendDirectVoiceNote(note);
    };
    const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(Recognition){
      note.recognition=new Recognition();
      note.recognitionDone=new Promise(resolve=>{note.recognition.onend=resolve;note.recognition.onerror=resolve;});
      note.recognition.lang=state.current?.language_profile?.avatar_primary_language?.startsWith('en')?'en-US':'zh-CN';
      note.recognition.continuous=true;note.recognition.interimResults=true;
      note.recognition.onresult=e=>{note.transcript=Array.from(e.results).map(x=>x[0].transcript).join('');};
      try{note.recognition.start();}catch(_){}
    }
    $('#voiceMessageTranscript').dataset.edited='';note.recorder.start();$('#holdVoiceMessage').textContent=tr('松开发送 · 上滑取消');$('#holdVoiceMessage').classList.add('recording');
    note.timer=setTimeout(()=>finishVoiceMessage(),60000);
  }catch(error){cancelVoiceMessage();voiceNoteNotice(error.message||tr('麦克风不可用，请检查权限。'));}
}
async function sendDirectVoiceNote(note) {
  const generation=note.generation??voiceNoteGeneration;
  const belongs=()=>generation===voiceNoteGeneration&&state.currentId===note.avatarId&&!!state.previewMode===!!note.preview;
  if(!belongs())return;
  voiceSending=true;voiceNoteNotice(tr('语音发送中…'));
  try {
    const query=new URLSearchParams({kind:'audio',preview_mode:String(note.preview),duration:String(note.duration),client_key:note.key});
    const response=await fetch(`/api/avatars/${note.avatarId}/messages/attachment?${query}`,{method:'POST',headers:{'X-File-Name':encodeURIComponent(note.file.name),'Content-Type':note.file.type},body:note.file});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||tr('语音发送失败'));
    if(!belongs())return;
    await loadMessages();
    if(!belongs())return;
    voiceNoteNotice(note.transcript?tr('语音已发送'):tr('语音已发送，未识别到文字。可以补发一条文字消息。'));
    if(note.transcript)await sendTextMessage(note.transcript,result.id);
  } catch(error) {
    if(!belongs())return;
    voiceNoteNotice(tr`语音未发送：${error.message} `);
    const retry=document.createElement('button');retry.type='button';retry.textContent=tr('重试发送');
    retry.onclick=()=>{if(!voiceSending)sendDirectVoiceNote(note);};$('#composerNotice').append(retry);
  } finally {if(generation===voiceNoteGeneration)voiceSending=false;}
}
function finishVoiceMessage(event) {
  const note=voiceNote;if(!note)return;
  if(event?.clientY && note.startY-event.clientY>70){cancelVoiceMessage();voiceNoteNotice(tr('已取消录音'));return;}
  if(!note.recorder||note.recorder.state!=='recording'){cancelVoiceMessage();return;}
  note.duration=Math.min(60,(Date.now()-note.started)/1000);
  if(note.duration<0.5){cancelVoiceMessage();voiceNoteNotice(tr('说话时间太短，未发送。'));return;}
  $('#holdVoiceMessage').classList.remove('recording','cancelling');$('#holdVoiceMessage').textContent=tr('按住说话');voiceSending=true;note.recorder.stop();voiceNote=null;
}
$('#holdVoiceMessage').addEventListener('pointerdown',startVoiceMessage);
window.addEventListener('pointerup',finishVoiceMessage);
$('#holdVoiceMessage').addEventListener('pointercancel',cancelVoiceMessage);
$('#holdVoiceMessage').addEventListener('pointermove',event=>{if(voiceNote?.recorder?.state==='recording'){const cancel=voiceNote.startY-event.clientY>70;$('#holdVoiceMessage').classList.toggle('cancelling',cancel);$('#holdVoiceMessage').textContent=cancel?tr('松开取消'):tr('松开发送 · 上滑取消');}});
$('#holdVoiceMessage').addEventListener('keydown',event=>{if((event.key===' '||event.key==='Enter')&&!event.repeat)startVoiceMessage(event);});
$('#holdVoiceMessage').addEventListener('keyup',event=>{if(event.key===' '||event.key==='Enter')finishVoiceMessage();});
$('#voiceMessageTranscript').addEventListener('input',()=>{$('#voiceMessageTranscript').dataset.edited='true';});
function resetChatComposer() {
  ++composerGeneration;
  cancelVoiceMessage();stopChatCamera();closeComposerPanels();
  for(const id of ['chatAttachmentDialog','chatCameraDialog','chatLocationDialog','chatFavoritesDialog','callChoiceDialog'])$("#"+id).close();
  $('#chatMessageInput').value='';$('#chatMessageInput').dispatchEvent(new Event('input'));
}
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelVoiceMessage();stopChatCamera();}});
window.addEventListener('pagehide',()=>{cancelVoiceMessage();stopChatCamera();});
document.addEventListener('click',event=>{if(event.target.closest('[data-tab],[data-action="home"]'))resetChatComposer();});
function fitConversationHeight() {
  const panel=$('#chatTab');if(panel.classList.contains('hidden')||$('#studioView').classList.contains('hidden'))return;
  const top=panel.getBoundingClientRect().top;
  panel.style.height=`${Math.max(300,(window.visualViewport?.height||innerHeight)-top)}px`;
}
window.addEventListener('resize',fitConversationHeight);
window.visualViewport?.addEventListener('resize',fitConversationHeight);
new ResizeObserver(()=>requestAnimationFrame(fitConversationHeight)).observe($('.studio-sidebar'));

// Refresh dynamic controls too; message content and attachment filenames stay intact.
async function refreshChatLanguage() {
  $('#toggleVoiceMessage').setAttribute('aria-label', voiceNoteMode ? tr('切换到文字输入') : tr('切换到语音消息'));
  if (!voiceNote) $('#holdVoiceMessage').textContent = tr('按住说话');
  if (voiceNoteMode && !voiceNote && !voiceSending) voiceNoteNotice(tr('按住说话，松开发送，上滑取消。'));
  if ($('#chatFavoritesDialog').open) await openChatFavorites();
  if (activeVoiceCall?.active) voiceCallControls(activeVoiceCall);
  else if ($('#voiceCallDialog').open) await openVoiceWindow();
}
