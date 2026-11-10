const API = "http://127.0.0.1:8000";
const WS = "ws://127.0.0.1:8000";
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const form = $<HTMLFormElement>("capture-form");
const statusElement = $("status");
const startButton = $<HTMLButtonElement>("start");
const stopButton = $<HTMLButtonElement>("stop");
const endButton = $<HTMLButtonElement>("end-session");
$("origin").textContent = `Backend capture origin setting: ${location.origin}`;

type Speaker = "customer" | "salesperson" | null;
type WordGap = {start_ms: number; end_ms: number; duration_ms: number};
type RecordEvent = {
  segment: {source_id: string; segment_id: string; text: string; review_required: boolean; speaker: Speaker};
  gaps: WordGap[];
  turn: {analysis: {recommendation: {suggested_response: string; supporting_facts: string[]} | null}} | null;
};
type Source = {stream: MediaStream; socket: WebSocket; context?: AudioContext;
  playback?: AudioContext;
  worklet?: AudioWorkletNode; source?: MediaStreamAudioSourceNode; stopped: Promise<void>;
  finish: () => void; flushed?: () => void; sent: number; acknowledgedMs: number};
const sources: Source[] = [];
let sessionId: string | null = null;
let stopping = false;
let captureError: string | null = null;

function append(id: string, text: string): void {
  const item = document.createElement("li");
  item.textContent = text; // Transcript and product facts never become HTML.
  $(id).append(item);
}

