"""User-summary "stories" — small narrative insights derived from a user's
records. Each builder takes the user's daily records and returns a Story (or
None if it doesn't apply). Add a new insight by writing a builder and listing it
in STORY_BUILDERS; the route/template render whatever comes back.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field

import pandas as pd

from app.optimization.service import cap_change_date, tier_caps, weeks_in_month


@dataclass
class Story:
    key: str
    title: str
    headline: str                       # main narrative sentence
    detail: str = ""                    # secondary line
    tone: str = "info"                  # info | notable | alert
    icon: str = "•"                     # small glyph shown on the card
    metric: str = ""                    # optional big number/percent
    dates: list = field(default_factory=list)  # [{"date": "...", "note": "..."}]

    def to_dict(self) -> dict:
        return asdict(self)


def _user_daily(user_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the per-user records to one row context with a parsed date."""
    if user_df is None or user_df.empty:
        return pd.DataFrame()
    cols = {"date_partition", "usage_credits"}
    if not cols.issubset(user_df.columns):
        return pd.DataFrame()
    df = user_df.copy()
    df["_date"] = pd.to_datetime(df["date_partition"], errors="coerce")
    df = df.dropna(subset=["_date"])
    if df.empty:
        return pd.DataFrame()
    df["_credits"] = pd.to_numeric(df["usage_credits"], errors="coerce").fillna(0.0)
    return df


def _month_pace_stats(
    df: pd.DataFrame, year: int, month: int, tier_config: dict, tier_name: str,
    as_of: pd.Timestamp | None = None,
) -> dict | None:
    """Core per-month pace math, shared by the latest-month story and the
    full month-by-month history. `as_of` caps the month at a given date (for
    the current/latest month, which may be in progress); omit for past months."""
    month_df = df[(df["_date"].dt.year == year) & (df["_date"].dt.month == month)]
    if month_df.empty:
        return None

    days_in_month = calendar.monthrange(year, month)[1]
    last_day = as_of if as_of is not None else pd.Timestamp(year, month, days_in_month)

    # Budget for the month = the effective weekly cap for this month's regime,
    # times the weeks in the month. Post-switch (monthly) this equals the monthly
    # cap; pre-switch (weekly) it's the flat weekly cap across the month.
    wim = weeks_in_month(year, month)
    last_week_monday = (last_day - pd.Timedelta(days=int(last_day.weekday()))).normalize()
    caps = tier_caps(tier_config, week_start=last_week_monday)
    weekly_cap = caps.get(tier_name) or caps.get("Baseline") or 0.0
    allowance = float(weekly_cap) * wim
    if allowance <= 0:
        return None

    change = cap_change_date(tier_config)
    weekly_regime = change is not None and last_week_monday < change
    cap_word = "weekly-cap budget" if weekly_regime else "monthly cap"

    daily = month_df.groupby(month_df["_date"].dt.normalize())["_credits"].sum().sort_index()
    spend = float(daily.sum())
    pct = spend / allowance
    days_elapsed = int(last_day.day)
    month_label = f"{calendar.month_name[month]} {year}"

    cumulative = daily.cumsum()
    milestones = []
    for frac in (0.25, 0.50, 0.75, 1.00):
        hit = cumulative[cumulative >= allowance * frac]
        if not hit.empty:
            d = hit.index[0]
            milestones.append({
                "date": str(d.date()),
                "note": f"crossed {frac:.0%} of budget (day {d.day})",
            })

    day_hit_cap = None
    over = cumulative[cumulative >= allowance]
    if not over.empty:
        day_hit_cap = int(over.index[0].day)

    return {
        "year": year, "month": month, "month_label": month_label,
        "spend": spend, "allowance": allowance, "pct": pct,
        "days_in_month": days_in_month, "days_elapsed": days_elapsed,
        "day_hit_cap": day_hit_cap, "milestones": milestones,
        "weekly_regime": weekly_regime, "cap_word": cap_word,
    }


