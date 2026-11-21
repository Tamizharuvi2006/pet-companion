const $ = (id) => document.getElementById(id);
const status = $("status"), chat = $("chat"), start = $("start"), stop = $("stop"), talk = $("push-to-talk"), player = $("player"), playAudio = $("play-audio"), retryAudio = $("retry-audio"), form = $("text-form"), input = $("text-input"), petSpeech = $("pet-speech");
const voiceEngineSelect = $("voice-engine");
const authGate = $("auth-gate"), authForm = $("auth-form"), authPassword = $("auth-password"), authError = $("auth-error"), authSubmit = $("auth-submit"), logout = $("logout");
let socket, recorder, stream, sessionId, activeCaptureId = null, finalizedCaptureId = null, isRecording = false, isFinalizingAudio = false, streamingReply = null, partialTranscript = null, isPlaying = false, petMeowAudio = null, petSpeechTimer = 0, lastAssistantReply = "";
let audioContext, analyser, analyserSource, silenceFrame, silenceStartedAt = 0, speechDetected = false;
let pcmContext = null, activePcmStream = null;
let petVoiceTtsEnabled = false, petVoiceConfigPromise = null;
const audioQueue = [];
const voiceTraces = new Map();
const captureStops = new Map();
const failedAudioTraces = new Set();
const MAX_PENDING_MP3_BYTES = 4 * 1024 * 1024;
const MAX_PENDING_PCM_BYTES = 4 * 1024 * 1024;
let activeLegacyAudio = null, activeMediaStream = null;
const streamingMp3Supported = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported("audio/mpeg");
const CHUNK_DURATION_MS = 250, SILENCE_THRESHOLD = 0.015, SILENCE_STOP_MS = 1100;
const voiceEndpoint = new BellaVoiceEndpoint();
let audioSendChain = Promise.resolve();
let handsFree = false, idleVoiceTimer = 0;
let recordingLimitTimer = 0, maxRecordingSeconds = 30, resumeAfterLimit = false;
let discardVoiceCapture = false;
function resumeHandsFree() {
  if (handsFree && socket?.readyState === WebSocket.OPEN && !isRecording && !isFinalizingAudio) void beginRecording();
}
function stopHandsFree() {
  handsFree = false; clearTimeout(idleVoiceTimer);
  discardVoiceCapture = true;
  if (!isRecording && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'cancel_recording'}));
  $("voice-session").hidden = true;
  if (isRecording) endRecording();
}
$("voice-mode").onclick = async () => {
  if (socket?.readyState !== WebSocket.OPEN) return;
  handsFree = true; $("voice-session").hidden = false; resumeHandsFree();
};
$("end-voice-mode").onclick = stopHandsFree;
document.addEventListener("keydown", e => { if (e.key === "Escape" && handsFree) stopHandsFree(); });
document.addEventListener("visibilitychange", () => { if (document.hidden && handsFree) stopHandsFree(); });
const PET_TALK_LINES = [
  "Nyaa~! Gentle pets only, okay? I am very fluffy.",
  "Mrrp~! Hello, human. Be nice to this little kitty, okay?",
  "Nyaa nyaa~! A tiny head pat is okay. Do not squish my ears!",
  "Meow~! You may pet me now... just a little.",
  "Nyaa~! Careful, human. I am cute, but I am also the boss!",
];
const petTalkUrls = new Map(), petTalkLoads = new Map();
let queuedPetLine = PET_TALK_LINES[0];

