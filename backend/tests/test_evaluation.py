"""Test evaluator arithmetic/validation without requiring model accuracy."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.evaluation import EvaluationCase, evaluate, load_cases
from app.schemas import BuyingSignal, Objection


DATASET = Path(__file__).resolve().parents[2] / "ml/evaluation/sales_signals_v1.jsonl"


def make_case(case_id="fixture-1", **overrides):
    values = dict(case_id=case_id, speaker="customer", domain="software", text="It's too expensive.",
                  tags=["fixture"], rationale="A stated expense concern is not a buying decision.",
                  buying_signal="neutral", objections=["price"], evidence=["too expensive"])
    values.update(overrides)
    return EvaluationCase.model_validate(values)


def test_metrics_use_gold_labels_and_do_not_pass_them_to_predictor():
    cases = [
        make_case(),
        make_case("fixture-2", text="I'll buy.", buying_signal="purchase_intent",
                  objections=[], evidence=["I'll buy"]),
        make_case("fixture-3", text="Hello.", objections=[], evidence=[]),
    ]
    predictions = iter([
        SimpleNamespace(buying_signal="neutral", objections=["price", "trust"], evidence=["too expensive"]),
        SimpleNamespace(buying_signal="neutral", objections=[], evidence=[]),
        SimpleNamespace(buying_signal="purchase_intent", objections=[], evidence=["invented"]),
    ])

    def predictor(turn):
        assert set(turn.model_dump()) == {"speaker", "text"}
        return next(predictions)

    report = evaluate(cases, predictor)
    assert report["signal_accuracy"] == pytest.approx(1 / 3)
    assert report["signal_per_label"]["neutral"] == dict(
        precision=0.5, recall=0.5, f1=0.5, support=2, tp=1, fp=1, fn=1,
    )
    assert report["signal_macro_f1"] == pytest.approx(0.5 / 7)
    assert report["objection_exact_match"] == pytest.approx(2 / 3)
    assert report["objection_micro"]["precision"] == 0.5
    assert report["objection_micro"]["recall"] == 1.0
    assert report["objection_micro"]["f1"] == pytest.approx(2 / 3)
    assert report["objection_macro_f1"] == 0.2
    assert report["joint_accuracy"] == 0
    assert report["literal_evidence_rate"] == 0.5
    assert report["evidence_fragment_count"] == 2
    assert report["slices"]["domain:software"] == {"count": 3, "joint_correct": 0}
    assert len(report["errors"]) == 3
    assert report["errors"][-1]["evidence_is_literal"] is False
    assert "It's too expensive" not in json.dumps(report)
    assert "invented" not in json.dumps(report)


def test_objection_false_negatives_and_no_evidence_denominator():
    report = evaluate([make_case()], lambda turn: SimpleNamespace(
        buying_signal="neutral", objections=[], evidence=[],
    ))
    assert report["objection_per_label"]["price"]["fn"] == 1
    assert report["objection_micro"]["recall"] == 0
    assert report["literal_evidence_rate"] is None
    assert report["errors"][0]["evidence_is_literal"] is True


@pytest.mark.parametrize("overrides", [
    {"speaker": "salesperson"},
    {"buying_signal": "unknown"},
    {"objections": ["price", "price"]},
    {"objections": ["unknown"]},
    {"evidence": []},
    {"evidence": ["fabricated"]},
    {"tags": [" "]},
    {"tags": ["same", "same"]},
    {"rationale": " "},
    {"case_id": " "},
    {"text": " "},
    {"domain": "unknown"},
    {"extra": True},
])
def test_invalid_annotations_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make_case(**overrides)


@pytest.mark.parametrize("content", ["", "\n", "{broken}", "{}"])
def test_invalid_dataset_files_are_rejected(tmp_path, content):
    path = tmp_path / "cases.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_cases(path)


@pytest.mark.parametrize("same_id", [True, False])
def test_duplicate_ids_or_normalized_turns_are_rejected(tmp_path, same_id):
    first = make_case()
    second = make_case(
        "fixture-1" if same_id else "fixture-2",
        text="That is too expensive." if same_id else "IT'S  TOO EXPENSIVE.",
        evidence=["too expensive"] if same_id else ["TOO EXPENSIVE"],
    )
    path = tmp_path / "cases.jsonl"
    path.write_text(first.model_dump_json() + "\n" + second.model_dump_json())
    with pytest.raises(ValueError, match="line 2"):
        load_cases(path)


def test_empty_evaluation_is_rejected():
    with pytest.raises(ValueError):
        evaluate([])


def test_seed_dataset_is_complete_and_valid_without_asserting_model_scores():
    cases = load_cases(DATASET)
    assert len(cases) == 60
    assert {case.buying_signal for case in cases} == set(BuyingSignal)
    assert {label for case in cases for label in case.objections} == set(Objection)
    assert {case.domain for case in cases} == {"course", "software"}
    assert sum(case.speaker.value == "salesperson" for case in cases) == 4
    # Validating the gold file does not call the model or enforce baseline scores.


def test_cli_writes_reproducible_report_without_transcript_text(tmp_path, monkeypatch):
    import hashlib
    from app.evaluation import main

    dataset = tmp_path / "fixture.jsonl"
    dataset.write_text(make_case().model_dump_json() + "\n")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["evaluate", "--dataset", str(dataset), "--output", str(output)])
    main()
    first = output.read_bytes()
    main()
    assert output.read_bytes() == first
    report = json.loads(first)
    assert report["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert report["predictor"] == "rules-v0.1"
    assert "detection.py" in report["source_sha256"]
    assert "It's too expensive" not in first.decode()


def test_loader_errors_do_not_echo_input(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps({"text": "synthetic-sensitive-marker", "speaker": "unknown"}))
    with pytest.raises(ValueError) as caught:
        load_cases(path)
    assert str(caught.value) == "Invalid evaluation case at line 1"
    assert "synthetic-sensitive-marker" not in str(caught.value)
