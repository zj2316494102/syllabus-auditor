"""从 payload 构建各审核维度共用的结构化片段。"""

from __future__ import annotations

from typing import Any

from syllabus_auditor.core.content_layout import build_layout_context
from syllabus_auditor.utils.data import as_dict, as_list, exact_value, normalize_kzzd


def build_kcmb_audit_data(payload: dict[str, Any], *, include_all_goals: bool = True) -> dict[str, Any]:
    kcmb = as_dict(payload.get("kcmb"))
    data: dict[str, Any] = {
        "szmb": exact_value(kcmb.get("szmb")),
        "mbgs": exact_value(kcmb.get("mbgs")),
        "kzzd": normalize_kzzd(kcmb.get("kzzd")),
    }
    if include_all_goals:
        data["nlmb"] = exact_value(kcmb.get("nlmb"))
        data["zsmb"] = exact_value(kcmb.get("zsmb"))
    data.update(build_layout_context("kcmb", kcmb))
    return data


def build_jxnr_audit_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxnr = as_dict(payload.get("jxnr"))
    return {
        "tm": as_list(jxnr.get("tm")),
        "zongxs": exact_value(jxnr.get("zongxs")),
        "nrgs": exact_value(jxnr.get("nrgs")),
        **build_layout_context("jxnr", jxnr),
    }


def build_jxap_audit_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxap = as_dict(payload.get("jxap"))
    rows = []
    for row in as_list(jxap.get("tm")):
        item = as_dict(row)
        row_kzzd = normalize_kzzd(item.get("kzzd"))
        zy = exact_value(item.get("zy"))
        if zy:
            if isinstance(row_kzzd, list):
                row_kzzd = [*row_kzzd, {"bt": "作业", "nr": zy}]
            elif isinstance(row_kzzd, dict) and row_kzzd:
                row_kzzd = [row_kzzd, {"bt": "作业", "nr": zy}]
            else:
                row_kzzd = [{"bt": "作业", "nr": zy}]
        rows.append(
            {
                "zs": exact_value(item.get("zs")),
                "sknr": exact_value(item.get("sknr")),
                "skfs": exact_value(item.get("skfs")),
                "szyqjxx": exact_value(item.get("szyqjxx")),
                "kzzd": row_kzzd,
            }
        )
    return {
        "tm": rows,
        "apgs": exact_value(jxap.get("apgs")),
        **build_layout_context("jxap", jxap),
    }


def build_jxfs_audit_data(payload: dict[str, Any]) -> dict[str, Any]:
    jxap = as_dict(payload.get("jxap"))
    khfsb = as_dict(payload.get("khfsb"))
    return {
        "jxap": {
            "tm": as_list(jxap.get("tm")),
            "apgs": exact_value(jxap.get("apgs")),
            **build_layout_context("jxap", jxap),
        },
        "khfsb": {
            "tm": as_list(khfsb.get("tm")),
            "khgs": exact_value(khfsb.get("khgs")),
            **build_layout_context("khfsb", khfsb),
        },
        "kcyq": exact_value(payload.get("kcyq")),
    }
