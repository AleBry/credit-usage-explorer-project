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


# The three outlier "views". Each is a way of asking "who/what crossed a credit
# threshold in a window" — and matches the three alert-rule metrics so a
# notification can deep-link straight to the matching view.
OUTLIER_VIEWS = {
    "per_user_window": "Users over the window",
    "per_user_day": "User-days over the limit",
    "per_record": "Single prompts over the limit",
}


def _resolve_window(dates, lookback_days, start_date, end_date):
    """Return (mask, start_str, end_str) for an explicit date range or a rolling lookback."""
    max_date = dates.max()
    if start_date or end_date:
        start = pd.to_datetime(start_date, errors="coerce")
        end = pd.to_datetime(end_date, errors="coerce")
        if pd.isna(start):
            start = dates.min()
        if pd.isna(end):
            end = max_date
        return (dates >= start) & (dates <= end), str(start.date()), str(end.date())
    cutoff = max_date - pd.Timedelta(days=lookback_days)
    return dates >= cutoff, str(cutoff.date()), str(max_date.date())


def compute_outliers(
    df: pd.DataFrame,
    metric: str = "per_user_window",
    threshold: float = 100,
    lookback_days: int = 7,
    start_date: str = "",
    end_date: str = "",
    usage_type_filter: str = "",
    model_filter: str = "",
    top_n: int = 200,
) -> tuple[list[dict], int, str, str, list[dict]]:
    """Compute one of the outlier views.

    Returns (rows, count, window_start, window_end, columns) where ``columns``
    is an ordered list of {label, key, fmt, align} the template renders generically.
    """
    if metric not in OUTLIER_VIEWS:
        metric = "per_user_window"
    cols = _columns_for(metric)
    blank: tuple = ([], 0, "", "", cols)

    if df is None or df.empty or "usage_credits" not in df.columns or "date_partition" not in df.columns:
        return blank
    dates = pd.to_datetime(df["date_partition"], errors="coerce")
    if not dates.notna().any():
        return blank

    mask, start_s, end_s = _resolve_window(dates, lookback_days, start_date, end_date)
    recent = df[mask]
    if usage_type_filter and "usage_type_parsed_type" in recent.columns:
        recent = recent[recent["usage_type_parsed_type"] == usage_type_filter]
    if model_filter and "usage_type_model" in recent.columns:
        recent = recent[recent["usage_type_model"] == model_filter]
    if recent.empty:
        return [], 0, start_s, end_s, cols

    recent = recent.copy()
    recent["_c"] = pd.to_numeric(recent["usage_credits"], errors="coerce").fillna(0.0)
    name_col = "name" if "name" in recent.columns else None
    user_col = "email" if "email" in recent.columns else None
    gcols = [c for c in [name_col, user_col] if c]

    if metric == "per_record":
        flagged = recent[recent["_c"] > threshold]
        count = len(flagged)
        sel = flagged.sort_values("_c", ascending=False).head(top_n)
        rows = [{
            "name": (r.get(name_col) if name_col else "") or "",
            "email": (r.get(user_col) if user_col else "") or "",
            "date": str(r.get("date_partition", "")),
            "usage_type": r.get("usage_type_parsed_type", "") or r.get("usage_type", "") or "",
            "model": r.get("usage_type_model", "") or "",
            "credits": float(r["_c"]),
        } for _, r in sel.iterrows()]
        return rows, count, start_s, end_s, cols

    if metric == "per_user_day" and gcols:
        recent["_date"] = pd.to_datetime(recent["date_partition"], errors="coerce").dt.date
        day = recent.groupby(gcols + ["_date"], as_index=False).agg(
            credits=("_c", "sum"), records=("_c", "count"),
        )
        flagged = day[day["credits"] > threshold]
        count = len(flagged)
        sel = flagged.sort_values("credits", ascending=False).head(top_n)
        rows = [{
            "name": (r.get(name_col) if name_col else "") or "",
            "email": (r.get(user_col) if user_col else "") or "",
            "date": str(r["_date"]),
            "records": int(r["records"]),
            "credits": float(r["credits"]),
        } for _, r in sel.iterrows()]
        return rows, count, start_s, end_s, cols

    # per_user_window (default)
    if not gcols:
        return [], 0, start_s, end_s, cols
    grp = recent.groupby(gcols, as_index=False).agg(
        credits=("_c", "sum"), records=("_c", "count"),
    )
    flagged = grp[grp["credits"] > threshold]
    count = len(flagged)
    sel = flagged.sort_values("credits", ascending=False).head(top_n)
    if "usage_type_model" in recent.columns and not sel.empty:
        keys = sel[gcols]
        sub = recent.merge(keys, on=gcols, how="inner")
        top_model = (
            sub.groupby(gcols + ["usage_type_model"], as_index=False)
            .agg(mc=("_c", "sum")).sort_values("mc", ascending=False)
            .drop_duplicates(subset=gcols)
        )
        sel = sel.merge(top_model[gcols + ["usage_type_model"]], on=gcols, how="left")
    else:
        sel = sel.assign(usage_type_model="")
    rows = [{
        "name": (r.get(name_col) if name_col else "") or "",
        "email": (r.get(user_col) if user_col else "") or "",
        "model": r.get("usage_type_model", "") or "",
        "records": int(r["records"]),
        "credits": float(r["credits"]),
    } for _, r in sel.iterrows()]
    return rows, count, start_s, end_s, cols


def _columns_for(metric: str) -> list[dict]:
    user_cols = [
        {"label": "User", "key": "name", "fmt": "text"},
        {"label": "Email", "key": "email", "fmt": "muted"},
    ]
    if metric == "per_record":
        return user_cols + [
            {"label": "Date", "key": "date", "fmt": "text"},
            {"label": "Usage type", "key": "usage_type", "fmt": "muted"},
            {"label": "Model", "key": "model", "fmt": "muted"},
            {"label": "Credits", "key": "credits", "fmt": "credits", "align": "end"},
        ]
    if metric == "per_user_day":
        return user_cols + [
            {"label": "Date", "key": "date", "fmt": "text"},
            {"label": "Records", "key": "records", "fmt": "int", "align": "end"},
            {"label": "Credits", "key": "credits", "fmt": "credits", "align": "end"},
        ]
    return user_cols + [
        {"label": "Top Model", "key": "model", "fmt": "muted"},
        {"label": "Records", "key": "records", "fmt": "int", "align": "end"},
        {"label": "Credits", "key": "credits", "fmt": "credits", "align": "end"},
    ]


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
