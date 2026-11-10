# Sales signal evaluation, version 1

This is an initial **synthetic, agent-labelled benchmark**, not a statistically
representative sample or an independently reviewed test set. It contains 60
turns: 30 course and 30 software examples, with 56 customer turns (eight per
signal) and four salesperson boundary checks. Each row has a stable ID, domain,
scenario tags, gold labels, literal evidence and a reason for the annotation.
All examples are fictional. No customer transcripts or product claims were used.

The labels express the intended reading of the text. They are not copied from
model output. The set deliberately includes paraphrases the rules fail to
recognize, alongside ordinary phrasing and negative controls. Some scenarios
resemble existing regression tests, so this is not an independent estimate of
performance on unseen conversations. Labels are provisional until a human
reviewer checks them against the guidance below.

## Run the baseline

From the repository root, with the existing development environment installed:

```bash
PYTHONPATH=backend .venv/bin/python -m app.evaluation
```

Or, after activating the environment and installing the project with
`python -m pip install -e ".[dev]"` (also works on Windows):

```bash
python -m app.evaluation --output evaluation-report.json
```

The module requires a source checkout for its default dataset path. Supply
`--dataset path/to/cases.jsonl` to evaluate another file. The runner checks enum
labels, required fields, literal evidence, duplicate IDs and normalized duplicate
turns before inference. It passes only `speaker` and `text` to the predictor;
labels, tags, evidence and rationales are never model inputs.

The checked-in `baseline_rules_v0_1.json` records the initial run, dataset SHA-256
and hashes of the relevant source files. Runs are deterministic: no timestamps,
random split or network services are involved. The report contains case IDs and
label mismatches, not transcript text, evidence excerpts or customer data. Match
error IDs to rows locally to inspect mistakes.

Initial baseline results on these 60 examples:

| Measure | Result |
|---|---:|
| Signal accuracy | 78.33% |
| Signal macro F1 | 81.10% |
| Exact objection-set match | 98.33% |
| Objection macro F1 | 97.78% |
| Joint signal and objection accuracy | 76.67% |
| Predicted evidence fragments occurring literally in input | 100% |

There are 14 cases with label mismatches. These scores describe this small,
balanced synthetic set only. Four salesperson cases are included in overall
scores; speaker, domain and scenario slices show counts and joint correct counts.
A high objection exact-match score partly reflects turns with no objections.
Read it alongside per-objection support, precision, recall and F1.

## Annotation guidance

Annotate the customer's **expressed meaning**, not exact keyword presence,
expected purchase outcome, seller optimism or a confidence/probability estimate.
Read the complete turn before assigning labels. Do not assume missing context.

Choose one signal:

| Label | Meaning |
|---|---|
| `refusal` | Explicitly declines purchase, subscription or enrolment. A polite question or delayed decision alone is not refusal. |
| `conditional_interest` | Explicit interest/purchase depends on a stated condition. A feature question alone is not conditional interest. |
| `purchase_intent` | Explicit, unqualified readiness, commitment or transaction request. This is observed language, not proof that a sale will occur. |
| `deferral` | Explicitly postpones deciding or requests time/consultation. Do not infer delay merely from mentioning a budget. |
| `positive_interest` | Favourable reaction or stated interest without committing to purchase. |
| `information_request` | Asks for information, including polite requests without `?`, with no stronger signal. |
| `neutral` | No supported signal, including background statements or an objection without a decision/interest signal. |

To remain consistent with the current single-label contract, use this precedence
when multiple signals are explicit: refusal, conditional interest, purchase
intent, deferral, positive interest, information request, neutral. Retain all
applicable objections separately. This is an annotation policy, not a universal
claim about buyer psychology. An ambiguous contradiction requiring additional
context should be reviewed before inclusion, rather than guessed.

Assign zero or more objections:

| Label | Required meaning |
|---|---|
| `price` | Expressed cost, value or affordability constraint. A price question or review of a budget alone is insufficient. |
| `time_commitment` | Expressed lack of time or concern about required time, including onboarding/setup. A duration question alone is insufficient. |
| `trust` | Expressed distrust, doubt about legitimacy or credibility. A neutral security question alone is insufficient. |
| `product_fit` | Expressed mismatch with requirements, skill level or compatibility. Do not assume a mismatch from an integration question or a requested feature condition. |
| `cancellation_or_refund` | Expressed concern about cancellation/refunds or an asserted restrictive policy. A neutral policy question alone is insufficient; asking what happens if cancellation is impossible does express a concern. |

Additional rules:

- Negation is local: “not expensive” is not a price concern, but a separate
  “I cannot afford it” still is. An objection does not establish a decision signal.
- Quoted demonstrations and explicitly hypothetical commitments are not the
  customer's actual intent. Hypothetical policy-risk questions can be concerns.
- Questions followed by assertions retain the assertion's signal/objections.
- A salesperson turn is always labelled `neutral`, with no buyer objections or
  evidence, regardless of keywords. Their response does not resolve a concern.
- Gold evidence uses literal excerpts supporting labels. For information
  requests it can include the question/request; neutral negative controls need
  no evidence. Explain why the labels apply in `rationale`.
- Product descriptions and feature mentions do not authorize invented pricing,
  security guarantees, integration support or cancellation terms.

## Metrics and tests

The runner reports single-label signal accuracy and per-label precision, recall,
F1 and support; macro F1 averages all seven signal labels. Objections are
multi-label: exact match compares sets, micro scores aggregate TP/FP/FN across
all five labels, and macro F1 averages the five per-label scores. Zero denominators
produce zero, with support shown. Joint accuracy requires both signal and the
complete objection set to match.

The evidence metric checks only that returned fragments occur literally in the
input. It does **not** measure whether excerpts justify labels, are complete, or
match the annotated evidence. No fragments produces `null`, not perfect accuracy.
This benchmark does not measure recommendation quality, fact retrieval, latency,
conversation-level resolution or calibration. Those need separate evaluation.

`backend/tests/test_evaluation.py` tests arithmetic against hand-computed fixture
results, data validation, separation of gold labels from predictor inputs,
reproducible reports and error privacy. It validates this dataset's structure and
coverage without asserting that the rules must match its gold labels. Regression
tests and benchmark accuracy remain separate; known model errors do not fail
pytest. The CLI exits successfully when evaluation completes, even with errors.

## Keep evaluation separate from learning

Version 1 is reserved for evaluation: do not load it into training, prompt
examples, retrieval or fine-tuning. There is no training or tuning split here.
Future training and validation data must be created separately, with scenario
families and near-duplicates kept out of the evaluation split. Literal duplicate
checking in the loader does not detect semantic leakage across datasets.

Since this benchmark has been inspected and its scores are now visible, repeated
rule/model tuning against its errors would make it a development benchmark.
If we use it that way, retain it under that role and create a new independently
reviewed, unseen test set before reporting final trained-model performance.
Do not remove it when adding a trained model.

For a future model, pass a callable to `evaluate(cases, predictor=...)`. It takes
only a `TurnInput` and returns an object with the existing `buying_signal`,
`objections` and `evidence` attributes. An adapter can supply those fields without
changing the live API. Evaluate rules and the frozen trained model on the same
version and report metrics, errors and provenance for both.

Do not edit labels to match predictions. Correct annotation errors only with a
written reason and a new dataset version; retain the old dataset/report for
comparison. Add new scenarios in a new version. Before stronger claims, have a
second annotator review labels without seeing predictions, record disagreements,
and adjudicate them against these guidelines. Versioning is a documented process,
not an automated access restriction; this repository does not enforce data usage.
