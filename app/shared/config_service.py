from __future__ import annotations

import json
from pathlib import Path

import yaml

# Starter alert rules — mirror the previous built-in "heavy users this week".
DEFAULT_ALERT_RULES: list[dict] = [
    {
        "id": "heavy-users",
        "name": "Heavy users this week",
        "metric": "per_user_window",
        "threshold": 1000,
        "window_days": 7,
        "enabled": True,
    },
]


class AppConfig:
    def __init__(self, config_dir: Path) -> None:
        self.contract_path = config_dir / "contract_config.yaml"
        self.tier_path = config_dir / "tier_policy_config.yaml"
        self.alert_rules_path = config_dir / "alert_rules.json"

    def load_contract(self) -> dict:
        with open(self.contract_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_contract(self, data: dict) -> None:
        with open(self.contract_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_tiers(self) -> dict:
        with open(self.tier_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_tiers(self, data: dict) -> None:
        with open(self.tier_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_alert_rules(self) -> list[dict]:
        if not self.alert_rules_path.exists():
            return [dict(r) for r in DEFAULT_ALERT_RULES]
        try:
            data = json.loads(self.alert_rules_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else [dict(r) for r in DEFAULT_ALERT_RULES]
        except Exception:
            return [dict(r) for r in DEFAULT_ALERT_RULES]

    def save_alert_rules(self, rules: list[dict]) -> None:
        self.alert_rules_path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
