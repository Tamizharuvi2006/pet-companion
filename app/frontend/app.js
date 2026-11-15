const $ = (id) => document.getElementById(id);
const status = $("status"), chat = $("chat"), start = $("start"), stop = $("stop"), talk = $("push-to-talk"), player = $("player"), playAudio = $("play-audio"), retryAudio = $("retry-audio"), form = $("text-form"), input = $("text-input"), petSpeech = $("pet-speech");
const authGate = $("auth-gate"), authForm = $("auth-form"), authPassword = $("auth-password"), authError = $("auth-error"), authSubmit = $("auth-submit"), logout = $("logout");
let socket, recorder, stream, sessionId, activeCaptureId = null, finalizedCaptureId = null, isRecording = false, isFinalizingAudio = false, streamingReply = null, partialTranscript = null, isPlaying = false, petMeowAudio = null, petSpeechTimer = 0, lastAssistantReply = "";
let audioContext, analyser, analyserSource, silenceFrame, silenceStartedAt = 0, speechDetected = false;
let petVoiceTtsEnabled = false, petVoiceConfigPromise = null;
const audioQueue = [];
const voiceTraces = new Map();
const failedAudioTraces = new Set();
const MAX_PENDING_MP3_BYTES = 4 * 1024 * 1024;
let activeLegacyAudio = null, activeMediaStream = null;
const streamingMp3Supported = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported("audio/mpeg");
const CHUNK_DURATION_MS = 250, SILENCE_THRESHOLD = 0.015, SILENCE_STOP_MS = 1100;
let audioSendChain = Promise.resolve();
const PET_TALK_LINES = [
  "Nyaa~! Gentle pets only, okay? I am very fluffy.",
  "Mrrp~! Hello, human. Be nice to this little kitty, okay?",
  "Nyaa nyaa~! A tiny head pat is okay. Do not squish my ears!",
  "Meow~! You may pet me now... just a little.",
  "Nyaa~! Careful, human. I am cute, but I am also the boss!",
];
const petTalkUrls = new Map(), petTalkLoads = new Map();
let queuedPetLine = PET_TALK_LINES[0];

