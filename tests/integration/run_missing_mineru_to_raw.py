"""对缺失 MinerU 输出的 PDF 批量跑 MinerU 并写入 _mineru_raw。"""


from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_MD = PROJECT_ROOT / "data_md"
DEFAULT_MINERU = Path(r"C:\Users\Administrator\.conda\envs\course\Scripts\mineru.exe")
PARSE_SUBDIRS = ("hybrid_auto", "auto", "vlm", "office")


def log(msg: str, log_file: Path) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def has_raw_md(stem: str, raw_root: Path) -> bool:
    for sub in PARSE_SUBDIRS:
        md_path = raw_root / stem / sub / f"{stem}.md"
        if md_path.is_file():
            return True
    return False


def load_missing(coverage_path: Path) -> list[dict]:
    if not coverage_path.is_file():
        raise FileNotFoundError(f"coverage report not found: {coverage_path}")
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    rows: list[dict] = []
    for row in report.get("missing", []):
        key = row.get("source_pdf", "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def run_mineru(
    pdf_path: Path,
    raw_root: Path,
    mineru_cmd: Path,
    *,
    force_cpu: bool,
) -> tuple[int, str]:
    cmd = [
        str(mineru_cmd),
        "-p",
        str(pdf_path),
        "-o",
        str(raw_root),
        "-b",
        "pipeline",
        "-l",
        "ch",
        "-m",
        "auto",
        "-f",
        "false",
        "-t",
        "true",
    ]
    env = None
    if force_cpu:
        import os

        env = os.environ.copy()
        env["MINERU_DEVICE_MODE"] = "cpu"
        env["CUDA_VISIBLE_DEVICES"] = ""

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    tail = (result.stderr or result.stdout or "")[-3000:]
    return result.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU pipeline -> _mineru_raw for missing PDFs")
    parser.add_argument("--data-md-dir", type=Path, default=DEFAULT_DATA_MD)
    parser.add_argument(
        "--coverage",
        type=Path,
        default=PROJECT_ROOT / "docs" / "diagnose" / "mineru_raw_coverage.json",
    )
    parser.add_argument("--mineru-cmd", type=Path, default=DEFAULT_MINERU)
    parser.add_argument("--limit", type=int, default=0, help="Max runs (0 = all missing)")
    parser.add_argument("--force-cpu", action="store_true")
    args = parser.parse_args()

    data_md = args.data_md_dir.resolve()
    raw_root = data_md / "_mineru_raw"
    log_file = data_md / "batch_missing_raw.log"
    mineru_cmd = args.mineru_cmd.resolve()

    if not mineru_cmd.is_file():
        print(f"ERROR: mineru not found: {mineru_cmd}", file=sys.stderr)
        return 1

    raw_root.mkdir(parents=True, exist_ok=True)
    missing = load_missing(args.coverage.resolve())
    if args.limit > 0:
        missing = missing[: args.limit]

    stats = {"success": 0, "skipped": 0, "failed": 0}
    failures: list[dict] = []

    log(f"=== missing mineru batch start | count={len(missing)} ===", log_file)

    for i, row in enumerate(missing, 1):
        source_pdf = row["source_pdf"]
        stem = row["stem"]
        pdf_path = (PROJECT_ROOT / source_pdf).resolve()
        if not pdf_path.is_file():
            log(f"[{i}/{len(missing)}] SKIP missing file {source_pdf}", log_file)
            stats["failed"] += 1
            failures.append({"source_pdf": source_pdf, "error": "file not found"})
            continue
        if has_raw_md(stem, raw_root):
            log(f"[{i}/{len(missing)}] SKIP has raw {stem}", log_file)
            stats["skipped"] += 1
            continue

        log(f"[{i}/{len(missing)}] START {source_pdf}", log_file)
        started = time.time()
        code, tail = run_mineru(pdf_path, raw_root, mineru_cmd, force_cpu=args.force_cpu)
        elapsed = round(time.time() - started, 1)

        if code == 0 and has_raw_md(stem, raw_root):
            log(f"OK {stem} ({elapsed}s)", log_file)
            stats["success"] += 1
        else:
            log(f"FAIL {stem} ({elapsed}s) code={code}", log_file)
            stats["failed"] += 1
            failures.append({"source_pdf": source_pdf, "stem": stem, "code": code, "tail": tail})

    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "failures": failures,
    }
    out = PROJECT_ROOT / "docs" / "diagnose" / "mineru_missing_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"=== done {stats} ===", log_file)
    print(f"\nRun summary: {stats}")
    print(f"Details: {out}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
