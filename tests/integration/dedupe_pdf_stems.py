"""解析重复或尾部空格冲突的 PDF stem，生成重命名方案。"""


from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PDF_SUFFIX = ".pdf"
PARSE_SUBDIRS = ("hybrid_auto", "auto", "vlm", "office")
COURSE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


def list_pdf_files(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录: {input_dir}")
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


def extract_course_fields(pdf_path: Path) -> tuple[str, str, str]:
    """返回 (kcbh, zwkcmc, error)；轻量扫描基础信息表。"""
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


def college_tag(pdf_path: Path, data_dir: Path) -> str:
    try:
        rel = pdf_path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return "unknown"
    if not rel.parts:
        return "unknown"
    first = rel.parts[0]
    match = re.match(r"【([^】]+)】", first)
    if match:
        tag = re.sub(r"\s+", "", match.group(1))
        return tag[:24] or "unknown"
    return re.sub(r"\s+", "", first)[:24] or "unknown"


def has_raw_md(stem: str, raw_root: Path | None) -> bool:
    if raw_root is None or not raw_root.is_dir():
        return False
    doc_dir = raw_root / stem
    if not doc_dir.is_dir():
        return False
    for sub in PARSE_SUBDIRS:
        md_path = doc_dir / sub / f"{stem}.md"
        if md_path.is_file():
            return True
    return False


@dataclass
class PdfMeta:
    path: Path
    source_pdf: str
    stem: str
    stem_repr: str
    kcbh: str
    zwkcmc: str
    zwkcmc_norm: str
    college: str
    has_raw: bool
    extract_error: str = ""

    @property
    def course_key(self) -> tuple[str, str]:
        if self.kcbh:
            return ("kcbh", self.kcbh)
        if self.zwkcmc_norm:
            return ("zwkcmc", self.zwkcmc_norm)
        return ("path", self.source_pdf)

    def score(self) -> tuple[int, int, int, str]:
        """分数越高越优先作为规范候选。"""
        return (
            1 if self.has_raw else 0,
            1 if self.stem == self.stem.rstrip() else 0,
            1 if self.kcbh else 0,
            self.source_pdf,
        )


@dataclass
class Action:
    source_pdf: str
    action: str
    reason: str
    canonical_pdf: str | None = None
    new_source_pdf: str | None = None
    course_key: str = ""


@dataclass
class ConflictGroup:
    group_key: str
    stems: list[str]
    paths: list[Path] = field(default_factory=list)
    members: list[PdfMeta] = field(default_factory=list)


class StemUnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, stem: str) -> None:
        self.parent.setdefault(stem, stem)

    def find(self, stem: str) -> str:
        self.parent.setdefault(stem, stem)
        while self.parent[stem] != stem:
            self.parent[stem] = self.parent[self.parent[stem]]
            stem = self.parent[stem]
        return stem

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def extract_meta(pdf_path: Path, *, root: Path, data_dir: Path, raw_root: Path | None) -> PdfMeta:
    source_pdf = rel_posix(pdf_path, root)
    stem = pdf_path.stem
    kcbh, zwkcmc, err = extract_course_fields(pdf_path)
    return PdfMeta(
        path=pdf_path,
        source_pdf=source_pdf,
        stem=stem,
        stem_repr=repr(stem),
        kcbh=kcbh,
        zwkcmc=zwkcmc,
        zwkcmc_norm=normalize_name(zwkcmc),
        college=college_tag(pdf_path, data_dir),
        has_raw=has_raw_md(stem, raw_root),
        extract_error=err,
    )


def build_conflict_groups(pdfs: list[Path]) -> list[ConflictGroup]:
    by_stem: dict[str, list[Path]] = defaultdict(list)
    for pdf in pdfs:
        by_stem[pdf.stem].append(pdf)

    uf = StemUnionFind()
    for stem in by_stem:
        uf.add(stem)
    stems = list(by_stem)
    for stem in stems:
        trimmed = stem.rstrip()
        for other in stems:
            if other.rstrip() == trimmed:
                uf.union(stem, other)

    grouped: dict[str, list[Path]] = defaultdict(list)
    for stem, paths in by_stem.items():
        grouped[uf.find(stem)].extend(paths)

    conflict_groups: list[ConflictGroup] = []
    for root_stem in sorted(grouped):
        paths = sorted(set(grouped[root_stem]), key=lambda p: rel_posix(p, PROJECT_ROOT))
        if len(paths) <= 1:
            continue
        stems_in_group = sorted({p.stem for p in paths}, key=lambda s: (s.rstrip(), s))
        conflict_groups.append(
            ConflictGroup(
                group_key=stems_in_group[0].rstrip(),
                stems=stems_in_group,
                paths=paths,
            )
        )
    return conflict_groups


