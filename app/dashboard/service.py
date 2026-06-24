from __future__ import annotations

import json

import pandas as pd


def compute_summary_metrics(df: pd.DataFrame) -> dict:
    total_credits = float(df["usage_credits"].sum()) if "usage_credits" in df.columns else 0.0
    unique_users = int(df["email"].nunique()) if "email" in df.columns else 0
    total_records = len(df)
    usage_types = int(df["usage_type"].nunique()) if "usage_type" in df.columns else 0

    date_min = date_max = None
    active_users_recent = 0
    if "date_partition" in df.columns:
        dates = pd.to_datetime(df["date_partition"], errors="coerce").dropna()
        if not dates.empty:
            date_min = str(dates.min().date())
            date_max = str(dates.max().date())
            recent_cutoff = dates.max() - pd.Timedelta(days=7)
            recent_mask = pd.to_datetime(df["date_partition"], errors="coerce") >= recent_cutoff
            recent_df = df[recent_mask]
            if "usage_credits" in recent_df.columns and "email" in recent_df.columns:
                active_users_recent = int(
                    recent_df[recent_df["usage_credits"] > 0]["email"].nunique()
                )

    return {
        "total_credits": total_credits,
        "unique_users": unique_users,
        "total_records": total_records,
        "usage_types": usage_types,
        "date_min": date_min,
        "date_max": date_max,
        "active_users_recent": active_users_recent,
    }


def compute_weekly_trend(df: pd.DataFrame) -> str:
    if "date_partition" not in df.columns or "usage_credits" not in df.columns:
        return "[]"
    wdf = df[["date_partition", "usage_credits", "email"]].copy()
    wdf["_date"] = pd.to_datetime(wdf["date_partition"], errors="coerce")
    wdf = wdf.dropna(subset=["_date"])
    wdf["week"] = wdf["_date"] - pd.to_timedelta(wdf["_date"].dt.dayofweek, unit="D")
    weekly = (
        wdf.groupby("week", as_index=False)
        .agg(total_credits=("usage_credits", "sum"), unique_users=("email", "nunique"))
        .sort_values("week")
    )
    return json.dumps([
        {
            "week": str(row["week"].date()),
            "total_credits": round(float(row["total_credits"]), 2),
            "unique_users": int(row["unique_users"]),
        }
        for _, row in weekly.iterrows()
    ])
