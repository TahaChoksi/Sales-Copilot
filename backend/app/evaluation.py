"""Offline evaluation of labelled synthetic turns; never imported by API routes.

Run from a source checkout: PYTHONPATH=backend python -m app.evaluation
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from app.schemas import BuyingSignal, Objection, TurnInput
from app.store import analyse_turn


class EvaluationCase(TurnInput):
    case_id: str = Field(min_length=1)
    domain: Literal["course", "software"]
    tags: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    buying_signal: BuyingSignal
    objections: list[Objection]
    evidence: list[str]

    @field_validator("case_id", "rationale")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Annotation must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value) or len(value) != len(set(value)):
            raise ValueError("Tags must be nonblank and unique")
        return value

    @model_validator(mode="after")
    def valid_annotation(self) -> EvaluationCase:
        if len(self.objections) != len(set(self.objections)):
            raise ValueError("Objection labels must be unique")
        if any(not fragment.strip() or fragment not in self.text for fragment in self.evidence):
            raise ValueError("Evidence must be literal nonblank transcript excerpts")
        if (self.objections or self.buying_signal not in (
            BuyingSignal.NEUTRAL, BuyingSignal.INFORMATION_REQUEST,
        )) and not self.evidence:
            raise ValueError("Observed signals and objections require evidence")
        if self.speaker.value == "salesperson" and (
            self.buying_signal != BuyingSignal.NEUTRAL or self.objections or self.evidence
        ):
            raise ValueError("Salesperson turns cannot express buyer labels")
        return self


class Prediction(Protocol):
    buying_signal: BuyingSignal
    objections: list[Objection]
    evidence: list[str]


Predictor = Callable[[TurnInput], Prediction]


def load_cases(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    ids: set[str] = set()
    turns: set[tuple[str, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = EvaluationCase.model_validate_json(line)
            key = (case.speaker.value, " ".join(case.text.casefold().split()))
            if case.case_id in ids or key in turns:
                raise ValueError("Duplicate case ID or normalized turn")
        except ValueError:
            # Do not include raw transcript text or Pydantic input dumps.
            raise ValueError(f"Invalid evaluation case at line {line_number}") from None
        ids.add(case.case_id)
        turns.add(key)
        cases.append(case)
    if not cases:
        raise ValueError("Evaluation dataset must not be empty")
    return cases


def _scores(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    # Zero denominators score zero, including absent labels. Supports are shown
    # so macro scores on small slices are not mistaken for stable estimates.
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "support": tp + fn, "tp": tp, "fp": fp, "fn": fn,
    }


def evaluate(cases: list[EvaluationCase], predictor: Predictor = analyse_turn) -> dict:
    if not cases:
        raise ValueError("Evaluation dataset must not be empty")
    signals = {label: [0, 0, 0] for label in BuyingSignal}
    objections = {label: [0, 0, 0] for label in Objection}
    signal_correct = objection_correct = joint_correct = 0
    evidence_count = literal_count = 0
    errors: list[dict] = []
    slices: dict[str, dict[str, int]] = {}
    for case in cases:
        # Only model inputs cross this boundary; gold labels and rationale do not.
        prediction = predictor(TurnInput(speaker=case.speaker, text=case.text))
        predicted_signal = BuyingSignal(prediction.buying_signal)
        predicted_objections = {Objection(label) for label in prediction.objections}
        expected_objections = set(case.objections)
        signal_ok = predicted_signal == case.buying_signal
        objections_ok = predicted_objections == expected_objections
        signal_correct += signal_ok
        objection_correct += objections_ok
        joint_correct += signal_ok and objections_ok
        for label, counts in signals.items():
            expected, predicted = case.buying_signal == label, predicted_signal == label
            counts[0] += expected and predicted
            counts[1] += not expected and predicted
            counts[2] += expected and not predicted
        for label, counts in objections.items():
            expected, predicted = label in expected_objections, label in predicted_objections
            counts[0] += expected and predicted
            counts[1] += not expected and predicted
            counts[2] += expected and not predicted
        valid_evidence = all(fragment.strip() and fragment in case.text for fragment in prediction.evidence)
        evidence_count += len(prediction.evidence)
        literal_count += sum(bool(fragment.strip()) and fragment in case.text for fragment in prediction.evidence)
        for key in [f"domain:{case.domain}", f"speaker:{case.speaker.value}", *(f"tag:{tag}" for tag in case.tags)]:
            bucket = slices.setdefault(key, {"count": 0, "joint_correct": 0})
            bucket["count"] += 1
            bucket["joint_correct"] += signal_ok and objections_ok
        if not (signal_ok and objections_ok and valid_evidence):
            errors.append({
                "case_id": case.case_id,
                "expected_signal": case.buying_signal.value,
                "predicted_signal": predicted_signal.value,
                "expected_objections": sorted(label.value for label in expected_objections),
                "predicted_objections": sorted(label.value for label in predicted_objections),
                "evidence_is_literal": valid_evidence,
            })
    signal_scores = {label.value: _scores(*counts) for label, counts in signals.items()}
    objection_scores = {label.value: _scores(*counts) for label, counts in objections.items()}
    return {
        "case_count": len(cases),
        "signal_accuracy": signal_correct / len(cases),
        "signal_macro_f1": sum(score["f1"] for score in signal_scores.values()) / len(signals),
        "signal_per_label": signal_scores,
        "objection_exact_match": objection_correct / len(cases),
        "objection_macro_f1": sum(score["f1"] for score in objection_scores.values()) / len(objections),
        "objection_micro": _scores(*(sum(counts[i] for counts in objections.values()) for i in range(3))),
        "objection_per_label": objection_scores,
        "joint_accuracy": joint_correct / len(cases),
        "evidence_fragment_count": evidence_count,
        "literal_evidence_rate": literal_count / evidence_count if evidence_count else None,
        "slices": slices,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[2] / "ml/evaluation/sales_signals_v1.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset)
    except (OSError, ValueError):
        parser.exit(2, "Could not load a valid labelled evaluation dataset.\n")
    report = evaluate(cases)
    report["dataset_sha256"] = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    report["predictor"] = "rules-v0.1"
    report["source_sha256"] = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("detection.py", "coaching.py", "store.py", "schemas.py", "evaluation.py")
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
