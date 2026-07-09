from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from .alert_rules import DEFAULT_ALERT_RULES, AlertRule
from .credit_ledger import credit_entries_total, normalize_credit_entries

# Used when no contract_config.yaml exists yet (fresh install / setup wizard).
DEFAULT_CONTRACT_CONFIG: dict = {
    "contract": {
        "contract_start_date": "",
        "contract_end_date": "",
        "purchased_credits": 0,
        "purchased_credits_date": "",
        "credit_entries": [],
        "rollover_allowed": False,
    },
    "pricing": {
        "current_price_per_credit": 0.0,
        "next_contract_price_per_credit": 0.0,
    },
    "forecast": {
        "mode": "auto",
        "normalize_weights": True,
        "recent_average_window_weeks": 4,
        "minimum_weeks_for_recent_average": 4,
        "monte_carlo_runs": 10000,
        "snapshot_auto_save": "daily",
        "auto_weight_schedule": [
            {"min_operational_weeks": 0, "max_operational_weeks": 2, "historical_weight": 0.7, "latest_week_weight": 0.3, "recent_average_weight": None},
            {"min_operational_weeks": 3, "max_operational_weeks": 4, "historical_weight": 0.5, "latest_week_weight": 0.2, "recent_average_weight": 0.3},
            {"min_operational_weeks": 5, "max_operational_weeks": 8, "historical_weight": 0.3, "latest_week_weight": 0.2, "recent_average_weight": 0.5},
            {"min_operational_weeks": 9, "max_operational_weeks": None, "historical_weight": 0.2, "latest_week_weight": 0.2, "recent_average_weight": 0.6},
        ],
    },
}


