# Local voice capture prototype

This phase adds English speech recognition for Google Meet in Chrome, as approved:
local `faster-whisper`, downloaded model weights, separate tab/microphone sources,
and observed pause timing. Existing text API schemas and endpoints are unchanged.
The video-call integration consumes the meeting's **audio**; camera images and
visual behaviour are not captured or analysed.

The extension is an initial TypeScript capture/review harness with native controls.
The full React coaching frontend remains future work. Nothing in this phase was
pushed or deployed automatically.

## Run locally

From the repository root, install the approved optional speech dependencies:

```bash
.venv/bin/python -m pip install -e '.[dev,speech]'
```

The default CPU model is `small.en`, using int8 computation. Download it explicitly
once (network required; approximately 500 MB). The model directory is Git-ignored:

```bash
.venv/bin/python -c "from faster_whisper.utils import download_model; download_model('small.en', output_dir='.models/faster-whisper-small.en')"
```

Build the extension with Node.js 18+:

```bash
npm ci --prefix extension
npm run build --prefix extension
```

In Chrome, open `chrome://extensions`, enable **Developer mode**, choose
**Load unpacked**, and select this repository's `extension` directory. Copy the
extension ID shown by Chrome. Build outputs are ignored; rebuilding is required
in a fresh checkout. Reload the extension after rebuilding changed TypeScript.

Start the backend with its model path and the exact permitted extension origin:

```bash
SALES_COPILOT_SPEECH_MODEL=.models/faster-whisper-small.en \
SALES_COPILOT_EXTENSION_ORIGIN=chrome-extension://YOUR_EXTENSION_ID \
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Use a single server process. Leaving `SALES_COPILOT_SPEECH_MODEL` unset keeps the
original text-only startup; audio requests report `speech_unavailable`. The
model must already exist: server startup and request handling never download it.
Optional speech imports do not run in text-only mode. PyAV is bounded below v19
because faster-whisper 1.2's file decoder uses the older PyAV API.

## Capture and review

1. Open the Google Meet tab and click the extension action. This opens the capture
   page. Capture begins only after you click **Start capture** and confirm that
   participants agreed to audio processing.
2. Enter the product and any checked facts. The product stays fixed for this
   session; end the session before changing it.
3. Leave the remote speaker **unknown** for a multi-party meeting. Assign the tab
   to **customer** only when you have confirmed it contains one customer's speech.
   Chrome's tab mix does not identify individual meeting participants.
4. Optionally include your microphone as **salesperson**. Use headphones to reduce
   the chance that remote playback is picked up by the microphone too.
5. Leave automatic coaching unchecked for the initial trial. Read/correct each
   final transcript, confirm its speaker, and click **Use reviewed transcript**.
   Suggestions use the reviewed words, while the original recognition and timing
   stay in the transcript record. Do not submit guesses for inaudible words.
6. **Stop capture** releases audio devices and finishes buffered recognition; it
   keeps the session active for review. You may resume capture with new source
   IDs in that session. After reviewing, click **End session after review**.

Keep the capture page open during use. Closing it stops devices, but cannot
reliably flush the last audio or end the session; use Stop normally. The last
partial 100 ms frame is zero-padded on normal Stop so its real samples are sent.
If a flush or final transcription cannot be confirmed, the page warns you.

The capture page restores the meeting's playback after tab capture, before asking
for microphone access. Microphone audio is not played back locally. Recording
permissions can be revoked through Chrome's controls.

## What timing means

There are two separate observations, both relative to a **source's media clock**:

- `audio_pauses`: PCM frames below a normalized RMS level of 0.005, retained when
  a run lasts at least 500 ms. Resolution is 100 ms. The `pcm_rms` basis and
  threshold are included. Quiet audio can mean silence, mute, noise suppression,
  quiet speech or a connection problem; RMS does not prove absence of speech.
- `gaps`: gaps of at least 500 ms between recognized word timestamps, including
  consecutive final segments from the same source. The `word_timestamps` basis
  identifies these as alignment estimates, not independently verified silence.

Initial idle silence before any detected audio is not labelled as a pause.
Overlapping words do not create negative gaps. Missing word timing breaks the gap
chain rather than inventing an interval. A new source ID resets the timeline.
Clock positions come from sample counts, never WebSocket receipt times.
Tab and microphone clocks start independently; cross-speaker response latency
and overlap attribution are not implemented.

Pause observations do **not** change buying signals, claim hesitation, resolve
objections, trigger coaching by themselves, or produce a purchase probability.
They are retained for inspection and a future, separately evaluated interpretation
layer. Corrected words do not get invented timestamps: timing remains tied to the
original recognition.

## Recognition and coaching policy

The local model transcribes English, returns word timestamps, uses voice-activity
filtering, and does not reuse previous decoded text as a prompt. Returned wording
is retained without paraphrasing or filler cleanup. Whisper can still omit fillers,
miss negation, mistranscribe names/numbers, or hallucinate text, especially with
noise or overlapping voices. This is not a verbatim-accuracy guarantee.

The audio buffer uses a two-second low-energy endpoint and 200 ms pre-roll. A
20-second cap bounds each buffer. A forced cut, the fragment after a forced cut,
and a manually stopped partial utterance require review. Two seconds of quiet
is an acoustic boundary, not proof a sentence or purchase decision is complete.
Very quiet speech can be clipped by the energy heuristic, and pauses can split
one thought. Verify the full context before enabling automatic coaching.

Automatic coaching is opt-in and requires an explicitly mapped speaker. It is
withheld when word scores fall below 0.6, segment average log probability below
-1, no-speech score above 0.5, word timing is missing, or a window is incomplete.
These are conservative engineering heuristics, **not calibrated correctness
probabilities**. High scores do not establish an accurate transcript. By default,
all live transcripts require manual review.

Partial transcript revisions are supported by the transcript API and never produce
turns or coaching. The local audio adapter currently emits final recognition only
(after an acoustic endpoint), not live partial text. Identical final replays are
idempotent; stale revisions and changed final replays are rejected. Review is an
explicit action on an unanalysed final record; identical review retries do not
create duplicate turns. Already analysed text cannot be silently overwritten.

## Additive API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/sessions/{id}/transcripts` | Read latest segment revisions and retained audio pauses |
| POST | `/api/v1/sessions/{id}/transcripts` | Submit a typed partial/final transcript with word timing |
| POST | `/api/v1/sessions/{id}/transcripts/review` | Confirm/correct an unanalysed final transcript and speaker |
| WS | `/api/v1/sessions/{id}/audio` | Stream local PCM audio and receive recognition/timing events |

