# P0 级 PDF 抽取升级操作手册

本文档说明如何在 **不改架构、不引入 pymupdf 布局抽表** 的前提下，完成阶段一（P0）的五项更新。  
每项包含：目标、改哪些文件、具体步骤、自测命令、验收标准。

---

## 0. 开始之前

### 0.1 环境

```powershell
cd "c:\Users\Administrator\Desktop\课程方案\dev1"
conda activate course
$env:PYTHONPATH = "src;."
```

### 0.2 建立基线（必做）

在改代码前先跑一遍，保存对比基准：

```powershell
# 清空库并跑 200 份 PDF（约 6 分钟）
python tests/integration/run_missing_analysis.py

# 融合层统计
```

记录以下数字，写在 PR 描述里：

| 指标 | 基线（200 份） |
|------|----------------|
| 总告警 | 2903 |
| success / partial | 0 / 200 |
| missing_field（思政元素） | 465 |
| continued_table_without_header | 447 |
| validated_text_fallback_used | 677 |
| khfsb.tm 平均行数 | 0.53 |
| jxap 有行但缺 szyqjxx 的 PDF | 75 |

### 0.3 推荐 PR 顺序

```
PR-1  P0-1  思政列映射 + payload 回填
PR-2  P0-2  续表逻辑
PR-3  P0-3  融合加权评分
PR-4  P0-4  质检 / status 分层
PR-5  P0-5  考核表增强
```

**每合并一个 PR 就重跑 0.2 的命令**，不要五个一起做再测。

### 0.4 涉及文件一览

| 文件 | P0 任务 |
|------|---------|
| `config.py` | P0-3、P0-4 配置 |
| `src/syllabus_auditor/core/extractors/section_table_parser.py` | P0-1、P0-2、P0-5 |
| `src/syllabus_auditor/core/payload_builder.py` | P0-1、P0-5 |
| `src/syllabus_auditor/core/extractors/enhancer.py` | P0-3 |
| `src/syllabus_auditor/core/extractors/fusion.py` | P0-3 |
| `src/syllabus_auditor/core/extractors/text_candidates.py` | P0-5 |
| `src/syllabus_auditor/core/quality.py` | P0-4 |
| `src/syllabus_auditor/core/status.py` | P0-4 |

---

## P0-1：教学安排「思政元素」列映射

**目标**：把 `missing_field`（思政元素的融入和预期教学成效）从 465 降到约 80 以下。  
**根因**：表头别名不全；未识别列丢弃；`kzzd` 扩展字段未提升到 `szyqjxx`。

### 步骤 1：扩展表头别名

**文件**：`src/syllabus_auditor/core/extractors/section_table_parser.py`  
**位置**：`PROFILES` 中 `name="教学安排"` 的 `fields["思政元素的融入和预期教学成效"]`

在现有别名元组末尾追加（保留原有项）：

```python
"思政元素的融入和预期教学成效": (
    # ... 原有别名 ...
    "思政元素的融入及预期教学成效",
    "思政元素融入和预期教学成效",
    "融入的思政元素和预期教学成效",
    "课程思政元素的融入",
    "思政元素融入",
),
```

**不要**加入过于泛化的词（如「价值引领」「育人成效」），以免误映射到其他列。

### 步骤 2：增强 `_field_for_header`

**文件**：同上，函数 `_field_for_header`（约第 152 行）

在常规 alias 匹配之前，增加思政专项匹配（**仅**用思政相关词）：

```python
header_flat = re.sub(r"\s+", "", header or "")
if profile.name == "教学安排" and any(
    token in header_flat
    for token in ("思政", "预期教学成效", "课程思政", "思政元素", "思政融入")
):
    return "思政元素的融入和预期教学成效"
```

### 步骤 3：payload 层回填 szyqjxx

**文件**：`src/syllabus_auditor/core/payload_builder.py`

在 `_map_row` 之后新增 `_promote_schedule_sz_cn`，在映射前从未识别列 `kzzd` 或「授课内容」中提取思政字段：

```python
_SZ_KZZD_KEYS = ("思政", "预期教学成效", "课程思政", "思政元素", "思政融入")
```

修改 `build_payload` 中 schedule 构建段：

```python
schedule_items = [
    _map_row(_promote_schedule_sz_cn(dict(row)), SCHEDULE_ITEM_MAP)
    for row in raw.course_schedule
]
```

### 步骤 4：自测