class AppConfig:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.contract_path = config_dir / "contract_config.yaml"
        self.tier_path = config_dir / "tier_policy_config.yaml"
        self.user_tiers_path = config_dir / "user_tier_assignments.json"
        self.user_tier_history_path = config_dir / "user_tier_history.json"
        self.alert_rules_path = config_dir / "alert_rules.json"
        # Analyst-written "stories"/notes pinned to specific users, and
        # story-based alert rules (recency / burst / cross-tool) surfaced in the bell.
        self.user_notes_path = config_dir / "user_notes.json"
        self.story_rules_path = config_dir / "story_alert_rules.json"
        # Dated log of tier changes (email -> [{date, tier, source}]), append-only,
        # so "what tier were they on, as of what date" is answerable — distinct
        # from user_tier_history.json (undated, overwritten per tierlist import).
        self.tier_change_log_path = config_dir / "tier_change_log.json"
        # Which alert conditions the user has dismissed/read (the navbar bell
        # "inbox"). Persisted server-side so read-state survives across browsers
        # and machines, unlike the old per-browser localStorage approach.
        self.read_alerts_path = config_dir / "alert_read_state.json"

    def contract_exists(self) -> bool:
        return self.contract_path.exists()

    def is_contract_configured(self) -> bool:
        """True only when the contract has real dates + purchased credits set."""
        try:
            c = self.load_contract().get("contract", {})
            available = float(c.get("purchased_credits") or 0)
            if available <= 0:
                available = credit_entries_total(normalize_credit_entries(c))
            return bool(c.get("contract_start_date")) and bool(c.get("contract_end_date")) \
                and available > 0
        except Exception:
            return False

    def load_contract(self) -> dict:
        if not self.contract_path.exists():
            return copy.deepcopy(DEFAULT_CONTRACT_CONFIG)
        with open(self.contract_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or copy.deepcopy(DEFAULT_CONTRACT_CONFIG)

    def save_contract(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.contract_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_tiers(self) -> dict:
        if not self.tier_path.exists():
            return {"tiers": {}}
        with open(self.tier_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"tiers": {}}

    def save_tiers(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tier_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def is_tier_editing_locked(self) -> bool:
        """True when per-user tier changes are locked to prevent accidental edits."""
        try:
            return bool(self.load_tiers().get("editing_locked", False))
        except Exception:
            return False

    def set_tier_editing_locked(self, locked: bool) -> None:
        cfg = self.load_tiers()
        cfg["editing_locked"] = bool(locked)
        self.save_tiers(cfg)

    def load_user_tiers(self) -> dict[str, str]:
        if not self.user_tiers_path.exists():
            return {}
        try:
            data = json.loads(self.user_tiers_path.read_text(encoding="utf-8"))
            assignments = data.get("assignments", data) if isinstance(data, dict) else {}
            if not isinstance(assignments, dict):
                return {}
            return {
                str(email).strip().lower(): str(tier).strip()
                for email, tier in assignments.items()
                if str(email).strip() and str(tier).strip()
            }
        except Exception:
            return {}

    def save_user_tiers(self, assignments: dict[str, str]) -> None:
        clean = {
            str(email).strip().lower(): str(tier).strip()
            for email, tier in assignments.items()
            if str(email).strip() and str(tier).strip()
        }
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.user_tiers_path.write_text(
            json.dumps({"assignments": dict(sorted(clean.items()))}, indent=2),
            encoding="utf-8",
        )

    def load_user_tier_history(self) -> dict[str, list[str]]:
        if not self.user_tier_history_path.exists():
            return {}
        try:
            data = json.loads(self.user_tier_history_path.read_text(encoding="utf-8"))
            histories = data.get("histories", data) if isinstance(data, dict) else {}
            if not isinstance(histories, dict):
                return {}
            clean: dict[str, list[str]] = {}
            for email, tiers in histories.items():
                if not isinstance(tiers, list):
                    continue
                key = str(email).strip().lower()
                values = [str(tier).strip() for tier in tiers if str(tier).strip()]
                if key and values:
                    clean[key] = values
            return clean
        except Exception:
            return {}

    def save_user_tier_history(self, histories: dict[str, list[str]]) -> None:
        clean: dict[str, list[str]] = {}
        for email, tiers in histories.items():
            key = str(email).strip().lower()
            if not key or not isinstance(tiers, list):
                continue
            values = [str(tier).strip() for tier in tiers if str(tier).strip()]
            if values:
                clean[key] = values
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.user_tier_history_path.write_text(
            json.dumps({"histories": dict(sorted(clean.items()))}, indent=2),
            encoding="utf-8",
        )

    def load_alert_rules(self) -> list[AlertRule]:
        if not self.alert_rules_path.exists():
            return [AlertRule.from_dict(r) for r in DEFAULT_ALERT_RULES]
        try:
            data = json.loads(self.alert_rules_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [AlertRule.from_dict(r) for r in data]
            return [AlertRule.from_dict(r) for r in DEFAULT_ALERT_RULES]
        except Exception:
            return [AlertRule.from_dict(r) for r in DEFAULT_ALERT_RULES]

    def save_alert_rules(self, rules: list) -> None:
        # Normalize whatever we're handed (AlertRule or dict) to clean dicts.
        serializable = [AlertRule.from_dict(r).to_dict() for r in rules]
        self.alert_rules_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    # ── Analyst notes (mutable per-user "stories") ──────────────────────────
    def load_user_notes(self) -> dict[str, list[dict]]:
        """email(lowercased) -> list of note dicts {id, title, text, tone, created}."""
        if not self.user_notes_path.exists():
            return {}
        try:
            data = json.loads(self.user_notes_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_user_notes(self, notes: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.user_notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")

    def add_user_note(self, email: str, note: dict) -> None:
        key = str(email or "").strip().lower()
        if not key:
            return
        notes = self.load_user_notes()
        notes.setdefault(key, []).append(note)
        self.save_user_notes(notes)

    def delete_user_note(self, email: str, note_id: str) -> None:
        key = str(email or "").strip().lower()
        notes = self.load_user_notes()
        if key in notes:
            notes[key] = [n for n in notes[key] if str(n.get("id")) != str(note_id)]
            if not notes[key]:
                notes.pop(key)
            self.save_user_notes(notes)

    # ── Story alert rules (recency / burst / cross-tool, per user) ──────────
    def load_story_alert_rules(self) -> list[dict]:
        if not self.story_rules_path.exists():
            return []
        try:
            data = json.loads(self.story_rules_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_story_alert_rules(self, rules: list) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.story_rules_path.write_text(json.dumps(rules, indent=2), encoding="utf-8")

    # ── Dated tier-change log ────────────────────────────────────────────────
    def load_tier_change_log(self) -> dict[str, list[dict]]:
        if not self.tier_change_log_path.exists():
            return {}
        try:
            data = json.loads(self.tier_change_log_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_tier_change_log(self, log: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.tier_change_log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    def record_tier_change(self, email: str, tier: str, source: str, on_date: str | None = None) -> None:
        """Append a dated tier-change entry, skipping no-op repeats (same tier
        as the last recorded entry for this user)."""
        key = str(email or "").strip().lower()
        tier = str(tier or "").strip()
        if not key or not tier:
            return
        from datetime import date as _date
        entry_date = on_date or _date.today().isoformat()
        log = self.load_tier_change_log()
        entries = log.setdefault(key, [])
        if entries and entries[-1].get("tier") == tier:
            return
        entries.append({"date": entry_date, "tier": tier, "source": source})
        self.save_tier_change_log(log)

    # ── Alert read-state (navbar bell "inbox") ──────────────────────────────
    def load_read_alerts(self) -> set[str]:
        """The set of alert ids the user has marked read."""
        if not self.read_alerts_path.exists():
            return set()
        try:
            data = json.loads(self.read_alerts_path.read_text(encoding="utf-8"))
            return {str(x) for x in data} if isinstance(data, list) else set()
        except Exception:
            return set()

    def save_read_alerts(self, ids) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.read_alerts_path.write_text(
            json.dumps(sorted(str(i) for i in ids), indent=2), encoding="utf-8"
        )

    def prune_read_alerts(self, active_ids) -> set[str]:
        """Drop read ids that no longer match an active alert, so a resolved
        condition that later recurs re-notifies. Returns the surviving set;
        only rewrites the file when something actually changed."""
        read = self.load_read_alerts()
        kept = read & {str(i) for i in active_ids}
        if kept != read:
            self.save_read_alerts(kept)
        return kept

    def mark_read_alerts(self, ids, active_ids) -> set[str]:
        """Add `ids` to the read set (pruned to `active_ids`) and persist."""
        active = {str(i) for i in active_ids}
        read = (self.load_read_alerts() | {str(i) for i in ids}) & active
        self.save_read_alerts(read)
        return read