function setStatus(text, ready = false) { status.classList.toggle("ready", ready); status.lastChild.textContent = ` ${text}`; }
function addMessage(role, text) { chat.querySelector(".welcome")?.remove(); const item = document.createElement("div"); item.className = `message ${role}`; item.dataset.sender = role === "assistant" ? "Bella" : role === "user" ? "You" : "Diagnostic"; item.textContent = text; chat.append(item); chat.scrollTop = chat.scrollHeight; return item; }
function wsUrl() { return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/chat`; }
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
  const record = { type: "bella_voice_timing", trace_id: traceId, stage, offset_ms: Math.round(now - trace.startedAt), ...details };
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
    retryAudio.hidden = true;
    enqueueAudio(body.audio_url, `retry-${crypto.randomUUID()}`, 0);
    setStatus("Ready", true);
  } catch {
    setStatus("Audio retry failed");
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
  clientVoiceTiming(target.traceId, stage, { status });
  rememberFailedAudio(target.traceId);
  disposeMediaStream(target, true);
  addMessage("notice", "Bella's audio was interrupted in the browser. You can retry the reply audio.");
  if (lastAssistantReply) retryAudio.hidden = false;
}

player.addEventListener("playing", () => {
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
  const traceId = activeMediaStream?.traceId || activeLegacyAudio?.traceId;
  const trace = voiceTrace(traceId);
  if (trace?.playbackStarted && !trace.playbackComplete) {
    clientVoiceTiming(traceId, "playback_waiting_for_audio");
  }
});
player.addEventListener("ended", () => {
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
});
player.addEventListener("error", () => {
  const traceId = activeMediaStream?.traceId || activeLegacyAudio?.traceId;
  if (activeMediaStream) failMediaStream(activeMediaStream, "playback_error", player.error?.code || "media_error");
  else if (traceId) { clientVoiceTiming(traceId, "playback_error"); addMessage("notice", "Bella's audio could not finish playing. You can retry the reply audio."); retryAudio.hidden = !lastAssistantReply; }
  isPlaying = false; activeLegacyAudio = null; playAudio.hidden = false; playNextAudio();
});

function beginMp3Stream(traceId, chunkIndex) {
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

function monitorSilence() {
  if (!analyser || !isRecording) return;
  const samples = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(samples);
  const rms = Math.sqrt(samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / samples.length);
  const now = performance.now();
  if (rms >= SILENCE_THRESHOLD) { speechDetected = true; silenceStartedAt = 0; }
  else if (speechDetected) { silenceStartedAt ||= now; if (now - silenceStartedAt >= SILENCE_STOP_MS) { endRecording(); return; } }
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
  if (socket?.readyState === WebSocket.OPEN) return;
  try {
    const response = await fetch("/auth/session", { credentials: "same-origin" });
    if (!response.ok) throw new Error("session_check_failed");
    const session = await response.json();
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
    setStatus("Server unavailable");
    start.disabled = false;
    talk.disabled = true;
    return;
  }
  socket = new WebSocket(wsUrl());
  socket.binaryType = "arraybuffer";
  socket.onopen = () => { socket.send(JSON.stringify({ type: "client_capabilities", streaming_mp3: streamingMp3Supported })); setStatus("Ready", true); start.disabled = true; talk.disabled = false; };
  socket.onclose = (event) => { setStatus("Disconnected"); start.disabled = false; talk.disabled = true; stop.disabled = true; if (activeMediaStream) disposeMediaStream(activeMediaStream, true); audioQueue.length = 0; if (event.code === 4401) showAuthGate(); };
  socket.onerror = () => setStatus("Connection error");
  socket.onmessage = ({ data }) => {
    if (data instanceof ArrayBuffer) { appendMp3Bytes(data); return; }
    const event = JSON.parse(data);
    if (event.type === "status") setStatus(event.text, event.text === "Ready");
    if (event.type === "diagnostic_audio_mode") addMessage("notice", event.text);
    if (event.type === "speech_coverage") addMessage("notice", event.text);
    if (event.type === "partial_transcript") { if ((event.capture_id && event.capture_id !== activeCaptureId) || event.capture_id === finalizedCaptureId) return; if (!partialTranscript || partialTranscript.dataset.captureId !== event.capture_id) { partialTranscript = addMessage("user", ""); partialTranscript.dataset.captureId = event.capture_id || ""; } partialTranscript.textContent = `${event.text}…`; chat.scrollTop = chat.scrollHeight; }
    if (event.type === "transcript") { if (event.capture_id) finalizedCaptureId = event.capture_id; if (partialTranscript && (!event.capture_id || partialTranscript.dataset.captureId === event.capture_id)) { partialTranscript.textContent = event.text; partialTranscript = null; } else addMessage("user", event.text); }
    if (event.type === "reply_delta") { sessionId = event.session_id || sessionId; const trace = voiceTrace(event.trace_id); if (trace && trace.firstTextAt === undefined) { trace.firstTextAt = performance.now(); clientVoiceTiming(event.trace_id, "first_text_delta_received"); } if (!streamingReply) streamingReply = addMessage("assistant", ""); streamingReply.textContent += event.text; chat.scrollTop = chat.scrollHeight; }
    if (event.type === "reply") { sessionId = event.session_id || sessionId; lastAssistantReply = event.text || streamingReply?.textContent || lastAssistantReply; if (streamingReply) streamingReply = null; else addMessage("assistant", event.text); const trace = voiceTrace(event.trace_id); if (trace) trace.replyComplete = true; clientVoiceTiming(event.trace_id, "reply_complete_received"); finishMp3Stream(event.trace_id); if (failedAudioTraces.has(event.trace_id)) retryAudio.hidden = false; }
    if (event.type === "tts_stream_start") beginMp3Stream(event.trace_id, event.chunk_index);
    if (event.type === "tts_stream_end") clientVoiceTiming(event.trace_id, "audio_chunk_stream_end_received", { chunk: event.chunk_index });
    if (event.type === "tts_stream_abort") { clientVoiceTiming(event.trace_id, "audio_chunk_stream_aborted", { chunk: event.chunk_index }); rememberFailedAudio(event.trace_id); if (activeMediaStream?.traceId === event.trace_id) failMediaStream(activeMediaStream, "audio_chunk_stream_aborted", "provider_abort"); if (lastAssistantReply) retryAudio.hidden = false; }
    if (event.type === "audio") enqueueAudio(event.url, event.trace_id, event.chunk_index);
    if (event.type === "error") { addMessage("assistant", `Sorry, ${event.message}`); setStatus("Ready", true); }
  };
}

async function beginRecording() {
  if (!socket || socket.readyState !== WebSocket.OPEN || isRecording || isFinalizingAudio) return;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    activeCaptureId = crypto.randomUUID();
    audioContext = new AudioContext(); await audioContext.resume(); analyser = audioContext.createAnalyser(); analyser.fftSize = 1024; analyserSource = audioContext.createMediaStreamSource(stream); analyserSource.connect(analyser); silenceStartedAt = 0; speechDetected = false;
    recorder = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "" });
    audioSendChain = Promise.resolve();
    recorder.ondataavailable = ({ data }) => {
      if (!data.size) return;
      // Preserve MediaRecorder order. Without this queue, the asynchronous
      // conversion can let stop_recording overtake the WebM header chunk.
      audioSendChain = audioSendChain.then(async () => {
        const buffer = await data.arrayBuffer();
        let binary = "";
        new Uint8Array(buffer).forEach((byte) => { binary += String.fromCharCode(byte); });
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "audio_chunk", data: btoa(binary), duration_ms: CHUNK_DURATION_MS, session_id: sessionId, capture_id: activeCaptureId }));
        }
      });
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      // The final dataavailable event occurs just before onstop. Wait until it
      // has reached the server before marking this recording complete.
      void audioSendChain
        .catch(() => setStatus("Could not send microphone audio"))
        .then(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "stop_recording", session_id: sessionId, capture_id: activeCaptureId }));
            setStatus("Processing…");
          }
        })
        .finally(() => { isFinalizingAudio = false; });
    };
    recorder.start(CHUNK_DURATION_MS); isRecording = true; monitorSilence(); talk.classList.add("recording"); talk.textContent = "Listening…"; stop.disabled = false; setStatus("Listening…");
  } catch { setStatus("Microphone permission was denied"); }
}
function endRecording() { if (!isRecording) return; isRecording = false; isFinalizingAudio = true; stopSilenceMonitor(); recorder.stop(); talk.classList.remove("recording"); talk.textContent = "Hold to talk"; stop.disabled = true; }

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
form.onsubmit = (event) => { event.preventDefault(); const text = input.value.trim(); if (!text || socket?.readyState !== WebSocket.OPEN) return; addMessage("user", text); socket.send(JSON.stringify({ type: "text", data: text, session_id: sessionId })); input.value = ""; };
document.querySelectorAll("[data-prompt]").forEach((button) => { button.addEventListener("click", () => { input.value = button.dataset.prompt; input.focus(); }); });
document.querySelectorAll("[data-pet-sound]").forEach((pet) => { pet.addEventListener("click", () => { playMeow(pet); pet.classList.remove("is-meowing"); void pet.offsetWidth; pet.classList.add("is-meowing"); }); });
connect();