def story_month_pace(df: pd.DataFrame, tier_config: dict, tier_name: str) -> Story | None:
    """How much of the period budget the user spent in their most recent month,
    and how quickly they got there. Respects the weekly->monthly switch date:
    months before the switch are measured against the weekly-cap budget."""
    if df.empty:
        return None
    latest = df["_date"].max()
    stats = _month_pace_stats(df, latest.year, latest.month, tier_config, tier_name, as_of=latest)
    if stats is None:
        return None

    pct = stats["pct"]
    tone = "alert" if pct >= 1.0 else ("notable" if pct >= 0.80 else "info")
    regime_note = f", {tier_name} tier" + (" · weekly caps" if stats["weekly_regime"] else "")
    headline = (
        f"Spent {pct:.0%} of the {stats['cap_word']} in {stats['month_label']} "
        f"({stats['spend']:,.0f} / {stats['allowance']:,.0f} credits)."
    )
    if stats["day_hit_cap"] is not None:
        detail = (f"Burned through the whole {stats['month_label']} budget by day "
                   f"{stats['day_hit_cap']} of {stats['days_in_month']}.")
    else:
        detail = f"Through day {stats['days_elapsed']} of {stats['days_in_month']}{regime_note}."

    return Story(
        key="month_pace",
        title="This month's pace",
        headline=headline,
        detail=detail,
        tone=tone,
        icon="⏱",
        metric=f"{pct:.0%}",
        dates=stats["milestones"],
    )


def build_month_pace_history(user_df: pd.DataFrame, tier_config: dict, tier_name: str) -> list[dict]:
    """Pace stats for every month present in the user's records (not just the
    latest), oldest first — the "big stories" tab's monthly-pace table."""
    df = _user_daily(user_df)
    if df.empty:
        return []
    latest = df["_date"].max()
    months = sorted({(ts.year, ts.month) for ts in df["_date"]})
    out = []
    for year, month in months:
        is_latest = (year, month) == (latest.year, latest.month)
        stats = _month_pace_stats(
            df, year, month, tier_config, tier_name,
            as_of=latest if is_latest else None,
        )
        if stats is None:
            continue
        pct = stats["pct"]
        out.append({
            "month_label": stats["month_label"],
            "spend": stats["spend"],
            "allowance": stats["allowance"],
            "pct": pct,
            "pct_label": f"{pct:.0%}",
            "cap_word": stats["cap_word"],
            "weekly_regime": stats["weekly_regime"],
            "day_hit_cap": stats["day_hit_cap"],
            "days_in_month": stats["days_in_month"],
            "is_latest": is_latest,
            "tone": "alert" if pct >= 1.0 else ("notable" if pct >= 0.80 else "info"),
        })
    out.reverse()  # most recent month first, for the table
    return out


def story_activity(df: pd.DataFrame, reference_date: object = None) -> Story | None:
    """Recency of activity: how long since the user was last active, measured
    against the most recent date in the whole dataset (not today's calendar)."""
    if df.empty:
        return None
    user_last = df["_date"].max().normalize()
    ref = pd.Timestamp(reference_date).normalize() if reference_date is not None \
        and not pd.isna(reference_date) else user_last
    if ref < user_last:
        ref = user_last
    gap = int((ref - user_last).days)

    recent = df[df["_date"] >= ref - pd.Timedelta(days=13)]
    recent_days = recent.groupby(recent["_date"].dt.normalize())["_credits"].sum().sort_index()
    active_days_14 = int(recent_days.shape[0])

    if gap >= 30:
        tone, icon = "alert", "🔴"
        headline = f"No activity in {gap} days — last active {user_last.date()}."
        detail = f"Latest data is {ref.date()}; this user has likely gone quiet."
    elif gap >= 14:
        tone, icon = "notable", "🟠"
        headline = f"Quiet lately — last active {gap} days ago ({user_last.date()})."
        detail = f"Active on {active_days_14} of the last 14 data-days."
    else:
        tone, icon = "info", "🟢"
        headline = f"Active recently — last used {user_last.date()}."
        detail = f"Active on {active_days_14} of the last 14 data-days."

    dates = [
        {"date": str(d.date()), "note": f"{c:,.0f} cr"}
        for d, c in list(recent_days.items())[-10:]
    ]
    return Story(
        key="activity",
        title="Activity",
        headline=headline,
        detail=detail,
        tone=tone,
        icon=icon,
        metric=(f"{gap}d" if gap else "now"),
        dates=dates,
    )