Create the session through the existing API first. Send this WebSocket start event:

```json
{"type":"start","source_id":"unique-source-id","sample_rate":16000,"speaker":null,"enable_coaching":false,"consent_confirmed":true}
```

Wait for `audio_ready`, then send binary frames of **3200 bytes**: 100 ms of mono,
16 kHz signed PCM16 little-endian. Send quiet frames too; do not trim silence or
resample by skipping samples. The server acknowledges received media time in
`audio_ack`. It emits `transcript_processed` and `audio_pause` events. To finish,
send `{"type":"stop"}` and wait for `audio_stopped`.

Each continuous capture needs a new source ID, including reconnects. An invalid
frame ends the stream instead of guessing elapsed audio. The extension stops with
a warning when more than five seconds are unacknowledged or its outgoing socket
buffer exceeds 512 KB. It does not silently discard audio to catch up. CPU model
inference is serialized and run outside the ASGI event loop; no real-time latency
service level is promised. Abrupt disconnects discard buffered audio not yet
submitted for inference; recognition already in flight may finish before the
server detects the disconnect.

Browser audio sockets require the exact configured extension Origin. Local native
clients without an Origin are supported; this check is not authentication. All
features remain localhost-only. The participant-agreement checkbox is a user
confirmation, not an implemented legal/organisational consent system.

## Data and verification

Live audio is buffered only in process memory, with no audio-file writing,
cloud transcription, automatic training or raw transcript logging in the new
pipeline. ONNX runtime telemetry is disabled before inference. Model/dependency
downloads require network; actual local-model inference does not. Transcripts,
reviewed text and timing remain in the existing in-memory session store until
server restart. There is no account isolation or persistent secure storage.

Tests:

```bash
.venv/bin/python -m pytest -v
npm test --prefix extension
```

Backend tests cover framing, clocks, pause retention, bounded buffering, final/
partial handling, speaker/quality gates, lifecycle, correction idempotency, error
privacy and old API compatibility. The Node tests exercise PCM conversion, quiet
frames, channel mixing and partial-frame flushing; they do not run Chrome APIs.

An offline word-error evaluator accepts only explicitly authorised local clips:

```bash
.venv/bin/python backend/examples/evaluate_audio.py clip.wav reference.txt --streaming
```

Use clips no longer than 20 seconds. The `--streaming` option exercises the same
buffer/endpoint logic as capture. Output includes word-error counts, timing
observations and an audio hash, without printing the transcript/reference.
Punctuation/case are normalized; negation and numeric differences are retained.
Empty references have no defined WER (`null`); insertions are still counted.
Do not commit private clips or references. `.audio-evaluation/` is Git-ignored.

For reproducible fictional smoke clips, optionally install the test-only
`espeakng-loader` utility (not required by the application), then run
`python backend/examples/generate_synthetic_speech.py`. This creates four
WAV/reference pairs under `.audio-evaluation/`. The initial local smoke run used
faster-whisper 1.2.1, CPU int8 `small.en`, CTranslate2 4.8.5, PyAV 18.1.0 and
eSpeak loader 0.2.4. All 31 reference words across three clips matched. The actual
audio WebSocket was also checked with these clips. A scripted 1500 ms pause was
retained as a 1490 ms estimated word gap in offline streaming evaluation (1470 ms
through the WebSocket with additional trailing silence) and a 1400 ms low-energy
interval (100 ms frame resolution). Silence produced no transcript. These tiny clean
synthetic checks are not a real-call accuracy estimate or a new held-out benchmark.
A fourth 11-word clip containing fillers produced one substitution (9.09% WER)
in streaming evaluation (`plan` became `land`; the fillers and negation were
retained). Keep that error in the review record; the clean-clip results do not
establish verbatim recognition of real speech.

**Browser verification remains outstanding:** this development environment has
no Chrome/Chromium executable, and no live Meet call was recorded or tested.
Before routine use, test on an agreed fictional call: allow/deny microphone
permission; verify tab playback; speak negations, prices, product names and
fillers; pause for known intervals; try overlap/mute; stop/restart; close the
capture tab; and check that devices stop and uncertain/unknown speech produces
no automatic coaching. Review representative authorised clips against human
transcripts and measure word/negation errors and pause timing before claiming
accuracy or enabling automatic coaching in real sales calls.
