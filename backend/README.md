# AI Sales Copilot — FastAPI MVP v0.1

A **working local development starter** for a future real-time Google Meet sales coach. It analyses simulated text turns for buyer signals and objections, recommends a next action when appropriate, and stores a session history in memory.

**Scope:** This version processes text **not microphone audio**, uses **hand-written rules not a trained model**, and is **not safe to expose publicly**. No account login, consent framework, persistent database, or encrypted storage yet. Use only synthetic/test conversations.

## Prerequisites

- Python 3.11 or newer
- A terminal and code editor (Windows, macOS, or Linux)

## Run locally

Run all commands from the repository root (`GitHub/Project-1/`):

```bash
python -m venv .venv
```

Activate the environment:

- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.venv\\Scripts\\Activate.ps1`
- Windows Command Prompt: `.venv\\Scripts\\activate.bat`

Install:

```bash
python -m pip install -e ".[dev]"
```

Start the server in terminal 1:

```bash
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/docs** for the interactive API explorer.

Run the demo in terminal 2:

```bash
python backend/examples/replay.py
```

Run tests:

```bash
python -m pytest
```

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/v1/analyse` | Analyse one message without creating a session |
| POST | `/api/v1/sessions` | Start a session with explicit product facts |
| GET | `/api/v1/sessions/{id}` | Read session and its turns |
| POST | `/api/v1/sessions/{id}/turns` | Process a salesperson/customer text turn |
| POST | `/api/v1/sessions/{id}/end` | End a session |
| WS | `/api/v1/sessions/{id}/stream` | Submit JSON transcript turns, receive live analyses |

### Quick check in Swagger

1. Open `/docs`.
2. Expand `POST /api/v1/analyse` and select **Try it out**.
3. Enter:

```json
{
  "speaker": "customer",
  "text": "I like the course, but £99 per month is too expensive.",
  "product": {
    "name": "Demo Python Course",
    "facts": ["The course costs £99 per month."]
  }
}
```

You should receive the buying signal `positive_interest`, objection `price`, and a `explore_budget` recommendation. The evidence is the literal text matched by rules; it is **not a confidence score**.

### WebSocket contract

First create a session with the REST API, then open:

`ws://127.0.0.1:8000/api/v1/sessions/<session_id>/stream`

Send:

```json
{"speaker":"customer", "text":"I don't have enough time."}
```

Receive an event:

```json
{
  "type": "turn_processed",
  "data": {
    "turn_id": "...",
    "speaker": "customer",
    "text": "I don't have enough time.",
    "received_at": "...",
    "analysis": {
      "buying_signal": "neutral",
      "objections": ["time_commitment"],
      "evidence": ["don't have enough time"],
      "recommendation": {"action":"clarify_time_available", "suggested_response":"...", "rationale":"...", "supporting_facts":[]},
      "engine":"rules-v0.1"
    }
  }
}
```

The same `TurnInput` and `ProcessedTurn` schemas are used by the REST and WebSocket endpoints, so an audio transcription pipeline can produce these events later.

## What is and is not implemented

**Implemented**
- Product context specified per session (up to 20 factual statements)
- Buyer intent / objection rules (no purchase-probability guesses)
- A single recommendation for relevant customer turns
- Approved product facts may be surfaced verbatim for related questions
- Salesperson turns retained but not analysed for buyer intent
- Local in-memory history and basic conversation state (latest messages, observed concerns), simple end-session control, deterministic tests

**Not implemented yet**
- No speech-to-text, speaker diarisation, browser extension, or meeting integration
- No large language model, trained classifier, or semantic retrieval
- No authentication/authorization, persistence, privacy notices, audit logs or security hardening
- No conversation-level resolution tracking, event de-duplication, or transcript partial/final handling yet
- No seller-quality assessment, calibrated buying likelihood or outcome tracking

**Important limitation:** Current phrase matching misses many paraphrases, can misread negation and irony, and does not understand conversation context. It is a software/integration baseline, not a validated sales intelligence model.

## Next development steps

1. Agree on the sales-signal label taxonomy and write annotation guidelines.
2. Extend basic conversation state to track goals, answered questions and explicitly resolved concerns with unit tests.
3. Create an independent synthetic evaluation set and measure baseline precision/recall.
4. Replace `app/detection.py` behind the existing contract with a trained classifier.
5. Add the Chrome extension transcript source and privacy controls.
6. Replace in-memory storage with a permissioned, persistent data layer only when needed.

## Code map

- `app/schemas.py`: typed API input/output contracts
- `app/detection.py`: keyword/rule-based sales signal baseline
- `app/coaching.py`: suggestion templates and product-fact matching
- `app/store.py`: session storage and processing logic
- `app/main.py`: routes and WebSocket endpoint
- `examples/replay.py`: basic live-feel transcript simulator
- `tests/`: HTTP, WebSocket and classifier tests