```powershell
# 单 PDF 调试（把路径换成 data_pdf 下任意一份缺思政的 PDF）
conda run -n course python -c "
import sys; sys.path[:0]=['src','.']
from pathlib import Path
from syllabus_auditor.core.extractors.pdfplumber import PdfPlumberExtractor
from syllabus_auditor.core.payload_builder import build_payload
p = Path('data_pdf/...某课程....pdf')
raw = PdfPlumberExtractor().extract(p)
pl = build_payload(raw)
rows = pl['jxap']['tm']
missing = sum(1 for r in rows if not r.get('szyqjxx'))
print('jxap rows', len(rows), 'missing szyqjxx', missing)
"
```

### 验收标准

- [ ] `missing_field` + 标签「思政元素的融入和预期教学成效」≤ 80
- [ ] `jxap` 有行但缺 `szyqjxx` 的 PDF ≤ 20
- [ ] 不改变 `jxap.tm` 总行数（193 附近）

---

## P0-2：续表无表头（447 次告警）

**目标**：跨页表正确合并行；`continued_table_without_header` 告警归零或降为 info。  
**根因**：续页列数漂移被拒绝；续页被误判为新表头；成功续表仍写 error 级 warning。

### 步骤 1：续表成功时不写 extraction_warning

**文件**：`section_table_parser.py`  
**位置**：`_detect_header` 中 `continued_table_without_header` 分支（约第 230 行）

**改法**：删除或注释掉 `warnings.append({..., "reason": "continued_table_without_header", ...})`。

续表信息改写入 `parse_section_tables` 的返回值，供 meta 使用：

```python
# parse_section_tables 开头
continuation_info: list[dict[str, Any]] = []

# _detect_header 续表分支改为：
if active and _looks_like_continuation(table, active):
    continuation_info.append({
        "section": active.profile.name,
        "reason": "continued_table_without_header",
        "severity": "info",
    })
    return active, 0, []  # 不再向 warnings 追加
```

在 `parse_section_tables` 返回 dict 中增加：

```python
return {
    ...
    "continuation_info": continuation_info,
}
```

**文件**：`pdfplumber.py` 的 `extract` 方法

把 `continuation_info` 挂到 raw 上（需在 `ExtractionRaw` 类型中增加可选字段，或先写入 `section_extraction`）：

```python
parsed_sections = parse_section_tables(all_tables)
# 在 build_meta 之前：
# raw.section_extraction["table_continuations"] = parsed_sections.get("continuation_info", [])
```

若不想改 `ExtractionRaw`，可在 `enhancer.enhance_raw_extraction` 末尾从 parser warnings 迁移；**最小改法**是只删 warning、不写 info，先消 447 条告警。

### 步骤 2：放宽 `_looks_like_continuation`

**文件**：`section_table_parser.py`，函数 `_looks_like_continuation`

```python
def _looks_like_continuation(table, active) -> bool:
    ...
    col_count = max(len(row) for row in table)
    drift = abs(col_count - active.col_count)

    non_empty_rows = [row for row in table[:5] if any(clean_text(cell) for cell in row)]
    if not non_empty_rows:
        return False

    has_seq = any(is_sequence(_cell(row, 0)) for row in non_empty_rows)

    # 原：drift > 2 直接 return False
    # 新：首列像序号/周次时允许 drift <= 4
    if drift > 2 and not has_seq:
        return False
    if drift > 4:
        return False

    if has_seq:
        return True
    return any(not clean_text(row[0]) and sum(bool(clean_text(c)) for c in row[1:]) >= 1 for row in non_empty_rows)
```

### 步骤 3：续页假表头抑制

**文件**：`section_table_parser.py`，`parse_section_tables` 主循环

在 `detected, start_row, warnings = _detect_header(table, active)` 之后增加：

```python
if active is not None and detected is not None:
    # 已有 active 且新检测 profile 不同、且首行像数据行 → 强制走续表
    if (
        detected.profile.name != active.profile.name
        and _looks_like_continuation(table, active)
    ):
        detected = active
        start_row = 0
```

### 步骤 4：自测

选 3 份 `continued_table_without_header` 样本 PDF（从 `missing_field_comparison.json` 或 DB 查 `section=教学安排`），对比改前后 `jxap.tm` 行数是否增加。

```powershell
python tests/integration/check_jxap_gap.py
```

### 验收标准

- [ ] `continued_table_without_header` 在 `extraction_warnings` 中为 0
- [ ] `jxap.tm` 平均行数 ≥ 10.5（基线 10.45）
- [ ] 无「串表」回归：随机抽 5 份目视检查安排表周次是否连续

---

## P0-3：融合加权评分

