from __future__ import annotations

import json
from typing import Any


def build_prompt(audit_input: dict[str, Any]) -> str:
    input_json = json.dumps(audit_input, ensure_ascii=False, indent=2)
    return f"""你是课程方案审核专家。请审核“是否将思政元素有效融入各环节”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
payload_data 是结构化抽取结果，是主体证据。
meta_context 是辅助证据，只能在结构化字段为空、缺失、明显不完整或存在相关抽取 warning 时参考。
如果 meta_context 中有相关原文但结构化字段为空，应指出“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
不要把 meta 中孤立出现的政策关键词直接当作通过证据。

审核维度：是否将思政元素有效融入各环节

审核要求：
1. 课程目标中应包含明确的思政目标，能够体现立德树人、价值引领、责任感、使命感、家国情怀、职业伦理、社会责任等内容。
2. 教学安排中应体现思政元素融入，并且思政元素应与具体教学内容、周次、章节、知识点、案例、讨论、实践或教学方法发生关联。
3. 课程目标中的思政目标与教学安排中的思政融入应能形成呼应，不能目标里有思政但教学安排没有落地，也不能教学安排零散出现思政词但课程目标没有对应目标。
4. 不审核预期教学成效。

判断规则：
1. 思政目标明确，且教学安排中有具体、有效、可对应教学环节的思政融入，result 写“是”。
2. 任一部分为空、缺失、表述笼统、只有口号、无法与教学环节关联，result 写“否”。
3. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
4. 不要因为出现“思政”“立德树人”“价值引领”等少量关键词就直接判通过，要判断是否具体融入课程目标和教学安排。
5. evidence_paths 必须引用输入 JSON 中实际存在的路径。
6. suggestion 必须给出可执行修改建议。
7. 输出必须是严格 JSON，不要输出 Markdown。

输入 JSON：
{input_json}

请输出严格 JSON：
{{
  "dimension": "szysfyxrghj",
  "label": "是否将思政元素有效融入各环节",
  "result": "是或否",
  "reasons": [],
  "checks": {{
    "has_ideological_goal": {{
      "result": "是或否",
      "reason": "",
      "evidence_paths": []
    }},
    "has_arrangement_integration": {{
      "result": "是或否",
      "reason": "",
      "evidence_paths": []
    }},
    "is_effectively_integrated": {{
      "result": "是或否",
      "reason": "",
      "evidence_paths": []
    }}
  }},
  "evidence_paths": [],
  "suggestion": ""
}}
"""
