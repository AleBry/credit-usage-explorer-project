"""Ad-hoc diagnostics for usage-data files in data/test_anon/.

Reports each file's true date range, date format, the natural record key's
uniqueness, and any cross-file value conflicts on shared keys. Useful when a new
batch of exports behaves unexpectedly.

Run from the webapp_v3 directory:
    .venv\\Scripts\\python.exe testfiles\\diagnose_data.py

Paths resolve from the repo root relative to this file — nothing sensitive is
hard-coded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.shared.data_merge import normalize_date_partition, record_key  # noqa: E402

ANON_DIR = ROOT / "data" / "test_anon"


def main() -> int:
    files = sorted(ANON_DIR.glob("*.csv")) if ANON_DIR.exists() else []
    if not files:
        print(f"No CSV files found in {ANON_DIR.relative_to(ROOT)} — nothing to diagnose.")
        return 0

    frames: dict[str, pd.DataFrame] = {}
    print("=" * 70)
    print("PER-FILE SUMMARY")
    print("=" * 70)
    for f in files:
        df = normalize_date_partition(pd.read_csv(f, encoding="utf-8-sig"))
        frames[f.name] = df
        d = pd.to_datetime(df["date_partition"], errors="coerce")
        key = record_key(df.columns)
        dup = df.duplicated(subset=key).sum() if key else "n/a"
        print(f"\n  {f.name}")
        print(f"    rows           : {len(df):,}")
        print(f"    date range     : {d.min().date()} -> {d.max().date()}  ({d.nunique()} unique)")
        print(f"    record key     : {key}")
        print(f"    key duplicates : {dup}")

    print("\n" + "=" * 70)
    print("CROSS-FILE SHARED-KEY VALUE CONFLICTS")
    print("=" * 70)
    names = list(frames)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = frames[names[i]], frames[names[j]]
            key = record_key(a.columns)
            if not key or "usage_credits" not in a.columns:
                continue
            ga = a.groupby(key)["usage_credits"].sum()
            gb = b.groupby(key)["usage_credits"].sum()
            common = ga.index.intersection(gb.index)
            if len(common) == 0:
                print(f"\n  {names[i][:30]} vs {names[j][:30]}: no shared keys")
                continue
            conflicts = ((ga.loc[common] - gb.loc[common]).abs() > 1e-9).sum()
            print(f"\n  {names[i][:30]} vs {names[j][:30]}")
            print(f"    shared keys        : {len(common):,}")
            print(f"    value conflicts    : {conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
