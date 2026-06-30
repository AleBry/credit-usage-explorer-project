"""First-run setup wizard routes (registered onto the `main` blueprint)."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, session, url_for

from app.shared.credit_ledger import build_credit_entry, sync_credit_ledger


def register_setup_routes(bp, services) -> None:
    store = services.store
    config_svc = services.config_svc

    @bp.route("/setup", methods=["GET"])
    def setup_page() -> str:
        from config import DEFAULT_DATA_PATH
        contract = config_svc.load_contract()
        has_data = store.path != DEFAULT_DATA_PATH and not store.data.df.empty
        return render_template(
            "setup.html",
            contract=contract.get("contract", {}),
            pricing=contract.get("pricing", {}),
            has_config=config_svc.is_contract_configured(),
            has_data=has_data,
            total_records=len(store.data.df),
            data_filename=None if store.path == DEFAULT_DATA_PATH else store.path.name,
        )

    @bp.route("/setup/config", methods=["POST"])
    def setup_save_config() -> object:
        data_ = config_svc.load_contract()
        data_.setdefault("contract", {})
        data_.setdefault("pricing", {})
        try:
            contract_start_date = request.form.get("contract_start_date", "").strip()
            purchased_credits = int(float(request.form.get("purchased_credits", 0) or 0))
            data_["contract"]["contract_start_date"] = contract_start_date
            data_["contract"]["contract_end_date"] = request.form.get("contract_end_date", "").strip()
            data_["contract"]["purchased_credits_date"] = (
                request.form.get("purchased_credits_date", "").strip() or contract_start_date
            )
            data_["contract"]["rollover_allowed"] = "rollover_allowed" in request.form
            data_["contract"]["credit_entries"] = []
            if purchased_credits > 0:
                data_["contract"]["credit_entries"].append(
                    build_credit_entry(
                        date=contract_start_date,
                        credits=purchased_credits,
                        kind="purchased",
                        notes="Initial allocation",
                    )
                )
            sync_credit_ledger(data_["contract"])
            data_["pricing"]["current_price_per_credit"] = float(request.form.get("current_price_per_credit", 0) or 0)
            config_svc.save_contract(data_)
            flash("Contract configuration saved.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"Could not save configuration: {exc}", "danger")
        return redirect(url_for("main.setup_page"))

    @bp.route("/setup/skip", methods=["GET", "POST"])
    def setup_skip() -> object:
        session["setup_skipped"] = True
        flash("Setup skipped — you can configure anytime in Settings.", "info")
        return redirect(url_for("main.summary_page"))

    @bp.route("/setup/finish", methods=["GET", "POST"])
    def setup_finish() -> object:
        session["setup_skipped"] = True
        return redirect(url_for("main.summary_page"))
