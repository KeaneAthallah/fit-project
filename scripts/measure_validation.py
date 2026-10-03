"""Measured before/after comparison of validation error counts (requirement #30).

Run:  python scripts/measure_validation.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_config, set_config  # noqa: E402
from app.pipeline.orchestrator import discover, process_batch  # noqa: E402
from app.storage.database import get_engine, get_session_factory  # noqa: E402
from app.storage.repository import Repository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    set_config(cfg)
    discover(cfg, limit=args.limit)
    batch = process_batch(cfg, force=args.force, limit=args.limit)

    engine = get_engine(cfg)
    Session = get_session_factory(engine)
    with Session() as session:
        repo = Repository(session)
        docs = [d for d in repo.all_documents() if d.page_count]
        vals = repo.all_validations()

    print()
    print("=" * 50)
    print("MEASURED VALIDATION RESULTS (this run)")
    print("=" * 50)
    counts = Counter(v.status for v in vals)
    total = sum(counts.values()) or 1
    for k in ("VALID", "WARNING", "ERROR", "NOT_APPLICABLE", "NOT_FOUND",
              "INCOMPLETE", "REVIEW_REQUIRED", "UNMAPPED"):
        if counts.get(k):
            print(f"  {k}: {counts[k]} ({counts[k] * 100 // total}%)")
    print()
    print(f"Documents processed : {len(docs)}")
    print(f"Real ERROR rows     : {counts.get('ERROR', 0)}")
    print()
    print("Before (old logs)   -> After (measured):")
    before = {"2024.pdf": 126, "2020.pdf": 100, "2021.pdf": 94, "2023.pdf": 129}
    for d in docs[:8]:
        dv = Counter(v.status for v in vals if v.document_id == d.id)
        b = before.get(d.filename)
        if b:
            print(f"  {d.filename}: {b} errors -> {dv.get('ERROR', 0)} errors, "
                  f"{dv.get('VALID', 0)} valid, {dv.get('NOT_APPLICABLE', 0)} n/a")
    print("=" * 50)


if __name__ == "__main__":
    main()
