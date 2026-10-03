# Jev Eval

用 Python 评测 Jev 在中文音乐搜索、导航搜索中的 Choice、Noul、Score 能力。
**音乐/导航搜索不联网，使用固定 mock 数据；模型推理真实调用 Jev。**

## 快速开始

需要 Python 3.11+ 和 uv。默认使用清华 PyPI 镜像，依赖已锁定。

```bash
uv sync --locked
uv run jev-eval validate
uv run jev-eval dry-run --out results/requests.jsonl
uv run pytest
```

`validate`、`dry-run`、`report` 都不调用 Jev。dry-run 只生成请求，不生成假预测或能力分数。

真实评测：

```bash
export TYPESAFE_API_KEY='你的 Key'
uv run jev-eval run --model jev-1.13.0 --out results/run-001
# 单独运行某个领域、能力或数据划分
uv run jev-eval run --domain music --primitive score --split dev
# 不再次请求模型，调整 Noul 阈值重算指标
uv run jev-eval report --results results/run-001/results.jsonl --out results/recomputed --threshold 0.7
```

`.env.example` 仅为变量说明，程序不会自动加载 `.env`。不要将 Key 提交到 Git。
`--out` 运行目录必须不存在，以防覆盖原始结果。模型名称可通过 `--model` 或 `JEV_MODEL` 指定。
若当前账户不能访问默认版本，请指定账户实际可用的版本；正式比较应固定具体版本。

切换依赖镜像：修改 `pyproject.toml` 中 `tool.uv.index.url`，然后执行 `uv lock` 和 `uv sync --locked`。
国内镜像只加速 Python 依赖下载，不代理 Jev 服务。

## 当前实现

- JSONL 数据校验，按领域 / 任务 / 能力 / split 筛选。
- 官方 `typesafe-sdk` 适配器；请求中仅含 state 和 question，不传 gold / rationale。
- Choice：准确率、Macro-F1（包含配置中的未出现类别）。
- Noul：Precision、Recall、Brier、10 等宽区间 ECE；未知标签不进入二分类指标。
- Score：期望分数 MAE、最大概率等级的二次加权 Kappa。
- 分组排序：NDCG@5；不完整候选组不计算排序指标，全无关组标记并返回 null。
- 原始响应、请求、延迟、token 用量、规范化数据 SHA256、模型配置落盘。
- JSON 和 HTML 报告；异常样本保留，全部运行后以非零状态退出。

内置 **17 条人工编写的 smoke 样本**，覆盖两个领域的三种能力，含两个排序候选组和一个证据不足样本。
这些样本仅用于流程验证，全部属于 dev，不能用于宣称模型准确率或线上能力。

## 文件结构

- `src/jev_eval/`：schema、SDK adapter、metrics、CLI。
- `data/smoke.jsonl`：固定搜索候选和人工标签。
- `tests/`：数据校验、指标边界、SDK 请求隔离和 CLI 离线测试。
- `docs/evaluation-plan.md`：正式数据集与后续实验。

报告质量指标仅统计成功返回的样本，失败计数和总数单独展示，评估时必须同时查看。
当前顺序调用、关闭 SDK 自动重试；P50/P95 为每条判断的客户端耗时，不是整个 Agent 的耗时。
目前不调用其他 LLM，不输出虚构的基线成绩或价格估算。

## 官方参考

- [Python SDK](https://docs.typesafe.ai/sdk/python)
- [重排案例](https://docs.typesafe.ai/cookbooks/rerank_typesafe)
- [Function Calling](https://docs.typesafe.ai/cookbooks/function_calling)
- [模型已知弱点](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

## GitHub Actions 真实评测

1. 在仓库 **Settings → Secrets and variables → Actions → New repository secret** 中设置
   `TYPESAFE_API_KEY`，值为 Jev API Key。不要使用普通变量或工作流输入存放密钥。
2. 进入 **Actions → Jev evaluation → Run workflow**，选择 `main`。
3. 选择数据集、模型、领域、能力和 Noul 阈值；默认运行 expanded 的 600 条样本，也可选择 17 条 smoke。
4. 运行结束后在 Summary 查看成功/失败计数，在 Artifacts 下载 JSON、HTML 和原始响应。

工作流仅手动触发，不在普通 push 或 PR 中调用收费模型。缺少 Secret 时明确失败。
模型参数经环境变量和带引号的参数传递，API Key 仅注入推理步骤。失败时仍上传已有结果，
报告保留 14 天。已有 Offline checks 工作流继续执行不需要 Key 的 CI。


## 扩充样本：每个领域每种能力 100 条

`data/expanded/` 包含音乐和导航的六个 JSONL 文件，共 600 条；每个领域各 100 条
Choice、Noul、Score。CLI 的 `--data` 同时支持文件和目录，目录内 JSONL 按路径顺序加载。

```bash
uv run jev-eval validate --data data/expanded
uv run jev-eval run --data data/expanded
uv run jev-eval run --data data/expanded --domain navigation --primitive score
```

每个领域 25 个四候选排序组，包含 5 个全无关组。合成数据来源、标注规则和未知标签
详见 [数据集说明](data/expanded/README.md)。当前全部为 dev，不作为独立冻结测试集。
GitHub Actions 默认使用 expanded，可切换 smoke；运行超时上限为 60 分钟。


默认固定模型版本为 `jev-1.13.0`。`jev-1.13` 是文档中的系列简称，API 不接受这个 ID。
如果旧的手动运行参数仍为 `jev-1.13`，请在 Run workflow 中改成 `jev-1.13.0`。
服务错误记录 HTTP 状态和脱敏消息，方便区分模型名错误、认证失败及限流。
