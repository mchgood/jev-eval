import json
from pathlib import Path

import pytest
from typesafe_sdk import SystemOneResponse

from jev_eval.backend import JevBackend, request_for
from jev_eval.cli import main
from jev_eval.metrics import ndcg, summarize
from jev_eval.schema import Case, load_cases

DATA = Path(__file__).parents[1] / "data/smoke.jsonl"


def test_dataset_and_label_isolation():
    cases = load_cases(DATA)
    assert {(c.domain, c.question["type"]) for c in cases} == {
        (d, k) for d in ("music", "navigation") for k in ("choice", "noul", "score")
    }
    for case in cases:
        assert set(request_for(case)) == {"state", "questions"}
        assert "gold" not in request_for(case)
        assert "rationale" not in request_for(case)


def test_invalid_label_and_duplicate_ids(tmp_path):
    case = load_cases(DATA)[0].model_dump()
    case["gold"] = "invalid"
    with pytest.raises(ValueError):
        Case.model_validate(case)
    case = load_cases(DATA)[0].model_dump()
    path = tmp_path / "bad.jsonl"
    path.write_text((json.dumps(case) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_ndcg_and_no_relevant_candidates():
    assert ndcg([3, 1, 0], [0.9, 0.5, 0.1]) == pytest.approx(1)
    assert ndcg([3, 1, 0], [0.1, 0.5, 0.9]) < 1
    assert ndcg([0, 0], [0.8, 0.2]) is None


def test_sdk_adapter_uses_real_sdk_response(monkeypatch):
    import jev_eval.backend as module

    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["retry"].max_retries == 0

        def system_one(self, **kwargs):
            calls.append(kwargs)
            kind = kwargs["questions"]["decision"].type
            if kind == "choice":
                answer = {
                    "type": kind,
                    "choice": "song",
                    "confidence": 1,
                    "probabilities": {"song": 1, "artist": 0, "album": 0, "clarify": 0},
                }
            elif kind == "noul":
                answer = {"type": kind, "noul": 0.8}
            else:
                answer = {
                    "type": kind,
                    "score": 2.7,
                    "confidence": 0.8,
                    "legend": {0: "bad", 1: "weak", 2: "acceptable", 3: "exact"},
                    "probabilities": {0: 0, 1: 0, 2: 0.3, 3: 0.7},
                }
            return SystemOneResponse.model_validate(
                {"model": "jev-1.13", "usage": {}, "answers": {"decision": answer}}
            )

        def close(self):
            pass

    monkeypatch.setattr(module, "TypeSafeClient", Client)
    backend = JevBackend("jev-1.13", 30)
    cases = load_cases(DATA)
    for kind in ("choice", "noul", "score"):
        case = next(c for c in cases if c.question["type"] == kind)
        raw = backend.evaluate(case)
        assert raw["answers"]["decision"]["type"] == kind
        assert set(calls[-1]) == {"state", "questions", "model"}
    backend.close()


def row(case, answer=None):
    return {
        "case": case.model_dump(),
        "status": "ok" if answer else "error",
        "latency_ms": 10,
        "raw": {"answers": {"decision": answer}, "usage": {}},
    }


def test_unknown_noul_and_failure_not_hidden():
    cases = load_cases(DATA)
    true = next(c for c in cases if c.id == "navigation-noul-0")
    false = next(c for c in cases if c.id == "navigation-noul-1")
    unknown = next(c for c in cases if c.gold is None)
    rows = [
        row(true, {"noul": 0.8}),
        row(false, {"noul": 0.2}),
        row(true),
        row(unknown, {"noul": 0.51}),
    ]
    summary = summarize(rows, 0.5)
    hard = next(g for g in summary["groups"] if g["task"] == "hard_constraint")
    assert hard["failed"] == 1
    assert hard["brier"] == pytest.approx(0.04)
    assert hard["precision"] == 1
    uncertain = next(g for g in summary["groups"] if g["task"] == "parking_evidence")
    assert uncertain["unknown_count"] == 1
    assert "brier" not in uncertain


def test_incomplete_ranking_and_fractional_score():
    cases = [c for c in load_cases(DATA) if c.domain == "music" and c.ranking_group]
    rows = [
        row(c, {"score": 2.7, "probabilities": {"0": 0, "1": 0, "2": 0.3, "3": 0.7}}) for c in cases
    ]
    assert summarize(rows, 0.5)["groups"][0]["mae"] == pytest.approx(1.5666666667)
    rows[-1]["status"] = "error"
    rank = summarize(rows, 0.5)["rankings"][0]
    assert not rank["complete"]
    assert "ndcg_at_5" not in rank


def test_dry_run_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    out = tmp_path / "requests.jsonl"
    monkeypatch.setattr("sys.argv", ["jev-eval", "dry-run", "--data", str(DATA), "--out", str(out)])
    main()
    requests = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(requests) == 17
    assert all("gold" not in r and "raw" not in r for r in requests)


def test_run_requires_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["jev-eval", "run", "--data", str(DATA)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
