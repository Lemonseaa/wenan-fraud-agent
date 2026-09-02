# V1 Dataset Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已提交的350条V1任务按来源关联组无泄漏地划分为开发集、验证集和封存测试集，并生成可复现的清单与统计报告。

**Architecture:** 保持 `data/review/public_cases/structured/*.json` 不变。一个纯Python脚本读取全部已审批任务，将相同 `source_id` 或相同 `real_case_id` 相连的任务合并为不可拆分组，使用固定随机种子搜索接近60/20/20且标签均衡的划分，再写出逐任务清单和汇总报告。

**Tech Stack:** Python 3标准库、`unittest`、JSON/JSONL。

**Spec:** `README.md` 的“7.6 数据隔离”和 `公开案例数据加工 SOP .md` 第11步关于按 `real_case_id` 整组划分的约束。

## Global Constraints

- 输入只包含 `review_status=approved` 的结构化任务。
- 同一 `source_id` 或同一 `real_case_id` 关联的所有任务必须属于同一集合。
- 划分比例固定为 development 60%、validation 20%、test 20%，允许因整组分配产生小幅偏差。
- 每个集合的每类 `label` 与目标数量相差不超过8条。
- 分布在至少3个来源关联组中的 `fraud_type` 必须覆盖三个集合；不足3组的类型只报告实际分布。
- 随机种子固定为 `20260901`，相同输入必须产生完全相同输出。
- 不向现有十字段JSON增加 `split` 字段。
- 封存测试集只生成清单，本任务不运行模型、不读取答案做Skill优化。
- 不增加第三方依赖。
- Agent不执行Git提交、推送、分支或暂存操作；每个任务结束后交由项目负责人检查。

---

### Task 1: 数据加载与确定性校验

**Files:**
- Create: `scripts/split_v1_dataset.py`
- Create: `tests/test_split_v1_dataset.py`

**Interfaces:**
- Produces: `load_cases(input_dir: Path) -> list[dict]`
- Produces: `group_cases(cases: list[dict]) -> dict[str, list[dict]]`

- [ ] **Step 1: 编写失败测试**

测试必须覆盖：只读取JSON、拒绝未审批任务、拒绝重复 `case_id`、拒绝缺失 `real_case_id` 或 `source_id`，并确认相同来源和案例家族不会被拆分。

```python
def test_group_cases_keeps_family_together(self):
    cases = [
        {"case_id": "C0001-F01", "real_case_id": "RC0001", "label": "fraud", "review_status": "approved"},
        {"case_id": "C0001-N01", "real_case_id": "RC0001", "label": "normal", "review_status": "approved"},
    ]
    groups = group_cases(cases)
    self.assertEqual([x["case_id"] for x in groups["RC0001"]], ["C0001-F01", "C0001-N01"])
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: FAIL，因为 `scripts.split_v1_dataset` 尚不存在。

- [ ] **Step 3: 实现最小加载与分组逻辑**

实现要求：文件按名称排序读取；JSON解析错误带文件路径；只接受 `fraud`、`normal`、`insufficient`；发现未审批任务立即失败，不静默跳过。

- [ ] **Step 4: 运行测试并确认通过**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: Task 1相关测试全部PASS。

- [ ] **Step 5: 用户检查点**

项目负责人检查函数输入输出、错误信息和“未审批即失败”的边界；不执行Git操作。

---

### Task 2: 按来源关联组进行均衡划分

**Files:**
- Modify: `scripts/split_v1_dataset.py`
- Modify: `tests/test_split_v1_dataset.py`

**Interfaces:**
- Consumes: `group_cases(cases)`
- Produces: `split_groups(groups: dict[str, list[dict]], seed: int = 20260901) -> dict[str, str]`
- 返回值映射 `group_id -> development | validation | test`

- [ ] **Step 1: 编写失败测试**

测试必须证明：每个来源关联组只出现一次、所有组都有分配、同样输入和种子得到相同结果、三个集合都非空、标签数量接近目标。

```python
def test_split_groups_is_deterministic(self):
    first = split_groups(self.groups, seed=20260901)
    second = split_groups(self.groups, seed=20260901)
    self.assertEqual(first, second)
    self.assertEqual(set(first), set(self.groups))
