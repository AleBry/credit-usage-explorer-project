"""
Run from the webapp_v3 directory:
    .venv\\Scripts\\python.exe testfiles\\test_data_filters.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.shared.data_filters import corrected_usage_view  # noqa: E402


def test_api_usage_rolls_up_to_codex_without_touching_raw_usage_type() -> None:
    raw_usage_type = "api.gpt_5_4_mini_2026_03_17_text_input_v_1"
    df = pd.DataFrame({
        "usage_type": [
            raw_usage_type,
            "api.gpt_5_4_2026_03_05_text_input_v_1",
            "chat.completion.5.reasoning",
        ],
        "usage_type_model": [
            "GPT 5.4 Mini (API)",
            "GPT 5.4 (API)",
            "Completion 5 Reasoning",
        ],
        "usage_type_parsed_type": ["chat", "chat", "chat"],
        "usage_units": ["counts", "counts", "counts"],
    })

    corrected = corrected_usage_view(df)

    assert df.loc[0, "usage_type_parsed_type"] == "chat"
    assert corrected.loc[0, "usage_type"] == raw_usage_type
    assert corrected.loc[0, "usage_type_parsed_type"] == "codex"
    assert corrected.loc[1, "usage_type_parsed_type"] == "codex"
    assert corrected.loc[2, "usage_type_parsed_type"] == "chat"
    assert corrected.loc[0, "usage_units"] == "tokens"
    assert corrected.loc[1, "usage_units"] == "tokens"
    assert corrected.loc[2, "usage_units"] == "counts"


if __name__ == "__main__":
    test_api_usage_rolls_up_to_codex_without_touching_raw_usage_type()
    print("PASS data_filters")
