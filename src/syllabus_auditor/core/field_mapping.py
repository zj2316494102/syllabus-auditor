"""Excel 列名 → courses 表列名映射。"""

from __future__ import annotations

EXCEL_TO_DB_COLUMN: dict[str, str] = {
    "课程编号": "kcbh",
    "开课（院）系": "kkyx",
    "中文课程名称": "zwkcmc",
    "英文课程名称": "ywkcmc",
    "上课语言": "skyy",
    "允许学院外选课": "yxwxyxk",
    "是否允许外学院选课": "yxwxyxk",
    "考核方式": "khfs",
    "课程性质": "kcxz",
    "课程类别": "kclb",
    "周学时": "zxs",
    "上课周数": "skzs",
    "总学时": "zongxs",
    "教学学时": "jxxs",
    "实验学时": "syxs",
    "实践学时": "sjxs",
    "其他学时": "qtxs",
    "自学学时": "zxxs",
    "学分": "kcxf",
    "主讲教师姓名": "zjjsxm",
    "其他课程": "qtkc",
    "是否生效": "sfsx",
    "审核状态": "shzt",
}

COURSE_DB_COLUMNS: tuple[str, ...] = tuple(EXCEL_TO_DB_COLUMN.values())
