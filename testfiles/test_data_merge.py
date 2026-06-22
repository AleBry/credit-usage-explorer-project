"""Tests for the order-independent usage-data merge.

Run from the webapp_v3 directory:
    .venv\\Scripts\\python.exe testfiles\\test_data_merge.py

Exercises app.shared.data_merge against:
  1. Synthetic mock files with overlapping date ranges.
  2. The real anonymized exports in data/test_anon/ (if present), proving every
     upload order yields an identical merged result through the real DataStore.

No absolute/sensitive paths are hard-coded; everything resolves from the repo
root relative to this file.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.shared.data_merge import merge_usage_data, normalize_date_partition  # noqa: E402

MOCK_DIR = ROOT / "data" / "test_mock"
ANON_DIR = ROOT / "data" / "test_anon"

USERS = [f"user_{i:03d}" for i in range(1, 6)]
USAGE_TYPES = [
    ("chat.completion.5.reasoning", 40.0),
    ("api.codex_fast_gpt_5_text_output_v_1", 12.5),
    ("chat.completion.4o", 5.0),
]


def _rows(start: date, end: date) -> list[dict]:
    rows, d = [], start
    while d <= end:
        for i, uid in enumerate(USERS):
            for usage_type, credits in USAGE_TYPES:
                factor = 1.0 + (d.toordinal() % 7) * 0.05
                rows.append({
                    "date_partition": str(d),
                    "account_id": "acct_test",
                    "account_user_id": uid,
                    "email": f"{uid}@bnl.gov",
                    "name": f"User {i+1}",
                    "public_id": f"pub_{uid}",
                    "usage_type": usage_type,
                    "usage_credits": round(credits * factor, 4),
                    "usage_quantity": round(credits * factor, 2),
                    "usage_units": "counts",
                })
        d += timedelta(days=1)
    return rows


def _fingerprint(df: pd.DataFrame) -> tuple:
    dates = pd.to_datetime(df["date_partition"], errors="coerce")
    return (
        len(df),
        dates.dt.normalize().nunique(),
        str(dates.min().date()),
        str(dates.max().date()),
        round(pd.to_numeric(df["usage_credits"], errors="coerce").sum(), 2),
    )


def _passed(cond: bool) -> str:
    return "PASS" if cond else "FAIL"


def generate_mock_files() -> dict[str, Path]:
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    specs = {
        "mock_1_mar_to_jun1.csv":   (date(2026, 3, 1), date(2026, 6, 1)),
        "mock_2_mar_to_jun7.csv":   (date(2026, 3, 1), date(2026, 6, 7)),
        "mock_3_jun1_to_jun22.csv": (date(2026, 6, 1), date(2026, 6, 22)),
    }
    paths = {}
    print("=" * 64)
    print("Generating mock files")
    print("=" * 64)
    for name, (start, end) in specs.items():
        df = pd.DataFrame(_rows(start, end))
        p = MOCK_DIR / name
        df.to_csv(p, index=False)
        paths[name] = p
        print(f"  {name:28} {len(df):>5,} rows  {start} -> {end}")
    return paths


def test_mock_order_independence(paths: dict[str, Path]) -> bool:
    print("\n" + "=" * 64)
    print("Mock data: all upload orders must match")
    print("=" * 64)
    frames = {k: pd.read_csv(p) for k, p in paths.items()}
    fps = []
    for order in permutations(paths.keys()):
        merged = None
        for name in order:
            merged = merge_usage_data(merged, frames[name])
        fp = _fingerprint(merged)
        fps.append(fp)
        short = " -> ".join(n.split("_")[1] for n in order)
        print(f"  {short:18} rows={fp[0]:,} dates={fp[1]} credits={fp[4]:,.2f}")
    ok = all(fp == fps[0] for fp in fps)
    # Union of dates Mar1..Jun22 == 114
    exp_dates = (date(2026, 6, 22) - date(2026, 3, 1)).days + 1
    ok_dates = fps[0][1] == exp_dates
    print(f"\n  all orders identical : [{_passed(ok)}]")
    print(f"  unique dates == {exp_dates} : [{_passed(ok_dates)}]  (got {fps[0][1]})")
    return ok and ok_dates


def test_conflict_resolution() -> bool:
    print("\n" + "=" * 64)
    print("Conflict resolution: larger credits wins, order-independent")
    print("=" * 64)
    base = pd.DataFrame(_rows(date(2026, 3, 1), date(2026, 3, 2)))
    conflict = base.copy()
    # Same keys, inflate credits on the second file
    conflict["usage_credits"] = conflict["usage_credits"] * 2
    fp_ab = _fingerprint(merge_usage_data(base, conflict))
    fp_ba = _fingerprint(merge_usage_data(conflict, base))
    same = fp_ab == fp_ba
    # Winner must equal the larger (doubled) total, and row count unchanged
    expected_rows = len(base)
    rows_ok = fp_ab[0] == expected_rows
    doubled_total = round(pd.to_numeric(conflict["usage_credits"]).sum(), 2)
    credit_ok = abs(fp_ab[4] - doubled_total) < 1e-6
    print(f"  A->B == B->A          : [{_passed(same)}]")
    print(f"  no double-count (rows={expected_rows}) : [{_passed(rows_ok)}]  (got {fp_ab[0]})")
    print(f"  kept larger credits   : [{_passed(credit_ok)}]  ({fp_ab[4]:,.2f} == {doubled_total:,.2f})")
    return same and rows_ok and credit_ok


def test_mixed_date_formats() -> bool:
    print("\n" + "=" * 64)
    print("Mixed date formats (US vs ISO) normalize and merge cleanly")
    print("=" * 64)
    iso = pd.DataFrame(_rows(date(2026, 6, 1), date(2026, 6, 3)))
    us = pd.DataFrame(_rows(date(2026, 6, 2), date(2026, 6, 5)))
    # Rewrite this file's dates as US-style M/D/YYYY (no zero padding)
    us["date_partition"] = pd.to_datetime(us["date_partition"]).map(
        lambda d: f"{d.month}/{d.day}/{d.year}"
    )
    merged = merge_usage_data(iso, us)
    fmt_ok = merged["date_partition"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$").all()
    dates_ok = pd.to_datetime(merged["date_partition"]).dt.normalize().nunique() == 5  # Jun1..Jun5
    print(f"  stored all ISO        : [{_passed(fmt_ok)}]")
    print(f"  union dates == 5      : [{_passed(dates_ok)}]")
    return fmt_ok and dates_ok


def test_real_files_through_store() -> bool | None:
    files = sorted(ANON_DIR.glob("*.csv")) if ANON_DIR.exists() else []
    if len(files) < 2:
        print("\n(real anonymized files not present — skipping store round-trip test)")
        return None
    from app.shared.data_store import DataStore

    print("\n" + "=" * 64)
    print(f"Real files through DataStore + disk ({len(files)} files, all orders)")
    print("=" * 64)
    tmp = ROOT / "data" / "_merge_test_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    derived = {"usage_type_parsed_type", "usage_type_model", "usage_type_date",
               "usage_type_medium", "usage_type_io"}
    raw = {f.name: pd.read_csv(f, encoding="utf-8-sig") for f in files}

    fps = []
    for order in permutations(raw.keys()):
        current = tmp / "current.csv"
        if current.exists():
            current.unlink()
        store = None
        for name in order:
            existing = None
            if store is not None and not store.data.df.empty:
                existing = store.data.df.drop(
                    columns=[c for c in derived if c in store.data.df.columns], errors="ignore"
                )
            merged = merge_usage_data(existing, raw[name])
            merged.to_csv(current, index=False)
            store = DataStore(current) if store is None else (store.reload(current) or store)
        fp = _fingerprint(store.data.df)
        fps.append(fp)
        print(f"  {' -> '.join(n[:14] for n in order)}\n      rows={fp[0]:,} dates={fp[1]} "
              f"range={fp[2]}..{fp[3]} credits={fp[4]:,.2f}")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    ok = all(fp == fps[0] for fp in fps)
    print(f"\n  all orders identical  : [{_passed(ok)}]")
    return ok


def main() -> int:
    results = []
    paths = generate_mock_files()
    results.append(("mock order independence", test_mock_order_independence(paths)))
    results.append(("conflict resolution", test_conflict_resolution()))
    results.append(("mixed date formats", test_mixed_date_formats()))
    real = test_real_files_through_store()
    if real is not None:
        results.append(("real files via store", real))

    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    all_ok = True
    for name, ok in results:
        all_ok &= ok
        print(f"  {name:28} [{_passed(ok)}]")
    print("=" * 64)
    print("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
