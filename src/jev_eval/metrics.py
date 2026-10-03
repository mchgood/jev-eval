"""Group metrics by domain, task and primitive. Report failures explicitly."""

import math
from collections import defaultdict

import numpy as np
from sklearn.metrics import cohen_kappa_score, f1_score, precision_score, recall_score


def answer_from(raw: dict, kind: str) -> dict:
    if "answers" in raw:
        return raw["answers"]["decision"]
    return raw[{"choice": "choices", "noul": "nouls", "score": "scores"}[kind]]["decision"]


def ndcg(golds, predictions, k=5):
    order = sorted(range(len(golds)), key=lambda i: (-predictions[i], i))[:k]
    ideal = sorted(golds, reverse=True)[:k]
    dcg = sum((2 ** golds[i] - 1) / math.log2(rank + 2) for rank, i in enumerate(order))
    idcg = sum((2**g - 1) / math.log2(rank + 2) for rank, g in enumerate(ideal))
    return dcg / idcg if idcg else None


def latency_stats(rows):
    values = [r["latency_ms"] for r in rows]
    if not values:
        return None
    return {
        "total": float(sum(values)), "mean": float(np.mean(values)),
        "min": float(min(values)), "max": float(max(values)),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
    }


def verdict(row, threshold):
    """Unknown labels are excluded; request failures fail any labeled case."""
    gold = row["case"]["gold"]
    if gold is None:
        return None, None
    if row["status"] != "ok":
        return False, None
    kind = row["case"]["question"]["type"]
    answer = answer_from(row["raw"], kind)
    if kind == "choice":
        predicted = answer["choice"]
    elif kind == "noul":
        predicted = answer["noul"] >= threshold
    else:
        predicted = int(max(answer["probabilities"], key=answer["probabilities"].get))
    return predicted == gold, predicted


def pass_stats(rows, threshold):
    outcomes = [verdict(r, threshold)[0] for r in rows]
    labeled = sum(v is not None for v in outcomes)
    passed = sum(v is True for v in outcomes)
    success = sum(r["status"] == "ok" for r in rows)
    return {
        "total": len(rows), "success": success, "failed": len(rows) - success,
        "request_success_rate": success / len(rows) if rows else None,
        "labeled": labeled, "passed": passed, "not_passed": labeled - passed,
        "excluded_unknown": len(rows) - labeled,
        "pass_rate": passed / labeled if labeled else None,
        "latency_ms": latency_stats(rows),
    }


def summarize(rows: list[dict], threshold: float, manifest: dict | None = None) -> dict:
    grouped = defaultdict(list)
    for r in rows:
        c = r["case"]
        grouped[(c["domain"], c["task"], c["question"]["type"])].append(r)
    results = []
    for (domain, task, kind), group in sorted(grouped.items()):
        ok = [r for r in group if r["status"] == "ok"]
        m = {
            "domain": domain,
            "task": task,
            "primitive": kind,
            "total": len(group),
            "success": len(ok),
            "failed": len(group) - len(ok),
        }
        m.update(pass_stats(group, threshold))
        if ok:
            m["input_tokens"] = sum(
                (r["raw"].get("usage") or {}).get("input_tokens") or 0 for r in ok
            )
            answers = [answer_from(r["raw"], kind) for r in ok]
            gold = [r["case"]["gold"] for r in ok]
            if kind == "choice":
                pred = [a["choice"] for a in answers]
                labels = sorted(
                    {label for r in group for label in r["case"]["question"]["criteria"]}
                )
                m["accuracy"] = sum(p == g for p, g in zip(pred, gold)) / len(ok)
                m["macro_f1"] = float(
                    f1_score(gold, pred, labels=labels, average="macro", zero_division=0)
                )
            elif kind == "noul":
                pairs = [(g, a["noul"]) for g, a in zip(gold, answers) if g is not None]
                m["unknown_count"] = sum(g is None for g in gold)
                m["unknown_probabilities"] = [a["noul"] for g, a in zip(gold, answers) if g is None]
                if pairs:
                    y, p = zip(*pairs)
                    pred = [x >= threshold for x in p]
                    m["precision"] = float(precision_score(y, pred, zero_division=0))
                    m["recall"] = float(recall_score(y, pred, zero_division=0))
                    m["brier"] = sum((x - int(g)) ** 2 for g, x in pairs) / len(pairs)
                    m["ece_10_bins"] = sum(
                        len(bucket)
                        / len(pairs)
                        * abs(
                            sum(x for _, x in bucket) / len(bucket)
                            - sum(int(g) for g, _ in bucket) / len(bucket)
                        )
                        for b in range(10)
                        if (bucket := [(g, x) for g, x in pairs if min(int(x * 10), 9) == b])
                    )
            else:
                pred = [a["score"] for a in answers]  # SDK Score is an expected value.
                levels = [int(max(a["probabilities"], key=a["probabilities"].get)) for a in answers]
                m["mae"] = sum(abs(p - g) for p, g in zip(pred, gold)) / len(ok)
                m["quadratic_kappa"] = (
                    float(cohen_kappa_score(gold, levels, weights="quadratic"))
                    if len(set(gold + levels)) > 1
                    else None
                )
        results.append(m)
    rankings = defaultdict(list)
    for r in rows:
        c = r["case"]
        if c["ranking_group"]:
            rankings[(c["domain"], c["ranking_group"])].append(r)
    rank_metrics = []
    for (domain, name), group in sorted(rankings.items()):
        complete = all(r["status"] == "ok" for r in group)
        item = {"domain": domain, "group": name, "complete": complete, "size": len(group)}
        if complete:
            golds = [r["case"]["gold"] for r in group]
            scores = [answer_from(r["raw"], "score")["score"] for r in group]
            item["ndcg_at_5"] = ndcg(golds, scores)
            item["all_irrelevant"] = not any(golds)
        rank_metrics.append(item)
    capabilities = defaultdict(list)
    for r in rows:
        capabilities[(r["case"]["domain"], r["case"]["question"]["type"])].append(r)
    capability_metrics = [
        {"domain": domain, "primitive": kind, **pass_stats(group, threshold)}
        for (domain, kind), group in sorted(capabilities.items())
    ]
    failures = []
    for r in rows:
        passed, predicted = verdict(r, threshold)
        if passed is False or r["status"] != "ok":
            c = r["case"]
            failures.append({
                "id": c["id"], "domain": c["domain"], "primitive": c["question"]["type"],
                "gold": c["gold"], "predicted": predicted, "status": r["status"],
                "error": r.get("error_message", r.get("error_type", "")),
                "latency_ms": r["latency_ms"], "rationale": c.get("rationale", ""),
            })
    return {
        "threshold": threshold, "overview": pass_stats(rows, threshold),
        "run": manifest or {}, "groups": results, "capabilities": capability_metrics,
        "rankings": rank_metrics,
        "failures": failures,
    }
