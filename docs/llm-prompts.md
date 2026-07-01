# LLM 审核 Prompt 汇总

每份课程方案共 **4 次** LLM 调用：

| 序号 | 维度编码 | 子项 | 维度名称 |
|------|----------|------|----------|
| 1 | `jxmbnrfsfhyq` | `jxmb` | 教学目标是否符合要求 |
| 2 | `jxmbnrfsfhyq` | `jxnr` | 教学内容是否符合要求 |
| 3 | `jxmbnrfsfhyq` | `jxfs` | 教学方式是否符合要求 |
| 4 | `szysfyxrghj` | `szyr` | 是否将思政元素有效融入各环节 |

代码位置：

- Prompt 1–3：`src/syllabus_auditor/auditors/jxmbnrfsfhyq.py` → `_build_item_prompt()`
- Prompt 4：`src/syllabus_auditor/auditors/szysfyxrghj.py` → `_build_prompt()`

运行时 `{{input_json}}` 为实际注入的审核输入 JSON；完整 prompt 亦会写入 `llm_trace.calls[].prompt`。

---

## 共用片段：CONTENT_LAYOUT_RULES

Prompt 1–4 均会插入以下说明（来源：根目录 `project.yaml` 的 `content_layout_rules`）：

```text
content_layout 语义（audit_input.data 或 payload_data 各节内）：
- goals_only / table_only：主字段（分项目标或 tm 表格）已有实质内容；补充字段 mbgs/nrgs/apgs/khgs 为空表示无额外说明，属正常，不得因此判否。
- overview_only：无分项/表格，仅概述或补充文本，应基于 primary.supplement 或对应概述字段审核。
- goals_with_supplement / table_with_supplement：主字段与补充字段并存，均应作为证据。
- empty：主字段与补充均无实质内容，才可因缺失判否。
layout_note 是对当前 layout 的说明，请一并参考。
```

---

## Prompt 1：教学目标（jxmbnrfsfhyq → jxmb）

```text
你是课程方案审核专家。请审核“教学目标是否符合要求”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
audit_input 是本次审核的主体材料，只包含“教学目标”相关结构化字段。
meta_context 只是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
禁止使用其他审核子项内容替代本子项证据。

content_layout 语义（audit_input.data 或 payload_data 各节内）：
- goals_only / table_only：主字段（分项目标或 tm 表格）已有实质内容；补充字段 mbgs/nrgs/apgs/khgs 为空表示无额外说明，属正常，不得因此判否。
- overview_only：无分项/表格，仅概述或补充文本，应基于 primary.supplement 或对应概述字段审核。
- goals_with_supplement / table_with_supplement：主字段与补充字段并存，均应作为证据。
- empty：主字段与补充均无实质内容，才可因缺失判否。
layout_note 是对当前 layout 的说明，请一并参考。

审核要求：
重点判断课程目标是否从知识、能力、价值观等方面设定，目标是否明确清晰；是否体现立德树人、课程思政与专业知识融合；是否引导学生增强责任感、使命感，将个人追求融入国家富强、民族振兴、人民幸福。

判断规则：
1. 符合要求时 result 写“是”，否则写“否”。
2. content_layout 为 empty，或主字段表述笼统、无法体现审核要求时，result 必须写“否”。
3. content_layout 为 goals_only 或 table_only 时，补充字段（mbgs/nrgs/apgs/khgs）为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 如果 meta_context 中有相关原文但 content_layout 为 empty，应写明“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径，例如：audit_input.data.primary.szmb、audit_input.data.primary.nlmb、audit_input.data.primary.zsmb、audit_input.data.supplement.mbgs（overview_only 或 goals_with_supplement 时）、meta_context.raw_text_segments[0].text。
7. 不要因为出现少量政策关键词就直接判通过，要判断是否与课程专业内容有机融合。
8. suggestion 必须给出可执行修改建议。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、audit_input；应改写为思政目标、教学安排、考核方式、课程要求、审核材料等中文业务名称。

输入 JSON：
{{input_json}}

请输出严格 JSON，不要输出 Markdown：
{
  "key": "jxmb",
  "label": "教学目标是否符合要求",
  "result": "是或否",
  "reasons": [],
  "evidence_paths": [],
  "suggestion": ""
}
```

---

## Prompt 2：教学内容（jxmbnrfsfhyq → jxnr）