def story_pro_then_codex(df: pd.DataFrame) -> Story | None:
    """Days where the user used both Pro prompts and Codex — a signal of working
    a hard problem across tools in a single day."""
    if df.empty:
        return None
    raw_type = df.get("usage_type")
    parsed = df.get("usage_type_parsed_type")
    if raw_type is None and parsed is None:
        return None

    is_pro = df["usage_type"].astype(str).str.contains("pro", case=False, na=False) \
        if "usage_type" in df.columns else pd.Series(False, index=df.index)
    is_codex = df["usage_type_parsed_type"].astype(str).str.lower().eq("codex") \
        if "usage_type_parsed_type" in df.columns else pd.Series(False, index=df.index)
    if not bool(is_pro.any()) or not bool(is_codex.any()):
        return None

    d = df.copy()
    d["_d"] = d["_date"].dt.normalize()
    d["_is_pro"] = is_pro
    d["_is_codex"] = is_codex
    d["_pro_cr"] = d["_credits"].where(is_pro, 0.0)
    d["_codex_cr"] = d["_credits"].where(is_codex, 0.0)
    by_day = d.groupby("_d").agg(
        pro=("_is_pro", "any"),
        codex=("_is_codex", "any"),
        pro_credits=("_pro_cr", "sum"),
        codex_credits=("_codex_cr", "sum"),
    )
    both = by_day[by_day["pro"] & by_day["codex"]].sort_index()
    if both.empty:
        return None

    dates = [
        {
            "date": str(day.date()),
            "note": f"Pro {row['pro_credits']:,.0f} cr · Codex {row['codex_credits']:,.0f} cr",
        }
        for day, row in both.iterrows()
    ]
    n = len(dates)
    return Story(
        key="pro_then_codex",
        title="Pro + Codex, same day",
        headline=f"Used Pro prompts and Codex on the same day {n} time{'s' if n != 1 else ''}.",
        detail="Often a sign of tackling a hard problem across tools — click to see the dates.",
        tone="notable",
        icon="🧠",
        metric=str(n),
        dates=dates,
    )


STORY_ALERT_METRICS = {
    "inactive": "No activity in N days",
    "burst_cap": "Burned a full monthly cap within N days",
    "pro_codex": "Used Pro + Codex the same day within N days",
}


def _story_alert(rid: str, level: str, title: str, detail: str, email: str | None) -> dict:
    return {
        "id": f"story:{rid}",
        "level": level,
        "title": title,
        "detail": detail,
        "link_endpoint": "analytics.user_summary" if email else "analytics.user_cards_page",
        "link_args": {"email": email} if email else {},
    }


