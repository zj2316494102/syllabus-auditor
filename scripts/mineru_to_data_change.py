"""Run MinerU pipeline on PDFs and organize output into data_change/."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from syllabus_auditor.core.db.connection import get_project_root  # noqa: E402
from syllabus_auditor.loaders.syllabus_pdf import list_pdf_files  # noqa: E402

DATA_CHANGE = PROJECT_ROOT / "data_change"
RAW_ROOT = DATA_CHANGE / "_mineru_raw"
DIRS = {
    "md": DATA_CHANGE / "md",
    "json": DATA_CHANGE / "json",
    "pdf": DATA_CHANGE / "pdf",
    "image": DATA_CHANGE / "image",
}
MANIFEST = DATA_CHANGE / "manifest" / "index.jsonl"
LOG_FILE = DATA_CHANGE / "batch.log"


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ensure_dirs() -> None:
    for path in (*DIRS.values(), RAW_ROOT, MANIFEST.parent):
        path.mkdir(parents=True, exist_ok=True)


def stem_of(pdf_path: Path) -> str:
    return pdf_path.stem


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_done_stems() -> set[str]:
    done: set[str] = set()
    if not MANIFEST.exists():
        return done
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") == "success":
            done.add(row.get("stem", ""))
    return done


def count_successes() -> int:
    if not MANIFEST.exists():
        return 0
    count = 0
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") == "success":
            count += 1
    return count


def append_manifest(record: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def find_auto_dir(stem: str) -> Path | None:
    candidate = RAW_ROOT / stem / "auto"
    if candidate.is_dir():
        return candidate
    matches = list(RAW_ROOT.glob(f"*/auto/{stem}.md"))
    if matches:
        return matches[0].parent
    loose = list(RAW_ROOT.rglob("auto"))
    for auto in loose:
        if (auto / f"{stem}.md").exists():
            return auto
    return None


def organize_output(stem: str, source_pdf: Path) -> dict:
    auto_dir = find_auto_dir(stem)
    if auto_dir is None:
        raise FileNotFoundError(f"MinerU auto output not found for stem={stem!r}")

    root = get_project_root()
    record: dict = {
        "stem": stem,
        "source_pdf": rel_posix(source_pdf, root),
        "status": "success",
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "md": None,
        "json": {},
        "pdf": {},
        "images": [],
    }

    md_src = auto_dir / f"{stem}.md"
    if md_src.exists():
        dst = DIRS["md"] / f"{stem}.md"
        shutil.move(str(md_src), str(dst))
        record["md"] = rel_posix(dst, root)

    for src in sorted(auto_dir.glob("*.json")):
        dst = DIRS["json"] / src.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))
        key = src.stem.removeprefix(f"{stem}_") if src.stem.startswith(stem) else src.stem
        record["json"][key] = rel_posix(dst, root)

    for src in sorted(auto_dir.glob("*.pdf")):
        dst = DIRS["pdf"] / src.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))
        key = src.stem.removeprefix(f"{stem}_") if src.stem.startswith(stem) else src.stem
        record["pdf"][key] = rel_posix(dst, root)

    images_dir = auto_dir / "images"
    if images_dir.is_dir():
        for src in sorted(images_dir.iterdir()):
            if not src.is_file():
                continue
            dst_name = f"{stem}__{src.name}"
            dst = DIRS["image"] / dst_name
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            record["images"].append(rel_posix(dst, root))
        try:
            images_dir.rmdir()
        except OSError:
            pass

    # Remove empty MinerU tree for this document.
    doc_root = auto_dir.parent
    shutil.rmtree(doc_root, ignore_errors=True)

    return record


def run_mineru(pdf_path: Path, *, force_cpu: bool) -> None:
    cmd = [
        "mineru",
        "-p",
        str(pdf_path),
        "-o",
        str(RAW_ROOT),
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
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-4000:]
        raise RuntimeError(f"mineru failed (code={result.returncode}): {tail}")


def is_already_done(stem: str) -> bool:
    md_ok = (DIRS["md"] / f"{stem}.md").exists()
    middle_ok = (DIRS["json"] / f"{stem}_middle.json").exists()
    return md_ok and middle_ok


def process_pdf(pdf_path: Path, *, force_cpu: bool, skip_existing: bool) -> str:
    stem = stem_of(pdf_path)
    root = get_project_root()

    if skip_existing and is_already_done(stem):
        return "skipped"

    log(f"START {rel_posix(pdf_path, root)}")
    started = time.time()
    try:
        run_mineru(pdf_path, force_cpu=force_cpu)
        record = organize_output(stem, pdf_path)
        record["elapsed_sec"] = round(time.time() - started, 1)
        record["mineru_backend"] = "pipeline"
        append_manifest(record)
        log(f"OK {stem} ({record['elapsed_sec']}s)")
        return "success"
    except Exception as exc:
        append_manifest(
            {
                "stem": stem,
                "source_pdf": rel_posix(pdf_path, root),
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "parsed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        log(f"FAIL {stem}: {exc}")
        return "failed"


def organize_existing_raw() -> int:
    """Organize any leftover _mineru_raw outputs without re-running mineru."""
    count = 0
    for auto_md in RAW_ROOT.glob("*/auto/*.md"):
        stem = auto_md.stem
        pdf_guess = None
        for pdf in list_pdf_files(get_project_root() / "data"):
            if pdf.stem == stem:
                pdf_guess = pdf
                break
        if pdf_guess is None:
            continue
        if is_already_done(stem):
            continue
        record = organize_output(stem, pdf_guess)
        record["status"] = "success"
        record["parsed_at"] = datetime.now(timezone.utc).isoformat()
        record["mineru_backend"] = "pipeline"
        record["note"] = "organized from existing _mineru_raw"
        append_manifest(record)
        count += 1
        log(f"ORGANIZED existing raw output for {stem}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch MinerU -> data_change organizer")
    parser.add_argument("--pdf", type=Path, default=None, help="Process a single PDF")
    parser.add_argument("--limit", type=int, default=0, help="Max PDF count (0 = all)")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    parser.add_argument("--force-cpu", action="store_true", help="Force CPU pipeline")
    parser.add_argument("--organize-only", action="store_true", help="Only organize _mineru_raw")
    parser.add_argument(
        "--max-success",
        type=int,
        default=0,
        help="Stop after this many successful documents (0 = no limit)",
    )
    args = parser.parse_args()

    ensure_dirs()
    log("=== batch start ===")

    if args.organize_only:
        n = organize_existing_raw()
        log(f"=== organize-only done: {n} ===")
        return 0

    if args.pdf:
        pdfs = [args.pdf.resolve()]
    else:
        pdfs = list_pdf_files(get_project_root() / "data")
        if args.limit > 0:
            pdfs = pdfs[: args.limit]

    stats = {"success": 0, "failed": 0, "skipped": 0}
    log(f"PDF count: {len(pdfs)}")
    if args.max_success > 0:
        log(f"max_success: {args.max_success} (already {count_successes()})")

    for i, pdf_path in enumerate(pdfs, 1):
        if args.max_success > 0 and count_successes() >= args.max_success:
            log(f"=== reached max_success={args.max_success}, stopping ===")
            break
        log(f"[{i}/{len(pdfs)}] {pdf_path.name}")
        outcome = process_pdf(pdf_path, force_cpu=args.force_cpu, skip_existing=args.skip_existing)
        stats[outcome] += 1

    log(f"=== batch done: {stats} | total_success={count_successes()} ===")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
