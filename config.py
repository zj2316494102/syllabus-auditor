from __future__ import annotations

from functools import lru_cache
from typing import Any

EXTRACTION_CONFIG: dict[str, Any] = {
    "section_titles": {
        "all": [
            "课程基本信息", "基本信息", "课程中文简介", "课程英文简介", "预备知识要求",
            "课程目标", "教学目标", "教学内容", "课程内容", "教学安排", "课程安排",
            "授课安排", "课程要求", "教材及阅读材料", "阅读材料", "考核方式",
        ],
        "course_goal": ["课程目标", "教学目标"],
        "teaching_content": ["教学内容", "课程内容"],
        "course_schedule": ["教学安排", "课程安排", "授课安排", "教学进度"],
        "assessment": ["考核方式", "课程考核", "成绩评定"],
        "course_requirements": ["课程要求", "学习要求", "课堂要求"],
        "reading_material": ["教材及阅读材料", "教材", "阅读材料", "参考书", "参考文献"],
    },
    "validated_text_rules": [
        {"field": "课程目标概述", "titles": ["课程目标", "教学目标"], "keywords": ["思政", "能力", "知识", "价值", "育人", "责任", "使命", "目标"], "min_len": 8, "warning_section": "course_goal", "warning_field": "课程目标概述", "meta_key": "course_goal_text_fallback"},
        {"field": "考核方式说明", "titles": ["考核方式", "课程考核", "成绩评定", "考核与评价", "评价方式"], "keywords": ["考试", "考核", "成绩", "平时", "期末", "闭卷", "开卷", "论文", "分值", "占比", "总计"], "min_len": 10, "warning_section": "assessment_rows", "warning_field": "考核方式说明", "meta_key": "assessment_text_fallback"},
        {"field": "课程要求", "titles": ["课程要求", "学习要求", "课堂要求"], "keywords": ["作业", "阅读", "考勤", "出勤", "讨论", "预习", "提交", "课堂", "要求", "完成"], "min_len": 6, "warning_section": "course_requirements", "warning_field": "课程要求", "meta_key": "course_requirement_text_fallback"},
        {"field": "阅读材料", "titles": ["教材及阅读材料", "教材", "阅读材料", "参考书", "参考文献"], "keywords": ["教材", "阅读材料", "参考书", "参考文献", "书目", "作者", "版次"], "min_len": 6, "warning_section": "jcjydcl", "warning_field": "阅读材料", "meta_key": "reading_material_fallback"},
    ],
}

PDF_EXTRACTOR_CONFIG: dict[str, Any] = {
    "raw_cn_fields": [
        "课程编号", "开课（院）系", "中文课程名称", "英文课程名称", "课程性质", "课程类别", "课程模块",
        "授课语言", "是否允许外学院选课", "考核方式", "周学时", "上课周数", "总学时", "教学学时",
        "实验学时", "实践学时", "其他学时", "自学学时", "课程学分", "任课教师姓名", "教师工号",
        "职称", "学历", "E-mail", "联系电话", "课程中文简介", "课程英文简介", "思政目标", "能力目标",
        "知识目标", "课程目标概述", "教学内容概述", "课程安排概述", "预备知识要求", "课程要求", "阅读材料",
        "考核方式说明",
    ],
    "basic_pair_labels": [
        "课程编号", "开课（院）系", "中文课程名称", "英文课程名称", "课程性质", "课程类别", "课程模块",
        "授课语言", "考核方式", "周学时", "上课周数", "总学时", "教学学时", "实验学时", "实践学时",
        "其他学时", "自学学时", "课程学分",
    ],
    "teacher_labels": ["任课教师姓名", "教师工号", "职称", "学历", "E-mail", "联系电话"],
    "two_column_section_labels": ["课程中文简介", "课程英文简介", "思政目标", "能力目标", "知识目标", "预备知识要求"],
}