def evaluate_story_rules(
    df: pd.DataFrame,
    rules: list,
    monthly_cap_by_email: dict | None = None,
    default_monthly_cap: float = 400.0,
    reference_date: object = None,
) -> list[dict]:
    """Turn story-based alert rules into nav-bell alert dicts.

    Rule shape: {id, name, metric, email (blank=all users), days, enabled}.
    Metrics: 'inactive', 'burst_cap', 'pro_codex'.
    """
    out: list[dict] = []
    if df is None or df.empty:
        return out
    if not {"date_partition", "usage_credits", "email"}.issubset(df.columns):
        return out

    d = df.copy()
    d["_date"] = pd.to_datetime(d["date_partition"], errors="coerce")
    d = d.dropna(subset=["_date"])
    if d.empty:
        return out
    d["_credits"] = pd.to_numeric(d["usage_credits"], errors="coerce").fillna(0.0)
    d["_email"] = d["email"].astype(str).str.strip().str.lower()
    ref = pd.Timestamp(reference_date).normalize() if reference_date is not None \
        and not pd.isna(reference_date) else d["_date"].max().normalize()
    caps = monthly_cap_by_email or {}

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        metric = str(rule.get("metric", "inactive"))
        name = rule.get("name") or "Story alert"
        rid = rule.get("id", "story")
        target = str(rule.get("email", "") or "").strip().lower()
        days = max(int(rule.get("days", 30) or 30), 1)
        sub = d[d["_email"] == target] if target else d
        if sub.empty:
            continue

        if metric == "inactive":
            last_by = sub.groupby("_email")["_date"].max().dt.normalize()
            gap = (ref - last_by).dt.days
            stale = gap[gap >= days]
            if target and not stale.empty:
                out.append(_story_alert(rid, "warning", name,
                    f"{target} has no activity in {int(stale.iloc[0])} days "
                    f"(last {last_by.iloc[0].date()}).", target))
            elif not target and int(stale.shape[0]):
                out.append(_story_alert(rid, "info", name,
                    f"{int(stale.shape[0]):,} user(s) inactive {days}+ days.", None))

        elif metric == "burst_cap":
            hits = []
            for em, g in sub.groupby("_email"):
                daily = g.groupby(g["_date"].dt.normalize())["_credits"].sum().sort_index()
                if daily.empty:
                    continue
                peak = float(daily.rolling(f"{days}D").sum().max())
                cap = float(caps.get(em, default_monthly_cap))
                if cap > 0 and peak >= cap:
                    hits.append((em, peak, cap))
            if target and hits:
                em, peak, cap = hits[0]
                out.append(_story_alert(rid, "warning", name,
                    f"{em} spent {peak:,.0f} cr (>= {cap:,.0f} monthly cap) within {days} days.", em))
            elif not target and hits:
                out.append(_story_alert(rid, "warning", name,
                    f"{len(hits):,} user(s) burned a full monthly cap within {days} days.", None))

        elif metric == "pro_codex":
            cutoff = ref - pd.Timedelta(days=days - 1)
            w = sub[sub["_date"] >= cutoff]
            if w.empty:
                continue
            is_pro = w["usage_type"].astype(str).str.contains("pro", case=False, na=False) \
                if "usage_type" in w.columns else pd.Series(False, index=w.index)
            is_cx = w["usage_type_parsed_type"].astype(str).str.lower().eq("codex") \
                if "usage_type_parsed_type" in w.columns else pd.Series(False, index=w.index)
            ww = w.assign(_d=w["_date"].dt.normalize(), _pro=is_pro, _cx=is_cx)
            by = ww.groupby(["_email", "_d"]).agg(pro=("_pro", "any"), cx=("_cx", "any"))
            both = by[by["pro"] & by["cx"]]
            users = both.reset_index()["_email"].nunique()
            if target and users:
                n = int(both.reset_index()["_email"].eq(target).sum())
                out.append(_story_alert(rid, "info", name,
                    f"{target} used Pro + Codex on the same day {n} time(s) in {days} days.", target))
            elif not target and users:
                out.append(_story_alert(rid, "info", name,
                    f"{int(users):,} user(s) used Pro + Codex the same day within {days} days.", None))
    return out


def build_user_stories(
    user_df: pd.DataFrame,
    tier_config: dict,
    tier_name: str,
    reference_date: object = None,
) -> list[dict]:
    """Return the list of applicable stories (as dicts) for a user."""
    df = _user_daily(user_df)
    if df.empty:
        return []
    candidates = [
        story_month_pace(df, tier_config, tier_name),
        story_activity(df, reference_date),
        story_pro_then_codex(df),
    ]
    return [s.to_dict() for s in candidates if s]