**目标**：选源时考虑授课方式、思政列、考核占比；让 text 源在 table 残缺时更容易胜出。  
**根因**：`enhancer._current_candidates` 对 `course_schedule` 只要求 `("序号", "授课内容")`。

### 步骤 1：在 config 增加评分配置

**文件**：`config.py`

在 `PROJECT_CONFIG` 中增加（并挂到 `load_project_config()` 返回值）：

```python
FUSION_SCORING: dict[str, Any] = {
    "course_schedule": {
        "required": ("序号", "授课内容"),
        "weighted": {
            "授课方式": 15,
            "思政元素的融入和预期教学成效": 25,
        },
        "min_rows": 3,
        "min_improvement": 5.0,
    },
    "teaching_content": {
        "required": ("序号", "主题", "知识点", "学时"),
        "weighted": {},
        "min_rows": 2,
        "min_improvement": 8.0,
    },
    "assessment_rows": {
        "required": ("考试形式", "占比"),
        "weighted": {"考察内容": 10, "考察方式": 10},
        "min_rows": 2,
        "min_improvement": 3.0,
    },
    "course_requirements": {
        "required": (),
        "weighted": {"要求内容": 20},
        "min_rows": 1,
        "min_improvement": 8.0,
    },
}
```

### 步骤 2：实现加权评分函数

**文件**：`src/syllabus_auditor/core/extractors/fusion.py`

新增：

```python
def score_rows_weighted(
    rows: list[dict[str, Any]],
    *,
    required: tuple[str, ...],
    weighted: dict[str, int] | None = None,
    min_rows: int = 1,
    warning_penalty: int = 5,
    warnings: list[dict[str, Any]] | None = None,
) -> float:
    if not rows:
        return 0.0
    weighted = weighted or {}
    base = row_completeness(rows, required) * 50.0
    if weighted:
        w_total = sum(weighted.values()) or 1
        w_hits = sum(
            weighted[field]
            for row in rows
            for field, weight in weighted.items()
            if str(row.get(field, "")).strip()
        )
        base += (w_hits / (len(rows) * w_total)) * 30.0
    row_bonus = min(len(rows), 20) / 20 * 20.0
    if len(rows) < min_rows:
        base *= len(rows) / max(min_rows, 1)
    penalty = (len(warnings or [])) * warning_penalty
    return max(base + row_bonus - penalty, 0.0)
```

修改 `make_row_candidate`：增加可选参数 `scoring_config: dict | None = None`，有配置时调用 `score_rows_weighted`。

### 步骤 3：enhancer 传入各 section 配置

**文件**：`src/syllabus_auditor/core/extractors/enhancer.py`

```python
from config import load_project_config

def _fusion_scoring(section_key: str) -> dict[str, Any]:
    cfg = load_project_config().get("fusion_scoring", {})
    return cfg.get(section_key, {})

def _current_candidates(raw: ExtractionRaw) -> dict[str, ExtractionCandidate]:
    return {
        "course_schedule": make_row_candidate(
            "course_schedule",
            "pdfplumber_table",
            raw.course_schedule,
            ("序号", "授课内容"),
            scoring_config=_fusion_scoring("course_schedule"),
        ),
        # teaching_content / assessment_rows / course_requirements 同理
    }
```

### 步骤 4：按 section 配置 min_improvement

**文件**：`fusion.py` 的 `choose_candidate`

增加参数 `min_improvement: float = 8.0`（已有），在 `enhancer._select_rows` 调用时传入：

```python
cfg = _fusion_scoring(section_key)
selected = choose_candidate(
    current,
    candidates,
    min_improvement=float(cfg.get("min_improvement", 8.0)),
)
```

### 步骤 5：自测

```powershell
```

关注：

- `alternative_candidate_selected` 是否从 56 上升
- `assessment_rows` 的 `pdfplumber_text` 胜出是否增加
- `course_schedule` 平均 score 是否上升

### 验收标准

- [ ] `assessment_rows` 平均 selected_score > 20（基线 12.73）
- [ ] 切换到 text 源的 PDF ≥ 70（基线 47）
- [ ] 无明显回归：`jxap.tm` 有行 PDF 仍 ≥ 190

---

## P0-4：质检与 status 分层

**目标**：概述兜底（`apgs`/`nrgs`/`khgs`/`mbgs`）不再触发 error；`success` 可达。  
**根因**：`quality.py` 不区分 severity；`status.py` 只要有 warning 或 overview 就 partial。

### 步骤 1：warning 增加 severity 字段

**文件**：`config.py`

