# AI Sales Copilot — FastAPI MVP v0.1

A **local text-based backend MVP** for a future real-time sales coach. It analyses simulated text turns for buyer signals and objections, recommends a next action when appropriate, and stores a session history in memory.

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

Use `python -m pytest -v` for individual test results. On macOS/Linux, if
`python` points to the system interpreter, use `.venv/bin/python` instead.
The MVP acceptance suite includes REST/WebSocket parity, invalid input recovery,
missing and ended sessions, product-fact isolation, and independent store snapshots.

Run one server process: in-memory sessions are local to that process. Reloading
the server clears sessions; multiple workers do not share them.

## Agreed MVP decisions

- Python, FastAPI and Pydantic; endpoints delegate analysis and storage to modules.
- Final text turns with an explicit customer or salesperson label, delivered by
  REST or WebSocket using the same schemas and processing path.
- Product facts supplied explicitly per session; suggestions may surface these
  facts verbatim, but the application does not independently verify them.
- Deterministic rules with literal transcript evidence, no purchase probability,
  and at most one recommendation per customer turn. Refusal suppresses coaching.
- In-memory session history; salesperson replies do not resolve observed concerns.
  Store inputs and returned snapshots are copied to prevent external mutation.
- Existing v1 response contracts retained, with no new production dependencies.

Authentication, persistence, browser UI, audio and trained ML are outside this
MVP. Changes to these decisions require agreement before implementation.

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
- Supplied product facts surfaced verbatim across mentioned topics (up to two)
- Product-neutral coaching for courses and software subscriptions, including
  explicit integration mismatches and onboarding time concerns
- Conservative quotation and hypothetical-intent guards; explicit conditional
  subscriptions remain conditional, with literal transcript evidence
- Salesperson turns retained but not analysed for buyer intent
- Local in-memory history and basic conversation state (latest messages, observed concerns), simple end-session control, deterministic tests

**Not implemented yet**
- No speech-to-text, speaker diarisation, browser extension, or meeting integration
- No large language model, trained classifier, or semantic retrieval
- No authentication/authorization, persistence, privacy notices, audit logs or security hardening
- No conversation-level resolution tracking, event de-duplication, or transcript partial/final handling yet
- No seller-quality assessment, calibrated buying likelihood or outcome tracking

**Important limitation:** Current phrase matching misses many paraphrases, can misread negation and irony, and does not understand conversation context. It is a software/integration baseline, not a validated sales intelligence model.

Fact retrieval matches complete words and explicit word forms for recordings,
price, time/setup, cancellation, integrations, and security. For general
questions it takes one fact per topic before taking a second from any topic,
deduplicating exact text and stopping at two facts. Topic order is deterministic:
recordings, price, time, cancellation, integrations, security; facts within each
topic keep their supplied order. Objection-focused coaching restricts facts to
the selected objection's topic. The existing coaching priority remains
cancellation, trust, price, time, then product fit. Security facts may support a
trust concern and integration facts a fit concern only when those topics are
explicitly mentioned. Other trust/fit concerns receive clarifying questions
without loosely related facts. Supplied facts are not independently verified.

Quotation guards cover paired straight double quotes and smart double quotes;
hypothetical-intent guards cover sentences starting with `what if`, `suppose`,
or `imagine`. Policy questions such as "What if I can't cancel?" still preserve
the cancellation concern. These are narrow rules, not a general grammar parser:
unquoted reported speech, arbitrary nested negation, sarcasm, and other
hypothetical forms can still be misread. Topic matching does not determine
whether a fact answers an exact question or proves compatibility with a named
system. It also does not resolve references to earlier turns.

Session isolation is data separation inside one process,
not an authorization boundary: anyone with access to this local API and a session
ID can read that session. History grows for the lifetime of the process, and
snapshots copy the complete history; this is suitable for short local demos only.
No response-time or model-accuracy target has been measured.

## Next development steps

The initial synthetic evaluation set, annotation guidance and recorded rule
baseline are in [ml/evaluation](../ml/evaluation/README.md). Run it from the
repository root with `PYTHONPATH=backend .venv/bin/python -m app.evaluation`.
It measures interpretation separately from passing regression tests; it is not
an independently reviewed estimate of real-world accuracy.

1. Review the provisional labels and annotation guidelines with a second annotator.
2. Extend basic conversation state to track goals, answered questions and explicitly resolved concerns with unit tests.
3. Expand independent evaluation coverage, keeping training and tuning data separate.
4. Replace `app/detection.py` behind the existing contract with a trained classifier.
5. Add the Chrome extension transcript source and privacy controls.
6. Replace in-memory storage with a permissioned, persistent data layer only when needed.

## Code map

- `app/schemas.py`: typed API input/output contracts
- `app/detection.py`: keyword/rule-based sales signal baseline
- `app/coaching.py`: suggestion templates and product-fact matching
- `app/store.py`: session storage and processing logic
- `app/evaluation.py`: offline labelled-data validation and evaluation metrics
- `app/main.py`: routes and WebSocket endpoint
- `examples/replay.py`: basic live-feel transcript simulator
- `tests/`: HTTP, WebSocket and classifier tests
