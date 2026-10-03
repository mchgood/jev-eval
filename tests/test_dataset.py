"""Check authored coverage, label integrity and reproducibility without model calls."""

import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path

from jev_eval.backend import request_for
from jev_eval.schema import load_cases

ROOT = Path(__file__).parents[1]


def test_each_domain_and_primitive_has_100_cases():
    cases = load_cases(ROOT / "data/evaluation.xlsx")
    counts = Counter((c.domain, c.question["type"]) for c in cases)
    assert len(cases) == 600
    assert counts == {
        (d, k): 100 for d in ("music", "navigation") for k in ("choice", "noul", "score")
    }
    assert all(c.split == "dev" for c in cases)
    inputs = [json.dumps(request_for(c), sort_keys=True, ensure_ascii=False) for c in cases]
    assert len(inputs) == len(set(inputs))


def test_ranking_groups_are_complete_and_permuted():
    groups = defaultdict(list)
    for c in load_cases(ROOT / "data/evaluation.xlsx"):
        if c.ranking_group:
            groups[(c.domain, c.ranking_group)].append(c)
    assert len(groups) == 50
    assert all(len(group) == 4 for group in groups.values())
    assert all(len({c.state["query"] for c in group}) == 1 for group in groups.values())
    assert all(
        len({json.dumps(c.state["history"]) for c in group}) == 1 for group in groups.values()
    )
    assert sum(all(c.gold == 0 for c in group) for group in groups.values()) == 10
    normal = [group for group in groups.values() if any(c.gold for c in group)]
    assert all(sorted(c.gold for c in group) == [0, 1, 2, 3] for group in normal)
    assert {next(i for i, c in enumerate(group) if c.gold == 3) for group in normal} == {0, 1, 2, 3}


def test_unknown_labels_and_binary_balance():
    for domain in ("music", "navigation"):
        cases = [
            c
            for c in load_cases(ROOT / "data/evaluation.xlsx")
            if c.domain == domain and c.question["type"] == "noul"
        ]
        counts = Counter(c.gold for c in cases)
        assert counts[True] >= 25 and counts[False] >= 25 and counts[None] >= 10


def test_expansion_reproduces_committed_samples():
    spec = importlib.util.spec_from_file_location(
        "dataset_builder", ROOT / "scripts/build_dataset.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.choices()
    module.nouls()
    module.scores()
    generated = {r["id"]: r for r in module.ROWS}
    committed = {
        r["id"]: r
        for path in (ROOT / "data/expanded").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if (r := json.loads(line))
    }
    assert generated == committed