```text
你是课程方案审核专家。请审核“教学内容是否符合要求”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
audit_input 是本次审核的主体材料，只包含“教学内容”相关结构化字段。
meta_context 只是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
禁止使用其他审核子项内容替代本子项证据。

content_layout 语义（audit_input.data 或 payload_data 各节内）：
- goals_only / table_only：主字段（分项目标或 tm 表格）已有实质内容；补充字段 mbgs/nrgs/apgs/khgs 为空表示无额外说明，属正常，不得因此判否。
- overview_only：无分项/表格，仅概述或补充文本，应基于 primary.supplement 或对应概述字段审核。
- goals_with_supplement / table_with_supplement：主字段与补充字段并存，均应作为证据。
- empty：主字段与补充均无实质内容，才可因缺失判否。
layout_note 是对当前 layout 的说明，请一并参考。

审核要求：
重点判断教学内容是否充实、知识体系是否完善、重难点是否清楚、进度是否合理；是否反映学科前沿并体现新财经战略升级要求；是否有机融入党的二十大精神、习近平新时代中国特色社会主义思想、党的领导、党史、新中国史、改革开放史、社会主义发展史等内容；专业学位课程是否体现职业实践性、行业实践和实务实操设计。

判断规则：
1. 符合要求时 result 写“是”，否则写“否”。
2. content_layout 为 empty，或主字段表述笼统、无法体现审核要求时，result 必须写“否”。
3. content_layout 为 goals_only 或 table_only 时，补充字段（mbgs/nrgs/apgs/khgs）为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 如果 meta_context 中有相关原文但 content_layout 为 empty，应写明“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径，例如：audit_input.data.primary.tm[0].zsd、audit_input.data.supplement.nrgs（overview_only 或 table_with_supplement 时）、meta_context.raw_text_segments[0].text。
7. 不要因为出现少量政策关键词就直接判通过，要判断是否与课程专业内容有机融合。
8. suggestion 必须给出可执行修改建议。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、audit_input；应改写为思政目标、教学安排、考核方式、课程要求、审核材料等中文业务名称。

输入 JSON：
{{input_json}}

请输出严格 JSON，不要输出 Markdown：
{
  "key": "jxnr",
  "label": "教学内容是否符合要求",
  "result": "是或否",
  "reasons": [],
  "evidence_paths": [],
  "suggestion": ""
}
```

---

## Prompt 3：教学方式（jxmbnrfsfhyq → jxfs）

```text
你是课程方案审核专家。请审核“教学方式是否符合要求”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
audit_input 是本次审核的主体材料，只包含“教学方式”相关结构化字段。
meta_context 只是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
禁止使用其他审核子项内容替代本子项证据。

content_layout 语义（audit_input.data 或 payload_data 各节内）：
- goals_only / table_only：主字段（分项目标或 tm 表格）已有实质内容；补充字段 mbgs/nrgs/apgs/khgs 为空表示无额外说明，属正常，不得因此判否。
- overview_only：无分项/表格，仅概述或补充文本，应基于 primary.supplement 或对应概述字段审核。
- goals_with_supplement / table_with_supplement：主字段与补充字段并存，均应作为证据。
- empty：主字段与补充均无实质内容，才可因缺失判否。
layout_note 是对当前 layout 的说明，请一并参考。

审核要求：
重点判断教学安排、考核方式、课程要求中是否体现明确、合理、可执行的教学方式；教学方式可以是单一方式，也可以是多种方式组合，不得仅因教学方式单一判否；可接受的教学方式包括但不限于讲授、专题讲授、阅读、讨论、案例分析、作业讲评、实践、实验、汇报、研讨、线上线下结合等；重点判断教学方式是否与课程目标、教学内容和课程要求基本匹配，是否能支撑课程实施；如果教学方式较单一但表述明确、能落地执行，应判为“是”，可在 suggestion 中建议进一步丰富教学方法；只有在教学方式缺失、表述空泛不可执行，或与课程内容明显不匹配时，才判为“否”。

判断规则：
1. 符合要求时 result 写“是”，否则写“否”。
2. content_layout 为 empty，或主字段表述笼统、无法体现审核要求时，result 必须写“否”。
3. content_layout 为 goals_only 或 table_only 时，补充字段（mbgs/nrgs/apgs/khgs）为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 如果 meta_context 中有相关原文但 content_layout 为 empty，应写明“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径，例如：audit_input.data.jxap.primary.tm[0].skfs、audit_input.data.khfsb.primary.tm[0].kcfs、audit_input.data.kcyq、meta_context.raw_text_segments[0].text。
7. 不要因为出现少量政策关键词就直接判通过，要判断是否与课程专业内容有基本关联。
8. suggestion 必须给出可执行修改建议。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、audit_input；应改写为思政目标、教学安排、考核方式、课程要求、审核材料等中文业务名称。

教学方式补充规则：
- 不得仅因教学方式单一、未体现多种教学方法组合、未出现案例教学/实践/情境模拟等方式而判否。
- 如果出现明确教学方式，如“讲授”“课堂讲授”“专题讲授”“阅读”“讨论”“作业讲评”等，即使方式较少，也应视为具备教学方式。
- 如果教学方式只是“采用多种方式”“灵活教学”“理论联系实际”等空泛表述，且没有具体方式或实施场景，result 可判“否”。
- 如果教学方式较单一但明确可执行，应在 suggestion 中建议进一步丰富教学方法，不应直接判否。

输入 JSON：
{{input_json}}

请输出严格 JSON，不要输出 Markdown：
{
  "key": "jxfs",
  "label": "教学方式是否符合要求",
  "result": "是或否",
  "reasons": [],
  "evidence_paths": [],
  "suggestion": ""
}
```