```

- [ ] **Step 2: 运行新增测试并确认失败**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: FAIL，因为 `split_groups` 尚不存在。

- [ ] **Step 3: 实现确定性搜索**

使用标准库 `random.Random(seed)` 生成固定候选顺序。对若干候选划分计算目标函数：三个集合的总任务数偏差、各标签数量偏差和诈骗类型覆盖偏差；选择分数最低的方案。禁止拆分来源关联组。

- [ ] **Step 4: 运行测试并确认通过**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: 所有测试PASS。

- [ ] **Step 5: 用户检查点**

项目负责人确认比例只是目标，来源和案例家族隔离优先于精确条数；不执行Git操作。

---

### Task 3: 生成划分清单和报告

**Files:**
- Modify: `scripts/split_v1_dataset.py`
- Modify: `tests/test_split_v1_dataset.py`
- Create: `data/splits/v1_split.jsonl`
- Create: `data/splits/v1_split_report.json`

**Interfaces:**
- Produces: `build_manifest(cases: list[dict], assignment: dict[str, str]) -> list[dict]`
- 每行固定为 `case_id`、`real_case_id`、`split` 三个字段。
- Produces: `build_report(cases: list[dict], manifest: list[dict]) -> dict`
- 报告包含数据版本、固定种子、总数、各集合任务数、来源关联组数、案例家族数、标签与诈骗类型分布，以及两类泄漏检查结果。

- [ ] **Step 1: 编写失败测试**

测试清单字段、排序、无重复、完整覆盖以及报告中的 `source_leakage_count == 0` 和 `family_leakage_count == 0`。

```python
def test_manifest_has_fixed_fields(self):
    rows = build_manifest(self.cases, self.assignment)
    self.assertTrue(all(set(row) == {"case_id", "real_case_id", "split"} for row in rows))
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: FAIL，因为清单和报告函数尚不存在。

- [ ] **Step 3: 实现CLI和原子写入**

CLI固定支持：

```text
python3 scripts/split_v1_dataset.py \
  --input data/review/public_cases/structured \
  --manifest data/splits/v1_split.jsonl \
  --report data/splits/v1_split_report.json \
  --seed 20260901
```

先写同目录临时文件，成功后再替换目标，避免中断留下半份清单。

- [ ] **Step 4: 运行单元测试**

Run: `python3 -m unittest tests.test_split_v1_dataset -v`

Expected: 所有测试PASS。

- [ ] **Step 5: 生成真实V1划分**

Run: `python3 scripts/split_v1_dataset.py --input data/review/public_cases/structured --manifest data/splits/v1_split.jsonl --report data/splits/v1_split_report.json --seed 20260901`

Expected: 输出350条清单，报告显示0个来源泄漏和0个案例家族泄漏。

- [ ] **Step 6: 用户检查点**

项目负责人检查三个集合的条数、标签比例和报告；不执行Git操作。

---

### Task 4: 集成校验与团队说明

**Files:**
- Modify: `tests/test_split_v1_dataset.py`
- Modify: `README.md`

**Interfaces:**
- 集成测试读取仓库真实数据和生成清单，验证350条完整覆盖、无重复、无家族泄漏、所有任务仍为 `approved`。

- [ ] **Step 1: 增加真实数据集集成测试**

测试不能修改数据，只读取 `structured/` 和 `v1_split.jsonl`，并分别验证 `source_id` 与 `real_case_id` 不跨集合。

- [ ] **Step 2: 运行完整测试**

Run: `python3 -m unittest discover -s tests -v`

Expected: 所有测试PASS，0 failures，0 errors。

- [ ] **Step 3: 检查Python语法**

Run: `python3 -m compileall -q scripts tests`

Expected: exit code 0。

- [ ] **Step 4: 更新README导航**

在仓库导航中增加 `data/splits/v1_split.jsonl`，说明它只记录集合归属，不复制或修改权威任务数据。

- [ ] **Step 5: 检查文档和工作区**

Run: `git diff --check`

Expected: exit code 0。项目负责人随后自行检查、提交和推送。
