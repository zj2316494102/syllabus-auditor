"""审计 data_pdf 与 _mineru_raw 的文件名匹配覆盖率，找出缺失 MinerU 输出的 PDF。"""


from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PARSE_SUBDIRS = ("hybrid_auto", "auto", "vlm", "office")
PDF_SUFFIX = ".pdf"


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


@dataclass(frozen=True)
class RawMatch:
    stem: str
    raw_dir: Path | None
    parse_subdir: str | None
    md_path: Path | None

    @property
    def status(self) -> str:
        if self.md_path is not None:
            return "has_md"
        if self.parse_subdir is not None:
            return "dir_only"
        if self.raw_dir is not None:
            return "empty_dir"
        return "missing"


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def find_raw_match(stem: str, raw_root: Path) -> RawMatch:
    """按 PDF stem 精确匹配 _mineru_raw 目录（空格也计入匹配）。"""
    raw_dir = raw_root / stem
    if not raw_dir.is_dir():
        return RawMatch(stem=stem, raw_dir=None, parse_subdir=None, md_path=None)

    for sub in PARSE_SUBDIRS:
        parse_dir = raw_dir / sub
        if not parse_dir.is_dir():
            continue
        md_path = parse_dir / f"{stem}.md"
        if md_path.is_file():
            return RawMatch(stem=stem, raw_dir=raw_dir, parse_subdir=sub, md_path=md_path)
        return RawMatch(stem=stem, raw_dir=raw_dir, parse_subdir=sub, md_path=None)

    return RawMatch(stem=stem, raw_dir=raw_dir, parse_subdir=None, md_path=None)


def collect_raw_stems(raw_root: Path) -> set[str]:
    if not raw_root.is_dir():
        return set()
    return {p.name for p in raw_root.iterdir() if p.is_dir()}


def audit_coverage(data_dir: Path, raw_root: Path) -> dict:
    root = PROJECT_ROOT
    pdfs = list_pdf_files(data_dir)
    pdf_stems = [p.stem for p in pdfs]

    stem_to_pdfs: dict[str, list[str]] = {}
    for pdf in pdfs:
        stem_to_pdfs.setdefault(pdf.stem, []).append(rel_posix(pdf, root))

    duplicate_stems = {stem: paths for stem, paths in stem_to_pdfs.items() if len(paths) > 1}

    entries: list[dict] = []
    status_counts: dict[str, int] = {}
    for pdf in pdfs:
        match = find_raw_match(pdf.stem, raw_root)
        status_counts[match.status] = status_counts.get(match.status, 0) + 1
        entries.append(
            {
                "source_pdf": rel_posix(pdf, root),
                "stem": pdf.stem,
                "stem_repr": repr(pdf.stem),
                "status": match.status,
                "raw_dir": rel_posix(match.raw_dir, root) if match.raw_dir else None,
                "parse_subdir": match.parse_subdir,
                "md": rel_posix(match.md_path, root) if match.md_path else None,
            }
        )

    pdf_stem_set = set(pdf_stems)
    raw_stems = collect_raw_stems(raw_root)
    orphan_raw = sorted(raw_stems - pdf_stem_set)

    missing = [e for e in entries if e["status"] == "missing"]
    no_md = [e for e in entries if e["status"] in {"dir_only", "empty_dir"}]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": rel_posix(data_dir, root),
        "raw_root": rel_posix(raw_root, root),
        "summary": {
            "pdf_total": len(pdfs),
            "unique_stems": len(pdf_stem_set),
            "raw_dir_total": len(raw_stems),
            "has_md": status_counts.get("has_md", 0),
            "dir_only": status_counts.get("dir_only", 0),
            "empty_dir": status_counts.get("empty_dir", 0),
            "missing": status_counts.get("missing", 0),
            "duplicate_stem_count": len(duplicate_stems),
            "orphan_raw_dir_count": len(orphan_raw),
        },
        "duplicate_stems": duplicate_stems,
        "missing": missing,
        "incomplete": no_md,
        "orphan_raw_dirs": orphan_raw,
        "entries": entries,
    }


def print_report(report: dict) -> None:
    summary = report["summary"]
    print("=== MinerU _mineru_raw coverage ===")
    print(f"data_pdf PDFs:   {summary['pdf_total']} ({summary['unique_stems']} unique stems)")
    print(f"_mineru_raw dirs:  {summary['raw_dir_total']}")
    print(f"has .md:           {summary['has_md']}")
    print(f"dir, no .md:       {summary['dir_only']}")
    print(f"empty raw dir:     {summary['empty_dir']}")
    print(f"missing in raw:    {summary['missing']}")
    print(f"duplicate stems:   {summary['duplicate_stem_count']}")
    print(f"orphan raw dirs:   {summary['orphan_raw_dir_count']}")

    if report["duplicate_stems"]:
        print("\n--- duplicate stems in data_pdf/ (exact match required separately) ---")
        for stem, paths in sorted(report["duplicate_stems"].items(), key=lambda x: x[0]):
            print(f"  {stem!r}: {len(paths)} files")
            for path in paths:
                print(f"    - {path}")

    if report["missing"]:
        print(f"\n--- missing ({len(report['missing'])}) ---")
        for row in report["missing"]:
            print(f"  {row['source_pdf']}  stem={row['stem_repr']}")

    if report["incomplete"]:
        print(f"\n--- raw dir exists but no .md ({len(report['incomplete'])}) ---")
        for row in report["incomplete"]:
            print(f"  [{row['status']}] {row['source_pdf']}  stem={row['stem_repr']}")

    if report["orphan_raw_dirs"]:
        print(f"\n--- orphan _mineru_raw dirs ({len(report['orphan_raw_dirs'])}) ---")
        for stem in report["orphan_raw_dirs"]:
            print(f"  {stem!r}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit which data_pdf/ PDFs have matching _mineru_raw output (exact stem)."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data_pdf",
        help="PDF input directory (default: project data_pdf/)",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=PROJECT_ROOT / "data_md" / "_mineru_raw",
        help="MinerU raw output root (default: data_md/_mineru_raw)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnose" / "mineru_raw_coverage.json",
        help="JSON report output path",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    raw_root = args.raw_root.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: data dir not found: {data_dir}", file=sys.stderr)
        return 1
    if not raw_root.is_dir():
        print(f"ERROR: raw root not found: {raw_root}", file=sys.stderr)
        return 1

    report = audit_coverage(data_dir, raw_root)
    print_report(report)

    out_path = args.out.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON report: {out_path}")

    return 0 if report["summary"]["missing"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
