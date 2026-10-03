# Excel 评测用例维护

正式维护入口为 `data/evaluation.xlsx`，当前有 600 条开发用例。快速检查使用
`data/smoke.xlsx`，当前有 17 条。两者是不同规模的数据集，不需要同时加载。

## 编辑方式

- **用例**：一行一条。编辑用户请求、判断问题、预期结果和标注依据；用例 ID 必须唯一。
- **输入字段**：按用例 ID 维护上下文、歌曲和 POI 候选，每行一个字段，不使用 JSON 单元格。
- **判断标准**：Choice 一行一个选项；Score 一行一个等级；Noul 可以在判断问题中完整描述，或配置 true、false 两条标准。
- **说明**：字段类型、维护规则与来源说明。

领域使用 `music`、`navigation`；能力使用 `choice`、`noul`、`score`；划分使用
`dev`、`calibration`、`test`。这三列有下拉选择，表头冻结且表格支持筛选。
机器读取工作表名称和中文列名，不要修改它们。可以增加数据行和用例，但不要填写公式。

预期结果：Choice 填已定义选项名；Noul 填“真”“假”“未知”；Score 填整数等级。
Score 等级从 0 连续编号。排序组与候选 ID 同时填写，组内必须使用相同划分与评分标准。
标签用英文分号分隔。

## 输入字段

字段路径如 `/candidate/title`、`/history/0/text`。父对象和数组也有一行：

| 字段路径 | 类型 | 值 |
| --- | --- | --- |
| /candidate | object | 留空 |
| /candidate/title | text | 晴天 |
| /candidate/live | boolean | 假 |
| /history | array | 留空 |

`text` 是文本，`boolean` 是真或假，`integer` 是整数，`number` 是数值。
`null`、`object`、`array` 的值必须留空。数组下标从 0 连续编号，不要删除父容器行。
对象字段名包含 `/` 时写 `~1`，包含 `~` 时写 `~0`。用户请求只在用例表维护，
不能在输入字段中重复定义 `/query`。同一用例的字段路径不得重复。

## 校验和运行

```bash
uv sync --locked
uv run jev-eval validate --data data/evaluation.xlsx
uv run jev-eval dry-run --data data/evaluation.xlsx --out results/requests.jsonl
uv run jev-eval run --data data/evaluation.xlsx --out results/run-excel
```

`validate` 与 `dry-run` 不调用模型。`run` 仍只真实调用 Jev，搜索数据使用 mock。
密钥仍保存在环境变量或 Actions Secret，不要放进 Excel。

Actions 的 expanded / smoke 输入分别读取对应 Excel。历史 JSONL 仅保留作迁移参照，
不会与 Excel 自动双向同步；修改 Excel 后不需要同步 JSONL。结果 JSON、JSONL 继续用于
报告重算和机器分析，此次调整只改变测试用例配置入口。
