from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List, Dict, Optional

# Simple role config so you can extend later for CB, CMF, W etc
ROLE_CONFIG: Dict[str, Dict] = {
    "CF": {
        "metric_cols": [
            "Goals per 90",
            "xG per 90",
            "Shots per 90",
            "Shots on target, %",
            "Goal conversion, %",
            # engineered below
            "xG accuracy",
            "Shooting efficiency",
        ],
        "target_col": "Goals per 90",
    }
    # add "CB", "CMF" etc here later when you define their metric sets
}


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def add_striker_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add engineered features for strikers.
    Assumes Wyscout style column names already present.
    """
    out = df.copy()

    if "Goals per 90" in out.columns and "xG per 90" in out.columns:
        g = _to_numeric(out["Goals per 90"])
        xg = _to_numeric(out["xG per 90"])
        out["xG accuracy"] = np.where(xg > 0, g / xg, np.nan)
    else:
        out["xG accuracy"] = np.nan

    if "Goal conversion, %" in out.columns and "Shots on target, %" in out.columns:
        conv = _to_numeric(out["Goal conversion, %"])
        sot = _to_numeric(out["Shots on target, %"])
        # convert both to zero to one then multiply
        out["Shooting efficiency"] = (conv / 100.0) * (sot / 100.0)
    else:
        out["Shooting efficiency"] = np.nan

    return out


def compute_dynamic_weights(
    df: pd.DataFrame,
    metric_cols: List[str],
    target_col: str,
) -> Dict[str, float]:
    """
    Compute correlation based weights for each metric against the chosen target.
    Weights sum to one across metrics that have valid correlation.
    """
    weights: Dict[str, float] = {}
    corrs = {}

    if target_col not in df.columns:
        # fallback equal weights
        valid = [c for c in metric_cols if c in df.columns]
        if not valid:
            return {}
        w = 1.0 / len(valid)
        return {c: w for c in valid}

    y = _to_numeric(df[target_col])

    for col in metric_cols:
        if col not in df.columns:
            continue
        x = _to_numeric(df[col])
        mask = x.notna() & y.notna()
        if mask.sum() < 10:
            continue
        corr = np.corrcoef(x[mask], y[mask])[0, 1]
        corrs[col] = float(corr)

    if not corrs:
        # equal weights when no correlations can be computed
        valid = [c for c in metric_cols if c in df.columns]
        if not valid:
            return {}
        w = 1.0 / len(valid)
        return {c: w for c in valid}

    # use absolute correlation so direction does not flip importance
    abs_corrs = {c: abs(v) for c, v in corrs.items()}
    total = sum(abs_corrs.values())
    if total == 0:
        valid = list(abs_corrs.keys())
        w = 1.0 / len(valid)
        return {c: w for c in valid}

    for c, v in abs_corrs.items():
        weights[c] = v / total

    return weights


def zscore_column(series: pd.Series) -> pd.Series:
    vals = _to_numeric(series)
    mean = vals.mean()
    std = vals.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(np.zeros(len(vals)), index=vals.index)
    return (vals - mean) / std


def compute_bps_cfpi_emergence_for_cohort(
    df_cohort: pd.DataFrame,
    role: str,
    age_col: str = "Age",
    minutes_col: str = "Minutes played",
    young_max_age: int = 23,
    mature_min_age: int = 25,
    mature_max_age: int = 30,
) -> pd.DataFrame:
    """
    Core engine that takes a cohort for one role and returns
    BPS, CFPI Youth, CFPI Mature, CFPI Balanced, CFPI Consistency,
    and Emergence Index.
    """

    if role not in ROLE_CONFIG:
        raise ValueError(f"Role {role} has no ROLE_CONFIG entry yet")

    cfg = ROLE_CONFIG[role]
    metric_cols = cfg["metric_cols"]
    target_col = cfg["target_col"]

    df = df_cohort.copy()

    # engineered features for CF role
    if role == "CF":
        df = add_striker_features(df)

    # restrict to players with a useful minutes value
    if minutes_col in df.columns:
        mins = _to_numeric(df[minutes_col])
        df["_mins_num"] = mins
    else:
        df["_mins_num"] = np.nan

    # compute weights based on this cohort
    weights = compute_dynamic_weights(df, metric_cols, target_col)

    # z scores for each metric used
    for col in metric_cols:
        if col in df.columns:
            df[f"_z_{col}"] = zscore_column(df[col])
        else:
            df[f"_z_{col}"] = 0.0

    # base performance score
    z_cols = [f"_z_{c}" for c in weights.keys()]
    if z_cols:
        df["_bps"] = 0.0
        for c, w in weights.items():
            df["_bps"] += df[f"_z_{c}"] * w
    else:
        df["_bps"] = 0.0

    # age handling
    if age_col in df.columns:
        ages = _to_numeric(df[age_col])
    else:
        ages = pd.Series(np.nan, index=df.index)

    # simple age factors that you can tune later
    def youth_factor(a: float) -> float:
        if np.isnan(a):
            return 1.0
        if a <= young_max_age:
            # reward younger, stronger boost below twenty one
            return 1.0 + (young_max_age - a) / 10.0
        # soften above youth band
        return max(0.7, 1.0 - (a - young_max_age) / 20.0)

    def mature_factor(a: float) -> float:
        if np.isnan(a):
            return 1.0
        if mature_min_age <= a <= mature_max_age:
            return 1.1
        if a < mature_min_age:
            return 0.9
        # slightly penalise above peak band
        return 0.95

    df["_cfpi_youth"] = df["_bps"] * ages.apply(youth_factor)
    df["_cfpi_mature"] = df["_bps"] * ages.apply(mature_factor)

    df["_cfpi_balanced"] = 0.5 * (df["_cfpi_youth"] + df["_cfpi_mature"])

    # consistency proxy from minutes
    mins_clean = df["_mins_num"].fillna(0)
    if (mins_clean > 0).any():
        rel = np.log1p(mins_clean)
        rel = rel / rel.max()
    else:
        rel = pd.Series(1.0, index=df.index)

    df["_cfpi_consistency"] = df["_cfpi_balanced"] * (0.5 + 0.5 * rel)

    # emergence index
    df["_emergence_index"] = df["_cfpi_youth"] - df["_cfpi_mature"]

    return df


def build_position_cohort(
    df: pd.DataFrame,
    role: str,
    position_col: str = "Position",
    role_profile_col: str | None = None,
    role_profile_filter: Optional[List[str]] = None,
    min_minutes: int = 300,
    age_max: Optional[int] = None,
    minutes_col: str = "Minutes played",
    age_col: str = "Age",
) -> pd.DataFrame:
    """
    Generic filter for a position or Role profile cohort before we compute CFPI.
    """

    out = df.copy()

    if position_col in out.columns:
        # simple string containment, works with Wyscout style multi position strings
        mask_pos = out[position_col].fillna("").str.contains(role, na=False)
        out = out[mask_pos].copy()

    if role_profile_col and role_profile_filter:
        out = out[out[role_profile_col].isin(role_profile_filter)].copy()

    if minutes_col in out.columns:
        mins = _to_numeric(out[minutes_col])
        out = out[mins >= float(min_minutes)].copy()

    if age_max is not None and age_col in out.columns:
        ages = _to_numeric(out[age_col])
        out = out[ages <= age_max].copy()

    return out


def prepare_u21_position_frame(
    df_master: pd.DataFrame,
    position_code: str,
    max_age: int = 21,
    min_minutes: int = 300,
    role_profiles: Optional[List[str]] = None,
    role_profile_col: str | None = None,
    role_key_for_config: str = "CF",
    age_col: str = "Age",
    minutes_col: str = "Minutes played",
) -> pd.DataFrame:
    """
    One stop helper for the U21 tab.

    1. Filters master df to the chosen position and optional Role profiles
    2. Applies U21 and minutes filters
    3. Computes BPS, CFPI variants, and Emergence Index using the cohort
    """

    cohort = build_position_cohort(
        df_master,
        role=position_code,
        position_col="Position",
        role_profile_col=role_profile_col,
        role_profile_filter=role_profiles,
        min_minutes=min_minutes,
        age_max=max_age,
        minutes_col=minutes_col,
        age_col=age_col,
    )

    if cohort.empty:
        return cohort

    scored = compute_bps_cfpi_emergence_for_cohort(
        cohort,
        role=role_key_for_config,
        age_col=age_col,
        minutes_col=minutes_col,
    )

    return scored


# Optional Streamlit rendering helper for the U21 tab
def render_u21_tab(
    st,
    df_master: pd.DataFrame,
    position_options: List[str],
    role_profile_options: List[str],
):
    """
    Streamlit UI for the Emerging Talent View.
    You pass in st, the master df, and choice lists.
    """

    st.subheader("Emerging Talent View")

    col1, col2, col3 = st.columns(3)
    position_code = col1.selectbox("Position filter", position_options, index=0)
    sel_roles = col2.multiselect("Role profiles (optional)", role_profile_options, default=[])
    metric_choice = col3.selectbox(
        "Rank by metric",
        ["_emergence_index", "_cfpi_youth", "_cfpi_balanced", "_bps"],
        format_func=lambda x: {
            "_emergence_index": "Emerging Talent Score",
            "_cfpi_youth": "CFPI Youth",
            "_cfpi_balanced": "CFPI Balanced",
            "_bps": "Base Performance Score",
        }.get(x, x),
    )

    min_minutes = st.slider("Minimum minutes", min_value=0, max_value=2000, value=300, step=50)
    max_age = st.slider("Maximum age", min_value=16, max_value=23, value=21, step=1)

    if st.button("Refresh U21 cohort"):
        st.experimental_rerun()

    role_profiles = sel_roles if sel_roles else None

    df_scored = prepare_u21_position_frame(
        df_master,
        position_code=position_code,
        max_age=max_age,
        min_minutes=min_minutes,
        role_profiles=role_profiles,
        role_profile_col="_role_profile_guess",  # you already create this in enrich_with_groups
        role_key_for_config="CF",        # for now we use CF config, extend later
    )

    if df_scored.empty:
        st.info("No players match the current U21 filters.")
        return

    metric_col = metric_choice

    df_ranked = df_scored.sort_values(metric_col, ascending=False).copy()
    df_ranked["Rank"] = range(1, len(df_ranked) + 1)

    show_cols = [
        "Rank",
        "Player",
        "Team",
        "League",
        "Age",
        "Minutes played",
        "Position",
        "_role_profile_guess",
        "_bps",
        "_cfpi_youth",
        "_cfpi_mature",
        "_cfpi_balanced",
        "_cfpi_consistency",
        "_emergence_index",
    ]
    show_cols = [c for c in show_cols if c in df_ranked.columns]

    st.markdown("#### Top emerging players for this position")
    st.dataframe(df_ranked[show_cols].head(20), use_container_width=True, hide_index=True)

    # simple bar chart
    try:
        import altair as alt

        top = df_ranked.head(20)
        chart = (
            alt.Chart(top)
            .mark_bar()
            .encode(
                x=alt.X("Player:N", sort="-y"),
                y=alt.Y(f"{metric_col}:Q", title=metric_choice.replace("_", " ").title()),
                color="League:N",
                tooltip=show_cols,
            )
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption("Chart ranks young players by the selected development score within the chosen position group.")
    except Exception:
        st.caption("Altair not available, showing table only.")