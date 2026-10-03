"""Portable Markdown and HTML reports from saved evaluation results."""

import html
import json
from pathlib import Path


def number(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def percent(value):
    return "—" if value is None else f"{value:.2%}"


def cell(value):
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", "<br>")


def table(headers, rows):
    return (
        "| " + " | ".join(headers) + " |\n"
        + "| " + " | ".join(["---"] * len(headers)) + " |\n"
        + "".join("| " + " | ".join(cell(v) for v in row) + " |\n" for row in rows)
        + "\n"
    )


def report_markdown(summary):
    overview = summary["overview"]
    run = summary["run"]
    timing = overview["latency_ms"] or {}
    elapsed = run.get("elapsed_seconds")
    text = "# Jev 评测报告\n\n"
    text += table(["指标", "结果"], [
        ["已评测 / 计划样本", f"{overview['total']} / {len(run.get('cases', [])) or '未知'}"],
        ["判断通过率", percent(overview["pass_rate"])],
        ["通过 / 未通过 / 未知标签", f"{overview['passed']} / {overview['not_passed']} / {overview['excluded_unknown']}"],
        ["接口成功率", percent(overview["request_success_rate"])],
        ["接口成功 / 报错", f"{overview['success']} / {overview['failed']}"],
        ["评测循环总耗时（秒）", number(elapsed)],
        ["累计请求耗时（秒）", number(timing.get("total", 0) / 1000)],
        ["平均 / P50 / P95 请求耗时（毫秒）",
         " / ".join(number(timing.get(k)) for k in ("mean", "p50", "p95"))],
        ["吞吐量（样本/秒）", number(overview["total"] / elapsed if elapsed else None)],
        ["模型", run.get("model", "未知")],
        ["开始 / 结束（UTC）", f"{run.get('started_at', '未知')} / {run.get('ended_at', '未知')}"],
        ["数据集", run.get("dataset_path", "未知")],
        ["数据 SHA256", run.get("dataset_sha256", "未知")],
    ])
    text += (
        "判断通过规则：Choice 标签一致；Noul 概率 ≥ " + str(summary["threshold"])
        + " 判为真；Score 取最高概率等级，与 gold 严格一致（概率并列取响应中的首项）。"
        "有标签的接口报错计入未通过；未知标签排除。总通过率按样本加权，受样本构成影响。\n\n"
        "耗时统计包含成功和失败请求，由客户端测量，涵盖网络与服务耗时。"
        "评测循环总耗时包含调用、写入和客户端关闭，不包含依赖安装和报告渲染；"
        "旧结果没有记录总耗时则显示 —，累计请求耗时不能替代总耗时。\n\n"
        "搜索数据为 mock，推理调用真实 Jev。当前合成 dev 数据用于开发验证，"
        "不能代表独立真实用户测试或线上召回效果。\n\n## 分项结果\n\n"
    )
    text += table(
        ["领域", "能力", "总数", "接口报错", "通过/有标签", "通过率", "平均 ms", "P95 ms"],
        [[g["domain"], g["primitive"], g["total"], g["failed"],
          f"{g['passed']}/{g['labeled']}", percent(g["pass_rate"]),
          *[number((g["latency_ms"] or {}).get(k)) for k in ("mean", "p95")]]
         for g in summary["capabilities"]],
    )
    text += "## 任务明细\n\n"
    text += table(
        ["领域", "任务", "能力", "总数", "接口报错", "通过/有标签", "通过率", "平均 ms", "P50 ms", "P95 ms"],
        [[g["domain"], g["task"], g["primitive"], g["total"], g["failed"],
          f"{g['passed']}/{g['labeled']}", percent(g["pass_rate"]),
          *[number((g["latency_ms"] or {}).get(k)) for k in ("mean", "p50", "p95")]]
         for g in summary["groups"]],
    )
    text += "## 能力指标\n\n以下质量指标基于成功返回样本；Noul 再排除未知标签。\n\n"
    text += table(["领域", "任务", "指标"], [
        [g["domain"], g["task"], "; ".join(
            f"{k}={number(g[k], 4)}" for k in
            ("accuracy", "macro_f1", "precision", "recall", "brier", "ece_10_bins", "mae", "quadratic_kappa")
            if k in g)] for g in summary["groups"]
    ])
    text += "## 候选排序\n\n不完整组不计算 NDCG；全无关组没有有效 IDCG，单独统计。\n\n"
    rank_rows = []
    for domain in sorted({r["domain"] for r in summary["rankings"]}):
        groups = [r for r in summary["rankings"] if r["domain"] == domain]
        values = [r["ndcg_at_5"] for r in groups if r.get("ndcg_at_5") is not None]
        rank_rows.append([domain, len(groups), sum(r["complete"] for r in groups),
                          sum(r.get("all_irrelevant", False) for r in groups), len(values),
                          number(sum(values) / len(values) if values else None, 4)])
    text += table(["领域", "组数", "完整组", "全无关组", "有效组", "平均 NDCG@5"], rank_rows)
    text += "## 未通过和接口报错案例\n\n"
    text += table(["ID", "能力", "标注", "预测", "状态", "错误 / 标注依据"], [
        [r["id"], r["primitive"], r["gold"], r["predicted"], r["status"],
         r["error"] or r["rationale"]] for r in summary["failures"]
    ]) if summary["failures"] else "无。\n"
    return text


def markdown_html(markdown):
    """Render only the small, escaped Markdown subset emitted above."""
    parts = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("| "):
            if line.startswith("| ---"):
                continue
            tag = "td" if in_table else "th"
            if not in_table:
                parts.append('<div class="table"><table>')
                in_table = True
            cells = line[2:-2].split(" | ")
            parts.append("<tr>" + "".join(f"<{tag}>{v}</{tag}>" for v in cells) + "</tr>")
        else:
            if in_table:
                parts.append("</table></div>")
                in_table = False
            if line.startswith("# "):
                parts.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                parts.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line:
                parts.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        parts.append("</table></div>")
    return "\n".join(parts)


def write_reports(out: Path, summary: dict):
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("summary.json", summary), ("failures.json", summary["failures"])):
        (out / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    markdown = report_markdown(summary)
    (out / "report.md").write_text(markdown, encoding="utf-8")
    (out / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Jev 评测报告</title><style>'
        'body{font:15px/1.6 system-ui,sans-serif;color:#17283b;background:#f6f8fb;'
        'margin:0;padding:32px}main{max-width:1200px;margin:auto;background:white;padding:32px;'
        'border-radius:16px}h1{color:#1652a3}h2{margin-top:36px}p{color:#526174}'
        '.table{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:16px 0}'
        'th,td{text-align:left;border-bottom:1px solid #dce3eb;padding:10px;overflow-wrap:anywhere}'
        'th{background:#eaf1fb}tr:nth-child(even){background:#f8fafc}'
        '@media(max-width:600px){body{padding:8px}main{padding:16px}}'
        '</style></head><body><main>' + markdown_html(markdown) + '</main></body></html>',
        encoding="utf-8",
    )