```python
WARNING_SEVERITY: dict[str, str] = {
    "missing_field": "error",
    "empty_section": "error",
    "validated_text_fallback_used": "info",
    "continued_table_without_header": "info",
    "alternative_candidate_selected": "info",
    "unknown_columns": "warn",
    "missing_required_columns": "warn",
    "missing_teaching_method": "warn",
    "text_row_low_confidence": "warn",
    "suspiciously_few_rows": "warn",
    "sanitized_control_chars": "info",
    "pymupdf_extract_failed": "warn",
}
```

**文件**：`quality.py`

1. 修改 `_warning`，增加 `severity: str = "error"` 参数并写入 dict。

2. 新增辅助函数：

```python
def _default_severity(reason: str) -> str:
    from config import load_project_config
    mapping = load_project_config().get("warning_severity", {})
    return mapping.get(reason, "error")


def _has_overview_substitute(payload: dict, section: str) -> bool:
    substitutes = {
        "jxnr": ("nrgs",),
        "jxap": ("apgs",),
        "kcmb": ("mbgs",),
        "khfsb": ("khgs",),
        "kcyqb": ("yqgs",),
    }
    block = payload.get(section) or {}
    for key in substitutes.get(section, ()):
        if not _is_empty(block.get(key)):
            return True
    return False
```

3. 修改 `build_completeness_warnings`：

- 对 `field == "tm"` 且 `_is_empty(value)`：
  - 若 `_has_overview_substitute(payload, section)` → 追加 `reason="overview_used_instead_of_table"`, `severity="info"`
  - 否则 → 保持 `empty_section`, `severity="error"`

- 行级 `missing_field`（jxap/jxnr/khfsb 行内）：
  - 若同 section 有 overview  substitute → `severity="warn"`
  - 否则 → `severity="error"`

4. 在 `prepare_payload_and_meta_for_insert` 合并 meta 已有 warnings 时，为缺 severity 的旧 warning 补上 `_default_severity(reason)`。

### 步骤 2：重写 status 判定

**文件**：`status.py`

```python
def _warning_severity(w: dict) -> str:
    return str(w.get("severity") or "error")


def judge_extraction_status(payload: dict[str, Any], meta: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or not payload:
        return "failed"

    warnings = meta.get("extraction_warnings") or []
    error_warnings = [w for w in warnings if _warning_severity(w) == "error"]

    jcxx = payload.get("jcxx") or {}
    has_kcbh = bool(jcxx.get("kcbh"))
    has_goals = any((payload.get("kcmb") or {}).get(k) for k in ("szmb", "nlmb", "zsmb", "mbgs"))
    has_jxnr = bool((payload.get("jxnr") or {}).get("tm")) or bool((payload.get("jxnr") or {}).get("nrgs"))
    has_jxap = bool((payload.get("jxap") or {}).get("tm")) or bool((payload.get("jxap") or {}).get("apgs"))

    if error_warnings:
        return "partial"
    if not (has_goals and has_jxnr):
        return "partial"
    if not has_kcbh:
        return "partial"
    # 安排表：有 tm 或 apgs 即可
    if not has_jxap:
        return "partial"

    return "success"
```

说明：

- 去掉「有 overview 必 partial」逻辑
- 去掉「有 unmapped 必 partial」（unmapped 可单独 warn，不阻断 success）
- 若希望更严，可把 `unmapped_segments` 非空时降为 partial

### 步骤 3：enhancer 写 warning 时带 severity

**文件**：`enhancer.py`，`_append_warning`

```python
def _append_warning(raw, section, reason, **extra):
    from config import load_project_config
    severity = load_project_config().get("warning_severity", {}).get(reason, "error")
    warning = {"section": section, "reason": reason, "severity": severity}
    warning.update(extra)
    raw.extraction_warnings.append(warning)
```

`section_table_parser` 里直接 append 的 warnings 在 P0-2 已减少；剩余的可在 parser 返回前统一 `_attach_severity(warnings)`。

### 步骤 4：自测

```powershell
python tests/integration/run_missing_analysis.py
```

### 验收标准

- [ ] `success` ≥ 60（200 份中）
- [ ] `validated_text_fallback_used` 仍为 info，不计入 error
- [ ] 总 error 级告警 ≤ 600

---

## P0-5：考核表增强

**目标**：`khfsb.tm` 平均行数从 0.53 提到 ≥ 1.8；减少考核 `empty_section`。  
**根因**：表头别名不足；文本 regex 过窄；有 `khgs` 无 `tm` 仍报空表。

### 步骤 1：扩展考核 profile 别名

**文件**：`section_table_parser.py`，`name="考核方式"` 的 profile

