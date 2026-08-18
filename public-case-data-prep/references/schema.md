# 字段规范

本文件规定公开案例数据整理前六步使用的 JSONL 文件结构。JSONL 表示每行一个完整 JSON 对象。所有 `data/...` 路径都相对于当前案例项目的项目根目录，不是相对于 skill 目录。

前六步是数据准备和自检阶段，不写 `review_status`。人工审批状态属于后续 Markdown 审批稿和结构化 JSON 阶段。

## source_registry.jsonl

路径：`data/sources/source_registry.jsonl`

字段：

```json
{
  "source_id": "SRC0001",
  "url": "https://example.com/source"
}
```

规则：

- `source_id` 使用 `SRC` 加四位数字。
- 一个唯一 URL 只登记一次。
- 不写标题、摘要、来源等级、核验结论、答案或案例编号。

## source_validation.jsonl

路径：`data/sources/source_validation.jsonl`

字段：

```json
{
  "source_id": "SRC0001",
  "validation_status": "usable",
  "source_type": "specific_case",
  "intended_use": "public_case_rewrite_candidate",
  "validation_reason": "来源支持的核验理由。"
}
```

枚举值：

- `validation_status`：`usable`、`disputed`、`rejected`
- `source_type`：`specific_case`、`typical_mechanism`、`risk_warning`、`null`
- `intended_use`：`public_case_rewrite_candidate`、`controlled_synthetic_reference`、`rule_reference_only`、`null`

说明：

- `validation_status` 是来源可用性结论，不是人工审批状态。
- `usable` 表示来源可进入后续真实案件拆分。
- `disputed` 表示来源存在争议或需要交叉核验，默认不进入第 5 步，除非用户另行授权。
- `rejected` 表示来源退回，不进入第 5 步。

## real_case_registry.jsonl

路径：`data/sources/real_case_registry.jsonl`

字段：

```json
{
  "real_case_id": "RC0001",
  "source_id": "SRC0001",
  "source_locator": "原文中可定位案件事实的位置，例如小标题、段落、页码或案号。",
  "fact_summary": "忠于原文的事实摘要。"
}
```

规则：

- `real_case_id` 使用 `RC` 加四位数字。
- `source_locator` 必须能定位到原文标题、段落、案号、页码或序号。
- `fact_summary` 只能概括来源明确支持的事实。
- 不写训练题面、标签、证据、`case_id` 或审批状态。

## real_case_fact_split.jsonl

路径：`data/sources/real_case_fact_split.jsonl`

字段：

```json
{
  "real_case_id": "RC0001",
  "source_id": "SRC0001",
  "pre_event_visible_facts": [],
  "post_event_confirmed_facts": [],
  "not_provided_facts": []
}
```

字段含义：

- `pre_event_visible_facts`：接触方式、宣传话术、承诺、推荐内容、平台/APP/链接、充值或转账请求、用户操作前可见的收益截图、群聊话术等。
- `post_event_confirmed_facts`：后台控制、身份造假、资金流向、最终损失、无法提现后的结果、警方抓捕、起诉、判决、监管结论等。
- `not_provided_facts`：原文没有写明的账户、设备、IP、完整聊天记录、资金流水、截图、后台操作过程等。

规则：

- 不要把警方认定、法院判决、诈骗团伙控制、最终被骗、事后无法提现等事后结论写入 `pre_event_visible_facts`。
- 不要把原文没有提供的信息写成已知事实。
- 不写 `review_status`。

## 校验建议

检查 JSONL 是否可解析：

```powershell
Get-Content data\sources\real_case_registry.jsonl | ForEach-Object { $_ | ConvertFrom-Json } | Measure-Object
```

检查编号是否连续：

```powershell
$expected = 1..27 | ForEach-Object { 'RC{0:D4}' -f $_ }
$actual = Get-Content data\sources\real_case_registry.jsonl | ForEach-Object { ($_ | ConvertFrom-Json).real_case_id }
Compare-Object $expected $actual
```

实际使用时，把 `27` 改成当前真实案件数量。
