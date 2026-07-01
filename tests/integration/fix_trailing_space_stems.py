"""修剪 PDF 文件名及 _mineru_raw 目录尾部空格，处理 stem 冲突。"""


from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_MD = PROJECT_ROOT / "data_md"
PDF_SUFFIX = ".pdf"
PARSE_SUBDIRS = ("hybrid_auto", "auto", "vlm", "office")
COURSE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


def list_pdf_files(input_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    pdfs: list[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != PDF_SUFFIX:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        pdfs.append(path)
    return pdfs


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def clean_course_code(value: str) -> str:
    text = re.sub(r"\s+", "", (value or "").strip())
    if not text or not COURSE_CODE_RE.fullmatch(text):
        return ""
    return text


def normalize_label(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def college_tag(pdf_path: Path, data_dir: Path) -> str:
    try:
        rel = pdf_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return "unknown"
    if not rel.parts:
        return "unknown"
    match = re.match(r"【([^】]+)】", rel.parts[0])
    if match:
        return re.sub(r"\s+", "", match.group(1))[:24] or "unknown"
    return re.sub(r"\s+", "", rel.parts[0])[:24] or "unknown"


def extract_course_fields(pdf_path: Path) -> tuple[str, str, str]:
    kcbh = ""
    zwkcmc = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:3]:
                for table in page.extract_tables() or []:
                    if not table:
                        continue
                    flat = normalize_label("".join(str(c or "") for row in table for c in row))
                    if "课程编号" not in flat and "中文课程名称" not in flat:
                        continue
                    for row in table:
                        cells = [str(c or "").strip() for c in row]
                        for idx in range(0, len(cells), 2):
                            label = normalize_label(cells[idx] if idx < len(cells) else "")
                            value = cells[idx + 1].strip() if idx + 1 < len(cells) else ""
                            if not value:
                                continue
                            if label == "课程编号" and not kcbh:
                                kcbh = clean_course_code(value)
                            elif label in {"中文课程名称", "课程名称"} and not zwkcmc:
                                zwkcmc = value
                if kcbh and zwkcmc:
                    break
    except Exception as exc:
        return "", "", f"{type(exc).__name__}: {exc}"
    return kcbh, zwkcmc, ""


def course_key(kcbh: str, zwkcmc: str, source_pdf: str) -> tuple[str, str]:
    if kcbh:
        return ("kcbh", kcbh)
    norm = normalize_name(zwkcmc)
    if norm:
        return ("zwkcmc", norm)
    return ("path", source_pdf)


def propose_new_stem(base: str, *, kcbh: str, college: str, source_pdf: str, used: set[str]) -> str:
    base = base.rstrip()
    for candidate in (
        f"{base}__{kcbh}" if kcbh else "",
        f"{base}__{college}" if college else "",
        f"{base}__{hashlib.sha1(source_pdf.encode()).hexdigest()[:8]}",
    ):
        if candidate and candidate not in used:
            return candidate
    n = 2
    while True:
        candidate = f"{base}__dup{n}"
        if candidate not in used:
            return candidate
        n += 1


def load_stem_rename_map(dedupe_path: Path) -> dict[str, str]:
    if not dedupe_path.is_file():
        return {}
    report = json.loads(dedupe_path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for row in report.get("applied", []):
        if row.get("status") != "renamed":
            continue
        old_pdf = row.get("source_pdf", "")
        new_pdf = row.get("new_source_pdf", "")
        if not old_pdf or not new_pdf:
            continue
        old_stem = Path(old_pdf).stem
        new_stem = Path(new_pdf).stem
        if old_stem and new_stem and old_stem != new_stem:
            mapping[old_stem] = new_stem
    return mapping


def raw_has_md(stem: str, raw_root: Path) -> bool:
    for sub in PARSE_SUBDIRS:
        parse_dir = raw_root / stem / sub
        if not parse_dir.is_dir():
            continue
        if any(parse_dir.glob("*.md")):
            return True
    return False


def plan_raw_stem(
    old_stem: str,
    *,
    used_stems: set[str],
    raw_root: Path,
    stem_rename_map: dict[str, str],
) -> tuple[str, str]:
    trimmed = old_stem.rstrip()
    if trimmed not in used_stems or not (raw_root / trimmed).exists():
        return trimmed, "trim raw dir to match pdf stem"

    if old_stem in stem_rename_map:
        return stem_rename_map[old_stem], f"conflict with {trimmed!r}; use dedupe rename"

    if trimmed in stem_rename_map:
        return stem_rename_map[trimmed], f"conflict with {trimmed!r}; use dedupe rename (trimmed key)"

    kcbh = ""
    for sub in PARSE_SUBDIRS:
        middle = raw_root / old_stem / sub / f"{old_stem}_middle.json"
        if not middle.is_file():
            middle = raw_root / old_stem / sub / f"{trimmed}_middle.json"
        if not middle.is_file():
            continue
        try:
            payload = json.loads(middle.read_text(encoding="utf-8"))
        except Exception:
            continue
        for page in payload if isinstance(payload, list) else []:
            for block in page if isinstance(page, list) else []:
                text = str(block.get("text", "") if isinstance(block, dict) else "")
                match = re.search(r"课程编号\s*[:：]?\s*([A-Za-z0-9._-]{3,32})", text)
                if match:
                    kcbh = clean_course_code(match.group(1))
                    break
            if kcbh:
                break
        if kcbh:
            break

    new_stem = propose_new_stem(
        trimmed,
        kcbh=kcbh,
        college="",
        source_pdf=old_stem,
        used=used_stems | {p.name for p in raw_root.iterdir() if p.is_dir()},
    )
    return new_stem, f"conflict with {trimmed!r}; rename via kcbh/college"


def rename_raw_tree(old_stem: str, new_stem: str, raw_root: Path, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    old_dir = raw_root / old_stem
    if not old_dir.is_dir():
        return actions
    new_dir = raw_root / new_stem
    if new_dir.exists():
        actions.append(f"SKIP raw rename (target exists): {old_stem!r} -> {new_stem!r}")
        return actions

    if dry_run:
        actions.append(f"RAW DIR {old_stem!r} -> {new_stem!r}")
        return actions

    old_dir.rename(new_dir)
    actions.append(f"RAW DIR {old_stem!r} -> {new_stem!r}")

    for sub in PARSE_SUBDIRS:
        parse_dir = new_dir / sub
        if not parse_dir.is_dir():
            continue
        for path in list(parse_dir.iterdir()):
            if not path.is_file():
                continue
            if path.stem == old_stem or path.name.startswith(f"{old_stem}_"):
                new_name = path.name.replace(old_stem, new_stem, 1)
                dst = path.with_name(new_name)
                if not dst.exists():
                    path.rename(dst)
                    actions.append(f"  file {path.name} -> {new_name}")
    return actions


def plan_pdf_rename(
    pdf_path: Path,
    *,
    data_dir: Path,
    root: Path,
    stem_index: dict[str, list[Path]],
    used_stems: set[str],
) -> tuple[str, str, dict]:
    stem = pdf_path.stem
    trimmed = stem.rstrip()
    kcbh, zwkcmc, err = extract_course_fields(pdf_path)
    college = college_tag(pdf_path, data_dir)
    key = course_key(kcbh, zwkcmc, rel_posix(pdf_path, root))

    conflicts = [p for p in stem_index.get(trimmed, []) if p.resolve() != pdf_path.resolve()]
    if not conflicts:
        new_stem = trimmed
        reason = "trim trailing space"
    else:
        conflict = conflicts[0]
        ck, cv = extract_course_fields(conflict)
        conflict_key = course_key(ck, cv, rel_posix(conflict, root))
        if key == conflict_key:
            new_stem = trimmed
            reason = f"trim; same course as {rel_posix(conflict, root)}"
        else:
            new_stem = propose_new_stem(
                trimmed,
                kcbh=kcbh,
                college=college,
                source_pdf=rel_posix(pdf_path, root),
                used=used_stems,
            )
            reason = f"conflict with {rel_posix(conflict, root)}; rename via kcbh/college"

    return new_stem, reason, {
        "source_pdf": rel_posix(pdf_path, root),
        "old_stem": stem,
        "new_stem": new_stem,
        "kcbh": kcbh,
        "zwkcmc": zwkcmc,
        "reason": reason,
        "extract_error": err,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim trailing spaces in PDF/raw stems.")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data_pdf")
    parser.add_argument("--data-md-dir", type=Path, default=DEFAULT_DATA_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnose" / "trailing_space_fix.json",
    )
    parser.add_argument(
        "--dedupe-json",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnose" / "pdf_stem_dedupe.json",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    raw_root = args.data_md_dir.resolve() / "_mineru_raw"
    root = PROJECT_ROOT
    dry_run = not args.apply
    stem_rename_map = load_stem_rename_map(args.dedupe_json.resolve())

    pdfs = list_pdf_files(data_dir)
    stem_index: dict[str, list[Path]] = {}
    for pdf in pdfs:
        stem_index.setdefault(pdf.stem, []).append(pdf)

    used_stems = {p.stem for p in pdfs}
    pdf_plans: list[dict] = []
    pdf_actions: list[str] = []

    trailing_pdfs = [p for p in pdfs if p.stem != p.stem.rstrip()]
    for pdf in trailing_pdfs:
        new_stem, _, plan = plan_pdf_rename(
            pdf, data_dir=data_dir, root=root, stem_index=stem_index, used_stems=used_stems
        )
        pdf_plans.append(plan)
        if new_stem == pdf.stem:
            continue
        dst = pdf.with_name(f"{new_stem}{PDF_SUFFIX}")
        if dst.exists() and dst.resolve() != pdf.resolve():
            pdf_actions.append(f"SKIP pdf (target exists): {plan['source_pdf']} -> {rel_posix(dst, root)}")
            continue
        if dry_run:
            pdf_actions.append(f"PDF {plan['source_pdf']} -> {rel_posix(dst, root)} ({plan['reason']})")
        else:
            pdf.rename(dst)
            used_stems.discard(pdf.stem)
            used_stems.add(new_stem)
            pdf_actions.append(f"PDF {plan['source_pdf']} -> {rel_posix(dst, root)}")
            raw_actions = rename_raw_tree(pdf.stem, new_stem, raw_root, dry_run=False)
            pdf_actions.extend(raw_actions)

    raw_plans: list[dict] = []
    raw_actions: list[str] = []
    if raw_root.is_dir():
        for d in sorted(raw_root.iterdir(), key=lambda p: p.name):
            if not d.is_dir() or d.name == d.name.rstrip():
                continue
            new_stem, reason = plan_raw_stem(
                d.name,
                used_stems=used_stems,
                raw_root=raw_root,
                stem_rename_map=stem_rename_map,
            )
            raw_plans.append({"old": d.name, "new": new_stem, "reason": reason})
            if dry_run:
                raw_actions.append(f"RAW {d.name!r} -> {new_stem!r} ({reason})")
                continue
            if new_stem == d.name:
                continue
            target = raw_root / new_stem
            if target.exists():
                if raw_has_md(new_stem, raw_root):
                    trimmed = d.name.rstrip()
                    if trimmed in used_stems and trimmed != new_stem:
                        raw_actions.append(
                            f"SKIP remove {d.name!r}: trimmed stem {trimmed!r} is a live PDF (Windows path alias risk)"
                        )
                    else:
                        trash = raw_root / f"_trash_{hashlib.sha1(d.name.encode()).hexdigest()[:8]}"
                        if trash.exists():
                            shutil.rmtree(trash, ignore_errors=True)
                        d.rename(trash)
                        shutil.rmtree(trash, ignore_errors=True)
                        raw_actions.append(
                            f"REMOVE orphan raw {d.name!r} (target {new_stem!r} already has .md)"
                        )
                else:
                    raw_actions.append(
                        f"SKIP raw {d.name!r} -> {new_stem!r} (target exists, no .md)"
                    )
            else:
                raw_actions.extend(rename_raw_tree(d.name, new_stem, raw_root, dry_run=False))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry-run" if dry_run else "apply",
        "trailing_pdfs": len(trailing_pdfs),
        "pdf_plans": pdf_plans,
        "pdf_actions": pdf_actions,
        "raw_plans": raw_plans,
        "raw_actions": raw_actions,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== trailing space fix ===")
    print(f"mode: {report['mode']}")
    print(f"trailing PDFs: {len(trailing_pdfs)}")
    for line in pdf_actions:
        print(line)
    for line in raw_actions:
        print(line)
    print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