async function post(path: string, data: unknown = {}): Promise<Record<string, unknown>> {
  const response = await fetch(API + path, {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data), signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error("The local API rejected the request. Check the session and product facts.");
  return await response.json() as Record<string, unknown>;
}

function showTranscript(data: RecordEvent, label: string): void {
  let text = `${label} (${data.segment.speaker ?? "unknown speaker"}): ${data.segment.text}`;
  if (data.segment.review_required || !data.segment.speaker) text += "\nReview required — coaching withheld.";
  const recommendation = data.turn?.analysis.recommendation;
  if (recommendation) {
    text += `\nSuggestion: ${recommendation.suggested_response}`;
    for (const fact of recommendation.supporting_facts) text += `\nSupplied fact: ${fact}`;
  }
  append("transcripts", text);
  if (!data.turn && sessionId) {
    const reviewSessionId = sessionId;
    const item = document.createElement("li");
    const labelElement = document.createElement("label");
    labelElement.textContent = "Check or correct this transcript before analysis";
    const input = document.createElement("textarea");
    input.value = data.segment.text; input.maxLength = 2000;
    labelElement.append(input);
    const speakerLabel = document.createElement("label");
    speakerLabel.textContent = "Confirmed speaker";
    const speakerSelect = document.createElement("select");
    for (const [value, name] of [["", "Choose speaker"], ["customer", "Customer"], ["salesperson", "Salesperson"]]) {
      const option = document.createElement("option"); option.value = value; option.textContent = name;
      speakerSelect.append(option);
    }
    speakerSelect.value = data.segment.speaker ?? ""; speakerLabel.append(speakerSelect);
    const button = document.createElement("button");
    button.type = "button"; button.className = "review"; button.textContent = "Use reviewed transcript";
    button.onclick = () => {
      if (!input.value.trim() || !speakerSelect.value) { statusElement.textContent = "Confirm both the words and speaker before analysis."; return; }
      button.disabled = true;
      void post(`/api/v1/sessions/${reviewSessionId}/transcripts/review`, {
        source_id: data.segment.source_id, segment_id: data.segment.segment_id,
        text: input.value, speaker: speakerSelect.value,
      }).then((record) => {
        input.disabled = true; speakerSelect.disabled = true;
        const reviewed = record as unknown as RecordEvent;
        const suggestion = reviewed.turn?.analysis.recommendation;
        append("transcripts", `Reviewed ${speakerSelect.value}: ${input.value}`
          + (suggestion ? `\nSuggestion: ${suggestion.suggested_response}` : "\nNo recommendation."));
      }).catch(() => { button.disabled = false; statusElement.textContent = "Review could not be applied. The session may have ended or this transcript was already analysed."; });
    };
    item.append(labelElement, speakerLabel, button); $("transcripts").append(item);
  }
  for (const gap of data.gaps) append("pauses", `${label}: estimated word gap ${gap.duration_ms} ms (${gap.start_ms}–${gap.end_ms} ms).`);
}

function fail(message: string): void {
  captureError = message;
  statusElement.textContent = message;
  void stopCapture();
}

async function connectSource(stream: MediaStream, role: Speaker, label: string, playback?: AudioContext): Promise<void> {
  const socket = new WebSocket(`${WS}/api/v1/sessions/${sessionId}/audio`);
  let finish!: () => void;
  const stopped = new Promise<void>((resolve) => { finish = resolve; });
  const source: Source = {stream, socket, stopped, finish, playback, sent: 0, acknowledgedMs: 0};
  sources.push(source);
  const ready = new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("The local transcription service did not become ready.")), 15000);
    socket.onopen = () => socket.send(JSON.stringify({type: "start", source_id: crypto.randomUUID(),
      speaker: role, sample_rate: 16000, consent_confirmed: true,
      enable_coaching: $<HTMLInputElement>("coaching").checked}));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string);
      if (message.type === "audio_ready") { clearTimeout(timeout); resolve(); }
      if (message.type === "audio_ack") source.acknowledgedMs = message.received_ms as number;
      if (message.type === "transcript_processed") showTranscript(message.data as RecordEvent, label);
      if (message.type === "audio_pause") {
        const data = message.data as WordGap;
        append("pauses", `${label}: measured low-energy interval ${data.duration_ms} ms (${data.start_ms}–${data.end_ms} ms).`);
      }
      if (message.type === "audio_stopped") source.finish();
      if (message.type === "error") {
        clearTimeout(timeout);
        const error = new Error(`Local audio service: ${String(message.code)}. Stop and review capture.`);
        reject(error); fail(error.message);
      }
    };
    socket.onerror = () => {
      clearTimeout(timeout);
      reject(new Error("Cannot connect to the local audio service. Check the server and extension origin setting."));
      if (!stopping) fail("Audio connection failed. Capture stopped.");
    };
    socket.onclose = () => {
      clearTimeout(timeout); source.finish();
      reject(new Error("Audio service closed before becoming ready."));
      if (!stopping) fail("Audio connection closed unexpectedly. Capture stopped; pending audio may be incomplete.");
    };
  });
  await ready;
  if (stopping || captureError) throw new Error("Capture startup was interrupted.");
  const context = new AudioContext({sampleRate: 16000});
  source.context = context;
  if (context.sampleRate !== 16000) throw new Error("This browser did not provide the required 16 kHz audio context.");
  await context.audioWorklet.addModule("build/pcm-worklet.js");
  const input = context.createMediaStreamSource(stream);
  const worklet = new AudioWorkletNode(context, "pcm-capture");
  source.source = input; source.worklet = worklet;
  worklet.port.onmessage = (event) => {
    if (!(event.data instanceof ArrayBuffer)) { source.flushed?.(); return; }
    if (socket.readyState !== WebSocket.OPEN) { fail("Audio connection lost. Capture stopped."); return; }
    if (!stopping && (socket.bufferedAmount > 512000 || source.sent * 100 - source.acknowledgedMs > 5000)) {
      fail("Transcription cannot keep up. Capture stopped rather than dropping audio silently."); return;
    }
    socket.send(event.data); source.sent++;
  };
  input.connect(worklet);
  const silent = context.createGain(); silent.gain.value = 0;
  worklet.connect(silent).connect(context.destination);
  for (const track of stream.getTracks()) track.onended = () => fail("An audio source ended. Capture stopped.");
  await context.resume();
}

