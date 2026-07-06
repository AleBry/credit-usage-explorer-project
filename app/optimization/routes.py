from __future__ import annotations

from datetime import date
from io import StringIO
import re

import pandas as pd
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .service import build_optimization_result, tier_caps


def create_optimization_blueprint(services) -> Blueprint:
    store = services.store
    config_svc = services.config_svc
    bp = Blueprint("optimization", __name__, template_folder="templates", url_prefix="")

    def _result():
        return build_optimization_result(
            store.data.df,
            config_svc.load_tiers(),
            config_svc.load_user_tiers(),
        )

    def _slug(value: object, max_chars: int = 36) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text[:max_chars].strip("-")

    def _range_label(min_value: str, max_value: str) -> str:
        min_value = str(min_value or "").strip()
        max_value = str(max_value or "").strip()
        if not min_value and not max_value:
            return ""
        return f"{min_value or '0'}-to-{max_value or 'max'}"

    def _filter_recommendations(result):
        state = {
            "q": request.args.get("q", "").strip(),
            "action": request.args.get("action", "").strip(),
            "priority": request.args.get("priority", "").strip(),
            "current_tier": request.args.get("current_tier", "").strip(),
            "recommended_tier": request.args.get("recommended_tier", "").strip(),
            "min_util": request.args.get("min_util", "").strip(),
            "max_util": request.args.get("max_util", "").strip(),
            "min_avg_credits": request.args.get("min_avg_credits", "").strip(),
            "max_avg_credits": request.args.get("max_avg_credits", "").strip(),
        }

        df = result.recommendations.copy()
        if df.empty:
            return df, state

        if state["q"]:
            mask = pd.Series(False, index=df.index)
            for col in ("email", "latest_name", "latest_department"):
                if col in df.columns:
                    mask |= df[col].astype(str).str.contains(state["q"], case=False, na=False, regex=False)
            df = df[mask]
        if state["action"] and "recommended_action" in df.columns:
            df = df[df["recommended_action"] == state["action"]]
        if state["priority"] and "review_priority" in df.columns:
            df = df[df["review_priority"] == state["priority"]]
        if state["current_tier"] and "latest_governance_tier" in df.columns:
            df = df[df["latest_governance_tier"] == state["current_tier"]]
        if state["recommended_tier"] and "recommended_tier" in df.columns:
            df = df[df["recommended_tier"] == state["recommended_tier"]]

        for key, col in (
            ("min_util", "latest_cap_utilization"),
            ("max_util", "latest_cap_utilization"),
            ("min_avg_credits", "avg_weekly_credits_used"),
            ("max_avg_credits", "avg_weekly_credits_used"),
        ):
            if not state[key] or col not in df.columns:
                continue
            val = pd.to_numeric(state[key], errors="coerce")
            if pd.isna(val):
                continue
            series = pd.to_numeric(df[col], errors="coerce")
            df = df[series >= float(val)] if key.startswith("min") else df[series <= float(val)]

        return df, state

    def _csv_response(df: pd.DataFrame, name: str, filters: dict) -> Response:
        parts = [name]
        for key in ("q", "action", "priority", "current_tier", "recommended_tier"):
            val = _slug(filters.get(key, ""))
            if val:
                parts.append(f"{_slug(key, 16)}-{val}")
        util_range = _range_label(filters.get("min_util", ""), filters.get("max_util", ""))
        credit_range = _range_label(filters.get("min_avg_credits", ""), filters.get("max_avg_credits", ""))
        if util_range:
            parts.append(f"util-{_slug(util_range)}")
        if credit_range:
            parts.append(f"avgcredits-{_slug(credit_range)}")
        parts.append(date.today().isoformat())
        filename = "_".join(parts)
        if len(filename) > 145:
            filename = f"{filename[:134].rstrip('-_')}_{date.today().isoformat()}"
        bio = StringIO()
        df.to_csv(bio, index=False)
        return Response(
            bio.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    @bp.route("/optimization", methods=["GET"])
    def optimization_page() -> str:
        result = _result()
        recommendations, filters = _filter_recommendations(result)
        tiers = tier_caps(config_svc.load_tiers())
        available_tiers = [name for name, _ in sorted(tiers.items(), key=lambda item: item[1])]
        assigned_tier_count = len(config_svc.load_user_tiers())

        source = result.recommendations
        actions = sorted(source["recommended_action"].dropna().unique().tolist()) if not source.empty else []
        priorities = sorted(source["review_priority"].dropna().unique().tolist()) if not source.empty else []
        current_tiers = sorted(set(available_tiers) | (set(source["latest_governance_tier"].dropna().unique().tolist()) if not source.empty else set()))
        recommended_tiers = sorted(set(available_tiers) | (set(source["recommended_tier"].dropna().unique().tolist()) if not source.empty else set()))
        actionable = int(source["review_priority"].isin(["ACTIONABLE"]).sum()) if not source.empty else 0

        return render_template(
            "optimization.html",
            result=result,
            recommendations=recommendations.head(250).to_dict(orient="records") if not recommendations.empty else [],
            recommendation_count=len(recommendations),
            actions=actions,
            priorities=priorities,
            current_tiers=current_tiers,
            recommended_tiers=recommended_tiers,
            filters=filters,
            actionable=actionable,
            available_tiers=available_tiers,
            tier_editing_locked=config_svc.is_tier_editing_locked(),
            assigned_tier_count=assigned_tier_count,
            return_to=request.full_path,
            rec_summary=result.recommendation_summary.to_dict(orient="records") if not result.recommendation_summary.empty else [],
            tier_summary=result.tier_summary.to_dict(orient="records") if not result.tier_summary.empty else [],
        )

    def _safe_next(default_endpoint: str = "optimization.optimization_page") -> str:
        next_url = request.form.get("next", "") or url_for(default_endpoint)
        if not next_url.startswith("/"):
            next_url = url_for(default_endpoint)
        return next_url

    @bp.route("/optimization/user-tier", methods=["POST"])
    def update_user_tier() -> object:
        email = request.form.get("email", "").strip().lower()
        tier = request.form.get("tier", "").strip()
        next_url = _safe_next()

        if config_svc.is_tier_editing_locked():
            flash("Tier editing is locked. Unlock it in Settings to change tiers.", "warning")
            return redirect(next_url)

        tiers = tier_caps(config_svc.load_tiers())
        assignments = config_svc.load_user_tiers()
        if not email:
            flash("No user selected for tier update.", "warning")
            return redirect(next_url)
        if tier and tier not in tiers:
            flash(f"Tier '{tier}' is not in the current tier policy.", "danger")
            return redirect(next_url)

        if tier:
            assignments[email] = tier
            flash(f"Tier updated for {email}.", "success")
        else:
            assignments.pop(email, None)
            flash(f"Tier reset to Baseline default for {email}.", "success")
        config_svc.save_user_tiers(assignments)
        return redirect(next_url)

    @bp.route("/optimization/user-tier/reset", methods=["POST"])
    def reset_user_tier() -> object:
        """Restore a user's tier to the value from the imported tierlist.

        Manual tier changes only overwrite ``user_tier_assignments.json``; the
        tierlist import also records ``user_tier_history.json``, so the last
        entry there is the original tierlist assignment we reset back to.
        """
        email = request.form.get("email", "").strip().lower()
        next_url = _safe_next()
        if not email:
            flash("No user selected for tier reset.", "warning")
            return redirect(next_url)

        tiers = tier_caps(config_svc.load_tiers())
        assignments = config_svc.load_user_tiers()
        history = config_svc.load_user_tier_history().get(email, [])
        tierlist_tier = history[-1] if history else ""

        if tierlist_tier and tierlist_tier in tiers:
            assignments[email] = tierlist_tier
            config_svc.save_user_tiers(assignments)
            flash(f"Tier for {email} reset to tierlist value: {tierlist_tier}.", "success")
        elif tierlist_tier:
            assignments.pop(email, None)
            config_svc.save_user_tiers(assignments)
            flash(
                f"Tierlist tier '{tierlist_tier}' for {email} is not in the current "
                f"policy; reset to Baseline default.",
                "warning",
            )
        else:
            assignments.pop(email, None)
            config_svc.save_user_tiers(assignments)
            flash(f"No tierlist entry for {email}; reset to Baseline default.", "success")
        return redirect(next_url)

    @bp.route("/optimization/user-tier/reset-all", methods=["POST"])
    def reset_all_user_tiers() -> object:
        """Discard every manual tier override and rebuild assignments from the
        imported tierlist history (each user's last recorded tier)."""
        next_url = _safe_next("settings.settings_page")
        tiers = tier_caps(config_svc.load_tiers())
        histories = config_svc.load_user_tier_history()
        rebuilt = {
            email: hist[-1]
            for email, hist in histories.items()
            if hist and hist[-1] in tiers
        }
        config_svc.save_user_tiers(rebuilt)
        flash(
            f"Reset all tier assignments to the tierlist: {len(rebuilt):,} user(s) "
            f"restored, manual overrides discarded.",
            "success",
        )
        return redirect(next_url)

    @bp.route("/optimization/export.csv", methods=["GET"])
    def optimization_export_csv() -> Response:
        result = _result()
        recommendations, filters = _filter_recommendations(result)
        return _csv_response(recommendations, "optimization_recommendations", filters)

    return bp

