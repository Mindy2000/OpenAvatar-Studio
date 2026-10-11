/* Isolated interaction lifecycle regression: no browser devices or cloud requests. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=name=>fs.readFileSync(path.join(root,'openavatar/static',name),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const results=[];
function fixture() {
  const nodes=new Map(),requests=[],apis=[],sent=[],played=[],revoked=[];
  let serial=0,stopped=0;
  const element=()=>({open:false,hidden:false,value:'',textContent:'',dataset:{},innerHTML:'',srcObject:null,
    classList:{add(){},remove(){},toggle(){},contains(){return false;}},listeners:{},
    addEventListener(n,fn){this.listeners[n]=fn;},setAttribute(){},removeAttribute(){},replaceChildren(){},append(){},appendChild(){},remove(){},dispatchEvent(){},getBoundingClientRect(){return{top:0};},
    showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},querySelector(){return element();},querySelectorAll(){return[];},reset(){}});
  const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const state={currentId:'avatar-a',previewMode:false,current:{name:'A'},videoCall:null,livekitRoom:null};
  const context=vm.createContext({state,$,$$:()=>[],Number,Set,URLSearchParams,AbortController,Blob,Event,DOMException,
    document:{addEventListener(){},querySelectorAll:()=>[],createElement:element,head:element()},
    window:{addEventListener(){},visualViewport:{addEventListener(){}}},navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}],getAudioTracks:()=>[],getVideoTracks:()=>[]})}},
    activeVoiceCall:null,crypto:{randomUUID:()=>`fixture-${++serial}`},localStorage:{getItem:()=>'',setItem(){}},
    URL:{createObjectURL:()=>`blob:${++serial}`,revokeObjectURL:value=>revoked.push(value)},
    Audio:class{constructor(url){this.url=url;}addEventListener(){}pause(){this.paused=true;}play(){played.push({url:this.url,avatar:state.currentId});return Promise.resolve();}},
    ResizeObserver:class{observe(){}},requestAnimationFrame(){},setTimeout,clearTimeout,performance:{now:()=>1},
    tr:(x,...args)=>Array.isArray(x)?x.reduce((s,v,i)=>s+v+(args[i]??''),''):x,ui:(_zh,en)=>en,escapeHtml:x=>x,systemText:x=>x,confirm:()=>true,toast(){},
    api:async(url,options)=>{apis.push({url,options});return{};},
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
    loadMessages:async()=>{},sendTextMessage:async(text,id)=>sent.push({text,sourceId:id,avatar:state.currentId,preview:state.previewMode}),
  });
  return{context,state,$,nodes,requests,apis,sent,played,revoked,getStopped:()=>stopped};
}
function action(f,name,next){
  const s=source('app.js'),start=s.indexOf(`    if (action === "${name}")`),end=s.indexOf(`    if (action === "${next}")`,start);
  assert.ok(start>=0&&end>start);
  vm.runInContext(`globalThis.runAction=async()=>{const action=${JSON.stringify(name)};${s.slice(start,end)}};`,f.context);
}
function activeVideo(f,id=40) {
  f.state.videoCall={id};
  vm.runInContext('videoSession={avatarId:state.currentId,preview:!!state.previewMode,call:state.videoCall,cancelled:false}',f.context);
}
(async()=>{
  for(const destination of ['avatar','preview','cancel']) {
    const f=fixture();vm.runInContext(source('chat-composer.js'),f.context);
    let releaseLoad;f.context.loadMessages=()=>new Promise(resolve=>releaseLoad=resolve);
    const pending=f.context.sendDirectVoiceNote({avatarId:'avatar-a',preview:false,key:'voice-1',duration:1,file:{name:'voice.webm',type:'audio/webm'},transcript:'Old voice'});
    f.requests[0].resolve({ok:true,json:async()=>({id:12})});await tick();
    if(destination==='avatar')f.state.currentId='avatar-b';
    if(destination==='preview')f.state.previewMode=true;
    if(destination==='cancel')f.context.cancelVoiceMessage();
    releaseLoad();await pending;assert.equal(f.sent.length,0);
    results.push(`I-VOICE-LATE: ${destination}`);
  }
  {
    const f=fixture();vm.runInContext(source('chat-composer.js'),f.context);
    f.context.previewChatAttachment({name:'first.txt',type:'text/plain',size:4},'file');
    const sending=f.$('#sendChatAttachment').onclick();await f.$('#sendChatAttachment').onclick();assert.equal(f.requests.length,1);
    f.$('#chatAttachmentDialog').close();f.context.previewChatAttachment({name:'second.txt',type:'text/plain',size:5},'file');
    f.requests[0].resolve({ok:true,json:async()=>({id:13})});await sending;
    assert.equal(f.$('#chatAttachmentDialog').open,true);assert.equal(vm.runInContext('pendingChatAttachment.file.name',f.context),'second.txt');
    assert.equal(f.$('#sendChatAttachment').disabled,false);results.push('I-ATTACHMENT-DRAFT: old completion preserves new draft');
  }
  {
    const f=fixture();vm.runInContext(source('chat-composer.js'),f.context);
    f.context.previewChatAttachment({name:'voice.webm',type:'audio/webm',size:4},'audio');f.$('#voiceMessageTranscript').value='captured';
    let releaseLoad;f.context.loadMessages=()=>new Promise(resolve=>releaseLoad=resolve);
    const sending=f.$('#sendChatAttachment').onclick();f.requests[0].resolve({ok:true,json:async()=>({id:13})});await tick();
    f.state.previewMode=true;releaseLoad();await sending;assert.equal(f.sent.length,0);results.push('I-ATTACHMENT-DRAFT: no stale audio continuation');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);
    let permit,stopped=0;f.context.navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>permit=resolve);
    const starting=f.context.startVideoCall();await f.context.stopConversationMedia();f.state.currentId='avatar-b';
    permit({getTracks:()=>[{stop(){stopped++;}}],getAudioTracks:()=>[],getVideoTracks:()=>[]});await starting;
    assert.equal(stopped,1);assert.equal(f.apis.length,0);assert.equal(f.state.videoCall,null);results.push('I-VIDEO-LIFECYCLE: cancelled permission never creates remote session');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);
    let release;f.context.api=(url,options)=>{f.apis.push({url,options});return url.endsWith('/calls')?new Promise(resolve=>release=resolve):Promise.resolve({});};
    const starting=f.context.startVideoCall();await tick();await f.context.endVideoCall();f.state.currentId='avatar-b';
    release({id:20,video_call:{livekit:{}}});await starting;
    assert.equal(f.state.videoCall,null);assert.deepEqual(f.apis.map(x=>x.url),['/api/avatars/avatar-a/calls','/api/avatars/avatar-a/calls/20/end']);
    results.push('I-VIDEO-LIFECYCLE: late creation released under original owner');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);activeVideo(f,30);
    let stopped=0,fail;f.state.userMedia={getTracks:()=>[{stop(){stopped++;}}]};
    f.context.api=()=>new Promise((_,reject)=>fail=reject);
    const ending=f.context.endVideoCall();assert.equal(stopped,1);assert.equal(f.state.videoCall,null);
    fail(new Error('remote unavailable'));await ending;
    assert.equal(vm.runInContext('pendingVideoReleases.size',f.context),1);
    assert.match(f.$('#videoCallDetails').innerHTML,/end-video-call/);
    f.context.api=async()=>({});await f.context.endVideoCall();assert.equal(vm.runInContext('pendingVideoReleases.size',f.context),0);
    results.push('I-VIDEO-LIFECYCLE: local stop precedes failed remote end; retry retained');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);activeVideo(f);
    let connect,disconnected=0;f.context.window.LivekitClient={Room:class{on(){}connect(){return new Promise(resolve=>connect=resolve);}disconnect(){disconnected++;return Promise.resolve();}}};
    const pending=f.context.connectNorthLiveKit({url:'fixture',token:'fixture'});await tick();await f.context.endVideoCall();connect();
    await assert.rejects(pending,{name:'AbortError'});assert.ok(disconnected>=1);assert.equal(f.state.livekitRoom,null);
    results.push('I-VIDEO-LIFECYCLE: cancelled connecting room never publishes media');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);activeVideo(f);f.$('#videoTranscriptInput').value='Old question';
    let reply;f.context.api=(url,options)=>{f.apis.push({url,options});return url.endsWith('/chat')?new Promise(resolve=>reply=resolve):Promise.resolve({});};
    const pending=f.context.sendVideoTurn();f.$('#videoTranscriptInput').value='duplicate';await f.context.sendVideoTurn();assert.equal(f.apis.length,1);
    await f.context.endVideoCall();f.state.currentId='avatar-b';activeVideo(f,41);reply({reply:'Old answer'});await pending;
    assert.equal(f.apis.filter(x=>x.url.endsWith('/turns')).length,0);assert.equal(f.requests.length,0);
    assert.equal(f.apis[0].options.signal.aborted,true);results.push('I-VIDEO-TURN: duplicate locked and late reply cannot reach new call/TTS');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);
    const button={},node={querySelector:selector=>selector==='span'?{textContent:'Approved reply'}:button};
    const first=f.context.speakChatMessage(node),second=f.context.speakChatMessage(node);await second;assert.equal(f.requests.length,1);
    f.context.stopSpeechPlayback();f.state.currentId='avatar-b';f.requests[0].resolve({ok:true,blob:async()=>({})});await first;
    assert.equal(f.played.length,0);assert.equal(f.requests[0].options.signal.aborted,true);assert.equal(button.disabled,false);
    await f.context.playSpeechBlob({});const old=f.state.currentSpeechAudio;await f.context.playSpeechBlob({});assert.equal(old.paused,true);
    await f.context.stopConversationMedia();assert.equal(f.state.currentSpeechAudio,null);
    results.push('I-SPEECH-REPLAY: single in-flight request, stale discarded, single stoppable player');
  }
  {
    const f=fixture();vm.runInContext(source('video-call.js'),f.context);action(f,'save-proactive','save-avatar-model-settings');
    const button={disabled:false};f.context.event={target:{closest:()=>button}};f.context.parseWindows=()=>[];f.context.parseQuiet=()=>({});
    f.$('#proactiveToggle').checked=true;f.$('#proactiveInterval').value='360';f.$('#proactiveDailyMax').value='2';f.$('#proactiveCooldown').value='120';
    let finish;f.context.api=(url,options)=>{f.apis.push({url,options});return new Promise(resolve=>finish=resolve);};
    const saving=f.context.runAction();await f.context.runAction();assert.equal(f.apis.length,1);f.state.currentId='avatar-b';f.state.current={name:'B'};
    finish({avatar:{name:'A',proactive_enabled:true}});await saving;assert.equal(f.state.current.name,'B');assert.equal(button.disabled,false);
    assert.equal(f.apis[0].url,'/api/avatars/avatar-a/proactive-settings');results.push('I-PROACTIVE-PARTIAL: one atomic request with captured owner');
  }
  console.log(JSON.stringify({passed:results.length,checks:results,cloud_calls:0,real_devices:0},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