def propose_new_stem(meta: PdfMeta, *, used_stems: set[str]) -> str:
    base = meta.stem.rstrip()
    candidates: list[str] = []
    if meta.kcbh:
        candidates.append(f"{base}__{meta.kcbh}")
    candidates.append(f"{base}__{meta.college}")
    digest = hashlib.sha1(meta.source_pdf.encode("utf-8")).hexdigest()[:8]
    candidates.append(f"{base}__{digest}")
    for candidate in candidates:
        if candidate not in used_stems:
            return candidate
    n = 2
    while True:
        candidate = f"{base}__dup{n}"
        if candidate not in used_stems:
            return candidate
        n += 1


def resolve_group(group: ConflictGroup, *, used_stems: set[str]) -> list[Action]:
    by_course: dict[tuple[str, str], list[PdfMeta]] = defaultdict(list)
    for meta in group.members:
        by_course[meta.course_key].append(meta)

    actions: list[Action] = []
    canonicals: list[PdfMeta] = []

    for course_key, members in by_course.items():
        members_sorted = sorted(members, key=lambda m: m.score(), reverse=True)
        canonical = members_sorted[0]
        canonicals.append(canonical)
        key_label = f"{course_key[0]}={course_key[1]}"
        for dup in members_sorted[1:]:
            actions.append(
                Action(
                    source_pdf=dup.source_pdf,
                    action="duplicate",
                    reason=f"same course as canonical ({key_label})",
                    canonical_pdf=canonical.source_pdf,
                    course_key=key_label,
                )
            )

    canonicals_sorted = sorted(canonicals, key=lambda m: m.score(), reverse=True)
    primary = canonicals_sorted[0]
    assigned_stems: dict[str, PdfMeta] = {primary.stem: primary}
    used_stems.add(primary.stem)

    actions.append(
        Action(
            source_pdf=primary.source_pdf,
            action="keep",
            reason="primary canonical in conflict group",
            course_key=f"{primary.course_key[0]}={primary.course_key[1]}",
        )
    )

    for meta in canonicals_sorted[1:]:
        key_label = f"{meta.course_key[0]}={meta.course_key[1]}"
        if meta.stem in assigned_stems or meta.stem.rstrip() in {s.rstrip() for s in assigned_stems}:
            new_stem = propose_new_stem(meta, used_stems=used_stems)
            new_path = meta.path.with_name(f"{new_stem}{PDF_SUFFIX}")
            used_stems.add(new_stem)
            actions.append(
                Action(
                    source_pdf=meta.source_pdf,
                    action="rename",
                    reason="different course but conflicting stem",
                    new_source_pdf=rel_posix(new_path, PROJECT_ROOT),
                    course_key=key_label,
                )
            )
            continue

        if meta.stem.endswith(" ") and meta.stem.rstrip() == primary.stem:
            new_stem = meta.stem.rstrip()
            if new_stem in used_stems:
                new_stem = propose_new_stem(meta, used_stems=used_stems)
            new_path = meta.path.with_name(f"{new_stem}{PDF_SUFFIX}")
            used_stems.add(new_stem)
            actions.append(
                Action(
                    source_pdf=meta.source_pdf,
                    action="rename",
                    reason="trim trailing space from filename",
                    new_source_pdf=rel_posix(new_path, PROJECT_ROOT),
                    course_key=key_label,
                )
            )
            continue

        assigned_stems[meta.stem] = meta
        used_stems.add(meta.stem)
        actions.append(
            Action(
                source_pdf=meta.source_pdf,
                action="keep",
                reason="unique stem within group",
                course_key=key_label,
            )
        )

    return actions


def apply_actions(actions: list[Action], *, root: Path) -> list[dict]:
    applied: list[dict] = []
    for act in actions:
        if act.action != "rename" or not act.new_source_pdf:
            continue
        src = (root / act.source_pdf).resolve()
        dst = (root / act.new_source_pdf).resolve()
        if not src.is_file():
            applied.append({"source_pdf": act.source_pdf, "status": "missing", "new_source_pdf": act.new_source_pdf})
            continue
        if dst.exists():
            applied.append({"source_pdf": act.source_pdf, "status": "target_exists", "new_source_pdf": act.new_source_pdf})
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        applied.append({"source_pdf": act.source_pdf, "status": "renamed", "new_source_pdf": act.new_source_pdf})
    return applied