PAYLOAD_CONFIG: dict[str, Any] = {
    "jcxx_field_map": {
        "课程编号": "kcbh", "开课（院）系": "kkyx", "中文课程名称": "zwkcmc", "英文课程名称": "ywkcmc",
        "授课语言": "skyy", "是否允许外学院选课": "sfyxwxyxk", "考核方式": "khfs", "课程性质": "kcxz",
        "课程类别": "kclb", "周学时": "zxs", "上课周数": "skzs", "总学时": "zongxs", "教学学时": "jxxs",
        "实验学时": "syxs", "实践学时": "sjxs", "其他学时": "qtxs", "自学学时": "zxxs", "课程学分": "kcxf",
        "任课教师姓名": "rkjsxm", "教师工号": "jsgh", "E-mail": "email", "联系电话": "lxdh",
    },
    "content_item_map": {"序号": "xh", "主题": "zt", "知识点": "zsd", "学时": "xs"},
    "schedule_item_map": {"序号": "zs", "授课内容": "sknr", "授课方式": "skfs", "作业": "zy", "思政元素的融入和预期教学成效": "szyqjxx"},
    "assessment_item_map": {"考试形式": "ksxs", "考察内容": "kcnr", "考察方式": "kcfs", "占比": "zb"},
    "requirement_item_map": {"要求类型": "yqlx", "要求内容": "yqnr", "作业要求": "zyyq", "考勤要求": "kqyq", "阅读要求": "ydyq"},
    "empty_markers": ["", "不填", "未填", "无", "暂无", "无特殊要求", "无特殊", "none", "null", "n/a", "na"],
    "total_hours_patterns": [r"课时总计[：:]\s*(\d+)\s*学时", r"学时总计[：:]\s*(\d+)\s*学时", r"课时总计[：:]\s*学时\s*(\d+)", r"总学时[：:]\s*(\d+)"],
}

COURSE_LIBRARY_CONFIG: dict[str, Any] = {
    "excel_to_db_column": {
        "课程编号": "kcbh", "开课（院）系": "kkyx", "中文课程名称": "zwkcmc", "英文课程名称": "ywkcmc",
        "上课语言": "skyy", "允许学院外选课": "yxwxyxk", "是否允许外学院选课": "yxwxyxk", "考核方式": "khfs",
        "课程性质": "kcxz", "课程类别": "kclb", "周学时": "zxs", "上课周数": "skzs", "总学时": "zongxs",
        "教学学时": "jxxs", "实验学时": "syxs", "实践学时": "sjxs", "其他学时": "qtxs", "自学学时": "zxxs",
        "学分": "kcxf", "主讲教师姓名": "zjjsxm", "其他课程": "qtkc", "是否生效": "sfsx", "审核状态": "shzt",
    },
}

LOADER_CONFIG: dict[str, Any] = {"excel_suffixes": [".xls", ".xlsx", ".xlsm", ".xlsb"], "pdf_suffix": ".pdf", "default_course_library_filename": "培养-课程库信息0616.xls"}
LLM_CONFIG: dict[str, Any] = {"provider": "openai_compatible", "model_env_vars": ["LLM_MODEL_NAME", "OPENAI_MODEL_NAME"], "api_key_env_vars": ["LLM_API_KEY", "OPENAI_API_KEY"], "base_url_env_vars": ["LLM_BASE_URL", "OPENAI_BASE_URL"], "system_prompt": "你是严格输出 JSON 的课程方案审核专家。", "temperature": 0, "response_format": {"type": "json_object"}}
AUDIT_CONFIG: dict[str, Any] = {
    "default_auditors": ["kcjbxxsfykckyz", "jxnrsfyxspp", "jxapsfyzcpp", "jxmbnrfsfhyq", "szysfyxrghj", "xxyzwzfhmb", "kcmb", "jxnr", "jxap", "kcyq", "khfsb"],
    "audit_modes": {"kcjbxxsfykckyz": {"type": "rule"}, "jxnrsfyxspp": {"type": "rule"}, "jxapsfyzcpp": {"type": "rule"}, "jxmbnrfsfhyq": {"type": "direct_llm"}, "szysfyxrghj": {"type": "direct_llm"}, "xxyzwzfhmb": {"type": "rule"}},
    "dimension_labels": {"kcjbxxsfykckyz": "课程基本信息是否与课程库一致", "jxnrsfyxspp": "教学内容是否与学时匹配", "jxapsfyzcpp": "教学安排是否与周次匹配", "jxmbnrfsfhyq": "教学目标、内容、方式是否符合要求", "szysfyxrghj": "是否将思政元素有效融入各环节", "xxyzwzfhmb": "信息要素完整、符合模板、是否有中英文简介"},
}
META_CONFIG: dict[str, Any] = {"extractor_version": "pdfplumber:0.11.0+pymupdf-fusion:0.1", "unmapped_cn_fields": ["课程模块", "职称", "学历"]}