async function stopCapture(): Promise<void> {
  if (stopping) return;
  stopping = true; stopButton.disabled = true;
  statusElement.textContent = captureError ?? "Stopping capture and finishing buffered speech…";
  await Promise.all(sources.map(async (source) => {
    if (source.worklet && source.context?.state === "running") {
      const flushed = new Promise<void>((resolve) => { source.flushed = resolve; });
      source.worklet.port.postMessage({type: "flush"});
      const didFlush = await Promise.race([flushed.then(() => true), new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 1000))]);
      if (!didFlush) captureError = "Audio stopped, but the final partial frame could not be confirmed. Review the last transcript.";
    }
    source.stream.getTracks().forEach((track) => track.stop());
    if (source.context && source.context.state !== "closed") await source.context.close();
    if (source.playback && source.playback.state !== "closed") await source.playback.close();
    if (source.socket.readyState === WebSocket.OPEN) {
      source.socket.send(JSON.stringify({type: "stop"}));
      const completed = await Promise.race([source.stopped.then(() => true), new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 30000))]);
      if (!completed) captureError = "Audio stopped, but final transcription timed out. Review the last transcript.";
    }
    source.socket.close();
  }));
  sources.length = 0;
  form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input,select,textarea")
    .forEach((input) => { input.disabled = Boolean(sessionId) && ["product", "facts"].includes(input.id); });
  endButton.disabled = !sessionId;
  startButton.disabled = false; stopping = false;
  statusElement.textContent = captureError ?? "Audio stopped. Review transcripts, then end the session. History remains in memory until the server restarts.";
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    startButton.disabled = true; captureError = null;
    endButton.disabled = true;
    statusElement.textContent = "Requesting audio access…";
    let tabStream: MediaStream | undefined;
    let microphone: MediaStream | undefined;
    let playback: AudioContext | undefined;
    try {
      if (!$<HTMLInputElement>("consent").checked) throw new Error("Confirm participant agreement first.");
      const tabId = Number(new URLSearchParams(location.search).get("tab"));
      const current = await chrome.tabs.getCurrent();
      if (!Number.isInteger(tabId) || tabId <= 0 || !current.id) throw new Error("Open capture by clicking the extension on the Google Meet tab.");
      const id = await chrome.tabCapture.getMediaStreamId({targetTabId: tabId, consumerTabId: current.id});
      tabStream = await navigator.mediaDevices.getUserMedia({video: false,
        audio: {mandatory: {chromeMediaSource: "tab", chromeMediaSourceId: id}} as MediaTrackConstraints});
      if (!tabStream.getAudioTracks().length) throw new Error("The selected tab has no audio track.");
      // Restore call playback immediately, before any microphone permission prompt.
      playback = new AudioContext();
      playback.createMediaStreamSource(tabStream).connect(playback.destination);
      await playback.resume();
      if ($<HTMLInputElement>("microphone").checked) microphone = await navigator.mediaDevices.getUserMedia({
        video: false, audio: {echoCancellation: true, noiseSuppression: false, autoGainControl: false},
      });
      const facts = $<HTMLTextAreaElement>("facts").value.split("\n").map((fact) => fact.trim()).filter(Boolean);
      if (!sessionId) {
        const session = await post("/api/v1/sessions", {product: {name: $<HTMLInputElement>("product").value, facts}});
        sessionId = session.session_id as string;
      }
      const role = $<HTMLSelectElement>("remote-role").value as Speaker | "";
      await connectSource(tabStream, role || null, "Meeting tab", playback);
      if (microphone) await connectSource(microphone, "salesperson", "Microphone");
      if (stopping || captureError) throw new Error("Capture startup was interrupted.");
      form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input,select,textarea")
        .forEach((input) => { input.disabled = true; });
      stopButton.disabled = false;
      statusElement.textContent = "Capturing audio locally. Keep this tab open. Only explicitly assigned speakers can receive coaching.";
    } catch (error) {
      tabStream?.getTracks().forEach((track) => track.stop());
      microphone?.getTracks().forEach((track) => track.stop());
      if (playback && playback.state !== "closed") await playback.close();
      captureError = error instanceof Error ? error.message : "Capture failed.";
      await stopCapture();
    }
  })();
});
stopButton.addEventListener("click", () => { void stopCapture(); });
endButton.addEventListener("click", () => {
  if (!sessionId || sources.length) return;
  endButton.disabled = true;
  void post(`/api/v1/sessions/${sessionId}/end`).then(() => {
    sessionId = null;
    $<HTMLInputElement>("product").disabled = false; $<HTMLTextAreaElement>("facts").disabled = false;
    document.querySelectorAll<HTMLButtonElement>(".review").forEach((button) => { button.disabled = true; });
    statusElement.textContent = "Session ended. You can start a new capture session.";
  }).catch(() => { endButton.disabled = false; statusElement.textContent = "Could not end the session. Check the local server."; });
});
window.addEventListener("pagehide", () => {
  // Closing the page stops devices immediately. An abrupt close cannot reliably
  // finish a final transcript or end the session; use the Stop button normally.
  for (const source of sources) { source.stream.getTracks().forEach((track) => track.stop()); source.socket.close(); }
});
