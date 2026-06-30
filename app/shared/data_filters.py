from __future__ import annotations

import re

import pandas as pd


API_USAGE_RE = re.compile(r"^api\.", re.IGNORECASE)
API_MODEL_RE = re.compile(r"\(API\)\s*$", re.IGNORECASE)


def mask_api_usage(df: pd.DataFrame) -> pd.Series:
    """Rows for API usage that should roll up under Codex."""
    if df.empty:
        return pd.Series(False, index=df.index)

    mask = pd.Series(False, index=df.index)
    if "usage_type" in df.columns:
        usage_type = df["usage_type"].fillna("").astype(str).str.strip()
        mask |= usage_type.str.contains(API_USAGE_RE, regex=True)
    if "usage_type_model" in df.columns:
        model = df["usage_type_model"].fillna("").astype(str).str.strip()
        mask |= model.str.contains(API_MODEL_RE, regex=True)
    return mask


def corrected_usage_view(df: pd.DataFrame) -> pd.DataFrame:
    """Return a corrected, non-destructive view of usage classifications.

    This intentionally does not modify source/uploaded rows. It only corrects
    derived classification columns used by dashboards and filters.
    """
    out = df.copy()
    apply_usage_corrections(out)
    return out


def apply_usage_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Apply in-memory classification corrections to an already-loaded frame."""
    if "usage_type_parsed_type" not in df.columns:
        return df

    mask = mask_api_usage(df)
    if mask.any():
        df.loc[mask, "usage_type_parsed_type"] = "codex"
    return df
