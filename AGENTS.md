
# AI Sales Copilot — Codex Instructions

## Project

AI Sales Copilot is a real-time sales coaching application.

The initial product supports salespeople selling online
courses and software subscriptions.

The long-term goal is a system that analyses meetings,
detects customer intentions and objections, and provides
evidence-based, context-aware sales recommendations.

## Current architecture

- Backend: Python, FastAPI, Pydantic
- Testing: pytest
- Initial storage: in-memory sessions
- AI: rule-based baseline, to be extended with trained ML
- Future frontend: Chrome extension with React/TypeScript
- Future ML: PyTorch, scikit-learn, Hugging Face
- Future audio: real-time transcription of online meetings

Inspect actual repository files before assuming a component
has already been implemented.

## Engineering principles

- Follow existing architecture unless a change is justified.
- Prefer simple, modular implementations.
- Keep API endpoints separate from business logic.
- Use clear type annotations and Pydantic validation.
- Avoid unnecessary dependencies or abstraction layers.
- Avoid duplicated logic and large monolithic functions.
- Preserve backward compatibility unless explicitly approved.
- Do not silently change existing API response contracts.

## Development workflow

For non-trivial tasks:

1. Inspect the relevant code and tests.
2. Identify the smallest reasonable implementation.
3. Write or update tests for the expected behaviour.
4. Implement the feature.
5. Run the relevant tests.
6. Review the diff for regressions and security issues.
7. Summarise changes, verification and unresolved risks.

Use a short plan for complex changes. Do not require a plan
for trivial fixes.

## Testing

Existing backend tests run with:

    python -m pytest -v

If the app package cannot be imported, inspect pytest's
configuration and the backend source layout before fixing it.

- Never delete tests just to make a change pass.
- Include tests for invalid inputs and missing sessions.
- Mock external AI APIs and services in unit tests.
- Keep tests deterministic.
- Report actual results, never assumed results.

## Sales intelligence requirements

- Separate observed customer signals from predictions.
- Never fabricate a probability of purchase.
- A salesperson replying does not mean an objection is resolved.
- Recommendations must use relevant conversation context.
- Do not invent product facts, guarantees or pricing.
- Recommendations must be explainable using transcript evidence.
- Prefer no recommendation over unsupported advice.

## Data and security

- Do not commit credentials, recordings or private transcripts.
- Use synthetic or explicitly authorised test data.
- Keep future customer and organisation data isolated.
- Do not log raw sensitive conversation content by default.
- Do not use customer data for model training automatically.

## Git and change management

- Make focused changes with readable diffs.
- Do not push, merge, deploy or modify remote resources
  without explicit permission.
- Ask before adding production dependencies.
- Do not rewrite unrelated files.

## Collaboration

The developer is learning software engineering and ML.

Explain significant architectural decisions, trade-offs,
and important implementation details briefly.

For completed tasks report:
- Files changed
- Behaviour implemented
- Tests executed and results
- Remaining risks
- Recommended next task

## Code Review Rules

- Flag API response changes that break existing consumers.
  Prefer preserving contracts or explicitly versioning them.
- Flag code that treats keyword matches as verified buyer
  intent or calibrated purchase probabilities.
- Flag accidental logging, persistence or sharing of
  sensitive customer conversation data.
