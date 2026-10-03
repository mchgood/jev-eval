"""Validate datasets; gold labels are never sent to Jev."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from typesafe_sdk import Choice, Noul, Score


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    domain: Literal["music", "navigation"]
    task: str
    split: Literal["dev", "calibration", "test"] = "dev"
    state: dict[str, Any]
    question: dict[str, Any]
    gold: str | bool | int | None
    rationale: str
    tags: list[str] = []
    ranking_group: str | None = None
    candidate_id: str | None = None

    @model_validator(mode="after")
    def validate_question(self):
        kind = self.question.get("type")
        cls = {"choice": Choice, "noul": Noul, "score": Score}
        if kind not in cls:
            raise ValueError("Invalid primitive")
        cls[kind].model_validate(self.question)
        criteria = self.question.get("criteria")
        if kind == "choice" and (not isinstance(self.gold, str) or self.gold not in criteria):
            raise ValueError("Choice gold must be an available option")
        if kind == "noul" and self.gold is not None and type(self.gold) is not bool:
            raise ValueError("Noul gold must be boolean or null (unknown)")
        if kind == "score" and (type(self.gold) is not int or not 0 <= self.gold < len(criteria)):
            raise ValueError("Score gold must be an integer rubric level")
        if bool(self.ranking_group) != bool(self.candidate_id):
            raise ValueError("ranking_group and candidate_id must occur together")
        if self.ranking_group and kind != "score":
            raise ValueError("Ranking groups currently require Score")
        return self


def load_cases(path: Path) -> list[Case]:
    cases = []
    paths = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    for source in paths:
        cases.extend(_load_file(source))
    return _validate_dataset(cases)


def _load_file(path: Path) -> list[Case]:
    cases = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                cases.append(Case.model_validate(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return cases


def _validate_dataset(cases: list[Case]) -> list[Case]:
    ids = [c.id for c in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("Empty dataset or duplicate case IDs")
    groups = {}
    for c in cases:
        if c.ranking_group:
            group = groups.setdefault((c.domain, c.ranking_group), [])
            if any(x.candidate_id == c.candidate_id for x in group):
                raise ValueError("Duplicate ranking candidate")
            if group and (c.split != group[0].split or c.question != group[0].question):
                raise ValueError("Ranking group must share split and rubric")
            group.append(c)
    return cases
