from __future__ import annotations

import json
from typing import Any


ITEM_PROMPTS = {
    "jxmb": {
        "label": "教学目标是否符合要求",
        "data_label": "教学目标",
        "requirement": (
            "重点判断课程目标是否从知识、能力、价值观等方面设定，目标是否明确清晰；"
            "是否体现立德树人、课程思政与专业知识融合；是否引导学生增强责任感、使命感，"
            "将个人追求融入国家富强、民族振兴、人民幸福。"
        ),
        "evidence_examples": "audit_input.data.szmb、audit_input.data.nlmb、audit_input.data.zsmb、meta_context.raw_text_segments[0].text",
    },
    "jxnr": {
        "label": "教学内容是否符合要求",
        "data_label": "教学内容",
        "requirement": (
            "重点判断教学内容是否充实、知识体系是否完善、重难点是否清楚、进度是否合理；"
            "是否反映学科前沿并体现新财经战略升级要求；是否有机融入党的二十大精神、"
            "习近平新时代中国特色社会主义思想、党的领导、党史、新中国史、改革开放史、社会主义发展史等内容；"
            "专业学位课程是否体现职业实践性、行业实践和实务实操设计。"
        ),
        "evidence_examples": "audit_input.data.tm[0].zsd、audit_input.data.nrgs、meta_context.raw_text_segments[0].text",
    },
    "jxfs": {
        "label": "教学方式是否符合要求",
        "data_label": "教学方式",
        "requirement": (
            "重点判断教学安排、考核方式、课程要求中是否体现恰当有效的教学方法；"
            "是否注重多种教学方法组合，是否与教学目标一致；是否包含案例教学、讨论、实践、真实情境等方式；"
            "是否体现讲道理与讲故事、抽象概念与生动案例、显性表述与隐性渗透相结合。"
        ),
        "evidence_examples": "audit_input.data.jxap.tm[0].skfs、audit_input.data.khfsb.tm[0].kcfs、audit_input.data.kcyqb.tm[0].yqnr、meta_context.raw_text_segments[0].text",
    },
}


def build_item_prompt(audit_input: dict[str, Any], item_key: str) -> str:
    config = ITEM_PROMPTS[item_key]
    item_input = {
        "audit_subject": {
            "dimension": "jxmbnrfsfhyq",
            "dimension_label": "教学目标、内容、方式是否符合要求",
            "item": item_key,
            "label": config["label"],
        },
        "audit_input": {
            "label": config["data_label"],
            **((audit_input.get("audit_inputs") or {}).get(item_key) or {}),
        },
        "meta_context": audit_input.get("meta_context") or {},
    }
    input_json = json.dumps(item_input, ensure_ascii=False, indent=2)
    return f"""你是课程方案审核专家。请审核“{config["label"]}”。

只能依据输入 JSON 判断，不得臆测未出现的信息。
audit_input 是本次审核的主体材料，只包含“{config["data_label"]}”相关结构化字段。
meta_context 只是辅助证据，只能在 audit_input 为空、缺失或抽取不完整时参考。
禁止使用其他审核子项内容替代本子项证据。

审核要求：
{config["requirement"]}

判断规则：
1. 符合要求时 result 写“是”，否则写“否”。
2. audit_input 为空、缺失、表述笼统或无法体现审核要求时，result 必须写“否”。
3. result 为“否”时 reasons 必须填写中文具体原因，不能只写“不符合要求”“内容不足”。
4. 如果 meta_context 中有相关原文但 audit_input 为空，应写明“结构化字段为空但原文疑似存在相关内容，需复核抽取”。
5. evidence_paths 必须引用输入 JSON 中实际存在的路径，例如：{config["evidence_examples"]}。
6. 不要因为出现少量政策关键词就直接判通过，要判断是否与课程专业内容有机融合。
7. suggestion 必须给出可执行修改建议。

输入 JSON：
{input_json}

请输出严格 JSON，不要输出 Markdown：
{{
  "key": "{item_key}",
  "label": "{config["label"]}",
  "result": "是或否",
  "reasons": [],
  "evidence_paths": [],
  "suggestion": ""
}}
"""


def build_prompt(audit_input: dict[str, Any]) -> str:
    return "\n\n".join(build_item_prompt(audit_input, key) for key in ITEM_PROMPTS)