def print_report(report: dict) -> None:
    summary = report["summary"]
    print("=== PDF stem dedupe ===")
    print(f"conflict groups:   {summary['conflict_groups']}")
    print(f"pdfs in groups:    {summary['pdfs_in_groups']}")
    print(f"keep:              {summary['keep']}")
    print(f"duplicate:         {summary['duplicate']}")
    print(f"rename:            {summary['rename']}")
    print(f"extract errors:    {summary['extract_errors']}")
    if report.get("applied"):
        print(f"applied renames:   {summary.get('applied_renames', 0)}")

    if report["rename"]:
        print("\n--- rename ---")
        for row in report["rename"]:
            print(f"  {row['source_pdf']}")
            print(f"    -> {row['new_source_pdf']}  ({row['reason']})")

    if report["duplicate"]:
        print(f"\n--- duplicate ({len(report['duplicate'])}) ---")
        for row in report["duplicate"][:20]:
            print(f"  {row['source_pdf']}")
            print(f"    canonical: {row['canonical_pdf']}")
        if len(report["duplicate"]) > 20:
            print(f"  ... and {len(report['duplicate']) - 20} more")

    if report["extract_errors"]:
        print(f"\n--- extract errors ({len(report['extract_errors'])}) ---")
        for row in report["extract_errors"][:10]:
            print(f"  {row['source_pdf']}: {row['error']}")


def run(
    *,
    data_dir: Path,
    raw_root: Path | None,
    apply: bool,
    out_path: Path,
) -> dict:
    root = PROJECT_ROOT
    pdfs = list_pdf_files(data_dir)
    all_stems = {p.stem for p in pdfs}
    used_stems = set(all_stems)

    groups = build_conflict_groups(pdfs)

    for group in groups:
        group.members = [
            extract_meta(p, root=root, data_dir=data_dir, raw_root=raw_root)
            for p in group.paths
        ]

    all_actions: list[Action] = []
    for group in groups:
        all_actions.extend(resolve_group(group, used_stems=used_stems))

    by_type: dict[str, list[dict]] = defaultdict(list)
    extract_errors: list[dict] = []
    for act in all_actions:
        row = {
            "source_pdf": act.source_pdf,
            "action": act.action,
            "reason": act.reason,
            "canonical_pdf": act.canonical_pdf,
            "new_source_pdf": act.new_source_pdf,
            "course_key": act.course_key,
        }
        by_type[act.action].append(row)

    for group in groups:
        for meta in group.members:
            if meta.extract_error:
                extract_errors.append({"source_pdf": meta.source_pdf, "error": meta.extract_error})

    applied: list[dict] = []
    if apply:
        applied = apply_actions(all_actions, root=root)

    group_reports = []
    for group in groups:
        group_reports.append(
            {
                "group_key": group.group_key,
                "stems": group.stems,
                "members": [
                    {
                        "source_pdf": m.source_pdf,
                        "stem_repr": m.stem_repr,
                        "kcbh": m.kcbh,
                        "zwkcmc": m.zwkcmc,
                        "college": m.college,
                        "has_raw": m.has_raw,
                        "course_key": f"{m.course_key[0]}={m.course_key[1]}",
                        "extract_error": m.extract_error,
                    }
                    for m in group.members
                ],
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": rel_posix(data_dir, root),
        "raw_root": rel_posix(raw_root, root) if raw_root else None,
        "mode": "apply" if apply else "dry-run",
        "summary": {
            "conflict_groups": len(groups),
            "pdfs_in_groups": sum(len(g.members) for g in groups),
            "keep": len(by_type["keep"]),
            "duplicate": len(by_type["duplicate"]),
            "rename": len(by_type["rename"]),
            "extract_errors": len(extract_errors),
            "applied_renames": sum(1 for row in applied if row.get("status") == "renamed"),
        },
        "groups": group_reports,
        "keep": by_type["keep"],
        "duplicate": by_type["duplicate"],
        "rename": by_type["rename"],
        "extract_errors": extract_errors,
        "applied": applied,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report)
    print(f"\nJSON report: {out_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedupe/rename conflicting PDF stems by kcbh/zwkcmc.")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data_pdf")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=PROJECT_ROOT / "data_md" / "_mineru_raw",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnose" / "pdf_stem_dedupe.json",
    )
    parser.add_argument("--apply", action="store_true", help="Apply rename actions (default: dry-run)")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    raw_root = args.raw_root.resolve() if args.raw_root else None
    if not data_dir.is_dir():
        print(f"ERROR: data dir not found: {data_dir}", file=sys.stderr)
        return 1

    run(data_dir=data_dir, raw_root=raw_root, apply=args.apply, out_path=args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
