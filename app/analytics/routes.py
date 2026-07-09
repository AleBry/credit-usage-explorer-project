from __future__ import annotations

import json
from urllib.parse import urlencode

import pandas as pd
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.dashboard.service import DEFAULT_RECORD_COLUMNS, build_record_view, record_column_meta
from app.shared.chart_data import usage_type_weekly_json
from app.shared.csv_export import csv_response
from app.shared.data_store import CreditUsageData
from app.shared.outliers import OUTLIER_VIEWS, compute_outliers
from .service import Leaderboards


def create_analytics_blueprint(services) -> Blueprint:
    store = services.store
    config_svc = services.config_svc
    bp = Blueprint("analytics", __name__, template_folder="templates", url_prefix="")
    max_result_limit = 10_000

    def data() -> CreditUsageData:
        return store.data

    def result_limit(name: str, default: int, min_value: int = 1) -> int:
        try:
            value = int(request.args.get(name, default) or default)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(value, max_result_limit))

    def _leaderboard_filtered_df(d: CreditUsageData) -> pd.DataFrame:
        usage_type_filter = request.args.get("usage_type_filter", "")
        model_filter = request.args.get("model_filter", "")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        min_credits = request.args.get("min_credits", "").strip()
        max_credits = request.args.get("max_credits", "").strip()
        zero_credits = request.args.get("zero_credits", "")

        df = d.df.copy()
        df = d.filter_by_date(df, start_date, end_date)

        if usage_type_filter and "usage_type_parsed_type" in df.columns:
            df = df[df["usage_type_parsed_type"] == usage_type_filter]
        if model_filter and "usage_type_model" in df.columns:
            df = df[df["usage_type_model"] == model_filter]

        return d.filter_by_credits(df, min_credits, max_credits, zero_credits)

    def _basic_user_rows(d: CreditUsageData) -> list[dict]:
        name_query = request.args.get("name_query", "").strip()
        email_query = request.args.get("email_query", "").strip()
        date_field = request.args.get("date_field", "date_partition")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        top_n = result_limit("top_n", 50)
        min_credits = request.args.get("min_credits", "").strip()
        max_credits = request.args.get("max_credits", "").strip()
        zero_credits = request.args.get("zero_credits", "")

        df = d.df.copy()
        if name_query and "name" in df.columns:
            df = df[df["name"].astype(str).str.contains(name_query, case=False, na=False, regex=False)]
        if email_query and "email" in df.columns:
            df = df[df["email"].astype(str).str.contains(email_query, case=False, na=False, regex=False)]
        if date_field and (start_date or end_date):
            df = d.filter_by_date(df, start_date, end_date, col=date_field)
        df = d.filter_by_credits(df, min_credits, max_credits, zero_credits)

        group_cols = [c for c in ["name", "email"] if c in df.columns]
        if not group_cols:
            return []
        df = df.copy()
        if "usage_units" in df.columns and "usage_quantity" in df.columns:
            df["tokens_qty"] = df["usage_quantity"].where(df["usage_units"] == "tokens", 0.0)
            df["counts_qty"] = df["usage_quantity"].where(df["usage_units"] == "counts", 0.0)
            df["duration_qty"] = df["usage_quantity"].where(df["usage_units"] == "duration_s", 0.0)
        else:
            df["tokens_qty"] = df["counts_qty"] = df["duration_qty"] = 0.0
        agg = (
            df.groupby(group_cols)
            .agg(
                rows=("usage_credits", "count"),
                total_credits=("usage_credits", "sum"),
                total_quantity=("usage_quantity", "sum"),
                total_tokens=("tokens_qty", "sum"),
                total_counts=("counts_qty", "sum"),
                total_duration_s=("duration_qty", "sum"),
            )
            .reset_index()
            .sort_values("total_credits", ascending=False)
            .head(top_n)
        )
        return agg.to_dict(orient="records")

    @bp.route("/leaderboard", methods=["GET"])
    def leaderboard_page() -> str:
        d = data()
        active_tab = request.args.get("active_tab", "users")
        usage_type_filter = request.args.get("usage_type_filter", "")
        model_filter = request.args.get("model_filter", "")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        top_n = result_limit("top_n", 25, 5)
        min_credits = request.args.get("min_credits", "").strip()
        max_credits = request.args.get("max_credits", "").strip()
        zero_credits = request.args.get("zero_credits", "")

        df = _leaderboard_filtered_df(d)

        all_usage_types = (
            sorted(d.df["usage_type_parsed_type"].dropna().unique().tolist())
            if "usage_type_parsed_type" in d.df.columns else []
        )
        all_models = (
            sorted(d.df["usage_type_model"].dropna().unique().tolist())
            if "usage_type_model" in d.df.columns else []
        )

        lb = Leaderboards(df, top_n)
        lb_users = lb.by_user()
        lb_users_by_type = lb.by_user_type()
        lb_models = lb.by_model()
        lb_usage_types = lb.by_usage_type()
        lb_biggest_single = lb.biggest_single()
        lb_daily = lb.daily()
        lb_weekly = lb.weekly()
        lb_monthly = lb.monthly()
        lb_yearly = lb.yearly()

        base_params = {k: v for k, v in {
            "usage_type_filter": usage_type_filter,
            "model_filter": model_filter,
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n if top_n != 25 else "",
            "min_credits": min_credits,
            "max_credits": max_credits,
            "zero_credits": zero_credits,
        }.items() if v}

        return render_template(
            "leaderboard.html",
            active_tab=active_tab,
            usage_type_filter=usage_type_filter,
            model_filter=model_filter,
            start_date=start_date,
            end_date=end_date,
            top_n=top_n,
            max_result_limit=max_result_limit,
            all_usage_types=all_usage_types,
            all_models=all_models,
            lb_users=lb_users,
            lb_users_by_type=lb_users_by_type,
            lb_models=lb_models,
            lb_usage_types=lb_usage_types,
            lb_biggest_single=lb_biggest_single,
            lb_daily=lb_daily,
            lb_weekly=lb_weekly,
            lb_monthly=lb_monthly,
            lb_yearly=lb_yearly,
            base_query=urlencode(base_params),
            min_credits=min_credits,
            max_credits=max_credits,
            zero_credits=zero_credits,
        )

    @bp.route("/leaderboard/export.csv", methods=["GET"])
    def leaderboard_export_csv() -> object:
        d = data()
        active_tab = request.args.get("active_tab", "users")
        top_n = result_limit("top_n", 25, 5)
        lb = Leaderboards(_leaderboard_filtered_df(d), top_n)

        boards: dict[str, tuple[list[dict], list[tuple[str, str]]]] = {
            "users": (
                lb.by_user(),
                [
                    ("Rank", "_rank"), ("Name", "name"), ("Email", "email"),
                    ("Credits", "total_credits"), ("Records", "rows"),
                    ("Token/msg tk", "total_tokens"), ("Token/msg msg", "total_messages"),
                ],
            ),
            "users_by_type": (
                lb.by_user_type(),
                [
                    ("Rank", "_rank"), ("Name", "name"), ("Email", "email"),
                    ("Usage Type", "usage_type_parsed_type"), ("Credits", "total_credits"),
                    ("Records", "rows"),
                ],
            ),
            "models": (
                lb.by_model(),
                [
                    ("Rank", "_rank"), ("Model", "usage_type_model"),
                    ("Credits", "total_credits"), ("Records", "rows"),
                    ("Unique users", "unique_users"),
                ],
            ),
            "usage_types": (
                lb.by_usage_type(),
                [
                    ("Rank", "_rank"), ("Usage Type", "usage_type_parsed_type"),
                    ("Credits", "total_credits"), ("Records", "rows"),
                    ("Unique users", "unique_users"),
                ],
            ),
            "biggest_single": (
                lb.biggest_single(),
                [
                    ("Rank", "_rank"), ("Name", "name"), ("Email", "email"),
                    ("Credits", "usage_credits"), ("Usage Type", "usage_type_parsed_type"),
                    ("Model", "usage_type_model"), ("IO", "usage_type_io"),
                    ("(Token/msg)", "usage_quantity"), ("Units", "usage_units"),
                    ("Date", "date_partition"), ("Raw usage type", "usage_type"),
                ],
            ),
            "yearly": (
                lb.yearly(),
                [
                    ("Rank", "_rank"), ("Year", "year"), ("Credits", "total_credits"),
                    ("Records", "rows"), ("Unique users", "unique_users"),
                ],
            ),
            "monthly": (
                lb.monthly(),
                [
                    ("Rank", "_rank"), ("Month", "month"), ("Credits", "total_credits"),
                    ("Records", "rows"), ("Unique users", "unique_users"),
                ],
            ),
            "weekly": (
                lb.weekly(),
                [
                    ("Rank", "_rank"), ("Week of", "week"), ("Credits", "total_credits"),
                    ("Records", "rows"), ("Unique users", "unique_users"),
                ],
            ),
            "daily": (
                lb.daily(),
                [
                    ("Rank", "_rank"), ("Date", "date_partition"), ("Credits", "total_credits"),
                    ("Records", "rows"), ("Unique users", "unique_users"),
                ],
            ),
        }
        rows, columns = boards.get(active_tab, boards["users"])
        export_rows = []
        for idx, row in enumerate(rows, start=1):
            row = dict(row)
            row["_rank"] = idx
            export_rows.append({label: row.get(key, "") for label, key in columns})
        date_range = (
            f"{request.args.get('start_date', '')}_to_{request.args.get('end_date', '')}"
            if request.args.get("start_date", "") or request.args.get("end_date", "") else ""
        )
        credit_range = (
            f"{request.args.get('min_credits', '').strip() or '0'}_to_"
            f"{request.args.get('max_credits', '').strip() or 'max'}"
            if request.args.get("min_credits", "").strip() or request.args.get("max_credits", "").strip()
            else ""
        )
        return csv_response(pd.DataFrame(export_rows, columns=[label for label, _ in columns]),
                            f"leaderboard_{active_tab}.csv", filters=[
                                ("type", request.args.get("usage_type_filter", "")),
                                ("model", request.args.get("model_filter", "")),
                                ("dates", date_range),
                                ("credits", credit_range),
                                ("zero", "only" if request.args.get("zero_credits") == "1" else ""),
                                ("top", top_n if top_n != 25 else ""),
                            ])

    @bp.route("/user-summary", methods=["GET"])
    def user_summary() -> str:
        d = data()
        name = request.args.get("name", "")
        email = request.args.get("email", "")
        date_field = request.args.get("date_field", "date_partition")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        sort_by = request.args.get("sort_by", "")
        sort_order = request.args.get("sort_order", "asc")
        active_tab = request.args.get("active_tab", "overview")
        is_form_submission = bool(request.args.get("fs", ""))
        models_explicitly_set = bool(request.args.get("mfs", ""))
        min_credits = request.args.get("min_credits", "").strip()
        max_credits = request.args.get("max_credits", "").strip()
        zero_credits = request.args.get("zero_credits", "")

        df = d.df.copy()
        if name and "name" in df.columns:
            df = df[df["name"].astype(str).str.contains(name.strip(), case=False, na=False, regex=False)]
        if email and "email" in df.columns:
            df = df[df["email"].astype(str).str.contains(email.strip(), case=False, na=False, regex=False)]
        if date_field and (start_date or end_date):
            df = d.filter_by_date(df, start_date, end_date, col=date_field)
        df = d.filter_by_credits(df, min_credits, max_credits, zero_credits)

        # Records scoped to this user only (before usage-type/model filters), so
        # the narrative "stories" see the full picture across tools.
        user_scope_df = df.copy()

        user_types = (
            sorted(df["usage_type_parsed_type"].dropna().unique().tolist())
            if "usage_type_parsed_type" in df.columns else []
        )
        requested_types = request.args.getlist("filter_types")
        filter_types = user_types if not is_form_submission else (requested_types or user_types)
        if "usage_type_parsed_type" in df.columns:
            df = df[df["usage_type_parsed_type"].isin(filter_types)]

        user_models = (
            sorted(df["usage_type_model"].dropna().unique().tolist())
            if "usage_type_model" in df.columns else []
        )
        requested_models = request.args.getlist("filter_models")
        if not is_form_submission:
            filter_models = user_models
        elif not models_explicitly_set:
            filter_models = user_models
        else:
            valid = [m for m in requested_models if m in user_models]
            filter_models = valid if (not requested_models or valid) else user_models
        if "usage_type_model" in df.columns:
            df = df[df["usage_type_model"].isin(filter_models)]

        if sort_by and sort_by in df.columns:
            df = df.sort_values(by=sort_by, ascending=(sort_order == "asc"))

        hidden_by_default = {"name", "email", "account_id", "account_user_id", "public_id"}
        selected_fields = request.args.getlist("selected_fields")
        if not selected_fields:
            selected_fields = [
                col for col in DEFAULT_RECORD_COLUMNS
                if col in df.columns and col not in hidden_by_default
            ]
            display_columns = selected_fields
        else:
            display_columns = [c for c in selected_fields if c in df.columns]

        record_columns, rows_data = build_record_view(df, display_columns)
        total_credits = float(df["usage_credits"].sum()) if "usage_credits" in df.columns else 0.0

        totals_by_unit: dict = {}
        if "usage_units" in df.columns and "usage_quantity" in df.columns:
            for unit in ["tokens", "counts", "duration_s"]:
                totals_by_unit[unit] = float(
                    df.loc[df["usage_units"] == unit, "usage_quantity"].sum()
                )

        def make_summary(group_col: str) -> list[dict]:
            if group_col not in df.columns or len(df) == 0 or "usage_credits" not in df.columns:
                return []
            result = df.groupby(group_col, as_index=False).agg(
                total_credits=("usage_credits", "sum")
            )
            result["rows"] = df.groupby(group_col).size().values
            return result.sort_values("total_credits", ascending=False).to_dict("records")

        first_row = df.iloc[0].fillna("").to_dict() if len(df) > 0 else {}
        hidden_columns = {"account_id", "account_user_id", "public_id", "name", "email"}
        display_headers = [col for col in d.columns if col not in hidden_columns]
        display_column_options = [record_column_meta(col) for col in display_headers]

        summ_usage_type = make_summary("usage_type_parsed_type")
        summ_model = make_summary("usage_type_model")
        summ_io = make_summary("usage_type_io")
        summ_raw = make_summary("usage_type")

        user_weekly_json = "[]"
        if "date_partition" in df.columns and "usage_credits" in df.columns:
            wdf = df[["date_partition", "usage_credits"]].copy()
            wdf["_d"] = pd.to_datetime(wdf["date_partition"], errors="coerce")
            wdf = wdf.dropna(subset=["_d"])
            if not wdf.empty:
                wdf["_w"] = wdf["_d"] - pd.to_timedelta(wdf["_d"].dt.dayofweek, unit="D")
                agg = wdf.groupby("_w", as_index=False).agg(credits=("usage_credits", "sum")).sort_values("_w")
                user_weekly_json = json.dumps([
                    {"week": str(r["_w"].date()), "credits": round(float(r["credits"]), 2)}
                    for _, r in agg.iterrows()
                ])

        type_chart_json = json.dumps([
            {"label": s.get("usage_type_parsed_type") or "Other",
             "value": round(float(s["total_credits"]), 2)}
            for s in summ_usage_type
            if float(s.get("total_credits", 0)) > 0
        ])

        optimization_user = None
        optimization_history = []
        optimization_tier_history = []
        optimization_tier_moves = []
        optimization_source = ""
        optimization_assigned_tier_count = 0
        has_codex_access = False

        # Tier history/Codex-access badge are cheap JSON lookups, independent of
        # the (heavier, more failure-prone) optimization recommendation build
        # below -- load them first so they still render even if that build fails.
        tier_cfg: dict = {}
        raw_assignments: dict[str, str] = {}
        tier_histories: dict[str, list[str]] = {}
        codex_access_map: dict[str, bool] = {}
        tier_history_key = (email or "").strip().lower()

        def _resolve_tier_history(key: str) -> None:
            nonlocal optimization_tier_history, optimization_tier_moves, has_codex_access
            from app.optimization.service import is_codex_access_tier

            optimization_tier_history = tier_histories.get(key, [])
            has_codex_access = codex_access_map.get(key, False) or is_codex_access_tier(
                raw_assignments.get(key, "")
            )
            if len(optimization_tier_history) > 1:
                optimization_tier_moves = [
                    {
                        "previous_tier": optimization_tier_history[idx - 1],
                        "new_tier": optimization_tier_history[idx],
                        "is_current": idx == len(optimization_tier_history) - 1,
                    }
                    for idx in range(1, len(optimization_tier_history))
                    if optimization_tier_history[idx - 1] != optimization_tier_history[idx]
                ]
            else:
                optimization_tier_moves = []

        try:
            tier_cfg = config_svc.load_tiers()
            raw_assignments = config_svc.load_user_tiers()
            tier_histories = config_svc.load_user_tier_history()
            codex_access_map = config_svc.load_user_codex_access()
            if tier_history_key:
                _resolve_tier_history(tier_history_key)
        except Exception:
            optimization_tier_history = []
            optimization_tier_moves = []
            has_codex_access = False

        try:
            from app.optimization.service import (
                build_optimization_result,
                resolve_governance_assignments,
                tier_caps,
            )

            # Codex groups are product access, not credit tiers — resolve them out
            # of governance so a user's real credit tier drives the recommendation.
            governance_assignments = resolve_governance_assignments(
                raw_assignments, tier_histories, tier_caps(tier_cfg)
            )
            opt = build_optimization_result(d.df, tier_cfg, governance_assignments)
            optimization_source = opt.source_label
            optimization_assigned_tier_count = len(raw_assignments)
            rec = opt.recommendations
            if rec is not None and not rec.empty:
                if email and "email" in rec.columns:
                    matches = rec[rec["email"].astype(str).str.lower() == email.lower()]
                elif name and "latest_name" in rec.columns:
                    matches = rec[rec["latest_name"].astype(str).str.contains(name, case=False, na=False, regex=False)]
                else:
                    matches = pd.DataFrame()
                if not matches.empty:
                    optimization_user = matches.iloc[0].fillna("").to_dict()

            if not tier_history_key and optimization_user:
                tier_history_key = str(optimization_user.get("email", "")).strip().lower()
                if tier_history_key:
                    _resolve_tier_history(tier_history_key)

            hist = opt.user_week_history
            if hist is not None and not hist.empty:
                if email and "email" in hist.columns:
                    hist = hist[hist["email"].astype(str).str.lower() == email.lower()]
                elif name and "latest_name" in hist.columns:
                    hist = hist[hist["latest_name"].astype(str).str.contains(name, case=False, na=False, regex=False)]
                else:
                    hist = pd.DataFrame()
                if not hist.empty:
                    optimization_history = (
                        hist.sort_values("week_start", ascending=False)
                        .head(12)
                        .fillna("")
                        .to_dict(orient="records")
                    )
        except Exception:
            optimization_user = None
            optimization_history = []
            optimization_source = ""
            optimization_assigned_tier_count = 0
        optimization_page_available = "optimization.optimization_page" in current_app.view_functions

        # Narrative "stories" for this user (month-to-date pace, cross-tool usage).
        user_stories: list[dict] = []
        user_month_history: list[dict] = []
        user_triggered_alerts: list[dict] = []
        cap_change_date = ""
        try:
            from app.analytics.stories import build_month_pace_history, build_user_stories, evaluate_story_rules
            from app.shared.alerts import evaluate_rules

            tcfg = config_svc.load_tiers()
            cap_change_date = str(tcfg.get("cap_period_change_date", "") or "")
            user_tier = "Baseline"
            if optimization_user:
                user_tier = str(optimization_user.get("latest_governance_tier") or "Baseline")
            # Reference "now" for recency = the most recent date across all data.
            reference_date = None
            if "date_partition" in d.df.columns:
                reference_date = pd.to_datetime(d.df["date_partition"], errors="coerce").max()
            user_stories = build_user_stories(
                user_scope_df, tcfg, user_tier, reference_date=reference_date
            )
            user_month_history = build_month_pace_history(user_scope_df, tcfg, user_tier)

            # This user's currently-triggering alerts (custom rules + story rules),
            # evaluated against just their own activity, so the conditions shown
            # are actually about them (not an org-wide rule that happens to fire).
            if email:
                key = email.strip().lower()
                from app.optimization.service import tier_monthly_caps

                mcaps = tier_monthly_caps(tcfg)
                monthly_cap = mcaps.get(user_tier, mcaps.get("Baseline", 400.0))
                user_triggered_alerts += evaluate_rules(user_scope_df, config_svc.load_alert_rules())
                story_rules_for_user = [
                    r for r in config_svc.load_story_alert_rules()
                    if not str(r.get("email", "")).strip()
                    or str(r.get("email", "")).strip().lower() == key
                ]
                user_triggered_alerts += evaluate_story_rules(
                    user_scope_df, story_rules_for_user, {key: monthly_cap}, monthly_cap, reference_date,
                )
        except Exception:
            user_stories = []
            user_month_history = []
            user_triggered_alerts = []

        user_tier_changes = []
        try:
            user_tier_changes = list(reversed(
                config_svc.load_tier_change_log().get((email or "").strip().lower(), [])
            ))
        except Exception:
            user_tier_changes = []

        return render_template(
            "user_summary.html",
            name=name,
            email=email,
            rows=len(df),
            total_credits=total_credits,
            totals_by_unit=totals_by_unit,
            rows_data=rows_data,
            display_columns=display_columns,
            display_headers=display_headers,
            display_column_options=display_column_options,
            record_columns=record_columns,
            headers=display_headers,
            date_field=date_field,
            start_date=start_date,
            end_date=end_date,
            min_credits=min_credits,
            max_credits=max_credits,
            zero_credits=zero_credits,
            selected_fields=selected_fields,
            summary_usage_type=summ_usage_type,
            summary_model=summ_model,
            summary_io=summ_io,
            summary_raw=summ_raw,
            user_models=user_models,
            filter_models=filter_models,
            user_types=user_types,
            filter_types=filter_types,
            active_tab=active_tab,
            account_id=first_row.get("account_id", ""),
            account_user_id=first_row.get("account_user_id", ""),
            public_id=first_row.get("public_id", ""),
            sort_by=sort_by,
            sort_order=sort_order,
            is_form_submission=is_form_submission,
            user_weekly_json=user_weekly_json,
            user_usage_type_weekly=usage_type_weekly_json(df),
            type_chart_json=type_chart_json,
            optimization_user=optimization_user,
            optimization_history=optimization_history,
            optimization_tier_history=optimization_tier_history,
            optimization_tier_moves=optimization_tier_moves,
            optimization_source=optimization_source,
            optimization_assigned_tier_count=optimization_assigned_tier_count,
            optimization_page_available=optimization_page_available,
            tier_editing_locked=config_svc.is_tier_editing_locked(),
            has_codex_access=has_codex_access,
            user_stories=user_stories,
            user_month_history=user_month_history,
            user_triggered_alerts=user_triggered_alerts,
            user_tier_changes=user_tier_changes,
            cap_change_date=cap_change_date,
            user_notes=config_svc.load_user_notes().get((email or "").strip().lower(), []),
        )

    @bp.route("/user-summary/note", methods=["POST"])
    def add_user_note() -> object:
        import uuid
        from datetime import date
        email = request.form.get("email", "").strip()
        title = request.form.get("title", "").strip()
        text = request.form.get("text", "").strip()
        tone = request.form.get("tone", "info").strip().lower()
        if tone not in {"info", "notable", "alert"}:
            tone = "info"
        if not email:
            flash("A user email is required to pin a note.", "danger")
        elif not (title or text):
            flash("Add a title or note text.", "danger")
        else:
            config_svc.add_user_note(email, {
                "id": uuid.uuid4().hex[:8],
                "title": title or "Note",
                "text": text,
                "tone": tone,
                "created": date.today().isoformat(),
            })
            flash("Note pinned.", "success")
        return redirect(url_for("analytics.user_summary", email=email))

    @bp.route("/user-summary/note/delete", methods=["POST"])
    def delete_user_note() -> object:
        email = request.form.get("email", "").strip()
        config_svc.delete_user_note(email, request.form.get("note_id", ""))
        flash("Note removed.", "success")
        return redirect(url_for("analytics.user_summary", email=email))

    @bp.route("/user-cards", methods=["GET"])
    def user_cards_page() -> str:
        d = data()
        mode = "advanced" if request.args.get("mode", "basic").strip() == "advanced" else "basic"
        view = request.args.get("view", "cards").strip()
        if view not in {"cards", "table", "list"}:
            view = "cards"
        name_query = request.args.get("name_query", "").strip()
        email_query = request.args.get("email_query", "").strip()
        # Default to the canonical usage date so a plain date-range search works
        # without forcing the user to choose a field first.
        date_field = request.args.get("date_field", "date_partition")
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")
        top_n = result_limit("top_n", 50)
        min_credits = request.args.get("min_credits", "").strip()
        max_credits = request.args.get("max_credits", "").strip()
        zero_credits = request.args.get("zero_credits", "")

        # The name/email search applies in both modes.
        df = d.df.copy()
        if name_query and "name" in df.columns:
            df = df[df["name"].astype(str).str.contains(name_query, case=False, na=False, regex=False)]
        if email_query and "email" in df.columns:
            df = df[df["email"].astype(str).str.contains(email_query, case=False, na=False, regex=False)]

        # Advanced (outlier) controls + result.
        metric = request.args.get("metric", "per_user_window").strip()
        if metric not in OUTLIER_VIEWS:
            metric = "per_user_window"
        credit_threshold = float(request.args.get("credit_threshold", 100) or 100)
        lookback_days = int(request.args.get("lookback_days", 7) or 7)
        adv_usage_type = request.args.get("usage_type_filter", "").strip()
        adv_model = request.args.get("model_filter", "").strip()

        all_types_list = (
            sorted(d.df["usage_type_parsed_type"].dropna().unique().tolist())
            if "usage_type_parsed_type" in d.df.columns else []
        )
        all_models_list = (
            sorted(d.df["usage_type_model"].dropna().unique().tolist())
            if "usage_type_model" in d.df.columns else []
        )

        user_list: list[dict] = []
        outlier_rows: list[dict] = []
        outlier_count = 0
        outlier_columns: list[dict] = []
        window_start = window_end = ""

        if mode == "advanced":
            outlier_rows, outlier_count, window_start, window_end, outlier_columns = compute_outliers(
                df, metric, credit_threshold, lookback_days,
                start_date=start_date, end_date=end_date,
                usage_type_filter=adv_usage_type, model_filter=adv_model,
                top_n=top_n,
            )
        else:
            user_list = _basic_user_rows(d)

        # Query string (minus `view`) so the cards/table/list toggle can switch
        # the view while preserving the active search/filters.
        base_params = {k: v for k, v in {
            "mode": "basic",
            "name_query": name_query,
            "email_query": email_query,
            "date_field": date_field,
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n if top_n != 50 else "",
            "min_credits": min_credits,
            "max_credits": max_credits,
            "zero_credits": zero_credits,
        }.items() if v}

        return render_template(
            "user_cards.html",
            headers=d.columns,
            mode=mode,
            view=view,
            base_query=urlencode(base_params),
            name_query=name_query,
            email_query=email_query,
            date_field=date_field,
            start_date=start_date,
            end_date=end_date,
            top_n=top_n,
            max_result_limit=max_result_limit,
            users=user_list,
            min_credits=min_credits,
            max_credits=max_credits,
            zero_credits=zero_credits,
            # advanced mode
            metric=metric,
            outlier_views=OUTLIER_VIEWS,
            outlier_rows=outlier_rows,
            outlier_columns=outlier_columns,
            outlier_count=outlier_count,
            credit_threshold=credit_threshold,
            lookback_days=lookback_days,
            usage_type_filter=adv_usage_type,
            model_filter=adv_model,
            all_types_list=all_types_list,
            all_models_list=all_models_list,
            window_start=window_start,
            window_end=window_end,
        )

    @bp.route("/user-cards/export.csv", methods=["GET"])
    def user_cards_export_csv() -> object:
        """Download the current Users result as CSV."""
        d = data()
        mode = "advanced" if request.args.get("mode", "basic").strip() == "advanced" else "basic"
        if mode != "advanced":
            columns = [
                ("Name", "name"), ("Email", "email"), ("Records", "rows"),
                ("Credits", "total_credits"), ("Quantity", "total_quantity"),
                ("Tokens", "total_tokens"), ("Messages", "total_counts"),
                ("Duration seconds", "total_duration_s"),
            ]
            rows = _basic_user_rows(d)
            export_df = pd.DataFrame(
                [{label: row.get(key, "") for label, key in columns} for row in rows],
                columns=[label for label, _ in columns],
            )
            date_range = (
                f"{request.args.get('start_date', '')}_to_{request.args.get('end_date', '')}"
                if request.args.get("start_date", "") or request.args.get("end_date", "") else ""
            )
            credit_range = (
                f"{request.args.get('min_credits', '').strip() or '0'}_to_"
                f"{request.args.get('max_credits', '').strip() or 'max'}"
                if request.args.get("min_credits", "").strip() or request.args.get("max_credits", "").strip()
                else ""
            )
            return csv_response(export_df, "users.csv", filters=[
                ("name", request.args.get("name_query", "").strip()),
                ("email", request.args.get("email_query", "").strip()),
                ("dates", date_range),
                ("credits", credit_range),
                ("zero", "only" if request.args.get("zero_credits") == "1" else ""),
                ("top", request.args.get("top_n", "") if request.args.get("top_n", "") != "50" else ""),
            ])

        name_query = request.args.get("name_query", "").strip()
        email_query = request.args.get("email_query", "").strip()
        metric = request.args.get("metric", "per_user_window").strip()
        if metric not in OUTLIER_VIEWS:
            metric = "per_user_window"
        credit_threshold = float(request.args.get("credit_threshold", 100) or 100)
        lookback_days = int(request.args.get("lookback_days", 7) or 7)
        top_n = result_limit("top_n", 200)
        adv_usage_type = request.args.get("usage_type_filter", "").strip()
        adv_model = request.args.get("model_filter", "").strip()
        start_date = request.args.get("start_date", "")
        end_date = request.args.get("end_date", "")

        df = d.df.copy()
        if name_query and "name" in df.columns:
            df = df[df["name"].astype(str).str.contains(name_query, case=False, na=False, regex=False)]
        if email_query and "email" in df.columns:
            df = df[df["email"].astype(str).str.contains(email_query, case=False, na=False, regex=False)]

        rows, count, win_start, win_end, columns = compute_outliers(
            df, metric, credit_threshold, lookback_days,
            start_date=start_date, end_date=end_date,
            usage_type_filter=adv_usage_type, model_filter=adv_model,
            top_n=top_n,
        )

        # Labeled DataFrame in the view's column order.
        labels = [c["label"] for c in columns]
        export_df = pd.DataFrame(
            [{c["label"]: r.get(c["key"]) for c in columns} for r in rows],
            columns=labels,
        )

        fname = f"outliers_{metric}_{win_start}_to_{win_end}.csv"
        threshold = int(credit_threshold) if credit_threshold == int(credit_threshold) else credit_threshold
        return csv_response(export_df, fname, filters=[
            ("name", name_query),
            ("email", email_query),
            ("type", adv_usage_type),
            ("model", adv_model),
            ("over", threshold),
            ("top", top_n if top_n != 200 else ""),
        ])

    @bp.route("/user-cards/export", methods=["GET"])
    def export_outliers() -> object:
        """Legacy URL: keep old links working, but return CSV now."""
        return user_cards_export_csv()

    return bp