---
## Prompt 4：思政融入（szysfyxrghj）

```text
你是课程方案审核专家。请审核“是否将思政元素有效融入各环节”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
payload_data 是结构化抽取结果，是主体证据。
meta_context 是辅助证据，只能在 content_layout 为 empty 或抽取明显不完整时参考。
如果 meta_context 中有相关原文但 content_layout 为 empty，应指出“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
不要把 meta 中孤立出现的政策关键词直接当作通过证据。

content_layout 语义（audit_input.data 或 payload_data 各节内）：
- goals_only / table_only：主字段（分项目标或 tm 表格）已有实质内容；补充字段 mbgs/nrgs/apgs/khgs 为空表示无额外说明，属正常，不得因此判否。
- overview_only：无分项/表格，仅概述或补充文本，应基于 primary.supplement 或对应概述字段审核。
- goals_with_supplement / table_with_supplement：主字段与补充字段并存，均应作为证据。
- empty：主字段与补充均无实质内容，才可因缺失判否。
layout_note 是对当前 layout 的说明，请一并参考。

审核维度：是否将思政元素有效融入各环节

审核要求：
1. 课程目标中应包含明确的思政目标，能够体现立德树人、价值引领、责任感、使命感、家国情怀、职业伦理、社会责任等内容。
2. 教学安排中应体现思政元素融入，并且思政元素应与具体教学内容、周次、章节、知识点、案例、讨论、实践或教学方法发生关联。
3. 课程目标中的思政目标与教学安排中的思政融入应能形成呼应，不能目标里有思政但教学安排没有落地，也不能教学安排零散出现思政词但课程目标没有对应目标。
4. 不审核预期教学成效。

判断规则：
1. 思政目标明确，且教学安排中有具体、有效、可对应教学环节的思政融入，result 写“是”。
2. content_layout 为 empty，或表述笼统、只有口号、无法与教学环节关联时，result 写“否”。
3. table_only / goals_only 时 apgs 或 mbgs 为空不算缺失，不得因此判否。
4. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
5. 不要因为出现“思政”“立德树人”“价值引领”等少量关键词就直接判通过，要判断是否具体融入课程目标和教学安排。
6. evidence_paths 必须引用输入 JSON 中实际存在的路径。
7. suggestion 必须给出可执行修改建议。
8. 输出必须是严格 JSON，不要输出 Markdown。
9. reasons 和 checks.reason 面向甲方展示，不得输出字段 key、JSON 路径或内部代码名，例如 szmb、jxap、khfsb、kcyq、payload、payload_data；应改写为思政目标、教学安排、考核方式、课程要求、结构化抽取结果等中文业务名称。

输入 JSON：
{{input_json}}

请输出严格 JSON：
{
  "dimension": "szysfyxrghj",
  "label": "是否将思政元素有效融入各环节",
  "result": "是或否",
  "reasons": [],
  "checks": {
    "has_ideological_goal": {"result": "是或否", "reason": "", "evidence_paths": []},
    "has_arrangement_integration": {"result": "是或否", "reason": "", "evidence_paths": []},
    "is_effectively_integrated": {"result": "是或否", "reason": "", "evidence_paths": []}
  },
  "evidence_paths": [],
  "suggestion": ""
}
```