```python
"考试形式": ("考试形式", "考核形式", "考核环节", "考核项目", "项目", "环节", "评定方式"),
"占比": ("占比", "比例", "权重", "成绩占比", "分值", "分数", "百分比"),
```

### 步骤 2：末列数字推断为占比

**文件**：`section_table_parser.py`，`_mapped_row` 末尾

```python
if active.profile.name == "考核方式" and "占比" not in item:
    for col_index in reversed(range(len(row))):
        value = _cell(row, col_index)
        if re.search(r"\d+\s*[%％]?", value):
            item["占比"] = value
            break
```

### 步骤 3：增强文本解析

**文件**：`text_candidates.py`，`parse_assessment`

在现有 `pattern.finditer` 之后增加备用规则：

```python
# 规则 B：「平时 30 + 期末 70」
for line in section.splitlines():
    m = re.findall(r"([\u4e00-\u9fa5]{2,12})\s*(\d+)\s*[%％]?", line)
    ...

# 规则 C：整段无 % 但有「总计100」→ 按行拆分
```

（实现时以单测/fixture 为准，不必一次写完所有变体。）

### 步骤 4：khgs → tm 回填

**文件**：`payload_builder.py`

在 `assessment_items` 构建后：

```python
def _assessment_from_text(text: str) -> list[dict[str, Any]]:
    from syllabus_auditor.core.extractors.text_candidates import parse_assessment
    candidate = parse_assessment(text, "payload_fallback")
    return [_map_row(row, ASSESSMENT_ITEM_MAP) for row in candidate.rows if row]

assessment_items = [_map_row(row, ASSESSMENT_ITEM_MAP) for row in raw.assessment_rows]
assessment_items = [item for item in assessment_items if item]
if not assessment_items and khgs:
    assessment_items = [item for item in _assessment_from_text(khgs) if item]
```

### 步骤 5：自测

```powershell
# 看 avg_khfsb_rows、empty_khfsb
```

### 验收标准

- [ ] `khfsb.tm` 平均行数 ≥ 1.8
- [ ] `empty_khfsb`（tm 为空）≤ 8
- [ ] 考核 `empty_section` 告警 ≤ 50

---

## 全部 P0 完成后的总验收

```powershell
conda activate course
$env:PYTHONPATH = "src;."

# 1. 清空并重跑 200 份
python tests/integration/run_missing_analysis.py

# 2. 融合统计
# 3. jxap / khfsb 交叉检查
python tests/integration/check_jxap_gap.py
```

| 指标 | 基线 | P0 目标 |
|------|------|---------|
| 总告警 | 2903 | ≤ 1000 |
| error 级告警 | ~2903 | ≤ 600 |
| success | 0 | ≥ 60 |
| 思政 missing_field | 465 | ≤ 80 |
| continued_table_without_header | 447 | 0 |
| khfsb 均行数 | 0.53 | ≥ 1.8 |
| 抽取误报率 | 80.5% | ≤ 35% |

结果 JSON：`data_pdf/analysis/missing_field_comparison.json`

---

## 常见问题

### Q1：改完 success 仍为 0？

检查 `quality.py` 是否给所有 warning 写了 `severity`；未标注的默认仍是 error。  
在 DB 执行：

```sql
SELECT w->>'reason', w->>'severity', COUNT(*)
FROM syllabus_extractions e,
     jsonb_array_elements(e.meta->'extraction_warnings') w
GROUP BY 1, 2
ORDER BY 3 DESC;
```

### Q2：思政列仍大量缺失？

1. 打印单份 PDF 的 `raw.course_schedule` 原始行（cn 键名）  
2. 看表头是否进了 `kzzd` → 检查 `_promote_schedule_sz`  
3. 看 `section_table_parser` 的 `col_map` 是否含思政列

### Q3：续表改完行数变少？

回滚 P0-2 步骤 3（假表头抑制），只保留步骤 1–2。

### Q4：payload_builder 里 `??????` 是什么？

当前代码第 107 行 `_clean_value(cn.get("??????", ""))` 应为 **「总学时」** 或 `full_text`，属于编码损坏 bug。  
P0 顺带修复：

```python
zongxs = _extract_total_hours(raw.full_text, raw.teaching_content)
```

---

## 附录：最小改动路径（时间紧）

若只能做 2 天，按此顺序：

1. **P0-1** 思政别名 + `_promote_schedule_sz`（收益最大）  
2. **P0-4** status + severity（success 数字立刻改善）  
3. **P0-2** 删掉续表 warning（告警数立刻减半）  

P0-3、P0-5 可放到下一迭代。