PROJECT_CONFIG: dict[str, Any] = {"extraction": EXTRACTION_CONFIG, "pdf_extractor": PDF_EXTRACTOR_CONFIG, "payload": PAYLOAD_CONFIG, "course_library": COURSE_LIBRARY_CONFIG, "loader": LOADER_CONFIG, "llm": LLM_CONFIG, "audit": AUDIT_CONFIG, "meta": META_CONFIG}


@lru_cache(maxsize=1)
def load_project_config() -> dict[str, Any]:
    return PROJECT_CONFIG


@lru_cache(maxsize=1)
def load_extraction_config() -> dict[str, Any]:
    return EXTRACTION_CONFIG

AUDIT_CONFIG["szysfyxrghj_meta"] = {
    "goal_section_hints": ["课程目标", "教学目标", "思政目标", "课程思政目标", "价值目标", "育人目标"],
    "arrangement_section_hints": ["教学安排", "课程安排", "授课安排", "教学进度", "课程思政", "思政元素", "思政元素融入"],
    "ideology_keywords": ["思政", "立德树人", "价值引领", "价值观", "责任感", "使命感", "家国情怀", "职业伦理", "社会责任", "诚信", "法治", "职业道德"],
}

AUDIT_CONFIG["xxyzwzfhmb_template"] = {
    "normal_basic_fields": [
        ["kcbh", "课程编号"], ["kkyx", "开课（院）系"], ["zwkcmc", "中文课程名称"], ["ywkcmc", "英文课程名称"],
        ["skyy", "授课语言"], ["sfyxwxyxk", "是否允许外学院选课"], ["khfs", "考核方式"], ["kcxz", "课程性质"],
        ["kclb", "课程类别"], ["zxs", "周学时"], ["skzs", "上课周数"], ["zongxs", "总学时"], ["jxxs", "教学学时"],
        ["kcxf", "课程学分"], ["rkjsxm", "任课教师姓名"], ["jsgh", "教师工号"], ["email", "E-mail"], ["lxdh", "联系电话"],
    ],
    "special_basic_fields": [["syxs", "实验学时"], ["sjxs", "实践学时"], ["qtxs", "其他学时"], ["zxxs", "自学学时"]],
    "top_level_fields": [["kczwjj", "课程中文简介"], ["kcywjj", "课程英文简介"], ["ybzsyq", "预备知识要求"], ["jcjydcl", "教材及阅读材料"]],
    "course_goal_fields": [["szmb", "思政目标"], ["nlmb", "能力目标"], ["zsmb", "知识目标"]],
    "jxnr_row_fields": [["xh", "序号"], ["zt", "主题"], ["zsd", "知识点"], ["xs", "学时"]],
    "jxap_row_fields": [["zs", "序号"], ["sknr", "授课内容"], ["skfs", "授课方式"], ["szyqjxx", "思政元素的融入和预期教学成效"]],
    "section_hints": {
        "jcxx": ["课程基本信息", "基本信息", "课程信息"],
        "kczwjj": ["课程中文简介"],
        "kcywjj": ["课程英文简介"],
        "ybzsyq": ["预备知识要求", "预备知识"],
        "jcjydcl": ["教材及阅读材料", "教材", "阅读材料"],
        "kcmb": ["课程目标", "教学目标"],
        "jxnr": ["教学内容", "课程内容"],
        "jxap": ["教学安排", "课程安排", "授课安排", "教学进度"],
        "kcyq": ["课程要求"],
    },
}
PROJECT_CONFIG["audit"] = AUDIT_CONFIG