function setStatus(text, ready = false) { status.classList.toggle("ready", ready); status.lastChild.textContent = ` ${text}`; const label = $("voice-session-status"); if(label) label.textContent = text; }
const welcomeTemplate = chat.querySelector(".welcome").cloneNode(true);
const drawer = $("history-drawer"), historyList = $("history-list"), historyToggle = $("toggle-history"), backdrop = $("history-backdrop"), jump = $("jump-latest");
const historyKey = "bella.chats.v1";
let savedChats = [];
try {
  const stored = JSON.parse(localStorage.getItem(historyKey) || "[]");
  if (Array.isArray(stored)) savedChats = stored.filter(x => x && typeof x.id === "string" && Array.isArray(x.messages));
} catch {}
let chatId = crypto.randomUUID(), followLatest = true, connectionVersion = 0, activeReplay;
const desktopHistory = matchMedia("(min-width: 900px)");
const chatPet = document.querySelector(".chat-pet");
const historySearch = $("history-search");
historySearch.addEventListener("input", renderHistory);
function updateChatPet() {
  const fox = Number.parseInt(chatId[0], 16) % 2 === 1;
  const pet = document.querySelector("[data-pet-sound]");
  pet.classList.toggle("mobile-pet-cat", !fox);
  pet.classList.toggle("mobile-pet-fox", fox);
  pet.querySelector("img").src = `/assets/bella-${fox ? "fox" : "cat"}-transparent.png`;
}
const messageText = (node) => [...node.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join("");
function updateScroll(force = false) {
  const viewport = $("conversation-scroll");
  if (force || followLatest) viewport.scrollTop = viewport.scrollHeight;
  jump.hidden = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 48;
}
$("conversation-scroll").addEventListener("scroll", () => { const viewport = $("conversation-scroll"); followLatest = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 48; jump.hidden = followLatest; });
jump.onclick = () => { followLatest = true; updateScroll(true); };
function storeChats() {
  try { localStorage.setItem(historyKey, JSON.stringify(savedChats)); }
  catch { $("history-drawer").querySelector("small").textContent = "Storage unavailable. Chats last until this page closes."; }
}
function saveChat() {
  const messages = [...chat.querySelectorAll(".message.user, .message.assistant")]
    .filter(node => node !== partialTranscript && node !== streamingReply)
    .slice(-150).map(node => ({ role: node.classList.contains("user") ? "user" : "assistant", text: messageText(node).slice(0, 16000) }));
  if (!messages.length) return;
  const previous = savedChats.find(x => x.id === chatId);
  savedChats = [{ id: chatId, sessionId, title: previous?.title || (messages.find(x => x.role === "user")?.text || "Conversation").replace(/\s+/g, " ").slice(0, 54), messages }, ...savedChats.filter(x => x.id !== chatId)].slice(0, 30);
  storeChats();
  if (!drawer.hidden) renderHistory();
}
function action(label, click) {
  const button = document.createElement("button");
  button.type = "button"; button.textContent = label; button.onclick = click; return button;
}
function renderHistory() {
  historyList.replaceChildren();
  if (!savedChats.length) { historyList.textContent = "No saved chats yet."; return; }
  const query = historySearch.value.trim().toLowerCase();
  const matches = savedChats.filter(entry => (entry.title || "").toLowerCase().includes(query));
  if (!matches.length) { historyList.textContent = "No matching chats."; return; }
  for (const entry of matches) {
    const row = document.createElement("div"); row.className = "history-row";
    const open = action(entry.title || "Conversation", () => switchChat(entry));
    if (entry.id === chatId) open.setAttribute("aria-current", "true");
    const menu = document.createElement("details");
    const summary = document.createElement("summary"); summary.textContent = "⋯"; summary.setAttribute("aria-label", "Chat options");
    menu.append(summary, action("Rename", () => {
      const name = window.prompt("Rename chat", entry.title);
      if (name?.trim()) { entry.title = name.trim().slice(0, 80); storeChats(); renderHistory(); }
    }), action("Delete", () => {
      if (!window.confirm("Delete this chat from this browser?")) return;
      savedChats = savedChats.filter(x => x.id !== entry.id); storeChats();
      if (entry.id === chatId) switchChat(null, false); else renderHistory();
    }));
    row.append(open, menu); historyList.append(row);
  }
}
function setDrawer(open, focus = true) {
  drawer.hidden = backdrop.hidden = !open;
  historyToggle.setAttribute("aria-expanded", String(open));
  historyToggle.setAttribute("aria-label", open ? "Close chat history" : "Open chat history");
  if (open) { renderHistory(); if (focus) $("new-chat").focus(); }
  else if (focus) historyToggle.focus();
}
setDrawer(desktopHistory.matches, false);
desktopHistory.addEventListener("change", () => setDrawer(desktopHistory.matches, false));
updateChatPet();
historyToggle.onclick = () => setDrawer(drawer.hidden);
$("close-history").onclick = backdrop.onclick = () => setDrawer(false);
$("new-chat").onclick = () => switchChat(null);
document.addEventListener("keydown", event => { if (event.key === "Escape" && !drawer.hidden) setDrawer(false); });
function switchChat(entry, preserve = true) {
  if (entry?.id === chatId) { if (!desktopHistory.matches) setDrawer(false); return; }
  if (preserve) saveChat();
  connectionVersion++;
  activeReplay?.abort();
  if (isRecording) { recorder.onstop = recorder.ondataavailable = null; recorder.stop(); }
  stream?.getTracks().forEach(track => track.stop());
  stopSilenceMonitor();
  isRecording = isFinalizingAudio = false;
  activeCaptureId = finalizedCaptureId = null;
  streamingReply = partialTranscript = null;
  talk.classList.remove("recording"); talk.querySelector("span").textContent = "Hold to talk"; talk.setAttribute("aria-label", "Hold to talk");
  talk.disabled = stop.disabled = true;
  if (socket) { socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null; socket.close(); socket = null; }
  beginFaceTurn(crypto.randomUUID());
  playAudio.hidden = retryAudio.hidden = true;
  lastAssistantReply = "";
  chatId = entry?.id || crypto.randomUUID(); sessionId = entry?.sessionId;
  updateChatPet();
  followLatest = true; chat.replaceChildren(chatPet);
  if (entry?.messages.length) {
    for (const { role, text } of entry.messages) if (["user","assistant"].includes(role) && typeof text === "string") {
      const item = addMessage(role, text);
      if (role === "assistant") addReplyActions(item);
    }
  } else chat.append(welcomeTemplate.cloneNode(true));
  input.value = ""; resizeComposer(); if (!desktopHistory.matches) setDrawer(false); updateScroll(true); input.focus();
  setStatus("Connecting…"); void connect();
}
function addMessage(role, text) {
  chat.querySelector(".welcome")?.remove();
  const item = document.createElement("div"); item.className = `message ${role}`;
  item.dataset.sender = role === "assistant" ? "Bella" : role === "user" ? "You" : "Diagnostic";
  item.textContent = text; chat.append(item); updateScroll(); return item;
}
function addReplyActions(item) {
  if (!item || !messageText(item) || item.querySelector(".reply-actions")) return;
  const tools = document.createElement("div"); tools.className = "reply-actions";
  const copy = action("Copy", async () => {
    try { await navigator.clipboard.writeText(messageText(item)); copy.textContent = "Copied"; }
    catch { copy.textContent = "Copy unavailable"; }
    setTimeout(() => { copy.textContent = "Copy"; }, 1600);
  });
  const replay = action("Read aloud", async () => {
    activeReplay?.abort();
    const request = activeReplay = new AbortController();
    replay.disabled = true; replay.textContent = "Preparing…";
    try {
      const response = await fetch("/tts", { method: "POST", credentials: "same-origin", signal: request.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: messageText(item) }) });
      if (!response.ok) throw new Error();
      const { audio_url } = await response.json();
      if (!request.signal.aborted) { beginFaceTurn(crypto.randomUUID()); enqueueAudio(audio_url, `read-${crypto.randomUUID()}`, 0); }
    } catch { if (!request.signal.aborted) replay.textContent = "Try again"; }
    finally { replay.disabled = false; if (replay.textContent === "Preparing…") replay.textContent = "Read aloud"; }
  });
  replay.title = "Generate audio for this reply";
  tools.append(copy, replay); item.append(tools); updateScroll();
}
function wsUrl() { return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`; }
function faceError(){BellaExpressions.emit('idle','conversation');BellaExpressions.emit('idle','playback');BellaExpressions.emit('error','error',2200);}
function beginFaceTurn(id){
  if(activeMediaStream)disposeMediaStream(activeMediaStream,true);
  player.pause();audioQueue.length=0;activeLegacyAudio=null;isPlaying=false;
  BellaExpressions.beginTurn(id);
}
function showPetSpeech(text, sourcePet) {
  window.clearTimeout(petSpeechTimer);
  petSpeech.textContent = text;
  petSpeech.hidden = false;
  petSpeech.classList.remove("is-visible", "is-hiding", "from-cat", "from-fox");
  petSpeech.classList.add(sourcePet.classList.contains("mobile-pet-cat") ? "from-cat" : "from-fox");
  void petSpeech.offsetWidth;
  petSpeech.classList.add("is-visible");
  petSpeechTimer = window.setTimeout(hidePetSpeech, 12_000);
}
function voiceTrace(traceId) {
  if (!traceId) return null;
  if (!voiceTraces.has(traceId) && voiceTraces.size >= 100) voiceTraces.delete(voiceTraces.keys().next().value);
  if (!voiceTraces.has(traceId)) voiceTraces.set(traceId, { startedAt: performance.now(), replyComplete: false, playbackStarted: false, playbackComplete: false });
  return voiceTraces.get(traceId);
}
function rememberFailedAudio(traceId) {
  failedAudioTraces.add(traceId);
  while (failedAudioTraces.size > 100) failedAudioTraces.delete(failedAudioTraces.values().next().value);
}
function clientVoiceTiming(traceId, stage, details = {}) {
  const trace = voiceTrace(traceId);
  if (!trace) return;
  const now = performance.now();
  const record = { type: "bella_voice_timing", trace_id: traceId, stage, offset_ms: Math.round(now - trace.startedAt), ...(trace.recordingStoppedAt === undefined ? {} : { since_recording_stop_ms: Math.round(now - trace.recordingStoppedAt) }), ...details };
  console.info("[bella_voice_timing]", JSON.stringify(record));
  return now;
}
function hidePetSpeech() {
  window.clearTimeout(petSpeechTimer);
  if (petSpeech.hidden) return;
  petSpeech.classList.remove("is-visible");
  petSpeech.classList.add("is-hiding");
  petSpeechTimer = window.setTimeout(() => {
    petSpeech.hidden = true;
    petSpeech.classList.remove("is-hiding");
  }, 280);
}
function pickPetLine(exceptLine = "") { return PET_TALK_LINES.filter((line) => line !== exceptLine)[Math.floor(Math.random() * (PET_TALK_LINES.length - 1))]; }
function loadPetVoiceConfig() {
  if (!petVoiceConfigPromise) {
    petVoiceConfigPromise = fetch("/client-config", { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error("Pet voice configuration is unavailable");
        return response.json();
      })
      .then((config) => {
        petVoiceTtsEnabled = config.pet_voice_synthesis_enabled === true;
        return petVoiceTtsEnabled;
      })
      .catch(() => {
        petVoiceTtsEnabled = false;
        petVoiceConfigPromise = null;
        return false;
      });
  }
  return petVoiceConfigPromise;
}
async function preparePetTalk(line) {
  if (petTalkUrls.has(line)) return petTalkUrls.get(line);
  if (!petTalkLoads.has(line)) {
    const loading = fetch("/tts", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: line,
      }),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not prepare pet voice");
        const { audio_url: audioUrl } = await response.json();
        petTalkUrls.set(line, audioUrl);
        return audioUrl;
      })
      .catch(() => null)
      .finally(() => { petTalkLoads.delete(line); });
    petTalkLoads.set(line, loading);
  }
  return petTalkLoads.get(line);
}
function playPetTalk(sourcePet) {
  const line = queuedPetLine;
  queuedPetLine = pickPetLine(line);
  showPetSpeech(line, sourcePet);
  void loadPetVoiceConfig().then((enabled) => enabled ? preparePetTalk(line) : null).then((audioUrl) => {
    if (!audioUrl) return;
    const catTalk = new Audio(audioUrl);
    catTalk.volume = 0.72;
    catTalk.playbackRate = 1.02;
    catTalk.addEventListener("ended", hidePetSpeech, { once: true });
    void catTalk.play().catch(hidePetSpeech);
  });
}
function playMeow(sourcePet) {
  petMeowAudio ||= new Audio("/assets/bella-meow.ogg");
  petMeowAudio.currentTime = 0;
  petMeowAudio.volume = 0.78;
  petMeowAudio.onended = () => playPetTalk(sourcePet);
  void petMeowAudio.play();
}
function playNextAudio() {
  if (isPlaying || !audioQueue.length) return;
  activeLegacyAudio = audioQueue.shift();
  isPlaying = true; player.src = activeLegacyAudio.url;
  clientVoiceTiming(activeLegacyAudio.traceId, "legacy_audio_source_set", { chunk: activeLegacyAudio.chunkIndex });
  player.play().then(() => { playAudio.hidden = true; }).catch(() => { isPlaying = false; playAudio.hidden = false; });
}
function enqueueAudio(url, traceId, chunkIndex) {
  audioQueue.push({ url, traceId, chunkIndex });
  clientVoiceTiming(traceId, "legacy_audio_received", { chunk: chunkIndex });
  playNextAudio();
}
playAudio.onclick = () => { isPlaying = true; player.play().then(() => { playAudio.hidden = true; }).catch(() => { isPlaying = false; }); };
retryAudio.onclick = async () => {
  if (!lastAssistantReply || retryAudio.disabled) return;
  const version = connectionVersion;
  retryAudio.disabled = true;
  setStatus("Preparing audio…");
  try {
    const response = await fetch("/tts", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: lastAssistantReply }),
    });
    if (!response.ok) throw new Error("TTS retry failed");
    const body = await response.json();
    if (version !== connectionVersion) return;
    retryAudio.hidden = true;
    enqueueAudio(body.audio_url, `retry-${crypto.randomUUID()}`, 0);
    setStatus("Ready", true);
  } catch {
    if (version === connectionVersion) setStatus("Audio retry failed");
  } finally {
    retryAudio.disabled = false;
  }
};

function disposeMediaStream(target, detach = false) {
  if (!target || target.disposed) return;
  target.disposed = true;
  target.ended = true;
  target.pending.length = 0;
  target.pendingBytes = 0;
  if (target.sourceBuffer?.updating) {
    try { target.sourceBuffer.abort(); } catch { /* SourceBuffer may already be detached. */ }
  }
  if (target.mediaSource?.readyState === "open") {
    try { target.mediaSource.endOfStream(); } catch { /* Best-effort stream teardown. */ }
  }
  if (detach && player.src === target.objectUrl) {
    player.pause();
    player.removeAttribute("src");
    player.load();
  }
  URL.revokeObjectURL(target.objectUrl);
  if (activeMediaStream === target) activeMediaStream = null;
}

function failMediaStream(target, stage, status = "unknown") {
  if (!target || target.failed) return;
  target.failed = true;
  faceError();
  clientVoiceTiming(target.traceId, stage, { status });
  rememberFailedAudio(target.traceId);
  disposeMediaStream(target, true);
  addMessage("notice", "Bella's audio was interrupted in the browser. You can retry the reply audio.");
  if (lastAssistantReply) retryAudio.hidden = false;
}

player.addEventListener("playing", () => {
  if(!activeMediaStream&&!activeLegacyAudio)return;
  BellaExpressions.emit('idle','connectivity',100);
  BellaExpressions.emit('speaking','playback');
  if (activeMediaStream && !activeMediaStream.trace.playbackStarted) {
    activeMediaStream.trace.playbackStarted = true;
    const at = clientVoiceTiming(activeMediaStream.traceId, "first_playback_started");
    if (at !== undefined && activeMediaStream.trace.firstTextAt !== undefined) {
      clientVoiceTiming(activeMediaStream.traceId, "first_text_to_playback", { duration_ms: Math.round(at - activeMediaStream.trace.firstTextAt) });
    }
  } else if (activeLegacyAudio) {
    const trace = voiceTrace(activeLegacyAudio.traceId);
    if (trace && !trace.playbackStarted) {
      trace.playbackStarted = true;
      const at = clientVoiceTiming(activeLegacyAudio.traceId, "first_playback_started", { chunk: activeLegacyAudio.chunkIndex });
      if (at !== undefined && trace.firstTextAt !== undefined) clientVoiceTiming(activeLegacyAudio.traceId, "first_text_to_playback", { duration_ms: Math.round(at - trace.firstTextAt) });
    }
  }
  playAudio.hidden = true;
});
player.addEventListener("waiting", () => {
  if(!activeMediaStream&&!activeLegacyAudio)return;
  BellaExpressions.emit('thinking','playback');
  const traceId = activeMediaStream?.traceId || activeLegacyAudio?.traceId;
  const trace = voiceTrace(traceId);
  if (trace?.playbackStarted && !trace.playbackComplete) {
    clientVoiceTiming(traceId, "playback_waiting_for_audio");
  }
});
player.addEventListener("ended", () => {
  if(!activeMediaStream&&!activeLegacyAudio)return;
  if (activeMediaStream) {
    const completed = activeMediaStream;
    clientVoiceTiming(completed.traceId, "playback_completed");
    completed.trace.playbackComplete = true;
    disposeMediaStream(completed, true);
  } else if (activeLegacyAudio) {
    const traceId = activeLegacyAudio.traceId;
    clientVoiceTiming(traceId, "audio_chunk_playback_completed", { chunk: activeLegacyAudio.chunkIndex });
    activeLegacyAudio = null;
    isPlaying = false;
    const trace = voiceTrace(traceId);
    if (trace?.replyComplete && !audioQueue.some((item) => item.traceId === traceId)) {
      trace.playbackComplete = true;
      clientVoiceTiming(traceId, "playback_completed");
    }
  }
  isPlaying = false;
  playNextAudio();
  if (!activeMediaStream && !activeLegacyAudio && !audioQueue.length) { BellaExpressions.emit('idle','playback'); BellaExpressions.emit('idle','conversation'); setTimeout(resumeHandsFree, 250); }
});
player.addEventListener("error", () => {
  faceError();
  const traceId = activeMediaStream?.traceId || activeLegacyAudio?.traceId;
  if (activeMediaStream) failMediaStream(activeMediaStream, "playback_error", player.error?.code || "media_error");
  else if (traceId) { clientVoiceTiming(traceId, "playback_error"); addMessage("notice", "Bella's audio could not finish playing. You can retry the reply audio."); retryAudio.hidden = !lastAssistantReply; }
  isPlaying = false; activeLegacyAudio = null; playAudio.hidden = false; playNextAudio();
});

function beginMp3Stream(traceId, chunkIndex) {
  stopPcmStream();
  clientVoiceTiming(traceId, "audio_stream_start_received", { chunk: chunkIndex });
  if (!streamingMp3Supported || failedAudioTraces.has(traceId)) return;
  let trace = voiceTrace(traceId);
  if (activeMediaStream && activeMediaStream.traceId !== traceId) {
    disposeMediaStream(activeMediaStream, true);
    audioQueue.length = 0;
    activeLegacyAudio = null;
    isPlaying = false;
  }
  if (!activeMediaStream && (activeLegacyAudio || audioQueue.length)) {
    audioQueue.length = 0;
    if (activeLegacyAudio) {
      player.pause();
      player.removeAttribute("src");
      player.load();
      activeLegacyAudio = null;
    }
    isPlaying = false;
  }
  if (!activeMediaStream) {
    const mediaSource = new MediaSource();
    const objectUrl = URL.createObjectURL(mediaSource);
    const mediaStream = { traceId, trace, mediaSource, objectUrl, sourceBuffer: null, pending: [], pendingBytes: 0, replyComplete: false, playbackRequested: false, ended: false, failed: false, disposed: false };
    activeMediaStream = mediaStream;
    player.pause();
    player.src = objectUrl;
    player.load();
    mediaSource.addEventListener("sourceopen", () => {
      try {
        if (activeMediaStream !== mediaStream) return;
        mediaStream.sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
        mediaStream.sourceBuffer.mode = "sequence";
        mediaStream.sourceBuffer.addEventListener("updateend", () => pumpMp3Stream(mediaStream));
        mediaStream.sourceBuffer.addEventListener("error", () => failMediaStream(mediaStream, "media_source_error", "source_buffer_error"));
        mediaStream.sourceBuffer.addEventListener("abort", () => {
          if (!mediaStream.disposed && !mediaStream.ended) failMediaStream(mediaStream, "media_source_error", "source_buffer_abort");
        });
        pumpMp3Stream(mediaStream);
      } catch (error) {
        failMediaStream(mediaStream, "media_source_error", error?.name || "unknown");
      }
    }, { once: true });
    mediaSource.addEventListener("sourceclose", () => {
      if (!mediaStream.disposed && !mediaStream.ended) failMediaStream(mediaStream, "media_source_error", "source_closed");
    }, { once: true });
  }
}
function appendMp3Bytes(data) {
  const target = activeMediaStream;
  if (!target || target.ended) return;
  if (target.trace.firstAudioAt === undefined) {
    target.trace.firstAudioAt = performance.now();
    clientVoiceTiming(target.traceId, "first_audio_bytes_received", { bytes: data.byteLength });
  }
  target.pendingBytes += data.byteLength;
  if (target.pendingBytes > MAX_PENDING_MP3_BYTES) {
    failMediaStream(target, "media_pending_limit", "buffer_limit");
    return;
  }
  target.pending.push(data);
  pumpMp3Stream(target);
}
function finishMp3Stream(traceId) {
  const target = activeMediaStream;
  if (!target || target.traceId !== traceId) return;
  target.replyComplete = true;
  pumpMp3Stream(target);
}
function pumpMp3Stream(target) {
  if (!target || target !== activeMediaStream || !target.sourceBuffer || target.sourceBuffer.updating) return;
  if (target.pending.length) {
    const bytes = target.pending.shift();
    target.pendingBytes -= bytes.byteLength;
    try {
      target.sourceBuffer.appendBuffer(bytes);
      if (!target.playbackRequested) {
        target.playbackRequested = true;
        player.play().then(() => { playAudio.hidden = true; }).catch(() => { playAudio.hidden = false; clientVoiceTiming(target.traceId, "autoplay_blocked"); });
      }
    } catch (error) {
      failMediaStream(target, "media_append_error", error?.name || "unknown");
    }
    return;
  }
  if (target.replyComplete && !target.ended && target.mediaSource.readyState === "open") {
    try { target.mediaSource.endOfStream(); target.ended = true; }
    catch (error) { failMediaStream(target, "media_end_error", error?.name || "unknown"); }
  }
}

function primePcmAudio() {
  try {
    if (!pcmContext || pcmContext.state === "closed") pcmContext = new AudioContext({ sampleRate: 24000 });
    return pcmContext.state === "suspended" ? pcmContext.resume() : Promise.resolve(pcmContext);
  } catch (error) {
    return Promise.reject(error);
  }
}
function stopPcmStream() {
  const target = activePcmStream;
  if (!target) return;
  activePcmStream = null;
  target.queue.length = 0;
  for (const source of target.sources) { try { source.stop(); } catch {} }
  target.sources.clear();
  isPlaying = false;
}
function beginPcmStream(traceId, sampleRate) {
  stopPcmStream();
  if (activeMediaStream) disposeMediaStream(activeMediaStream, true);
  activeLegacyAudio = null;
  audioQueue.length = 0;
  player.pause();
  player.removeAttribute("src");
  player.load();
  activePcmStream = { traceId, sampleRate: Number(sampleRate) || 24000, queue: [], queueBytes: 0, sources: new Set(), nextTime: 0, pumping: false, ended: false, playbackLogged: false };
  void primePcmAudio().catch(() => clientVoiceTiming(traceId, "audio_context_resume_failed"));
}
function appendPcmBytes(data) {
  const target = activePcmStream;
  if (!target || !(data instanceof ArrayBuffer) || data.byteLength < 2 || data.byteLength % 2) {
    if (target) clientVoiceTiming(target.traceId, "invalid_pcm_frame", { bytes: data?.byteLength || 0 });
    return;
  }
  if (target.firstAudioAt === undefined) {
    target.firstAudioAt = performance.now();
    clientVoiceTiming(target.traceId, "first_audio_bytes_received", { bytes: data.byteLength });
  }
  if (target.queueBytes + data.byteLength > MAX_PENDING_PCM_BYTES) {
    clientVoiceTiming(target.traceId, "pcm_pending_limit", { bytes: target.queueBytes + data.byteLength });
    stopPcmStream();
    faceError();
    addMessage("notice", "GPT Audio Mini audio arrived faster than this browser could play it.");
    return;
  }
  target.queue.push(data.slice(0));
  target.queueBytes += data.byteLength;
  void pumpPcmStream(target);
}
async function pumpPcmStream(target) {
  if (!target || target !== activePcmStream || target.pumping) return;
  target.pumping = true;
  try {
    await primePcmAudio();
    while (target === activePcmStream && target.queue.length) {
      if (target.nextTime - pcmContext.currentTime > 8) break;
      const bytes = target.queue.shift();
      target.queueBytes -= bytes.byteLength;
      const samples = new Int16Array(bytes);
      const floatSamples = new Float32Array(samples.length);
      for (let i = 0; i < samples.length; i++) floatSamples[i] = samples[i] / 32768;
      const buffer = pcmContext.createBuffer(1, floatSamples.length, target.sampleRate);
      buffer.copyToChannel(floatSamples, 0);
      const source = pcmContext.createBufferSource();
      source.buffer = buffer;
      source.connect(pcmContext.destination);
      target.sources.add(source);
      source.onended = () => {
        target.sources.delete(source);
        if (target.ended && !target.queue.length && !target.sources.size) finishPcmPlayback(target);
        else if (target === activePcmStream && target.queue.length) void pumpPcmStream(target);
      };
      const startsAt = Math.max(pcmContext.currentTime + 0.035, target.nextTime);
      target.nextTime = startsAt + buffer.duration;
      source.start(startsAt);
      isPlaying = true;
      if (!target.playbackLogged) {
        target.playbackLogged = true;
        BellaExpressions.emit("idle", "connectivity", 100);
        BellaExpressions.emit("speaking", "playback");
        const delay = Math.max(0, (startsAt - pcmContext.currentTime) * 1000);
        setTimeout(() => {
          if (target === activePcmStream) clientVoiceTiming(target.traceId, "first_playback_started");
        }, delay);
      }
    }
    if (target.ended && !target.queue.length && !target.sources.size) finishPcmPlayback(target);
  } catch (error) {
    clientVoiceTiming(target.traceId, "pcm_playback_error", { status: error?.name || "unknown" });
    stopPcmStream();
    faceError();
    addMessage("notice", "GPT Audio Mini audio could not play in this browser.");
  } finally {
    target.pumping = false;
  }
}
function finishPcmPlayback(target) {
  if (target !== activePcmStream) return;
  clientVoiceTiming(target.traceId, "playback_completed");
  activePcmStream = null;
  isPlaying = false;
  BellaExpressions.emit("idle", "playback");
  BellaExpressions.emit("idle", "conversation");
  setTimeout(resumeHandsFree, 250);
}

function monitorSilence() {
  if (!analyser || !isRecording) return;
  const samples = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(samples);
  const rms = Math.sqrt(samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / samples.length);
  const now = performance.now();
  if (voiceEndpoint.update(rms, now)) { endRecording(); return; }
  if (voiceEndpoint.voicedMs >= 160) speechDetected = true;
  silenceFrame = requestAnimationFrame(monitorSilence);
}
function stopSilenceMonitor() { if (silenceFrame) cancelAnimationFrame(silenceFrame); silenceFrame = 0; analyserSource?.disconnect(); analyser = null; analyserSource = null; if (audioContext) { void audioContext.close(); audioContext = null; } }

function showAuthGate(message = "") {
  authGate.hidden = false;
  authError.textContent = message;
  authError.hidden = !message;
  start.disabled = true;
  talk.disabled = true;
  authPassword.focus();
}

async function connect() {
  if (socket && socket.readyState <= WebSocket.OPEN) return;
  const version = ++connectionVersion;
  try {
    const response = await fetch("/auth/session", { credentials: "same-origin" });
    if (!response.ok) throw new Error("session_check_failed");
    const session = await response.json();
    if (version !== connectionVersion) return;
    logout.hidden = !session.required;
    if (!session.authenticated) {
      showAuthGate();
      setStatus("Sign in to continue");
      return;
    }
    void loadPetVoiceConfig();
    authGate.hidden = true;
    authError.hidden = true;
  } catch {
    if (version !== connectionVersion) return;
    setStatus("Server unavailable");
    start.disabled = false;
    talk.disabled = true;
    return;
  }
  socket = new WebSocket(wsUrl());
  socket.binaryType = "arraybuffer";
  socket.onopen = () => { BellaExpressions.emit('idle','connectivity',100); socket.send(JSON.stringify({ type: "client_capabilities", streaming_mp3: streamingMp3Supported, voice_engine: voiceEngineSelect.value })); setStatus("Ready", true); start.disabled = true; talk.disabled = false; };
  socket.onclose = (event) => { if(isRecording)endRecording();BellaExpressions.emit('offline','connectivity'); setStatus("Disconnected"); start.disabled = false; talk.disabled = true; stop.disabled = true; stopPcmStream(); if (activeMediaStream) disposeMediaStream(activeMediaStream, true); player.pause(); activeLegacyAudio=null; isPlaying=false; audioQueue.length = 0; if (event.code === 4401) showAuthGate(); };
  socket.onerror = () => setStatus("Connection error");
  socket.addEventListener("close", stopHandsFree);
  socket.onmessage = ({ data }) => {
    if (data instanceof ArrayBuffer) { if (activePcmStream) appendPcmBytes(data); else appendMp3Bytes(data); return; }
    const event = JSON.parse(data);
    if (event.type === "recording_limits") {
      if (Number.isFinite(event.max_seconds) && event.max_seconds >= 1) maxRecordingSeconds = event.max_seconds;
      return;
    }
    if (event.type === "voice_engine_selected") {
      if (voiceEngineSelect.value !== event.voice_engine) voiceEngineSelect.value = event.voice_engine;
      return;
    }
    if (handsFree && event.type === "error" && event.code === "recording_too_long") {
      // The session survives a bounded capture reset; never loop an oversized
      // recording or display a raw transport-limit error as Bella's reply.
      resumeAfterLimit = true;
      if (isRecording) endRecording();
      else if (!isFinalizingAudio) { resumeAfterLimit = false; resumeHandsFree(); }
      return;
    }
    if (handsFree && (event.type === "error" || event.type === "tts_stream_abort")) stopHandsFree();
    if (event.type === "status") setStatus(event.text, event.text === "Ready");
    if (event.type === "diagnostic_audio_mode") addMessage("notice", event.text);
    if (event.type === "speech_coverage") addMessage("notice", event.text);
    if (event.type === "partial_transcript") { if ((event.capture_id && event.capture_id !== activeCaptureId) || event.capture_id === finalizedCaptureId) return; if (!partialTranscript || partialTranscript.dataset.captureId !== event.capture_id) { partialTranscript = addMessage("user", ""); partialTranscript.dataset.captureId = event.capture_id || ""; } partialTranscript.textContent = `${event.text}…`; updateScroll(); }
    if (event.type === "transcript") {
      if (event.capture_id) finalizedCaptureId = event.capture_id;
      const trace = voiceTrace(event.trace_id);
      if (trace && captureStops.has(event.capture_id)) {
        trace.recordingStoppedAt = captureStops.get(event.capture_id);
        captureStops.delete(event.capture_id);
        clientVoiceTiming(event.trace_id, "final_transcript_received");
      }
      if (partialTranscript && (!event.capture_id || partialTranscript.dataset.captureId === event.capture_id)) { partialTranscript.textContent = event.text; partialTranscript = null; } else addMessage("user", event.text);
    }
    if (event.type === "voice_input_received") {
      addMessage('user', 'Voice message');
      const trace = voiceTrace(event.trace_id);
      if (trace && captureStops.has(event.capture_id)) {
        trace.recordingStoppedAt = captureStops.get(event.capture_id);
        captureStops.delete(event.capture_id);
      }
      clientVoiceTiming(event.trace_id, 'voice_input_received');
    }
    if (event.type === "reply_delta") { sessionId = event.session_id || sessionId; const trace = voiceTrace(event.trace_id); if (trace && trace.firstTextAt === undefined) { trace.firstTextAt = performance.now(); clientVoiceTiming(event.trace_id, "first_text_delta_received"); } if (!streamingReply) streamingReply = addMessage("assistant", ""); streamingReply.textContent += event.text; updateScroll(); }
    if (event.type === "reply") { sessionId = event.session_id || sessionId; lastAssistantReply = event.text || streamingReply?.textContent || lastAssistantReply; const item = streamingReply || addMessage("assistant", event.text); streamingReply = null; addReplyActions(item); saveChat(); const trace = voiceTrace(event.trace_id); if (trace) trace.replyComplete = true; clientVoiceTiming(event.trace_id, "reply_complete_received"); finishMp3Stream(event.trace_id); if (failedAudioTraces.has(event.trace_id)) retryAudio.hidden = false; }
    if (event.type === "tts_stream_start") beginMp3Stream(event.trace_id, event.chunk_index);
    if (event.type === "pcm_stream_start") { clientVoiceTiming(event.trace_id, "pcm_audio_stream_start_received", { sample_rate: event.sample_rate }); beginPcmStream(event.trace_id, event.sample_rate); }
    if (event.type === "pcm_stream_end") { const target = activePcmStream; if (target?.traceId === event.trace_id) { target.ended = true; clientVoiceTiming(event.trace_id, "pcm_audio_stream_end_received"); void pumpPcmStream(target); } }
    if (event.type === "pcm_stream_abort") { if (activePcmStream?.traceId === event.trace_id) stopPcmStream(); clientVoiceTiming(event.trace_id, "pcm_audio_stream_aborted"); }
    if (event.type === "tts_stream_end") clientVoiceTiming(event.trace_id, "audio_chunk_stream_end_received", { chunk: event.chunk_index });
    if (event.type === "tts_stream_abort") { clientVoiceTiming(event.trace_id, "audio_chunk_stream_aborted", { chunk: event.chunk_index }); rememberFailedAudio(event.trace_id); if (activeMediaStream?.traceId === event.trace_id) failMediaStream(activeMediaStream, "audio_chunk_stream_aborted", "provider_abort"); if (lastAssistantReply) retryAudio.hidden = false; }
    if (event.type === "audio") enqueueAudio(event.url, event.trace_id, event.chunk_index);
    if (event.type === "error") { faceError(); addMessage("assistant", `Sorry, ${event.message}`); setStatus("Ready", true); }
  };
}

async function beginRecording() {
  if (!socket || socket.readyState !== WebSocket.OPEN || isRecording || isFinalizingAudio) return;
  if (voiceEngineSelect.value === "gpt_audio_mini") void primePcmAudio().catch(() => {});
  const version = connectionVersion;
  discardVoiceCapture = false;
  voiceEndpoint.reset();
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (version !== connectionVersion) { acquired.getTracks().forEach(track => track.stop()); return; }
    stream = acquired;
    activeCaptureId = crypto.randomUUID();
    beginFaceTurn(activeCaptureId);BellaExpressions.emit('listening');
    audioContext = new AudioContext(); await audioContext.resume(); if (version !== connectionVersion) return; analyser = audioContext.createAnalyser(); analyser.fftSize = 1024; analyserSource = audioContext.createMediaStreamSource(stream); analyserSource.connect(analyser); silenceStartedAt = 0; speechDetected = false;
    recorder = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "" });
    audioSendChain = Promise.resolve();
    let pendingVoiceFrames = [];
    let sentVoiceFrames = false;
    const handsFreeCapture = handsFree;
    idleVoiceTimer = setTimeout(() => { if (handsFree && isRecording && !speechDetected) endRecording(); }, 8000);
    recorder.ondataavailable = ({ data }) => {
      if (!data.size) return;
      if (handsFreeCapture && !speechDetected) { pendingVoiceFrames.push(data); return; }
      const frames = [...pendingVoiceFrames, data]; pendingVoiceFrames = [];
      sentVoiceFrames = true;
      // Preserve MediaRecorder order. Without this queue, the asynchronous
      // conversion can let stop_recording overtake the WebM header chunk.
      audioSendChain = audioSendChain.then(async () => {
        for (const frame of frames) {
        const buffer = await frame.arrayBuffer();
        let binary = "";
        new Uint8Array(buffer).forEach((byte) => { binary += String.fromCharCode(byte); });
        if (version === connectionVersion && socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "audio_chunk", data: btoa(binary), duration_ms: CHUNK_DURATION_MS, session_id: sessionId, capture_id: activeCaptureId }));
        }
        }
      });
    };
    recorder.onstop = () => {
      clearTimeout(idleVoiceTimer);
      clearTimeout(recordingLimitTimer);
      stream.getTracks().forEach((track) => track.stop());
      // The final dataavailable event occurs just before onstop. Wait until it
      // has reached the server before marking this recording complete.
      void audioSendChain
        .catch(() => setStatus("Could not send microphone audio"))
        .then(() => {
          if (handsFreeCapture && discardVoiceCapture) {
            if (version === connectionVersion && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'cancel_recording'}));
            return;
          }
          if ((!handsFreeCapture || sentVoiceFrames) && version === connectionVersion && socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "stop_recording", session_id: sessionId, capture_id: activeCaptureId }));
            setStatus("Processing…");
          }
        })
        .finally(() => { if (version === connectionVersion) { isFinalizingAudio = false; if (handsFreeCapture && (!sentVoiceFrames || resumeAfterLimit)) { resumeAfterLimit = false; resumeHandsFree(); } } });
    };
    recorder.start(CHUNK_DURATION_MS); isRecording = true;
    recordingLimitTimer = setTimeout(() => { if (isRecording) endRecording(); }, Math.max(500, (maxRecordingSeconds - 2) * 1000));
    monitorSilence(); talk.classList.add("recording"); talk.querySelector("span").textContent = "Listening…"; talk.setAttribute("aria-label", "Listening"); stop.disabled = false; setStatus("Listening…");
  } catch { if (version === connectionVersion) { stopHandsFree(); stream?.getTracks().forEach(track=>track.stop());faceError();setStatus("Microphone permission was denied"); } }
}
function endRecording() { if (!isRecording) return; if (activeCaptureId) { captureStops.set(activeCaptureId, performance.now()); if (captureStops.size > 100) captureStops.delete(captureStops.keys().next().value); } BellaExpressions.emit('thinking'); isRecording = false; isFinalizingAudio = true; stopSilenceMonitor(); recorder.stop(); talk.classList.remove("recording"); talk.querySelector("span").textContent = "Hold to talk"; talk.setAttribute("aria-label", "Hold to talk"); stop.disabled = true; }

start.onclick = connect; stop.onclick = endRecording;
authForm.onsubmit = async (event) => {
  event.preventDefault();
  authSubmit.disabled = true;
  authError.hidden = true;
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: authPassword.value }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || "Could not sign in");
    }
    authPassword.value = "";
    authGate.hidden = true;
    await connect();
  } catch (error) {
    showAuthGate(error?.message || "Could not sign in");
  } finally {
    authSubmit.disabled = false;
  }
};
logout.onclick = async () => {
  socket?.close(1000, "User signed out");
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
  showAuthGate();
};
talk.addEventListener("pointerdown", beginRecording); talk.addEventListener("pointerup", endRecording); talk.addEventListener("pointerleave", endRecording);
function resizeComposer() { input.style.height = "auto"; input.style.height = `${Math.min(144, input.scrollHeight)}px`; }
input.addEventListener("input", resizeComposer);
input.addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); } });
form.onsubmit = (event) => { event.preventDefault(); const text = input.value.trim(); if (!text || socket?.readyState !== WebSocket.OPEN) return; if (voiceEngineSelect.value === "gpt_audio_mini") void primePcmAudio().catch(() => {}); beginFaceTurn(crypto.randomUUID());BellaExpressions.emit('thinking');followLatest = true;addMessage("user", text); saveChat(); socket.send(JSON.stringify({ type: "text", data: text, session_id: sessionId })); input.value = ""; resizeComposer(); };
voiceEngineSelect.addEventListener("change", () => {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "client_capabilities", streaming_mp3: streamingMp3Supported, voice_engine: voiceEngineSelect.value }));
  }
});
chat.addEventListener("click", event => { const button = event.target.closest("[data-prompt]"); if (button) { input.value = button.dataset.prompt; resizeComposer(); input.focus(); } });
document.querySelectorAll("[data-pet-sound]").forEach((pet) => { pet.addEventListener("click", () => { playMeow(pet); pet.classList.remove("is-meowing"); void pet.offsetWidth; pet.classList.add("is-meowing"); }); });
connect();
