# 扩充数据集 v1

| 领域 | Choice | Noul | Score | 总计 |
|---|---:|---:|---:|---:|
| 音乐 | 100 | 100 | 100 | 300 |
| 导航 | 100 | 100 | 100 | 300 |
| 总计 | 200 | 200 | 200 | 600 |

目录中的 6 个 JSONL 文件可整体加载，也可单独指定文件。原来的 smoke 保留。

## 来源与边界

人工定义场景、条件和标签，脚本确定性扩展实体变体。不是采集的真实用户请求，
不是 600 个独立场景，也尚未经过业务人员独立双人复核。每个领域 Choice 20 个场景族、
Noul 20 个场景族、Score 5 个场景族。每条 tags 标明 family，rationale 解释标注依据。
实体复用，场景模板复用；统一标记 dev，不能用同一批数据调参后宣称冻结测试成绩。
未来增加独立数据来源，再按实体和模板族切分校准/测试集。

## 覆盖

- Choice：资源类型、动作、搜索与执行区分、否定、明确改口、歧义、多轮续搜/重搜/选择、指令形文本。
- Noul：硬/软条件、歌手/语言/版本、区域/类别/停车/营业状态、动作、选择与无结果。
- Score：目标和硬条件冲突、关键证据缺失、硬条件满足但软偏好不满足、全部满足、多轮继承、无匹配结果。
- 导航的营业状态使用 mock 预计算布尔字段，不让模型比较日期或营业时间。
- 场景音乐使用显式 scene_tags，不依赖模型猜测歌曲风格。

每个领域 Score 25 组 × 4 候选 = 100 次评分，其中 5 组全部为 0。
普通组覆盖 0/1/2/3 全部等级，候选次序按组轮换；不是完整的随机置换稳定性实验。
全无关组 NDCG 为 null，不能因此认为拒绝推荐能力已验证。

未知 Noul 标签：音乐 10 条，导航 15 条；不进入二分类和校准指标，单独保留概率用于观察。
判别标签和理由不传给 Jev。品牌和 POI 设施均为模拟记录，不代表真实门店信息。

## 使用

```bash
uv run jev-eval validate --data data/expanded
uv run jev-eval dry-run --data data/expanded --out results/expanded-requests.jsonl
uv run jev-eval run --data data/expanded --domain music --primitive choice
uv run python scripts/build_dataset.py
```

600 行对应 600 次顺序 Jev 请求，不包含搜索接口调用。
