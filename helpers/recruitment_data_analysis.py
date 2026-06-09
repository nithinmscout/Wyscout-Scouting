# recruitment_data_analysis.py

from __future__ import annotations

import os
import io
import csv
import glob
import urllib.parse
import math
import re as _re
import numpy as np
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
import unicodedata
import difflib
import textwrap
import altair as alt
import streamlit.components.v1 as components
from datetime import date
import requests
from pathlib import Path
import difflib
import uuid
from logging import root

import matplotlib.pyplot as plt
from reportlab.lib.utils import ImageReader

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

try:
    import plotly.graph_objects as go
except Exception:
    go = None

# Import profile definitions
from helpers.profile_defs import (
    POSITION_ROLES, GLOBAL_TRAITS, RESPONSIBILITIES,
    ROLE_DEFINITIONS, TRAIT_DEFINITIONS, RESPONSIBILITY_DEFINITIONS,
    TIER_STRENGTH
)
from helpers.profile_defs import _to_num, role_group_from_profile, _dot_rating_row, norm_col_name, _resolve_metric_col,_weighted_mean, _metric_percentile
from helpers.profile_defs import _compute_responsibility_scores, _render_responsibilities_bar, _render_breakdown_radial
from helpers.profile_defs import LEAGUE_TIER_LABEL, tier_strength_coef
from helpers.shortlist_analysis import render_team_analysis_tab
from helpers.recruitment_data_wrangling import *
from helpers.recruitment_data_ui import (
    _da_escape,
    _da_fmt_int,
    _render_data_analysis_styles,
    _render_data_analysis_header,
    _render_data_tab_intro,
)
# will be set by render_data_analysis_page the first time it is called
_COMPUTE_AGE_SERIES_FOR_DA = None
_EXPORT_BUTTONS_FOR_DA = None

# ---------- local helpers that belong only to the data analysis page ----------



# -------- Plotly bar renderers with per bar tooltip definitions --------
def render_player_type_and_responsibilities_blocks(
    *,
    cohort_df: pd.DataFrame,
    target_row: pd.Series,
    position_text: str,
    ws_id: str,
    key_prefix: str = "pt",
):
    if cohort_df is None or cohort_df.empty or target_row is None or target_row.empty:
        st.info("Select a player and cohort to view player type and responsibilities.")
        return

    # 1) Decide profile_key
    raw = (position_text or "").strip().upper()

    # If the UI passed an actual profile key (recommended), prefer it.
    # This avoids mis-mapping from Wyscout strings entirely.
    try:
        known_profiles = set(RESPONSIBILITIES.keys())
    except Exception:
        known_profiles = set()

    if raw in known_profiles:
        profile_key = raw
    else:
        profile_key = _infer_profile_key(position_text)
    st.caption(f"Search tab mapping | position_text='{position_text}' -> profile_key='{profile_key}'")
    # after profile_key is decided
    if profile_key not in RESPONSIBILITIES:
        st.warning(f"Unmapped position_text='{position_text}'. No profile key derived, so no player type shown.")
        return
    
    role_group = role_group_from_profile(profile_key)
    # Helpful debug while you validate mapping
    st.caption(f"Profile: {profile_key} | Role group: {role_group}")

    st.markdown("### Player type")

    # --- Roles (profile specific) ---
    role_defs = POSITION_ROLES.get(role_group, {})
    role_scores = []
    role_detail = {}

    for role_name, rules in role_defs.items():
        score, detail = _score_bundle(rules, min_kpis=3, cohort_df=cohort_df, target_row=target_row)
        if pd.notna(score):
            role_scores.append((role_name, score))
            role_detail[role_name] = detail

    # --- Traits (global by default, but supports grouped traits too) ---
    # If you copied Player Reports, traits are usually a flat dict: {trait_name: rules}
    # If you built grouped traits, it might be: {role_group: {trait_name: rules}}
    trait_scores = []
    trait_detail = {}

    trait_defs = None
    try:
        trait_defs = GLOBAL_TRAITS
    except NameError:
        trait_defs = TRAITS

    # Detect structure
    if trait_defs:
        first_val = next(iter(trait_defs.values()))
        if isinstance(first_val, dict):
            # grouped by role
            trait_defs_use = trait_defs.get(role_group, {})
        else:
            # flat global traits
            trait_defs_use = trait_defs
    else:
        trait_defs_use = {}

    for trait_name, rules in trait_defs_use.items():
        score, detail = _score_bundle(rules, min_kpis=3, cohort_df=cohort_df, target_row=target_row)
        if pd.notna(score):
            trait_scores.append((trait_name, score))
            trait_detail[trait_name] = detail

    # --- Responsibilities (percentiles) ---
    resp_pct, resp_breakdown = _compute_responsibility_scores(cohort_df, target_row, profile_key)
    resp_rows = sorted(resp_pct.items(), key=lambda x: x[1], reverse=True)

    c1, c2 = st.columns(2)
    with c1:
        _render_hbar("Roles", role_scores, defs=ROLE_DEFINITIONS, key=f"{key_prefix}_hbar_roles")

    with c2:
        _render_hbar("Traits", trait_scores, defs=TRAIT_DEFINITIONS, key=f"{key_prefix}_hbar_traits")


    st.markdown("### Positional Responsibilities")

    # This is the missing “dots + bar” layout from Player Reports
    left, right = st.columns([1, 1], gap="large")

    with left:
        top_n = 8
        for name, pct in resp_rows[:top_n]:
            _dot_rating_row(name, float(pct), dots=10)

    with right:
        # If you already copied _render_responsibilities_bar from Player Reports, use it.
        # Otherwise fall back to hbar.
        if "_render_responsibilities_bar" in globals():
            _render_responsibilities_bar(resp_pct)
        else:
            _render_hbar(
                "Positional responsibilities (percentile)",
                resp_rows,
                defs=RESPONSIBILITY_DEFINITIONS,
                key=f"{key_prefix}_hbar_resp",
            )


    st.markdown("Responsibility metric breakdown")
    # Responsibility breakdown radial (no expander)
    if resp_breakdown and isinstance(resp_breakdown, dict):
        resp_names = list(resp_breakdown.keys())

        chosen = st.selectbox(
            "Responsibility metric breakdown",
            options=resp_names,
            index=0,
            key=f"{key_prefix}_resp_breakdown_pick",
        )


        metric_map = resp_breakdown.get(chosen, {}) or {}
        if isinstance(metric_map, dict) and metric_map:
            _render_breakdown_radial(
                metric_map,
                title=f"{chosen} | metric percentiles (vs cohort)",
            )
        else:
            st.info("No metric breakdown available for this responsibility.")
    else:
        st.info("No responsibility breakdown available.")



    # Optional explanation panel
    with st.expander("Why these roles and traits", expanded=False):
        show_top_n = 6

        st.markdown("### Position roles")
        for name, sc in sorted(role_scores, key=lambda x: x[1], reverse=True)[:show_top_n]:
            st.markdown(f"**{name}**  \nScore: {sc:.0f}")
            dd = role_detail.get(name, [])
            hits = [x for x in dd if x.get("hit")]
            misses = [x for x in dd if not x.get("hit")]
            if hits:
                st.write("Hit KPIs:")
                st.dataframe(
                    pd.DataFrame(hits)[["metric", "player_value", "goodness_pct", "threshold"]],
                    use_container_width=True,
                    hide_index=True,
                )
            if misses:
                st.write("Missed KPIs:")
                st.dataframe(
                    pd.DataFrame(misses)[["metric", "player_value", "goodness_pct", "threshold"]],
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("### Cross position traits")
        for name, sc in sorted(trait_scores, key=lambda x: x[1], reverse=True)[:show_top_n]:
            st.markdown(f"**{name}**  \nScore: {sc:.0f}")
            dd = trait_detail.get(name, [])
            hits = [x for x in dd if x.get("hit")]
            misses = [x for x in dd if not x.get("hit")]
            if hits:
                st.write("Hit KPIs:")
                st.dataframe(
                    pd.DataFrame(hits)[["metric", "player_value", "goodness_pct", "threshold"]],
                    use_container_width=True,
                    hide_index=True,
                )
            if misses:
                st.write("Missed KPIs:")
                st.dataframe(
                    pd.DataFrame(misses)[["metric", "player_value", "goodness_pct", "threshold"]],
                    use_container_width=True,
                    hide_index=True,
                )





def render_kpi_radar_compare(
    *,
    cohort_df: pd.DataFrame,
    rows: list[pd.Series],
    labels: list[str],
    kpis: list[str],
    title: str,
    key_prefix: str,
):
    if go is None:
        st.info("Plotly not available, cannot render radar.")
        return

    if not rows or not kpis:
        st.info("Pick at least one player and at least one KPI to render radar.")
        return

    thetas = list(kpis)
    thetas_closed = thetas + [thetas[0]]

    fig = go.Figure()

    for row, lab in zip(rows, labels):
        r = []
        for k in kpis:
            r.append(_percentile_of_value(cohort_df[k], row.get(k)))
        r_closed = r + [r[0]]
        fig.add_trace(
            go.Scatterpolar(
                r=r_closed,
                theta=thetas_closed,
                fill="toself",
                name=lab,
            )
        )

    fig.update_layout(
        title=title,
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_radar")


def _render_hbar(
    title: str,
    rows: list[tuple[str, float]],
    *,
    defs: dict[str, str] | None = None,
    height_base: int = 260,
    key: str | None = None,
):
    if not rows:
        st.info(f"No scores available for {title}.")
        return

    rows = sorted(rows, key=lambda x: x[1], reverse=True)
    names = [r[0] for r in rows]
    vals = [float(r[1]) for r in rows]

    if defs is None:
        defs = {}
    custom = [defs.get(n, "Definition not set for this label yet.") for n in names]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=vals,
            y=names,
            orientation="h",
            customdata=custom,
            hovertemplate=(
                "<b>%{y}</b>"
                "<br>%{customdata}"
                "<br><b>Role fit score</b>: %{x:.0f}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title=title,
        height=max(height_base, 28 * len(names)),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(range=[0, 100], title="Role fit score"),
        yaxis=dict(autorange="reversed"),
        showlegend=False,
    )

    if key is None:
        key = f"hbar_{id(fig)}"

    st.plotly_chart(fig, use_container_width=True, key=key)


#--------------------------------------------------------------------------------
# ---- Moneyball data analysis helpers ---- ----
#--------------------------------------------------------------------------------



def _mb_kpi_radar(df_scored, name_col, kpi_cols, target_name, comp_names, key_prefix):
    if not target_name or not comp_names:
        return

    use_cols = [c for c in kpi_cols if c in df_scored.columns]
    if not use_cols:
        return

    pct = df_scored[use_cols].rank(pct=True) * 100.0
    pct[name_col] = df_scored[name_col].values

    def row_for(n):
        r = pct.loc[pct[name_col] == n]
        if r.empty:
            return None
        return r.iloc[0][use_cols].values.tolist()

    labels = use_cols + [use_cols[0]]
    fig = go.Figure()

    t = row_for(target_name)
    if t is not None:
        t_vals = list(t)
        fig.add_trace(go.Scatterpolar(
            r=t_vals + [t_vals[0]],
            theta=labels,
            fill="toself",
            name=target_name
        ))


    for n in comp_names:
        v = row_for(n)
        if v is None:
            continue
        fig.add_trace(go.Scatterpolar(r=v + [v[0]], theta=labels, fill="toself", name=n))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        margin=dict(l=10, r=10, t=30, b=10),
        height=520,
        title="Radial KPI comparison"
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_mb_radar")


def render_moneyball_block(
    df,
    kpi_cols,
    key_prefix,
    metric_direction=None,
    title="Moneyball",
):
    if df is None or df.empty:
        st.info("No data available for Moneyball.")
        return

    if title:
        st.markdown(f"### {title}")

    name_col = _mb_pick_col(df, ["Player", "Player name", "Name", "player_name"])
    team_col = _mb_pick_col(df, ["Team", "Squad", "Club"])
    league_col = _mb_pick_col(df, ["League", "Competition", "Division"])
    mins_col = _mb_pick_col(df, ["Minutes", "Min", "Mins", "Minutes played"])
    age_col = _mb_pick_col(df, ["Age", "Player age"])

    work = df.copy()
    # --- Age filter (Moneyball) ---
    age_col = next((c for c in work.columns if str(c).strip().casefold() == "age"), None)

    if age_col is not None:
        import numpy as np
        ages_num = pd.to_numeric(work[age_col], errors="coerce")
        ages_num = ages_num.where(np.isfinite(ages_num))

        if ages_num.notna().any():
            amin = int(np.nanmin(ages_num.values))
            amax = int(np.nanmax(ages_num.values))

            a_lo, a_hi = st.slider(
                "Age range",
                min_value=amin,
                max_value=amax,
                value=(amin, amax),
                step=1,
                key=f"{key_prefix}_mb_age",
            )

            mask_age = ages_num.between(a_lo, a_hi, inclusive="both")
            work = work.loc[mask_age].copy()

            if work.empty:
                st.info("No players left after the age filter.")
                return


    if "_mv_eur" not in work.columns:
        mv_src = _mb_pick_col(work, ["Market value", "Market Value", "MV", "Transfermarkt value"])
        work["_mv_eur"] = work[mv_src].apply(_mb_parse_value_eur) if mv_src else np.nan

    if "_contract_dt" not in work.columns:
        c_src = _mb_pick_col(work, ["Contract expiry", "Contract Expiry", "Contract until", "Contract Until"])
        work["_contract_dt"] = work[c_src].apply(_mb_parse_contract_dt) if c_src else pd.NaT

    if name_col is None:
        st.warning("Moneyball needs a player name column to render.")
        return

    mv = pd.to_numeric(work["_mv_eur"], errors="coerce")
    keep = np.isfinite(mv.values) & (mv.values > 0)
    work = work.loc[keep].copy()
    if work.empty:
        st.info("No valid market values in this cohort.")
        return

    today = pd.Timestamp.today().normalize()
    contract_days = work["_contract_dt"].sub(today).dt.days
    work["_contract_months"] = pd.Series(np.divide(contract_days.values.astype(float), 30.0), index=work.index)

    perf, used_kpis = _mb_build_perf_score(work, kpi_cols=kpi_cols, metric_direction=metric_direction)
    work["_perf_z"] = perf

    value_model = globals().get("_mb_apply_professional_value_model")
    if callable(value_model):
        work, valuation_info = value_model(work, perf_col="_perf_z")
    else:
        log_mv = pd.Series(np.log(pd.to_numeric(work["_mv_eur"], errors="coerce").values), index=work.index)
        yhat = _mb_fit_expected_value(log_mv=log_mv, perf=work["_perf_z"], age=work[age_col] if age_col else None)
        work["_fair_log_mv"] = yhat
        work["_fair_mv_eur"] = pd.Series(
            np.exp(pd.to_numeric(work["_fair_log_mv"], errors="coerce").values),
            index=work.index,
        )
        work["_fair_low_eur"] = work["_fair_mv_eur"] * 0.70
        work["_fair_high_eur"] = work["_fair_mv_eur"] * 1.30
        work["_valuation_confidence"] = "Medium"
        valuation_info = {"status": "legacy", "rows_used": len(work), "features_used": []}

    work["_exp_log_mv"] = pd.to_numeric(work.get("_fair_log_mv"), errors="coerce")
    work["_exp_mv_eur"] = pd.to_numeric(work.get("_fair_mv_eur"), errors="coerce")
    # -------------------------------------------------------------------------
    # Render outputs (tables + optional radar)
    # -------------------------------------------------------------------------

    # Basic Moneyball outputs
    work["_value_gap_eur"] = pd.to_numeric(work["_exp_mv_eur"], errors="coerce") - pd.to_numeric(work["_mv_eur"], errors="coerce")
    denom = pd.to_numeric(work["_mv_eur"], errors="coerce").replace(0, np.nan)
    work["_value_gap_pct"] = (work["_value_gap_eur"] / denom) * 100.0

    # Optional minutes filter inside Moneyball (keeps the tool usable even when df is big)
    if mins_col and mins_col in work.columns:
        mins_num = pd.to_numeric(work[mins_col], errors="coerce").fillna(0.0)
        min_mins = st.slider(
            "Minimum minutes (Moneyball)",
            min_value=0,
            max_value=int(np.nanmax(mins_num.values)) if np.isfinite(np.nanmax(mins_num.values)) else 0,
            value=0,
            step=90,
            key=f"{key_prefix}_mb_min_mins",
        )
        work = work.loc[mins_num >= float(min_mins)].copy()
        if work.empty:
            st.warning("No players left after applying the minutes filter.")
            return

    # Small fingerprint so you can confirm Leagues tab vs Graphs tab are not pulling a different cohort
    import hashlib
    try:
        sample_hash = pd.util.hash_pandas_object(work.head(200), index=True).values.tobytes()
        df_sig = hashlib.md5(sample_hash).hexdigest()[:10]
    except Exception:
        df_sig = "na"

    model_status = valuation_info.get("status", "unknown") if isinstance(valuation_info, dict) else "unknown"
    rows_used = valuation_info.get("rows_used", 0) if isinstance(valuation_info, dict) else 0
    features_used = valuation_info.get("features_used", []) if isinstance(valuation_info, dict) else []
    model_weight = valuation_info.get("model_weight", 0.0) if isinstance(valuation_info, dict) else 0.0

    st.caption(
        f"Moneyball cohort signature: {df_sig} | rows: {len(work)} | KPIs used: {len(used_kpis)} | "
        f"valuation model: {model_status} | training rows: {rows_used} | model weight: {model_weight:.2f}"
    )

    with st.expander("Valuation model notes", expanded=False):
        st.markdown(
            "The fair value estimate uses a robust log market value model. "
            "It blends performance, age curve, minutes reliability, contract length, position group and league strength where those fields exist. "
            "Low sample players are pulled back towards their positional market baseline."
        )
        if features_used:
            st.write("Features used:")
            st.write(features_used)

    # Sort controls
    sort_mode = st.selectbox(
        "Sort by",
        options=[
            "Best value opportunity",
            "Most overvalued by model",
            "Best performance score",
            "Lowest market value",
            "Highest confidence opportunity",
        ],
        index=0,
        key=f"{key_prefix}_mb_sort",
    )

    top_n = st.slider(
        "Rows to show",
        min_value=10,
        max_value=200,
        value=50,
        step=10,
        key=f"{key_prefix}_mb_topn",
    )

    work2 = work.copy()

    if sort_mode == "Best value opportunity":
        work2 = work2.sort_values(["_value_gap_eur", "_valuation_confidence_score", "_perf_z"], ascending=[False, False, False])
    elif sort_mode == "Most overvalued by model":
        work2 = work2.sort_values("_value_gap_eur", ascending=True)
    elif sort_mode == "Best performance score":
        work2 = work2.sort_values("_perf_z", ascending=False)
    elif sort_mode == "Highest confidence opportunity":
        work2 = work2.sort_values(["_valuation_confidence_score", "_value_gap_eur", "_perf_z"], ascending=[False, False, False])
    else:
        work2 = work2.sort_values("_mv_eur", ascending=True)

    # Build display table
    display_cols = []
    for c in [name_col, team_col, league_col]:
        if c and c in work2.columns:
            display_cols.append(c)

    if "Position" in work2.columns:
        display_cols.append("Position")

    if age_col and age_col in work2.columns:
        display_cols.append(age_col)

    if mins_col and mins_col in work2.columns:
        display_cols.append(mins_col)

    display_cols += [
        "_mv_eur",
        "_exp_mv_eur",
        "_fair_low_eur",
        "_fair_high_eur",
        "_value_gap_eur",
        "_value_gap_pct",
        "_perf_z",
        "_contract_months",
        "_valuation_confidence",
    ]

    disp = work2.loc[:, [c for c in display_cols if c in work2.columns]].head(int(top_n)).copy()

    rename_map = {
        "_mv_eur": "Actual MV (EUR)",
        "_exp_mv_eur": "Model fair value (EUR)",
        "_fair_low_eur": "Fair value low (EUR)",
        "_fair_high_eur": "Fair value high (EUR)",
        "_value_gap_eur": "Opportunity gap (EUR)",
        "_value_gap_pct": "Opportunity gap (%)",
        "_perf_z": "Performance score",
        "_contract_months": "Contract months",
        "_valuation_confidence": "Model confidence",
    }
    disp = disp.rename(columns=rename_map)

    currency_cols = [
        "Actual MV (EUR)",
        "Model fair value (EUR)",
        "Fair value low (EUR)",
        "Fair value high (EUR)",
        "Opportunity gap (EUR)",
    ]
    for c in currency_cols:
        if c in disp.columns:
            disp[c] = pd.to_numeric(disp[c], errors="coerce").round(0).astype("Int64")
    for c in ["Opportunity gap (%)", "Performance score", "Contract months"]:
        if c in disp.columns:
            disp[c] = pd.to_numeric(disp[c], errors="coerce").round(2)

    st.dataframe(disp, use_container_width=True, hide_index=True)

    # Player inspection + radar chart (if plotly is available and KPIs exist)
    if used_kpis:
        st.markdown("### Player view")

        q = st.text_input("Search player", value="", key=f"{key_prefix}_mb_player_q")
        all_names = work2[name_col].dropna().astype(str).unique().tolist()
        all_names = sorted(all_names)

        if q.strip():
            q2 = q.strip().lower()
            opts = [n for n in all_names if q2 in n.lower()]
            if len(opts) > 200:
                opts = opts[:200]
        else:
            opts = all_names[:200] if len(all_names) > 200 else all_names

        if not opts:
            st.info("No player matches your search.")
            return

        target = st.selectbox("Player", options=opts, index=0, key=f"{key_prefix}_mb_player_pick")

        # Comparators: top performers (excluding target)
        comp_n = st.slider("Number of comparison players", 1, 5, 3, key=f"{key_prefix}_mb_comp_n")
        top_perf_names = (
            work2.sort_values("_perf_z", ascending=False)[name_col]
                 .dropna().astype(str).tolist()
        )
        comp = []
        for n in top_perf_names:
            if n == target:
                continue
            if n not in comp:
                comp.append(n)
            if len(comp) >= int(comp_n):
                break

        # Quick summary row for target
        tr = work2.loc[work2[name_col].astype(str) == str(target)]
        if not tr.empty:
            tr0 = tr.iloc[0]
            mv0 = float(pd.to_numeric(tr0.get("_mv_eur"), errors="coerce"))
            exp0 = float(pd.to_numeric(tr0.get("_exp_mv_eur"), errors="coerce"))
            gap0 = float(pd.to_numeric(tr0.get("_value_gap_eur"), errors="coerce"))
            low0 = float(pd.to_numeric(tr0.get("_fair_low_eur"), errors="coerce")) if "_fair_low_eur" in tr0.index else np.nan
            high0 = float(pd.to_numeric(tr0.get("_fair_high_eur"), errors="coerce")) if "_fair_high_eur" in tr0.index else np.nan
            conf0 = str(tr0.get("_valuation_confidence", "") or "").strip()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Actual MV (EUR)", f"{mv0:,.0f}" if np.isfinite(mv0) else "na")
            c2.metric("Model fair value (EUR)", f"{exp0:,.0f}" if np.isfinite(exp0) else "na")
            if np.isfinite(low0) and np.isfinite(high0):
                c3.metric("Fair value range", f"{low0:,.0f} to {high0:,.0f}")
            else:
                c3.metric("Fair value range", "na")
            c4.metric("Opportunity gap (EUR)", f"{gap0:,.0f}" if np.isfinite(gap0) else "na", help=f"Model confidence: {conf0 or 'na'}")

        # Radar
        if "go" in globals() and go is not None:
            _mb_kpi_radar(
                df_scored=work2,
                name_col=name_col,
                kpi_cols=used_kpis,
                target_name=target,
                comp_names=comp,
                key_prefix=key_prefix,
            )
        else:
            st.info("Plotly is not available, so the KPI radar is disabled.")
    else:
        st.info("No KPI columns available for Moneyball after validation.")


def _debug_moneyball_inputs(tag: str, df, kpis: list[str]):
    st.markdown(f"#### Moneyball debug: {tag}")
    st.write("df is None:", df is None)
    if df is not None:
        st.write("shape:", df.shape)
        st.write("columns (first 40):", list(df.columns)[:40])

        mv_candidates = ["Market value", "Market Value", "MV", "Transfermarkt value"]
        mv_col = next((c for c in mv_candidates if c in df.columns), None)
        st.write("market value column:", mv_col)

        if mv_col:
            st.write("mv sample:", df[mv_col].astype(str).head(8).tolist())

    st.write("kpi count:", len(kpis))
    st.write("kpis (first 25):", kpis[:25])

#--------------------------------------------------------------------------------
# ---- U21 emergence helpers ---- ----
def render_u21_emergence_block_from_df(st, df_in: pd.DataFrame, key_prefix: str, export_buttons):
    st.subheader("U21 development")

    if df_in is None or df_in.empty:
        st.info("No data in this cohort.")
        return

    df = df_in.copy()

    # Ensure Age
    if "Age" not in df.columns or pd.to_numeric(df["Age"], errors="coerce").isna().all():
        if "DOB" in df.columns:
            df["Age"] = compute_age_series(df)
        else:
            df["Age"] = pd.NA

    # Ensure league key
    if "__league_key" not in df.columns:
        def _mk_key(r):
            nation = str(r.get("__nation", "")).strip()
            league = str(r.get("League", "") or r.get("Competition", "") or "").strip()
            tier = str(r.get("__tier", "")).strip()
            parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
            return " · ".join(parts) if parts else "Unknown"
        df["__league_key"] = df.apply(_mk_key, axis=1)

    # Minutes
    if "Minutes played" in df.columns:
        df["_mins"] = pd.to_numeric(df["Minutes played"], errors="coerce")
    else:
        df["_mins"] = pd.to_numeric(df.get("_mins", pd.Series(dtype=float)), errors="coerce")

    # U21 and 300 minutes gate
    ages = pd.to_numeric(df["Age"], errors="coerce")
    df_u21 = df[(ages.notna()) & (ages <= 21)]
    df_u21 = df_u21[df_u21["_mins"] >= 300]

    if df_u21.empty:
        st.info("No U21 players with at least 300 minutes in this cohort.")
        return
    
        # Build selector options locally to avoid NameError in this module
    pos_choices = globals().get("POS_CHOICES")
    role_choices = globals().get("ROLE_PROFILE_CHOICES")

    if not isinstance(pos_choices, (list, tuple)) or len(pos_choices) == 0:
        tokens = set()
        if "Position" in df_u21.columns:
            for p in df_u21["Position"].astype(str).str.upper().tolist():
                tokens.update(_re.findall(r"[A-Z]{1,3}", p))
        pos_choices = sorted(tokens)

    if not isinstance(role_choices, (list, tuple)) or len(role_choices) == 0:
        if "_role_profile_guess" in df_u21.columns:
            role_choices = sorted(df_u21["_role_profile_guess"].dropna().astype(str).unique().tolist())
        else:
            # fallback to your role definitions dictionary if present in this module
            role_choices = sorted(list(ROLE_DEFINITIONS.keys())) if "ROLE_DEFINITIONS" in globals() else []

    # Filters for Wyscout positions and Role profiles
    col_f1, col_f2, col_f3 = st.columns(3)
    sel_pos = col_f1.multiselect(
        "Wyscout positions",
        options=pos_choices,
        default=[],
        key=f"{key_prefix}_u21_positions"
    )

    sel_roles = col_f2.multiselect(
        "Role profiles",
        options=role_choices,
        default=[],
        key=f"{key_prefix}_u21_role_profiles"
    )

    min_mins = col_f3.slider(
        "Minimum minutes",
        min_value=0,
        max_value=int(df_u21["_mins"].max()),
        value=300,
        step=30,
        key=f"{key_prefix}_u21_min_mins"
    )

    mask = df_u21["_mins"] >= min_mins

    if sel_pos and "Position" in df_u21.columns:
        s = df_u21["Position"].astype(str).str.upper()
        pos_mask = pd.Series(False, index=s.index)
        for token in sel_pos:
            pos_mask = pos_mask | s.str.contains(rf"\b{_re.escape(token.upper())}\b", regex=True)
        mask = mask & pos_mask

    if sel_roles and "_role_profile_guess" in df_u21.columns:
        role_mask = df_u21["_role_profile_guess"].astype(str).isin(sel_roles)
        mask = mask & role_mask

    df_u21 = df_u21[mask]

    if df_u21.empty:
        st.info("No U21 players match the filters.")
        return

    # Normalise minutes using max appearances per league (full df, not only U21)
    apps_candidates = [
        c for c in df.columns
        if c.lower() in {"appearances", "apps", "matches", "games", "matches played"}
    ]
    if apps_candidates:
        apps_col = apps_candidates[0]
        df["_apps"] = pd.to_numeric(df[apps_col], errors="coerce")

        # ensure league key exists on full df
        if "__league_key" not in df.columns:
            def _mk_league_key(row):
                nation = str(row.get("__nation", "")).strip()
                league = str(row.get("League", "") or row.get("Competition", "") or "").strip()
                tier = str(row.get("__tier", "")).strip()
                parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
                return " · ".join(parts) if parts else "Unknown"
            df["__league_key"] = df.apply(_mk_league_key, axis=1)

        df["__max_apps_league"] = df.groupby("__league_key")["_apps"].transform("max")
        df["__max_minutes_league"] = df["__max_apps_league"] * 90.0

        df_u21 = df_u21.merge(
            df[["__league_key", "__max_minutes_league"]].drop_duplicates(),
            on="__league_key",
            how="left",
        )

        df_u21["u21_norm_minutes_share"] = (df_u21["_mins"] / df_u21["__max_minutes_league"])
    else:
        df_u21["u21_norm_minutes_share"] = pd.NA

    # Find metric columns
    col_g90 = _find_metric_col(df_u21, ["goals per 90", "goals p90", "goals/90", "goals_per_90"])
    col_xg90 = _find_metric_col(df_u21, ["xg per 90", "xg p90", "xg/90", "expected goals per 90"])
    col_sh90 = _find_metric_col(df_u21, ["shots per 90", "shots p90", "shots/90"])
    col_sot_pct = _find_metric_col(df_u21, ["shots on target %", "shots on target, %", "sot %"])

    needed = [col_g90, col_xg90, col_sh90, col_sot_pct]
    if any(c is None for c in needed):
        st.warning(
            "Cannot build Emergence index because one of Goals per 90, xG per 90, Shots per 90, or Shots on target % is missing."
        )
        st.dataframe(df_u21, use_container_width=True, hide_index=True)
        return

    import numpy as np

    g = pd.to_numeric(df_u21[col_g90], errors="coerce")
    xg = pd.to_numeric(df_u21[col_xg90], errors="coerce")
    sh = pd.to_numeric(df_u21[col_sh90], errors="coerce")
    sot = pd.to_numeric(df_u21[col_sot_pct], errors="coerce") / 100.0

    sh = sh.replace(0, np.nan)
    conv = g / sh
    xg_acc = g - xg
    shoot_eff = conv * sot

    feats = pd.DataFrame(
        {"G90": g, "xG90": xg, "Shots90": sh, "SoT": sot, "Conv": conv, "xGAcc": xg_acc, "ShootEff": shoot_eff},
        index=df_u21.index,
    )

    def _z(s: pd.Series) -> pd.Series:
        m = s.mean(skipna=True)
        sd = s.std(skipna=True)
        if sd == 0 or np.isnan(sd):
            return pd.Series(0.0, index=s.index)
        return (s - m) / sd

    target = feats["G90"]
    weights: dict[str, float] = {}
    for col in ["xG90", "Shots90", "SoT", "Conv", "xGAcc", "ShootEff"]:
        if feats[col].notna().sum() > 2:
            corr = target.corr(feats[col])
            if pd.isna(corr):
                corr = 0.0
        else:
            corr = 0.0
        weights[col] = abs(corr)

    if sum(weights.values()) == 0:
        for k in weights:
            weights[k] = 1.0

    wsum = sum(weights.values())
    bps_vals = np.zeros(len(feats))
    for col, w in weights.items():
        bps_vals += _z(feats[col]).fillna(0.0).values * w
    bps_vals = bps_vals / wsum

    df_u21["BPS"] = bps_vals

    ages_u21 = pd.to_numeric(df_u21["Age"], errors="coerce")
    age_factor = (23 - ages_u21).clip(lower=0) / 6.0
    df_u21["EmergenceIndex"] = _z(df_u21["BPS"]) * age_factor

    metric_mode = st.radio(
        "Minutes metric",
        ["Normalised share", "Raw minutes"],
        index=0,
        horizontal=True,
        key=f"{key_prefix}_u21_minutes_metric",
    )

    metric_col = "u21_norm_minutes_share" if metric_mode == "Normalised share" else "_mins"
    metric_title = "Share of possible league minutes" if metric_mode == "Normalised share" else "Minutes played"

    topN = st.slider(
        "Number of players to show",
        min_value=5,
        max_value=50,
        value=15,
        step=1,
        key=f"{key_prefix}_u21_topN",
    )

    COL_PLAYER = next((c for c in df_u21.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM = next((c for c in df_u21.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")

    group_cols = [COL_PLAYER, COL_TEAM, "Age", "__league_key"]

    df_rank = (
        df_u21
        .groupby(group_cols, as_index=False)
        .agg({
            "_mins": "sum",
            "u21_norm_minutes_share": "max",
            "BPS": "mean",
            "EmergenceIndex": "mean",
        })
    )

    df_rank = df_rank.sort_values("EmergenceIndex", ascending=False).head(topN)
    df_rank.insert(0, "Rank", range(1, len(df_rank) + 1))

    import altair as alt

    chart_data = df_rank[[COL_PLAYER, COL_TEAM, "Age", "__league_key", "BPS", "EmergenceIndex", metric_col]].copy()
    chart_data = chart_data.rename(columns={COL_PLAYER: "Player", metric_col: metric_title})

    chart = (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            y=alt.Y("Player:N", sort="-x"),
            x=alt.X("EmergenceIndex:Q", title="Emergence index"),
            color=alt.Color("__league_key:N", title="League"),
            tooltip=[
                alt.Tooltip("Player:N", title="Player"),
                alt.Tooltip(f"{COL_TEAM}:N", title="Team"),
                alt.Tooltip("Age:Q", title="Age"),
                alt.Tooltip("BPS:Q", title="Base performance", format=".2f"),
                alt.Tooltip("EmergenceIndex:Q", title="Emergence index", format=".2f"),
                alt.Tooltip(metric_title + ":Q", title=metric_title, format=".2f"),
                alt.Tooltip("__league_key:N", title="League"),
            ],
        )
        .properties(height=30 * len(chart_data), width="container")
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### U21 ranking table")
    df_rank["_mins_raw"] = df_rank["_mins"]
    df_rank["_mins_norm_share"] = df_rank["u21_norm_minutes_share"]

    display_cols = [
        "Rank",
        COL_PLAYER,
        COL_TEAM,
        "Age",
        "__league_key",
        "_mins_raw",
        "_mins_norm_share",
        "BPS",
        "EmergenceIndex",
    ]
    st.dataframe(df_rank[display_cols], use_container_width=True, hide_index=True)
    export_buttons(df_rank[display_cols], key_suf=f"_{key_prefix}_u21_emergence")

#--------------------------------------------------------------------------------
# ---- Budget alternatives from similarity helpers ---- ----    
#--------------------------------------------------------------------------------
def render_budget_alternatives_block_from_similarity(
    st,
    *,
    candidates_df: "pd.DataFrame",
    target_row: "pd.Series",
    key_prefix: str,
    export_buttons=None,
) -> None:
    import numpy as np
    import pandas as pd

    if candidates_df is None or candidates_df.empty:
        st.info("No candidates dataframe available for budget alternatives.")
        return

    df = candidates_df.copy()

    score_options = []
    if "RTR_Sim" in df.columns:
        score_options.append("RTR_Sim")
    if "Similarity" in df.columns:
        score_options.append("Similarity")

    if not score_options:
        st.info("No Similarity or RTR_Sim column found in candidates.")
        return

    score_col = st.radio(
        "Score to use for budget alternatives",
        options=score_options,
        index=0,
        horizontal=True,
        key=f"{key_prefix}_score_col",
    )

    if "_mv_eur" in df.columns:
        mv_series = pd.to_numeric(df["_mv_eur"], errors="coerce")
    else:
        mv_col = next((c for c in df.columns if str(c).lower() in {"market value", "market_value", "mv"}), None)
        if mv_col is None:
            st.info("No market value column found for budget alternatives.")
            return
        parser = globals().get("_mb_parse_value_eur")
        if callable(parser):
            mv_series = df[mv_col].apply(parser)
        else:
            mv_str = df[mv_col].astype(str).str.replace(r"[^\d.]", "", regex=True)
            mv_series = pd.to_numeric(mv_str, errors="coerce")

    df["_mv_eur"] = pd.to_numeric(mv_series, errors="coerce")
    df["_mv_eur"] = df["_mv_eur"].where(df["_mv_eur"] > 0)
    df["_score"] = pd.to_numeric(df[score_col], errors="coerce").replace([np.inf, -np.inf], np.nan)

    col_player = "Player" if "Player" in df.columns else next((c for c in df.columns if str(c).lower() == "player"), "Player")
    col_team = "Team" if "Team" in df.columns else next((c for c in df.columns if str(c).lower() == "team"), "Team")
    col_age = "Age" if "Age" in df.columns else None
    col_mins = "Minutes" if "Minutes" in df.columns else ("Minutes played" if "Minutes played" in df.columns else None)

    mv_max = df["_mv_eur"].max(skipna=True)
    if pd.isna(mv_max) or mv_max <= 0:
        st.info("Market values are missing or zero, cannot build budget alternatives.")
        return

    budget_max = st.slider(
        "Budget max (€)",
        min_value=0,
        max_value=int(mv_max),
        value=int(min(mv_max, 10_000_000)),
        step=250_000,
        key=f"{key_prefix}_budget_max",
    )

    min_score = float(np.nanmin(df["_score"].to_numpy())) if df["_score"].notna().any() else 0.0
    max_score = float(np.nanmax(df["_score"].to_numpy())) if df["_score"].notna().any() else 1.0
    default_thr = 0.75 if "Similarity" in score_col else 0.65

    score_thr = st.slider(
        f"Minimum {score_col}",
        min_value=float(min_score),
        max_value=float(max_score),
        value=float(min(default_thr, max_score)),
        step=0.01,
        key=f"{key_prefix}_score_thr",
    )

    top_n = st.slider(
        "How many players to show",
        min_value=5,
        max_value=50,
        value=15,
        step=1,
        key=f"{key_prefix}_top_n",
    )

    t_name = str(target_row.get(col_player, target_row.get("Player", ""))).strip()
    t_team = str(target_row.get(col_team, target_row.get("Team", ""))).strip()

    is_target = (df[col_player].astype(str).str.strip() == t_name) & (df[col_team].astype(str).str.strip() == t_team)
    df = df[~is_target].copy()

    model_pool = df[df["_mv_eur"].notna() & df["_score"].notna()].copy()
    if model_pool.empty:
        st.info("No players with both market value and score found.")
        return

    value_model = globals().get("_mb_apply_professional_value_model")
    if callable(value_model):
        model_pool, valuation_info = value_model(model_pool, perf_col="_score")
    else:
        baseline = float(model_pool["_mv_eur"].median(skipna=True))
        model_pool["_fair_mv_eur"] = baseline
        model_pool["_fair_low_eur"] = baseline * 0.70
        model_pool["_fair_high_eur"] = baseline * 1.30
        model_pool["_valuation_confidence"] = "Low"
        valuation_info = {"status": "fallback", "rows_used": len(model_pool), "features_used": []}

    model_pool["_exp_mv_eur"] = pd.to_numeric(model_pool.get("_fair_mv_eur"), errors="coerce")
    model_pool["_value_gap_eur"] = model_pool["_exp_mv_eur"] - model_pool["_mv_eur"]
    model_pool["_value_ratio"] = model_pool["_exp_mv_eur"] / model_pool["_mv_eur"].replace(0, np.nan)

    rows_used = valuation_info.get("rows_used", 0) if isinstance(valuation_info, dict) else 0
    model_status = valuation_info.get("status", "unknown") if isinstance(valuation_info, dict) else "unknown"
    st.caption(f"Budget valuation model: {model_status} | training rows: {rows_used}")

    df = model_pool[(model_pool["_mv_eur"] <= budget_max) & (model_pool["_score"] >= score_thr)].copy()

    if df.empty:
        st.info("No players match the budget and minimum score filters.")
        return

    def _z(s: "pd.Series") -> "pd.Series":
        m = s.mean(skipna=True)
        sd = s.std(skipna=True)
        if sd == 0 or pd.isna(sd):
            return s * 0.0
        return (s - m) / sd

    confidence_score = pd.to_numeric(df.get("_valuation_confidence_score", pd.Series(50.0, index=df.index)), errors="coerce").fillna(50.0)
    df["_budget_match_score"] = (
        0.60 * _z(df["_score"])
        + 0.25 * _z(df["_value_ratio"])
        + 0.15 * _z(confidence_score)
    )

    df = df.sort_values(
        ["_budget_match_score", "_score", "_value_ratio", "_valuation_confidence_score"],
        ascending=[False, False, False, False],
    ).head(top_n)

    show_cols = [col_player, col_team]
    if col_age:
        show_cols.append(col_age)
    if col_mins:
        show_cols.append(col_mins)
    show_cols += [score_col]

    df_out = df.copy()
    df_out["Market value (€)"] = df_out["_mv_eur"].round(0).astype("Int64")
    df_out["Model fair value (€)"] = df_out["_exp_mv_eur"].round(0).astype("Int64")
    df_out["Fair range low (€)"] = pd.to_numeric(df_out.get("_fair_low_eur"), errors="coerce").round(0).astype("Int64")
    df_out["Fair range high (€)"] = pd.to_numeric(df_out.get("_fair_high_eur"), errors="coerce").round(0).astype("Int64")
    df_out["Opportunity gap (€)"] = df_out["_value_gap_eur"].round(0).astype("Int64")
    df_out["Value ratio"] = df_out["_value_ratio"].round(2)
    df_out["Budget match"] = df_out["_budget_match_score"].round(2)
    if "_valuation_confidence" in df_out.columns:
        df_out["Model confidence"] = df_out["_valuation_confidence"].astype(str)
    else:
        df_out["Model confidence"] = "Medium"

    final_cols = show_cols + [
        "Market value (€)",
        "Model fair value (€)",
        "Fair range low (€)",
        "Fair range high (€)",
        "Opportunity gap (€)",
        "Value ratio",
        "Budget match",
        "Model confidence",
    ]

    st.dataframe(df_out[final_cols], use_container_width=True, hide_index=True)

    if export_buttons is not None:
        export_buttons(df_out[final_cols], key_suf=f"_{key_prefix}_budget_alts")



#--------------------------------------------------------------------------------
# ---- Search tab gap/weaknesses analysis helpers ---- ----
#--------------------------------------------------------------------------------
# ---------- small helpers ----------

# ---------- main function ----------

def render_search_tab_gap_panel(
    *,
    cohort_df: "pd.DataFrame",
    target_row: "pd.Series",
    position_text: str,
    key_prefix: str = "search_gaps",
    top_n: int = 8,
    resp_floor: float = 50.0,
):
    """
    Search tab only: summarise weaknesses as 'gaps' (percentile points below thresholds)
    using the same Roles / Traits / Responsibilities logic you already use.

    Outputs a compact panel:
      - Best role + score, KPI coverage, avg gap, confidence (minutes)
      - Best trait + score, KPI coverage, avg gap
      - Top missed KPIs table (role + trait)
      - Bottom responsibilities vs a simple floor (default 50th percentile)
    """
    import pandas as pd
    import streamlit as st

    
    def _score_roles_traits_responsibilities(profile_key: str):
        role_group = role_group_from_profile(profile_key)

        # Roles
        role_defs = POSITION_ROLES.get(role_group, {})
        role_scores = []
        role_detail = {}
        for role_name, rules in (role_defs or {}).items():
            score, detail = _score_bundle(
                rules, min_kpis=3, cohort_df=cohort_df, target_row=target_row
            )
            if pd.notna(score):
                role_scores.append((role_name, float(score)))
                role_detail[role_name] = detail

            # Traits
            trait_scores = []
            trait_detail = {}

            trait_defs = None
            try:
                trait_defs = GLOBAL_TRAITS
            except NameError:
                trait_defs = TRAITS

            if trait_defs:
                first_val = next(iter(trait_defs.values()))
                if isinstance(first_val, dict):
                    trait_defs_use = trait_defs.get(role_group, {})
                else:
                    trait_defs_use = trait_defs
            else:
                trait_defs_use = {}

            for trait_name, rules in (trait_defs_use or {}).items():
                score, detail = _score_bundle(
                    rules, min_kpis=3, cohort_df=cohort_df, target_row=target_row
                )
                if pd.notna(score):
                    trait_scores.append((trait_name, float(score)))
                    trait_detail[trait_name] = detail

            # Responsibilities
            resp_pct, resp_breakdown = _compute_responsibility_scores(cohort_df, target_row, profile_key)

            return role_scores, role_detail, trait_scores, trait_detail, resp_pct, resp_breakdown
    

    # ---------- compute ----------
    if cohort_df is None or cohort_df.empty or target_row is None or len(target_row) == 0:
        return

    profile_key = _infer_profile_key_from_position_text(position_text)
    if not profile_key:
        return

    try:
        # only show if mapping exists in your responsibilities dictionary
        if profile_key not in RESPONSIBILITIES:
            return
    except Exception:
        pass

    role_scores, role_detail, trait_scores, trait_detail, resp_pct, resp_breakdown = _score_roles_traits_responsibilities(profile_key)

    mins = _pick_minutes(target_row)
    conf = _confidence_from_minutes(mins)

    # pick best role + trait
    best_role, best_role_score = ("", float("nan"))
    if role_scores:
        best_role, best_role_score = sorted(role_scores, key=lambda x: x[1], reverse=True)[0]

    best_trait, best_trait_score = ("", float("nan"))
    if trait_scores:
        best_trait, best_trait_score = sorted(trait_scores, key=lambda x: x[1], reverse=True)[0]

    role_rows = _detail_to_gap_rows(role_detail.get(best_role, []), area="Role", label=best_role) if best_role else []
    trait_rows = _detail_to_gap_rows(trait_detail.get(best_trait, []), area="Trait", label=best_trait) if best_trait else []

    role_cov, role_avg_gap, role_hits, role_misses = _coverage_and_avg_gap(role_rows)
    trait_cov, trait_avg_gap, trait_hits, trait_misses = _coverage_and_avg_gap(trait_rows)

    combined = [r for r in (role_rows + trait_rows) if not r["Hit"]]
    combined = sorted(combined, key=lambda r: r["Gap"], reverse=True)[:top_n]
    df_gaps = pd.DataFrame(combined)

    # responsibilities bottom vs floor
    low_resps = []
    if isinstance(resp_pct, dict) and resp_pct:
        for name, pct in sorted(resp_pct.items(), key=lambda x: x[1]):
            p = _as_float(pct)
            if pd.isna(p):
                continue
            if p < resp_floor:
                low_resps.append({"Responsibility": name, "Pct": round(p, 1), "Gap vs floor": round(resp_floor - p, 1)})
        low_resps = low_resps[:3]
    df_resp = pd.DataFrame(low_resps)

    # ---------- render ----------
    st.markdown("### Gaps and risk flags")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "Top role",
            f"{best_role}" if best_role else "N/A",
            delta=(f"Score {best_role_score:.0f}" if pd.notna(best_role_score) else None),
        )

    with c2:
        total_role = int(role_hits + role_misses)
        st.metric(
            "Role KPI coverage",
            f"{int(role_hits)}/{total_role}",
            delta=(f"{role_cov*100:.0f}%" if total_role else None),
        )

    with c3:
        if pd.notna(role_avg_gap):
            st.metric("Avg role gap", f"{role_avg_gap:.1f} pct pts")
        else:
            st.metric("Avg role gap", "N/A")

    with c4:
        mins_txt = f"{int(mins)} mins" if pd.notna(mins) else "mins N/A"
        st.metric("Data confidence", conf, delta=mins_txt)

    c5, c6, c7, c8 = st.columns(4)

    with c5:
        st.metric(
            "Top trait",
            f"{best_trait}" if best_trait else "N/A",
            delta=(f"Score {best_trait_score:.0f}" if pd.notna(best_trait_score) else None),
        )

    with c6:
        total_trait = int(trait_hits + trait_misses)
        st.metric(
            "Trait KPI coverage",
            f"{int(trait_hits)}/{total_trait}",
            delta=(f"{trait_cov*100:.0f}%" if total_trait else None),
        )

    with c7:
        if pd.notna(trait_avg_gap):
            st.metric("Avg trait gap", f"{trait_avg_gap:.1f} pct pts")
        else:
            st.metric("Avg trait gap", "N/A")

    with c8:
        major = sum(1 for r in combined if r.get("Gap", 0.0) >= 15.0)
        st.metric("Major gaps (15+)", str(int(major)))

    if not df_gaps.empty:
        st.caption("Gaps are measured as threshold minus player percentile (in percentile points).")
        st.dataframe(df_gaps, use_container_width=True, hide_index=True)
    else:
        st.info("No clear KPI gaps found for the top role or trait at your current thresholds.")

    if not df_resp.empty:
        st.caption(f"Lowest responsibilities (below {resp_floor:.0f}th percentile floor).")
        st.dataframe(df_resp, use_container_width=True, hide_index=True)

def render_weakness_visuals(gap_payload):
    """
    Renders the weakness summary using Streamlit metric cards and alert boxes
    instead of a plain text block.
    """
    if not gap_payload:
        return

    st.markdown("### 🚩 Risk & Gap Analysis")

    # Unpack payload
    mins = gap_payload.get("mins", 0)
    conf = gap_payload.get("confidence", "Unknown")
    major_gaps_count = gap_payload.get("major_gaps", 0)
    df_gaps = gap_payload.get("df_gaps", pd.DataFrame())
    df_resp = gap_payload.get("df_resp", pd.DataFrame())
    
    # 1. Top Level Status Bar
    # Determine overall risk level based on major gaps (gaps > 15%)
    if major_gaps_count >= 3:
        status_color = "error" # Red
        status_msg = f"HIGH RISK: {major_gaps_count} Major Statistical Deficits Detected"
        icon = "🛑"
    elif major_gaps_count >= 1:
        status_color = "warning" # Yellow
        status_msg = f"MODERATE RISK: {major_gaps_count} Major Statistical Deficits Detected"
        icon = "⚠️"
    else:
        status_color = "success" # Green
        status_msg = "LOW RISK: No major statistical deficits > 15% detected"
        icon = "✅"

    # Display the status alert
    if status_color == "error":
        st.error(f"{icon} {status_msg}")
    elif status_color == "warning":
        st.warning(f"{icon} {status_msg}")
    else:
        st.success(f"{icon} {status_msg}")

    # 2. Data Reliability Context
    c1, c2 = st.columns([1, 3])
    with c1:
        st.caption("Data Reliability")
        st.markdown(f"**{conf}**")
        st.markdown(f"*{int(mins)} minutes analyzed*")
    
    with c2:
        # 3. The Details (Tabs for Gaps vs Responsibilities)
        tab_gaps, tab_resp = st.tabs(["📉 KPI Deficits (Specific)", "⚠️ Baseline Failures (General)"])
        
        with tab_gaps:
            if not df_gaps.empty:
                for _, row in df_gaps.head(4).iterrows():
                    metric = row.get('Metric', 'Unknown')
                    gap = float(row.get('Gap', 0))
                    threshold = float(row.get('Threshold', 0))
                    actual = float(row.get('Player pct', 0))
                    
                    # Custom progress bar to show gap
                    st.markdown(f"**{metric}**")
                    c_txt, c_bar = st.columns([1, 3])
                    c_txt.caption(f"Gap: -{gap:.1f}%")
                    # Visual red bar for the gap size
                    c_bar.progress(min(1.0, max(0.0, actual / 100.0)), text=f"Player: {actual:.0f}% (Target: {threshold:.0f}%)")
            else:
                st.info("Player meets all key KPI thresholds for the selected role.")

        with tab_resp:
            if not df_resp.empty:
                st.markdown("The player falls below the **50th percentile (League Average)** in these core responsibility areas:")
                for _, row in df_resp.iterrows():
                    resp = row.get('Responsibility', '')
                    pct = row.get('Pct', 0)
                    st.markdown(f"- 🔴 **{resp}**: Only better than {pct:.0f}% of peers.")
            else:
                st.info("Player meets baseline standards (Top 50%) for all positional responsibilities.")


def render_season_trend_block(current_row, kpis, wys_root_func):
    """
    Renders the 24/25 vs Current Season comparison.
    """
    st.markdown("### 📅 Previous Season Trends (24/25)")
    
    # 1. Locate 24/25 Data
    # Assuming sibling folder structure: "Scouting Workspace/25 26" and "Scouting Workspace/24 25"
    # We go up from the current root and look for '24 25' or '2024 2025'
    root_candidates = ["24 25", "24-25", "2024 2025", "2024-2025"]
    
    # Try to find the folder relative to the environment root
    base = Path(os.environ.get("WYSROOTDIR", ".")).parent
    prev_path = None
    for c in root_candidates:
        p = base / c
        if p.exists():
            prev_path = p
            break
            
    if not prev_path:
        st.caption("🚫 Previous season folder (24/25) not found in the scouting directory.")
        return

    df_prev = _load_prev_season_master(prev_path)
    
    if df_prev.empty:
        st.caption("🚫 No data found inside the 24/25 folder.")
        return

    # 2. Match the Player
    # Try strict match on Name + Team first (teams change, so Name is primary)
    # Ideally use Wyscout ID if available
    name = str(current_row.get("Player", "")).strip()
    
    # Simple name match
    match = df_prev[df_prev["Player"].astype(str).str.contains(_re.escape(name), case=False, na=False)]
    
    if match.empty:
        st.info(f"Could not find historical data for **{name}** in the 24/25 database (Belgium/France/Netherlands).")
        return

    # If duplicates (common names), take the one with most minutes
    prev_row = match.sort_values("_mins", ascending=False).iloc[0]
    
    # 3. Render Comparison
    c1, c2 = st.columns([1, 2])
    
    with c1:
        # Context Cards
        cur_mins = float(current_row.get("_mins", 0))
        prev_mins = float(prev_row.get("_mins", 0))
        diff_mins = cur_mins - prev_mins
        
        st.metric("Minutes (24/25)", f"{int(prev_mins)}", delta=f"{int(diff_mins)} vs current")
        st.caption(f"**Team 24/25:** {prev_row.get('Team', 'Unknown')}")
        
        # Stability Analysis text
        if prev_mins > 900 and cur_mins > 900:
            st.markdown("**Sample Status:** ✅ High Reliability (Full data for both seasons)")
        elif prev_mins < 500:
            st.markdown("**Sample Status:** ⚠️ Low historical sample (<500 mins)")

    with c2:
        # Radar Overlay (Current vs Previous)
        # We need raw values for both, scaled 0-100 relative to *Current* league standards is best,
        # but for simplicity here we compare Raw Values or Percentiles if available.
        # Since we don't have the 24/25 cohort loaded for percentiles, we use RAW VALUES normalized.
        
        # Normalize raw values for visualization (simple scaling against current max)
        radar_vals_cur = []
        radar_vals_prev = []
        
        for k in kpis:
            v_cur = pd.to_numeric(current_row.get(k), errors="coerce")
            v_prev = pd.to_numeric(prev_row.get(k), errors="coerce")
            
            # Simple safeguard: fill NaNs
            v_cur = 0.0 if pd.isna(v_cur) else float(v_cur)
            v_prev = 0.0 if pd.isna(v_prev) else float(v_prev)
            
            radar_vals_cur.append(v_cur)
            radar_vals_prev.append(v_prev)

        # Plotly Radar
        fig = go.Figure()
        
        # We normalize strictly for the visual so charts don't explode
        # Scale: max of (cur, prev) = 100%
        max_vals = [max(c, p, 0.01) for c, p in zip(radar_vals_cur, radar_vals_prev)]
        norm_cur = [(c / m) * 100 for c, m in zip(radar_vals_cur, max_vals)]
        norm_prev = [(p / m) * 100 for p, m in zip(radar_vals_prev, max_vals)]
        
        labels = kpis + [kpis[0]]
        r_cur = norm_cur + [norm_cur[0]]
        r_prev = norm_prev + [norm_prev[0]]
        
        fig.add_trace(go.Scatterpolar(
            r=r_cur, theta=labels, fill='toself', name='25/26 (Current)',
            line_color='#00CC96', opacity=0.7
        ))
        fig.add_trace(go.Scatterpolar(
            r=r_prev, theta=labels, fill='toself', name='24/25 (Previous)',
            line_color='#EF553B', opacity=0.5, line=dict(dash='dot')
        ))
        
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=False, range=[0, 100])),
            showlegend=True,
            height=350,
            margin=dict(t=30, b=30, l=40, r=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02)
        )
        st.plotly_chart(fig, use_container_width=True)

    # 4. Metric Delta Table
    st.markdown("**Metric Evolution (Raw Per 90)**")
    
    # Create comparison dataframe
    delta_data = []
    for k in kpis:
        vc = pd.to_numeric(current_row.get(k), errors="coerce")
        vp = pd.to_numeric(prev_row.get(k), errors="coerce")
        
        if pd.notna(vc) and pd.notna(vp) and vp != 0:
            diff = vc - vp
            pct_change = (diff / abs(vp)) * 100
            trend = "📈" if diff > 0 else "📉"
            # Invert trend icon for negative metrics like "Fouls" if needed, keeping simple for now
            
            delta_data.append({
                "Metric": k,
                "24/25": f"{vp:.2f}",
                "25/26": f"{vc:.2f}",
                "Diff": f"{diff:+.2f}",
                "% Change": f"{pct_change:+.1f}%",
                "Trend": trend
            })
    
    if delta_data:
        st.dataframe(pd.DataFrame(delta_data), use_container_width=True, hide_index=True)
    else:
        st.caption("No overlapping numeric metrics found to compare.")


#--------------------------------------------------------------------------------
# --- SEARCH BY POSITION PANEL ---  
#--------------------------------------------------------------------------------
def render_search_by_position_panel(
    *,
    master_df: "pd.DataFrame",
    key_prefix: str = "da_pos_search",
    default_top_n: int = 50,
    use_tier_norm: bool = True,
):

    """
    Search tab panel.
    Filter by one or more Wyscout positions, then rank players by one or more selected role scores.
    Optional gates for Traits and Responsibilities.
    All scoring uses the same cohort logic as your existing Roles Traits Responsibilities blocks.
    Tier coefficient weightage is applied after the 0 to 100 score is computed.
    """

    try:
        from helpers.profile_defs import LEAGUE_TIER_LABEL, tier_strength_coef
    except Exception:
        LEAGUE_TIER_LABEL = {}

        def tier_strength_coef(_tier_label: str) -> float:
            return 1.0

    def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _ordered_unique(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            s = str(value or "").strip()
            if not s:
                continue
            key = s.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    def _tier_label_from_league_key(league_key: str | None) -> str:
        canon = _canonical_league_key(league_key)
        if not canon:
            return "Middle Tier"
        return LEAGUE_TIER_LABEL.get(canon, "Middle Tier")

    def _tier_adjust_pct(pct: float, league_key: str | None) -> float:
        """
        pct is 0 to 100.
        Apply tier coefficient as a shrink towards 50, similar spirit to your tier weighting.
        """
        if pct is None or (isinstance(pct, float) and np.isnan(pct)):
            return float("nan")
        if not use_tier_norm:
            return float(pct)

        coef = float(tier_strength_coef(_tier_label_from_league_key(league_key)))
        return float((pct * coef) + (50.0 * (1.0 - coef)))

    def _canonical_league_key(raw: str | None) -> str:
        """
        Convert:
          'England · T1' to 'England T1'
          'England T1' to 'England T1'
          'Belgium1' to 'Belgium T1'
        """
        s = str(raw or "").strip()
        if not s:
            return ""

        if "·" in s:
            left, right = [x.strip() for x in s.split("·", 1)]
            m = re.search(r"(\d+)", right)
            if m:
                return f"{left} T{m.group(1)}"
            return left

        m = re.search(r"^(.*)\s+T(\d+)\s*$", s)
        if m:
            return f"{m.group(1).strip()} T{m.group(2)}"

        m = re.search(r"^(.*?)(\d+)\s*$", s)
        if m:
            return f"{m.group(1).strip()} T{m.group(2)}"

        return s

    def _position_role_context(pos_code: str) -> dict:
        profile_key = _infer_profile_key_from_position_text(str(pos_code))
        role_group = role_group_from_profile(profile_key)
        role_defs = POSITION_ROLES.get(role_group, {}) or {}
        return {
            "pos_code": str(pos_code),
            "profile_key": profile_key,
            "role_group": role_group,
            "role_defs": role_defs,
        }

    if master_df is None or len(master_df) == 0:
        st.info("No data loaded.")
        return

    pos_col = _find_col(
        master_df,
        ["Position", "Primary position", "Primary Position", "position", "primary_position"],
    )
    if not pos_col:
        st.warning("Cannot find a Wyscout position column in the current dataset.")
        return

    player_col = _find_col(master_df, ["Player", "player", "Name", "name", "Player name", "Player Name", "player name"])
    team_col = _find_col(master_df, ["Team", "team", "Squad", "squad", "Club", "club", "Current team", "Current Team"])

    league_key_col = _find_col(
        master_df,
        ["__league_key", "__league", "__division", "League", "league", "Competition", "competition"],
    )

    leagues = []
    if league_key_col:
        leagues = sorted([
            x for x in master_df[league_key_col].dropna().unique().tolist()
            if str(x).strip() and str(x) != "Unknown"
        ])

    age_col = _find_col(master_df, ["Age", "age"])
    mins_col = _find_col(master_df, ["Minutes", "minutes", "Minutes played", "minutes_played", "Min", "min"])
    nation_col = _find_col(master_df, ["__nation", "Nation", "nation"])
    tier_col = _find_col(master_df, ["__tier", "Tier", "tier"])

    if "__league" not in master_df.columns and nation_col and tier_col:
        master_df = master_df.copy()
        master_df["__league"] = (
            master_df[nation_col].astype(str).str.strip()
            + " T"
            + master_df[tier_col].astype(str).str.strip()
        )

    pos_series_up = master_df[pos_col].fillna("").astype(str).str.upper()
    positions = [p for p in WS_POS_ORDER if pos_series_up.str.contains(rf"\b{p}\b", regex=True).any()]
    if not positions:
        positions = WS_POS_ORDER.copy()

    st.markdown("### Search by position")

    default_pos = positions[0] if positions else "CMF"
    c1, c2, c3 = st.columns([1.6, 1.1, 1.0])
    with c1:
        selected_pos_codes = st.multiselect(
            "Wyscout positions",
            positions,
            default=[default_pos],
            key=f"{key_prefix}_pos_multi",
            help="LCMF, RCMF and CMF are treated as one central midfield family. LAMF, RAMF and AMF are treated as one attacking midfield family. LW and RW remain side specific.",
        )
    with c2:
        top_n = st.slider("Max results", 10, 200, int(default_top_n), 5, key=f"{key_prefix}_topn")
    with c3:
        run = st.button("Run search", type="primary", key=f"{key_prefix}_run")

    selected_pos_codes = _ordered_unique(selected_pos_codes)
    if not selected_pos_codes:
        st.info("Select at least one Wyscout position.")
        return

    role_contexts = [_position_role_context(pos_code) for pos_code in selected_pos_codes]
    usable_role_contexts = [ctx for ctx in role_contexts if ctx["role_defs"]]

    if not usable_role_contexts:
        st.warning("No roles found for the selected position mapping.")
        return

    selected_profile_keys = _ordered_unique([ctx["profile_key"] for ctx in usable_role_contexts if ctx["profile_key"]])
    selected_role_groups = _ordered_unique([ctx["role_group"] for ctx in usable_role_contexts if ctx["role_group"]])

    st.caption(
        "Selected profiles: "
        + ", ".join(selected_profile_keys)
        + "   Role groups: "
        + ", ".join(selected_role_groups)
    )

    st.markdown("#### Role filters")

    role_meta_by_key: dict[str, dict] = {}
    role_name_counts: dict[str, int] = {}

    for ctx in usable_role_contexts:
        pos_code = str(ctx["pos_code"])
        role_group = str(ctx["role_group"])
        profile_key = str(ctx["profile_key"])
        role_defs = ctx["role_defs"] or {}

        for role_name, rules in role_defs.items():
            role_key = f"{role_group}::{role_name}"
            role_name_counts[role_name] = role_name_counts.get(role_name, 0) + 1

            if role_key not in role_meta_by_key:
                role_meta_by_key[role_key] = {
                    "role_key": role_key,
                    "role_name": role_name,
                    "role_group": role_group,
                    "profile_keys": [],
                    "pos_codes": [],
                    "rules": rules or [],
                }

            if profile_key not in role_meta_by_key[role_key]["profile_keys"]:
                role_meta_by_key[role_key]["profile_keys"].append(profile_key)
            if pos_code not in role_meta_by_key[role_key]["pos_codes"]:
                role_meta_by_key[role_key]["pos_codes"].append(pos_code)

    role_label_to_key: dict[str, str] = {}
    role_options: list[str] = []

    for role_key, meta in role_meta_by_key.items():
        role_name = str(meta["role_name"])
        role_group = str(meta["role_group"])
        label = f"{role_name} [{role_group}]" if role_name_counts.get(role_name, 0) > 1 else role_name
        meta["label"] = label
        role_label_to_key[label] = role_key
        role_options.append(label)

    role_options = sorted(role_options, key=str.casefold)

    default_roles = role_options[:1]
    selected_role_labels = st.multiselect(
        "Roles to test",
        role_options,
        default=default_roles,
        key=f"{key_prefix}_role_multi",
        help="This list is built from all roles available to the selected Wyscout positions. There is no weighting between roles.",
    )

    selected_role_labels = _ordered_unique(selected_role_labels)
    if not selected_role_labels:
        st.info("Select at least one role to score.")
        return

    selected_role_configs: list[dict] = []
    st.caption("Set the acceptable role score range for each selected role.")

    range_cols = st.columns(2)
    for idx, role_label in enumerate(selected_role_labels):
        role_key = role_label_to_key.get(role_label)
        meta = role_meta_by_key.get(role_key, {}) if role_key else {}
        if not meta:
            continue

        with range_cols[idx % 2]:
            score_range = st.slider(
                f"{role_label} score range",
                0.0,
                100.0,
                (60.0, 100.0),
                1.0,
                key=f"{key_prefix}_role_range_{role_key}",
            )
            st.caption("Position source: " + ", ".join(meta.get("pos_codes", [])))

        selected_role_configs.append(
            {
                "role_key": role_key,
                "profile_keys": meta.get("profile_keys", []),
                "pos_codes": meta.get("pos_codes", []),
                "role_group": meta.get("role_group", ""),
                "role_name": meta.get("role_name", role_label),
                "rules": meta.get("rules", []) or [],
                "score_range": score_range,
                "label": role_label,
            }
        )

    if not selected_role_configs:
        st.info("No valid role scorer could be built from the selected roles.")
        return

    st.markdown("#### Optional filters")
    f1, f2 = st.columns([1.2, 1.2])

    with f1:
        if league_key_col:
            leagues = sorted([x for x in master_df[league_key_col].dropna().unique().tolist() if str(x).strip() != ""])
        league_pick = st.multiselect(
            "Leagues",
            leagues,
            default=[],
            key=f"{key_prefix}_leagues",
            help="Leave empty for all leagues.",
        )

        if age_col:
            amin = float(pd.to_numeric(master_df[age_col], errors="coerce").min())
            amax = float(pd.to_numeric(master_df[age_col], errors="coerce").max())
            if np.isfinite(amin) and np.isfinite(amax):
                age_range = st.slider(
                    "Age range",
                    float(np.floor(amin)),
                    float(np.ceil(amax)),
                    (float(np.floor(amin)), float(np.ceil(amax))),
                    1.0,
                    key=f"{key_prefix}_age",
                )
            else:
                age_range = None
        else:
            age_range = None
            st.caption("Age filter unavailable because no Age column was found.")

        if mins_col:
            mmin = float(pd.to_numeric(master_df[mins_col], errors="coerce").min())
            mmax = float(pd.to_numeric(master_df[mins_col], errors="coerce").max())
            if np.isfinite(mmin) and np.isfinite(mmax):
                min_mins = st.slider(
                    "Minimum minutes",
                    float(np.floor(mmin)),
                    float(np.ceil(mmax)),
                    float(max(0.0, np.floor(mmin))),
                    10.0,
                    key=f"{key_prefix}_mins",
                )
            else:
                min_mins = None
        else:
            min_mins = None
            st.caption("Minutes filter unavailable because no Minutes column was found.")

    trait_defs_by_name: dict = {}
    for role_group in selected_role_groups:
        for name, rules in (_trait_defs_for_role_group(role_group) or {}).items():
            trait_defs_by_name.setdefault(name, rules)

    resp_profile_map: dict[str, list[str]] = {}
    for profile_key in selected_profile_keys:
        resp_defs = RESPONSIBILITIES.get(profile_key, {}) or {}
        names = list(resp_defs.keys()) if isinstance(resp_defs, dict) else list(resp_defs)
        for name in names:
            resp_profile_map.setdefault(name, []).append(profile_key)

    with f2:
        trait_names = list(trait_defs_by_name.keys())
        trait_pick = st.multiselect(
            "Traits to include",
            trait_names,
            default=[],
            key=f"{key_prefix}_traits",
        )
        trait_range = st.slider(
            "Trait score range",
            0.0,
            100.0,
            (60.0, 100.0),
            1.0,
            key=f"{key_prefix}_trait_range",
        )

        resp_names_all = list(resp_profile_map.keys())
        resp_pick = st.multiselect(
            "Responsibilities to include",
            resp_names_all,
            default=[],
            key=f"{key_prefix}_resp",
        )
        resp_range = st.slider(
            "Responsibility score range",
            0.0,
            100.0,
            (60.0, 100.0),
            1.0,
            key=f"{key_prefix}_resp_range",
        )

    if not run:
        return

    pool = master_df.copy()
    if league_key_col:
        pool = pool[pool[league_key_col].astype(str).str.strip().ne("Unknown")]

    eligible: set[str] = set()
    for pos_code in selected_pos_codes:
        eligible.update(WS_POS_COMPAT.get(str(pos_code), {str(pos_code)}))

    def _matched_position_text(pos_value) -> str:
        tokens = _ws_pos_tokens(pos_value)
        matched = [p for p in WS_POS_ORDER if p in tokens and p in eligible]
        return ", ".join(matched)

    pos_up = pool[pos_col].fillna("").astype(str).str.upper()
    mask = pos_up.apply(lambda s: len(_ws_pos_tokens(s) & eligible) > 0)
    pool = pool.loc[mask].copy()
    pool["__matched_positions"] = pool[pos_col].apply(_matched_position_text)

    if league_key_col and league_pick:
        pool = pool[pool[league_key_col].isin(league_pick)]

    if age_col and age_range is not None:
        a = pd.to_numeric(pool[age_col], errors="coerce")
        pool = pool[(a >= float(age_range[0])) & (a <= float(age_range[1]))]

    if mins_col and min_mins is not None:
        m = pd.to_numeric(pool[mins_col], errors="coerce")
        pool = pool[m >= float(min_mins)]

    pool = pool.reset_index(drop=True)

    with st.expander("Position matching debug", expanded=False):
        st.write(
            {
                "selected_positions": selected_pos_codes,
                "expanded_eligible_positions": [p for p in WS_POS_ORDER if p in eligible],
                "rows_after_position_filter": int(len(pool)),
            }
        )
        show_cols = [c for c in [player_col, team_col, pos_col, "__matched_positions"] if c and c in pool.columns]
        if show_cols:
            st.dataframe(pool[show_cols].head(40), use_container_width=True, hide_index=True)

    with st.expander("Tier normalisation debug", expanded=False):
        st.write("use_tier_norm:", bool(use_tier_norm))
        st.write("Detected league column:", league_key_col)

        if not league_key_col:
            st.warning("No league column found. Tier mapping cannot run.")
        else:
            dbg = pool.copy()

            dbg["_league_key"] = (
                dbg[league_key_col]
                .fillna("")
                .astype(str)
                .str.replace("\u00a0", " ", regex=False)
                .str.strip()
            )
            dbg["_league_key"] = dbg["_league_key"].replace(
                {"": "Unknown", "nan": "Unknown", "None": "Unknown"}
            )

            dbg["_tier_label"] = dbg["_league_key"].apply(_tier_label_from_league_key)
            dbg["_coef"] = dbg["_tier_label"].apply(lambda x: float(tier_strength_coef(str(x))))

            def _split_league_key(k: str) -> tuple[str, str]:
                if not k or k == "Unknown":
                    return ("Unknown", "")
                if " T" in k:
                    a, b = k.rsplit(" T", 1)
                    return (a.strip(), f"T{b.strip()}")
                return (k.strip(), "")

            nation_tier = dbg["_league_key"].apply(_split_league_key)
            dbg["_nation"] = nation_tier.apply(lambda x: x[0])
            dbg["_tier_code"] = nation_tier.apply(lambda x: x[1])

            league_summary = (
                dbg.groupby(["_league_key", "_nation", "_tier_code", "_tier_label", "_coef"], dropna=False)
                .size()
                .reset_index(name="n_players")
                .sort_values("n_players", ascending=False)
                .reset_index(drop=True)
            )
            st.markdown("##### League key to tier label to coefficient")
            st.dataframe(league_summary, use_container_width=True, hide_index=True)

            mapped_keys = set(LEAGUE_TIER_LABEL.keys()) if isinstance(LEAGUE_TIER_LABEL, dict) else set()
            league_summary["_is_unknown_key"] = (~league_summary["_league_key"].isin(mapped_keys)) | (
                league_summary["_league_key"] == "Unknown"
            )
            unknown_keys_df = league_summary[league_summary["_is_unknown_key"]].copy()

            st.markdown("##### Unknown league keys")
            st.write("Unknown key count:", int(len(unknown_keys_df)))
            if len(unknown_keys_df):
                st.dataframe(
                    unknown_keys_df[["_league_key", "_tier_label", "_coef", "n_players"]],
                    use_container_width=True,
                    hide_index=True,
                )

                show_cols = []
                for c in [player_col, team_col, league_key_col, pos_col, age_col, mins_col]:
                    if c and c in dbg.columns and c not in show_cols:
                        show_cols.append(c)

                st.markdown("##### Example player rows from unknown league keys")
                st.dataframe(
                    dbg[dbg["_league_key"].isin(set(unknown_keys_df["_league_key"]))][show_cols].head(30),
                    use_container_width=True,
                    hide_index=True,
                )

            tier_summary = (
                dbg.groupby(["_tier_label", "_coef"], dropna=False)
                .size()
                .reset_index(name="n_players")
                .sort_values("n_players", ascending=False)
                .reset_index(drop=True)
            )
            st.markdown("##### Tier labels currently used in this filtered pool")
            st.dataframe(tier_summary, use_container_width=True, hide_index=True)

            suspicious = tier_summary[tier_summary["_coef"].isin([0.50])]
            if len(suspicious):
                st.warning(
                    "Some tier labels are returning coefficient 0.50, which usually means the tier label is not in TIER_STRENGTH."
                )
                st.dataframe(suspicious, use_container_width=True, hide_index=True)

    if pool.empty:
        st.info("No players found after filters.")
        return

    if use_tier_norm:
        pool = _attach_tier_factor(pool)

    cohort_df = pool.copy()

    role_score_cols: list[str] = []
    role_score_labels: list[str] = []

    for cfg_idx, cfg in enumerate(selected_role_configs):
        col_name = f"__role_score_{cfg_idx}"
        role_score_cols.append(col_name)
        role_score_labels.append(str(cfg["label"]))

        scores = []
        for _idx, r in cohort_df.iterrows():
            score, _detail = _score_bundle(
                cfg["rules"],
                min_kpis=3,
                cohort_df=cohort_df,
                target_row=r,
                use_tier_z=bool(use_tier_norm),
            )
            scores.append(float(score) if pd.notna(score) else float("nan"))

        cohort_df[col_name] = scores

    role_gate_mask = pd.Series(True, index=cohort_df.index)

    for cfg_idx, cfg in enumerate(selected_role_configs):
        col_name = f"__role_score_{cfg_idx}"
        lo, hi = cfg.get("score_range", (0.0, 100.0))
        score_series = pd.to_numeric(cohort_df[col_name], errors="coerce")
        role_gate_mask = role_gate_mask & score_series.between(float(lo), float(hi), inclusive="both")

    cohort_df = cohort_df.loc[role_gate_mask].copy()

    if cohort_df.empty:
        st.info("No players matched the selected role score ranges.")
        return

    role_averages = []
    for _idx, r in cohort_df.iterrows():
        vals = np.array([float(r.get(col, np.nan)) for col in role_score_cols], dtype=float)
        valid = np.isfinite(vals)
        if not valid.any():
            role_averages.append(float("nan"))
            continue
        role_averages.append(float(np.mean(vals[valid])))

    cohort_df["RoleScore"] = role_averages

    out_rows: list[dict] = []

    for _idx, r in cohort_df.iterrows():
        lk = r.get(league_key_col) if league_key_col else None

        row_ok = True
        row_payload: dict = {}

        row_payload["Player"] = r.get(player_col, "") if player_col else ""
        row_payload["Team"] = r.get(team_col, "") if team_col else ""
        row_payload["League"] = r.get(league_key_col, "") if league_key_col else ""
        row_payload["Position"] = r.get(pos_col, "") if pos_col else ""
        row_payload["Matched positions"] = r.get("__matched_positions", "")
        row_payload["Age"] = r.get(age_col, np.nan) if age_col else np.nan
        row_payload["Minutes"] = r.get(mins_col, np.nan) if mins_col else np.nan
        row_payload["Role"] = " + ".join(role_score_labels)
        row_payload["RoleScore"] = float(r.get("RoleScore", np.nan))

        for cfg_idx, cfg in enumerate(selected_role_configs):
            row_payload[f"Score {cfg['label']}"] = float(r.get(f"__role_score_{cfg_idx}", np.nan))

        if use_tier_norm and "__tier_factor" in r.index:
            row_payload["TierCoef"] = float(r.get("__tier_factor"))

        for tname in trait_pick:
            trait_vals = []
            for role_group in selected_role_groups:
                trules = (_trait_defs_for_role_group(role_group) or {}).get(tname, {}) or {}
                if not trules:
                    continue
                tscore, _t_detail = _score_bundle(
                    trules,
                    min_kpis=3,
                    cohort_df=pool,
                    target_row=r,
                    use_tier_z=bool(use_tier_norm),
                )
                if pd.notna(tscore):
                    trait_vals.append(float(tscore))

            traw = max(trait_vals) if trait_vals else float("nan")
            tadj = _tier_adjust_pct(traw, lk)
            row_payload[f"Trait {tname}"] = tadj

            if pd.isna(tadj) or tadj < float(trait_range[0]) or tadj > float(trait_range[1]):
                row_ok = False

        if not row_ok:
            continue

        resp_cache: dict[str, dict] = {}
        for rname in resp_pick:
            resp_vals = []
            for profile_key in resp_profile_map.get(rname, []):
                if profile_key not in resp_cache:
                    resp_pct, _resp_breakdown = _compute_responsibility_scores(pool, r, profile_key)
                    resp_cache[profile_key] = resp_pct or {}
                v = resp_cache.get(profile_key, {}).get(rname, float("nan"))
                if pd.notna(v):
                    resp_vals.append(float(v))

            rraw = max(resp_vals) if resp_vals else float("nan")
            radj = _tier_adjust_pct(rraw, lk)
            row_payload[f"Resp {rname}"] = radj

            if pd.isna(radj) or radj < float(resp_range[0]) or radj > float(resp_range[1]):
                row_ok = False

        if not row_ok:
            continue

        extras = []
        for k, v in row_payload.items():
            if k.startswith("Trait ") or k.startswith("Resp "):
                if isinstance(v, (int, float)) and not np.isnan(v):
                    extras.append(float(v))

        if extras:
            row_payload["OverallAdj"] = float(np.mean([row_payload["RoleScore"]] + extras))
        else:
            row_payload["OverallAdj"] = row_payload["RoleScore"]

        out_rows.append(row_payload)

    if not out_rows:
        st.info("No players matched the selected role, trait and responsibility gates.")
        return

    out = pd.DataFrame(out_rows)
    out = out.sort_values(["OverallAdj", "RoleScore"], ascending=False).head(int(top_n))

    st.markdown("#### Results")
    st.caption(
        "Position search includes secondary positions from the Wyscout Position cell. "
        "Central midfield and attacking midfield families are side flexible. LW and RW stay side specific."
    )
    st.dataframe(out, use_container_width=True)

################################################################################
# -------- Reference players loader --------
#-------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)


def _safe_focus_suf() -> str:
    fid = st.session_state.get("profile_focus_id")
    return str(fid) if fid is not None else "analysis"



def _export_player_report_pdf(
    *,
    sel_player: str,
    target_row: pd.Series,
    league_key: str,
    raw_pos: str,
    minutes_text: str,
    minutes_share_text: str,
    player_vals: dict[str, float],
    league_pcts: dict[str, float],
    secondary_pcts: dict[str, float],
    secondary_label: str | None,
    sim_all: pd.DataFrame | None = None,
    sim_three: pd.DataFrame | None = None,
) -> None:
    """
    Create an A4 PDF with:
      • header and minutes
      • radar chart of league percentiles
      • full metric table with league and comparison percentiles
      • similar players tables (overall + Belgium/Netherlands/France)
    """

    out_dir = r"G:\My Drive\Reference Club\Databases\Scouting Workspace\Data Reports"
    os.makedirs(out_dir, exist_ok=True)

    safe_name = _re.sub(r"[^A-Za-z0-9_]+", "_", sel_player).strip("_") or "player"
    file_path = os.path.join(out_dir, f"{safe_name}_data_profile.pdf")

    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4
    margin = 2 * cm
    y = height - margin

    # ---------------- Header ----------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, sel_player)
    y -= 18

    c.setFont("Helvetica", 10)
    tier_txt = ""
    if "__tier" in target_row.index and pd.notna(target_row["__tier"]):
        try:
            tier_txt = f"T{int(target_row['__tier'])}"
        except Exception:
            tier_txt = str(target_row["__tier"])

    header_line = (
        f"{target_row.get('Team', '')} • {raw_pos} • {league_key} {tier_txt} • "
        f"Age: {target_row.get('Age', '')}"
    )
    c.drawString(margin, y, header_line)
    y -= 14

    # Minutes
    c.drawString(margin, y, f"Minutes: {minutes_text}{minutes_share_text}")
    y -= 20

    # ---------------- Radar chart ----------------
    radar_metrics: list[str] = []
    radar_vals: list[float] = []

    for m in sorted(player_vals.keys()):
        pct = league_pcts.get(m)
        if pct is None:
            continue
        try:
            v = float(pct)
        except Exception:
            continue
        if math.isnan(v):
            continue
        radar_metrics.append(m)
        radar_vals.append(v)

    if radar_metrics:
        angles = np.linspace(0, 2 * np.pi, len(radar_metrics), endpoint=False)
        vals = np.array(radar_vals, dtype=float)

        # Close loop
        angles = np.concatenate([angles, angles[:1]])
        vals = np.concatenate([vals, vals[:1]])

        fig = plt.figure(figsize=(5.5, 5.5))
        ax = fig.add_subplot(111, polar=True)

        ax.plot(angles, vals)
        ax.fill(angles, vals, alpha=0.25)

        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_yticklabels(["0", "25", "50", "75", "100"])

        ax.set_xticks(np.linspace(0, 2 * np.pi, len(radar_metrics), endpoint=False))
        ax.set_xticklabels(radar_metrics, fontsize=6)

        ax.set_title("League percentiles radar", fontsize=10, pad=12)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=260, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)

        radar_img = ImageReader(buf)

        img_width = 11 * cm
        img_height = 11 * cm

        c.drawImage(
            radar_img,
            margin,
            y - img_height,
            width=img_width,
            height=img_height,
            preserveAspectRatio=True,
            mask="auto",
        )

        y = y - img_height - 10  # move below radar

    if y < margin + 40:
        c.showPage()
        y = height - margin

    # ---------------- Metric table ----------------
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Metric")
    c.drawString(margin + 8 * cm, y, "Value")
    c.drawString(margin + 12 * cm, y, "League pct")
    if secondary_label:
        c.drawString(margin + 15.5 * cm, y, f"{secondary_label} pct")
    y -= 12

    c.setFont("Helvetica", 9)

    for m in sorted(player_vals.keys()):
        if y < margin + 25:
            c.showPage()
            y = height - margin

            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, y, "Metric")
            c.drawString(margin + 8 * cm, y, "Value")
            c.drawString(margin + 12 * cm, y, "League pct")
            if secondary_label:
                c.drawString(margin + 15.5 * cm, y, f"{secondary_label} pct")
            y -= 12
            c.setFont("Helvetica", 9)

        raw = player_vals.get(m)
        lp = league_pcts.get(m)
        sp = secondary_pcts.get(m) if secondary_label else None

        c.drawString(margin, y, str(m))

        # Raw value
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            raw_txt = "—"
        else:
            try:
                raw_txt = f"{float(raw):.2f}"
            except Exception:
                raw_txt = str(raw)
        c.drawRightString(margin + 10.5 * cm, y, raw_txt)

        # League pct
        if lp is None or (isinstance(lp, float) and math.isnan(lp)):
            lp_txt = "—"
        else:
            try:
                lp_txt = f"{float(lp):.1f}%"
            except Exception:
                lp_txt = str(lp)
        c.drawRightString(margin + 14.2 * cm, y, lp_txt)

        # Comparison pct
        if secondary_label:
            if sp is None or (isinstance(sp, float) and math.isnan(sp)):
                sp_txt = "—"
            else:
                try:
                    sp_txt = f"{float(sp):.1f}%"
                except Exception:
                    sp_txt = str(sp)
            c.drawRightString(margin + 18.0 * cm, y, sp_txt)

        y -= 10

    # ---------------- Similar players sections ----------------
    def _draw_sim_block(df: pd.DataFrame, title: str, y_pos: float) -> float:
        """Write one similarity section and return new y."""
        if df is None or df.empty:
            return y_pos

        nonlocal width, height, margin, c

        c.showPage()
        y_loc = height - margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, y_loc, title)
        y_loc -= 18

        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y_loc, "Top 5 overall")
        y_loc -= 14
        c.setFont("Helvetica", 9)

        df_sorted = df.sort_values("Similarity", ascending=False).copy()
        top5 = df_sorted.head(5)

        rank = 1
        for _, r in top5.iterrows():
            line = (
                f"{rank}. {r.get('Player','')} "
                f"({r.get('Team','')}, {r.get('Position','')}, "
                f"Age {r.get('Age','')}, {r.get('__league_key','')}) "
                f"Sim {float(r.get('Similarity',0)):.3f}"
            )
            c.drawString(margin, y_loc, line[:150])
            y_loc -= 11
            rank += 1

        # U22 block
        if "Age" in df_sorted.columns:
            c.setFont("Helvetica-Bold", 10)
            y_loc -= 6
            c.drawString(margin, y_loc, "Top 3 U22")
            y_loc -= 14
            c.setFont("Helvetica", 9)

            u22 = df_sorted[
                pd.to_numeric(df_sorted["Age"], errors="coerce") <= 22
            ].copy()
            top_u22 = u22.head(3)

            rank = 1
            for _, r in top_u22.iterrows():
                line = (
                    f"{rank}. {r.get('Player','')} "
                    f"({r.get('Team','')}, {r.get('Position','')}, "
                    f"Age {r.get('Age','')}, {r.get('__league_key','')}) "
                    f"Sim {float(r.get('Similarity',0)):.3f}"
                )
                c.drawString(margin, y_loc, line[:150])
                y_loc -= 11
                rank += 1

        return y_loc

    # Only render similarity sections if we actually have them
    if sim_all is not None and not sim_all.empty:
        y = _draw_sim_block(sim_all, "Similar players – overall database", y)

    if sim_three is not None and not sim_three.empty:
        y = _draw_sim_block(
            sim_three,
            "Similar players – Belgium / Netherlands / France",
            y,
        )

    c.showPage()
    c.save()




@st.cache_data(show_spinner=False)


def parse_date_any(s: str) -> pd.Timestamp | pd.NaT:
    if not s:
        return pd.NaT
    s = str(s).strip()
    fmts = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%b %d, %Y",
        "%d %b %Y",
    )
    for fmt in fmts:
        try:
            return pd.to_datetime(s, format=fmt)
        except Exception:
            pass
    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT


    
def export_buttons(df_view: pd.DataFrame, key_suf: str = ""):
    c1, c2 = st.columns(2)
    c1.download_button("Download CSV", data=df_view.to_csv(index=False).encode("utf-8"),
                       file_name=f"export{key_suf}.csv", mime="text/csv")
    try:
        with pd.ExcelWriter(io.BytesIO(), engine="xlsxwriter") as w:
            df_view.to_excel(w, index=False, sheet_name="Sheet1")
            data = w.book.filename.getvalue()  # type: ignore
        c2.download_button("Download Excel", data=data,
                           file_name=f"export{key_suf}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        st.caption("Install xlsxwriter for Excel export. CSV export always works.")

#-------End of utility functions-------

#------------------- Constants and config ------------------
POS_CHOICES = [
    "GK",
    "RB", "RWB", "RCB", "CB", "LCB", "LB", "LWB",
    "DMF", "RDMF", "LDMF", "CMF", "RCMF", "LCMF",
    "AMF", "RAMF", "LAMF",
    "RW", "RWF", "RM",
    "LW", "LWF", "LM",
    "CF", "ST", "SS",
]

ROLE_KPI_PACKS: dict[str, list[str]] = {
    "CBs": [
        "Successful defensive actions per 90",
        "Defensive duels per 90",
        "Defensive duels won, %",
        "Aerial duels per 90",
        "Aerial duels won, %",
        "Interceptions per 90",
        "PAdj Interceptions",
        "Shots blocked per 90",
        "Progressive passes per 90",
        "Accurate passes, %",
        "Passes to final third per 90",
        "Deep completions per 90",
    ],
    "FBs / WBs": [
        "Defensive duels per 90",
        "Defensive duels won, %",
        "Crosses per 90",
        "Accurate crosses, %",
        "Progressive runs per 90",
        "Dribbles per 90",
        "Successful dribbles, %",
        "Touches in box per 90",
        "Progressive passes per 90",
        "Passes to penalty area per 90",
    ],
    "6s": [
        # Out of possession
        "Successful defensive actions per 90",
        "Defensive duels per 90",
        "Defensive duels won, %",
        "Interceptions per 90",
        "PAdj Interceptions",
        "Aerial duels per 90",
        "Aerial duels won, %",
        "Fouls per 90",

        # On the ball security
        "Passes per 90",
        "Accurate passes, %",
        "Received passes per 90",

        # Progression and playmaking
        "Forward passes per 90",
        "Accurate forward passes, %",
        "Back passes per 90",
        "Accurate back passes, %",
        "Progressive passes per 90",
        "Passes to final third per 90",
        "Accurate passes to final third, %",
        "Passes to penalty area per 90",
        "Progressive runs per 90",
    ],
    "8s": [
        "Successful attacking actions per 90",
        "Assists per 90",
        "xA per 90",
        "Shots per 90",
        "Goals per 90",
        "Progressive runs per 90",
        "Dribbles per 90",
        "Smart passes per 90",
        "Key passes per 90",
        "Passes to final third per 90",
        "Passes to penalty area per 90",
    ],
    "WM": [
        "Assists per 90",
        "xA per 90",
        "Key passes per 90",
        "Shot assists per 90",
        "Smart passes per 90",
        "Passes to final third per 90",
        "Accurate passes to final third, %",
        "Crosses per 90",
        "Accurate crosses, %",
        "Dribbles per 90",
        "Successful dribbles, %",
        "Progressive runs per 90",
        "Defensive duels per 90",
        "Defensive duels won, %",
    ],
    "WF": [
        "Goals per 90",
        "xG per 90",
        "Shots per 90",
        "Shots on target, %",
        "Dribbles per 90",
        "Successful dribbles, %",
        "Offensive duels per 90",
        "Offensive duels won, %",
        "Crosses per 90",
        "Accurate crosses, %",
        "Touches in box per 90",
        "Progressive runs per 90",
    ],
    "9s": [
        "Goals per 90",
        "xG per 90",
        "Shots per 90",
        "Shots on target, %",
        "Head goals per 90",
        "Touches in box per 90",
        "Offensive duels per 90",
        "Offensive duels won, %",
        "Progressive runs per 90",
        "xA per 90",
        "Assists per 90",
    ],
}

THREE_NATION_FILTER = {"Belgium", "Netherlands", "France"}



def _render_similarity_section(
    df_sim: pd.DataFrame,
    *,
    title: str,
    top_overall: int,
    top_u22: int,
    key_prefix: str,
    current_player: str | None = None,
) -> None:
    """
    Generic renderer for a similarity table:
    - df_sim: dataframe with at least Player, Team, Position, Age, Similarity
    """
    if df_sim.empty:
        st.info(f"No similar players found for {title.lower()}.")
        return

    df = df_sim.copy()

    # make sure age is numeric
    if "Age" in df.columns:
        df["Age_num"] = pd.to_numeric(df["Age"], errors="coerce")
    else:
        df["Age_num"] = pd.NA

    # sort once by similarity
    df = df.sort_values("Similarity", ascending=False)

    # overall block
    top_overall_df = df.head(top_overall)

    # U22 block
    u22_df = df[df["Age_num"] <= 22].head(top_u22)

    st.markdown(f"#### {title}")

    st.write(f"Top {top_overall} similar players")
    st.dataframe(
        top_overall_df[["Player", "Team", "Position", "Age", "Similarity"]],
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_overall",
    )

    if not u22_df.empty:
        st.write(f"Top {top_u22} U22 similar players")
        st.dataframe(
            u22_df[["Player", "Team", "Position", "Age", "Similarity"]],
            use_container_width=True,
            hide_index=True,
            key=f"{key_prefix}_u22",
        )
    else:
        st.caption("No U22 players in this cohort for the similarity filter.")
    
    # ---- Quick navigation into these profiles ----

    # Combine names from both blocks, keep unique order
    all_candidates = pd.concat(
        [top_overall_df["Player"], u22_df["Player"]]
    ).dropna().astype(str).unique().tolist()

    if all_candidates:

        st.write("Jump to one of these profiles")
        selected = st.selectbox(
            "Select player to view profile",
            options=[""] + all_candidates,
            key=f"{key_prefix}_jump",
        )

        if selected:
            # remember where we are coming from
            if current_player:
                st.session_state["previous_player_name"] = current_player

            # tell the main search box which player to jump to
            st.session_state["goto_player_name"] = selected
            st.rerun()



#---------------------------
#------------------- Search by position tab ------------------
# This tab shares a lot of logic with the player comparison tab, but with a different UI and no similarity sections.

def render_position_search_tab(
    *,
    nation_dirs: list[str],
    compute_age_series,
    use_tier_norm: bool = True,
) -> None:
    import pandas as pd
    import streamlit as st

    st.subheader("Search by position")

    if not nation_dirs:
        st.info("No Wyscout league folders found yet.")
        return

    master = _build_global_wyscout_master(nation_dirs)
    if master.empty:
        st.info("No league data available.")
        return

    # Ensure Age exists, same logic as your player search tab
    if "Age" not in master.columns or pd.to_numeric(master["Age"], errors="coerce").isna().all():
        if "DOB" in master.columns and compute_age_series is not None:
            master["Age"] = compute_age_series(master)
        else:
            master["Age"] = pd.NA

    render_search_by_position_panel(
        master_df=master,
        key_prefix="da_pos_search_tab",
        default_top_n=50,
        use_tier_norm=use_tier_norm,
    )

#------------------- Player comparison tab ------------------

def render_player_comparison_tab(*, nation_dirs: list[str], key_prefix: str = "cmp", use_league_norm: bool = False) -> None:
    """
    Compare up to 4 players on a radar and a phase-grouped metric table.

    Radar and table values are expressed as percentiles against:
      1. Each player's own league positional peers, or
      2. tier one positional peers if that mode is selected.
    """
    import html
    import re

    # build the combined Wyscout master table from all configured leagues
    master = _build_global_wyscout_master(nation_dirs)
    if master is None or master.empty:
        st.info("No league data available for comparison.")
        return
    
    if use_league_norm:
        master = _attach_league_strength(master)


    df_all = master.copy()

    # Canonical columns for this comparison view (same logic as Search tab)
    COL_PLAYER = next((c for c in df_all.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM   = next((c for c in df_all.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")
    COL_POS    = next((c for c in df_all.columns if c.lower() in {"position", "pos"}), "Position")

    if COL_PLAYER not in df_all.columns:
        st.info("No Player column found in comparison dataframe.")
        return

    df_all = df_all.dropna(subset=[COL_PLAYER]).copy()

    # Build disambiguation label for the comparison picker:
    # Name (with and without accents) · Team · LeagueKey
    league_series = df_all.get("__league_key", pd.Series([""] * len(df_all), index=df_all.index))

    name_series = df_all[COL_PLAYER].astype(str).str.strip()
    name_ascii  = name_series.map(_strip_accents)

    # Show both accented and non-accented forms if they differ
    name_display = name_series.where(
        name_series == name_ascii,
        name_series + " / " + name_ascii,
    )

    team_series = df_all[COL_TEAM].astype(str).fillna("").str.strip()
    league_txt  = league_series.astype(str).fillna("").str.strip()

    df_all["__cmp_label"] = name_display + " · " + team_series + " · " + league_txt

    # Use the label for the multiselect options
    available_players = (
        df_all["__cmp_label"]
        .dropna()
        .astype(str)
        .sort_values()
        .unique()
        .tolist()
    )


    

    st.markdown("## 🆚 Player comparison")

    # 0  small helper inside this function
    def _build_positional_cohort(row: pd.Series, mode: str) -> pd.DataFrame:
        """Return the cohort dataframe used for percentile ranking."""
        league_key = str(row.get("__league_key", ""))
        pos_raw = str(row.get("Position", "") or "")
        pos_tokens = [p.strip().upper() for p in re.split(r"[/,]", pos_raw) if p.strip()]

        # start from full master and then restrict
        if mode == "Own league positional peers":
            cohort = master.copy()
            if "__league_key" in cohort.columns and league_key:
                cohort = cohort[cohort["__league_key"].astype(str) == league_key]
        elif mode == "Tier 1 positional peers":
            cohort = _tier_one_benchmark_cohort(master)
        else:
            cohort = master.copy()

        # minutes filter for reliability
        if "Minutes played" in cohort.columns:
            mins = pd.to_numeric(cohort["Minutes played"], errors="coerce").fillna(0.0)
            cohort = cohort[mins >= 210]  # same threshold you use elsewhere

        # positional filter so MLS LW is compared to MLS LW etc
        if "Position" in cohort.columns and pos_tokens:
            pos_series = cohort["Position"].astype(str).str.upper()
            mask = pd.Series(False, index=cohort.index)
            for tok in pos_tokens:
                patt = rf"\b{_re.escape(tok)}\b"
                mask |= pos_series.str.contains(patt, regex=True, na=False)
            cohort = cohort[mask].copy()

        return cohort

    # 1  choose players
    st.markdown("### Select players")

    col_sel1, col_sel2 = st.columns([3, 1])

    with col_sel1:
        cmp_players = st.multiselect(
            "Players to compare ",
            options=available_players,
            default=[],
            key=f"{key_prefix}_players",
        )

    with col_sel2:
        min_mins = st.number_input(
            "Minimum minutes",
            min_value=0,
            max_value=10000,
            value=300,
            step=30,
            key=f"{key_prefix}_min_mins",
        )

    if not cmp_players:
        st.info("Select at least one player to start the comparison.")
        return

    cmp_df = df_all[df_all["__cmp_label"].isin(cmp_players)].copy()

    if "Minutes played" in cmp_df.columns:
        cmp_df["Minutes played"] = pd.to_numeric(cmp_df["Minutes played"], errors="coerce")
        cmp_df = cmp_df[cmp_df["Minutes played"].fillna(0.0) >= float(min_mins)]

    if cmp_df.empty:
        st.warning("No rows left after applying the minutes filter.")
        return

    # we keep one row per comparison label (player + team + league)
    sort_cols = ["__cmp_label"]
    if "__season" in cmp_df.columns:
        sort_cols = ["__cmp_label", "__season"]

    cmp_df = (
        cmp_df.sort_values(sort_cols)
              .groupby("__cmp_label", as_index=False)
              .tail(1)
              .reset_index(drop=True)
    )

    cmp_labels = list(cmp_df["__cmp_label"])



    # 2  KPI selection  auto from positional presets (like Search tab)
    st.markdown("### Comparison role and KPIs")

    # numeric columns we are allowed to use (treat columns as numeric
    # if at least ~50% of their values can be parsed as numbers)
    exclude_cols = [
        COL_PLAYER,
        COL_TEAM,
        COL_POS,
        "Birth country",
        "Passport country",
        "__league_key",
        "__season",
        "__source_file",
    ]

    all_numeric_cols: list[str] = []
    for c in cmp_df.columns:
        if c in exclude_cols:
            continue

        # work on a copy to avoid changing df dtypes here
        s = pd.to_numeric(cmp_df[c], errors="coerce")
        if s.notna().sum() >= max(2, 0.5 * len(s)):
            all_numeric_cols.append(c)


    if not all_numeric_cols:
        st.info("No numeric KPIs available for comparison.")
        return

    # infer available position tokens from the selected players
    pos_tokens: set[str] = set()
    if COL_POS in cmp_df.columns:
        for txt in cmp_df[COL_POS].dropna().astype(str):
            for tok in _re.split(r"[/,]", txt):
                tok = tok.strip().upper()
                if tok:
                    pos_tokens.add(tok)

    if not pos_tokens:
        st.warning("No Wyscout positions found for the selected players, cannot build positional comparison.")
        return

    role_options = sorted(pos_tokens)

    compare_role = st.selectbox(
        "Compare as position (for KPI preset)",
        options=role_options,
        index=0,
        key=f"{key_prefix}_cmp_role",
    )

    # decide KPI list based on the chosen role (position only)
    sel_kpis: list[str] = []

    try:
        presets_df = _LOAD_PRESETS_FOR_DA().copy()
    except Exception:
        presets_df = None

    if presets_df is not None and "Positions" in presets_df.columns and "KPIs" in presets_df.columns:
        pos_str = presets_df["Positions"].astype(str)
        # simple word-boundary match on the chosen position
        patt = rf"\b{_re.escape(compare_role)}\b"
        mask = pos_str.str.contains(patt, case=False, regex=True)
        if mask.any():
            kpi_string = presets_df.loc[mask].iloc[0]["KPIs"]
            if "_PARSE_LIST_FOR_DA" in globals():
                kpi_list = _PARSE_LIST_FOR_DA(kpi_string)
            else:
                kpi_list = [x.strip() for x in str(kpi_string).split(",")]
            sel_kpis = [m for m in kpi_list if m in all_numeric_cols]

    # if no positional preset found, fall back to a generic list
    if not sel_kpis:
        generic_defaults = [
            "Goals per 90",
            "Non-penalty goals per 90",
            "xG per 90",
            "Shots per 90",
            "Assists per 90",
            "xA per 90",
            "Passes per 90",
            "Progressive passes per 90",
            "Progressive runs per 90",
            "Successful defensive actions per 90",
            "Defensive duels per 90",
            "Defensive duels won, %",
        ]
        sel_kpis = [m for m in generic_defaults if m in all_numeric_cols] or all_numeric_cols[:20]


    if not sel_kpis:
        st.warning("No suitable KPIs found for comparison.")
        return


    # 3  comparison context selectors
    st.markdown("### Comparison context")

    pct_mode_key = f"{key_prefix}_pct_mode"
    valid_pct_modes = {"Own league positional peers", "Tier 1 positional peers"}
    if st.session_state.get(pct_mode_key) not in (None, *valid_pct_modes):
        st.session_state[pct_mode_key] = "Tier 1 positional peers"

    pct_mode = st.radio(
        "Percentile reference group",
        options=[
            "Own league positional peers",
            "Tier 1 positional peers",
        ],
        index=0,
        horizontal=True,
        key=pct_mode_key,
    )

    # always group by phases in the metric table
    show_phases = True


    # 4  build percentile map for each player and metric
    pct_map: dict[str, dict[str, float]] = {}
    value_map: dict[str, dict[str, float]] = {}

    for _, row in cmp_df.iterrows():
        label = str(row["__cmp_label"])
        pct_map[label] = {}
        value_map[label] = {}

        cohort = _build_positional_cohort(row, pct_mode)
        # leave early if cohort is empty; everything will be NaN
        # compute values + percentiles for ALL numeric metrics,
        # not only the selected KPI subset
        for metric in all_numeric_cols:
            raw_val = pd.to_numeric(row.get(metric), errors="coerce")
            value_map[label][metric] = raw_val

            if metric not in cohort.columns:
                pct_map[label][metric] = np.nan
                continue

            col_vals = pd.to_numeric(cohort[metric], errors="coerce")
            col_vals = col_vals[~col_vals.isna()]
            if col_vals.empty or np.isnan(raw_val):
                pct_map[label][metric] = np.nan
            else:
                pct_map[label][metric] = float(
                    _percentile_rank(col_vals, float(raw_val))
                )
    # 5  radar chart based on percentiles
    st.markdown("### Radar comparison")

    try:
        import plotly.graph_objects as go
    except Exception:
        st.warning("Plotly is not available, radar plot skipped.")
    else:
        fig = go.Figure()

        theta = sel_kpis + sel_kpis[:1]

        # separate colour mapping for readability
        base_colours = [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
        ]

        for idx, label in enumerate(cmp_labels):
            r_vals = [pct_map[label].get(m, np.nan) for m in sel_kpis]
            r_vals = [0.0 if (v is None or np.isnan(v)) else float(v) for v in r_vals]
            r_loop = r_vals + r_vals[:1]

            fig.add_trace(
                go.Scatterpolar(
                    r=r_loop,
                    theta=theta,
                    fill="toself",
                    name=label,
                    line=dict(width=2),
                    opacity=0.7,
                    marker=dict(color=base_colours[idx % len(base_colours)]),
                )
            )

        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    tickfont=dict(size=10),
                    gridcolor="rgba(200,200,200,0.15)",
                ),
                angularaxis=dict(
                    tickfont=dict(size=9),
                ),
            ),
            showlegend=True,
            margin=dict(l=40, r=40, t=40, b=40),
            height=520,
        )

        st.plotly_chart(fig, use_container_width=True)

    # -------------------------------------------
    # 5  roles and responsibilities blocks
    #-------------------------------------------

    st.markdown("### Roles, traits and responsibilities comparison")

    # Use the compare position token to decide the profile key
    profile_key_for_compare = _text_to_profile_key(compare_role) or _infer_profile_key(compare_role)

    if not profile_key_for_compare:
        st.info("No profile key derived from the comparison position, cannot render roles and responsibilities.")
    else:
        # This section is designed for true side by side readability
        show_df = cmp_df.copy()
        if len(show_df) > 2:
            st.caption("Showing the first 2 selected players for side by side blocks. Reduce selection to 2 for full comparison.")
            show_df = show_df.head(2)

        cols = st.columns(len(show_df), gap="large")

        for i, (_, prow) in enumerate(show_df.iterrows()):
            with cols[i]:
                pname = str(prow.get(COL_PLAYER, "")).strip() or f"Player {i+1}"
                pteam = str(prow.get(COL_TEAM, "")).strip()

                st.markdown(f"#### {pname}")
                if pteam:
                    st.caption(pteam)

                # Build cohort aligned to the chosen compare_role, not the player's own positions
                cohort = master.copy()
                league_key = str(prow.get("__league_key", "")).strip()

                if pct_mode == "Own league positional peers":
                    if "__league_key" in cohort.columns and league_key:
                        cohort = cohort[cohort["__league_key"].astype(str) == league_key]

                elif pct_mode == "Tier 1 positional peers":
                    cohort = _tier_one_benchmark_cohort(master)

                # Positional filter based on the selected compare_role token
                if COL_POS in cohort.columns and compare_role:
                    patt = rf"\b{_re.escape(compare_role)}\b"
                    cohort = cohort[COL_POS].astype(str).str.contains(patt, case=False, regex=True)
                    cohort = master.loc[cohort.index] if hasattr(cohort, "index") else master.copy()

                # If cohort collapsed, fall back to the already computed cohort logic
                if cohort is None or getattr(cohort, "empty", True):
                    cohort = _build_positional_cohort(prow, pct_mode)

                if cohort is None or cohort.empty:
                    st.info("No cohort available for this player in the chosen reference group and position.")
                else:
                    render_player_type_and_responsibilities_blocks(
                        cohort_df=cohort,
                        target_row=prow,
                        position_text=profile_key_for_compare,
                        ws_id="",
                        key_prefix=f"{key_prefix}_cmp_blocks_{i}",
                    )
    # -------------------------------------------

    # 6  metric-by-metric table, grouped by phase
    st.markdown("### Metric by metric comparison")

    # build phase to metrics mapping for the selected KPIs
    if show_phases and "phases" in globals():
        phase_to_metrics: dict[str, list[str]] = {}
        covered: set[str] = set()

        for phase_name, phase_list in phases.items():
            in_phase = [m for m in sel_kpis if m in phase_list]
            if in_phase:
                phase_to_metrics[phase_name] = in_phase
                covered.update(in_phase)

        leftover = [m for m in sel_kpis if m not in covered]
        if leftover:
            phase_to_metrics["Other"] = leftover
    else:
        phase_to_metrics = {"All metrics": sel_kpis}

    # CSS can reuse your existing metric table styles
    st.markdown(
        """
        <style>
        .metric-table {
            border-collapse: collapse;
            width: 100%;
            font-size: 12px;
        }
        .metric-table th,
        .metric-table td {
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding: 4px 6px;
            text-align: left;
            vertical-align: middle;
        }
        .metric-mname {
            font-weight: 600;
            white-space: nowrap;
        }
        .metric-raw {
            font-variant-numeric: tabular-nums;
            margin-bottom: 2px;
        }
        .metric-cell {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 120px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for phase_name, metrics in phase_to_metrics.items():
        st.markdown(f"#### {phase_name}")

        header_cells = ["<th>Metric</th>"] + [
            f"<th>{html.escape(label)}</th>" for label in cmp_labels
        ]

        rows_html: list[str] = []

        for metric in metrics:
            row_cells = [f"<td class='metric-mname'>{html.escape(metric)}</td>"]

            for label in cmp_labels:
                raw_val = value_map[label].get(metric, np.nan)
                if raw_val is None or (isinstance(raw_val, float) and np.isnan(raw_val)):
                    raw_str = "—"
                else:
                    if abs(raw_val) >= 10:
                        raw_str = f"{raw_val:.1f}"
                    else:
                        raw_str = f"{raw_val:.2f}"

                pct_val = pct_map.get(label, {}).get(metric, np.nan)
                if pct_val is None or (isinstance(pct_val, float) and np.isnan(pct_val)):
                    bar_html = "—"
                else:
                    bar_html = _pct_bar_html(float(pct_val))

                cell_html = (
                    "<div class='metric-cell'>"
                    f"<div class='metric-raw'>{raw_str}</div>"
                    f"{bar_html}"
                    "</div>"
                )
                row_cells.append(f"<td>{cell_html}</td>")

            rows_html.append("<tr>" + "".join(row_cells) + "</tr>")

        table_html = (
            "<table class='metric-table'>"
            "<thead><tr>"
            + "".join(header_cells)
            + "</tr></thead>"
            "<tbody>"
            + "".join(rows_html)
            + "</tbody></table>"
        )

        st.markdown(table_html, unsafe_allow_html=True)

    # -------------------------------------------
    # Extra block: show all attributes with the same HTML visuals
    # -------------------------------------------
    st.markdown("### All attributes (all metrics with percentiles)")

    base_cols = [COL_PLAYER, COL_TEAM, COL_POS]
    base_cols = [c for c in base_cols if c in cmp_df.columns]

    # Keep all numeric metrics; we will show them all here
    metrics_all = [c for c in all_numeric_cols if c not in base_cols]

    if not metrics_all:
        st.caption("No numeric attributes available to show.")
        return

    # table header: Metric + each selected player label
    import html as _html

    header_cells_all = ["<th>Metric</th>"] + [
        f"<th>{_html.escape(label)}</th>" for label in cmp_labels
    ]

    rows_html_all: list[str] = []

    for metric in metrics_all:
        row_cells = [f"<td class='metric-mname'>{_html.escape(metric)}</td>"]

        for label in cmp_labels:
            raw_val = value_map.get(label, {}).get(metric, np.nan)

            if raw_val is None or (isinstance(raw_val, float) and np.isnan(raw_val)):
                raw_str = "—"
            else:
                try:
                    raw_val_float = float(raw_val)
                    if abs(raw_val_float) >= 10:
                        raw_str = f"{raw_val_float:.1f}"
                    else:
                        raw_str = f"{raw_val_float:.2f}"
                except Exception:
                    raw_str = str(raw_val)

            pct_val = pct_map.get(label, {}).get(metric, np.nan)
            if pct_val is None or (isinstance(pct_val, float) and np.isnan(pct_val)):
                bar_html = "—"
            else:
                bar_html = _pct_bar_html(float(pct_val))

            cell_html = (
                "<div class='metric-cell'>"
                f"<div class='metric-raw'>{raw_str}</div>"
                f"{bar_html}"
                "</div>"
            )
            row_cells.append(f"<td>{cell_html}</td>")

        rows_html_all.append("<tr>" + "".join(row_cells) + "</tr>")

    table_html_all = (
        "<table class='metric-table'>"
        "<thead><tr>"
        + "".join(header_cells_all)
        + "</tr></thead>"
        "<tbody>"
        + "".join(rows_html_all)
        + "</tbody></table>"
    )

    st.markdown(table_html_all, unsafe_allow_html=True)

    # -------------------------------------------
    # 5  Similarity index and suggested extra players
    #     – always relative to the first selected player
    # -------------------------------------------
    st.markdown("### Similarity index and similar players")

    # if nothing selected, nothing to compare
    if not cmp_labels:
        st.caption("Select at least one player to see similarities.")
        return

    # features used for similarity: all numeric attributes from the full table
    sim_cols = [c for c in metrics_all if c in df_all.columns]

    if not sim_cols:
        st.caption("No numeric attributes available to compute similarity.")
        return

    # build a positional cohort from the global table
    cohort = df_all.copy()
    if COL_POS in cohort.columns and compare_role:
        cohort = cohort[
            cohort[COL_POS]
            .astype(str)
            .str.contains(compare_role, case=False, na=False)
        ].copy()

    # we need at least a couple of players in the cohort
    if cohort.empty or len(cohort) < 2:
        st.caption("Not enough players in the positional cohort to compute similarity.")
        return

    # numeric matrix for the cohort
    num = cohort[sim_cols].apply(pd.to_numeric, errors="coerce")

    # keep only reasonably populated and non-constant metrics
    valid_cols: list[str] = []
    n_rows = len(num)
    for c in sim_cols:
        col = num[c]
        if col.notna().sum() >= max(5, int(0.3 * n_rows)) and col.std(skipna=True) > 0:
            valid_cols.append(c)

    if not valid_cols:
        st.caption("Not enough stable numeric data in the cohort to compute similarity.")
        return

    num = num[valid_cols]

    # z-score within cohort for each metric
    mu = num.mean()
    sigma = num.std(ddof=0).replace(0, np.nan)
    num_z = (num - mu) / sigma

    # reference player: first selected player in the comparison list
    ref_label = cmp_labels[0]
    ref_row_cmp = cmp_df.loc[cmp_df["__cmp_label"] == ref_label].head(1)

    if ref_row_cmp.empty:
        st.caption("Reference player not found in the comparison data.")
        return

    ref_vals = pd.to_numeric(ref_row_cmp.iloc[0][valid_cols], errors="coerce")
    ref_z = (ref_vals - mu) / sigma

    def _cosine(a: pd.Series, b: pd.Series) -> float:
        va = a.to_numpy(dtype="float64")
        vb = b.to_numpy(dtype="float64")
        na = np.linalg.norm(va)
        nb = np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return np.nan
        return float(va.dot(vb) / (na * nb))

    # 5.1  Similarity between selected players only (no limit on how many)
    if len(cmp_labels) >= 2:
        st.markdown("#### Between selected players")

        rows = []
        for lab in cmp_labels[1:]:
            row_cmp = cmp_df.loc[cmp_df["__cmp_label"] == lab].head(1)
            if row_cmp.empty:
                continue

            vals = pd.to_numeric(row_cmp.iloc[0][valid_cols], errors="coerce")
            vals_z = (vals - mu) / sigma
            score = _cosine(ref_z, vals_z)

            rows.append(
                {
                    "Compared player": lab,
                    "Similarity (0–1)": round(score, 3) if pd.notna(score) else None,
                }
            )

        if rows:
            sim_df = pd.DataFrame(rows).sort_values("Similarity (0–1)", ascending=False)
            st.dataframe(sim_df, use_container_width=True)
        else:
            st.caption("Not enough overlapping data to compare the selected players.")

    # 5.2  Suggested extra similar players from the wider positional cohort
    st.markdown("#### Suggested extra similar players to add")

    # if we have __cmp_label, use it to exclude already-selected players
    if "__cmp_label" in cohort.columns:
        cohort = cohort[~cohort["__cmp_label"].isin(cmp_labels)].copy()
        num_z = num_z.loc[cohort.index]

    if cohort.empty:
        st.caption("No extra players available in this positional cohort.")
        return

    sims: list[tuple[int, float]] = []
    for idx, row_z in num_z.iterrows():
        score = _cosine(ref_z, row_z)
        if pd.notna(score):
            sims.append((idx, score))

    if not sims:
        st.caption("Could not compute similarity scores for the wider cohort.")
        return

    sims.sort(key=lambda x: x[1], reverse=True)
    sims = sims[:10]  # show top 10 suggestions

    out_rows: list[dict] = []
    for idx, score in sims:
        rec = cohort.loc[idx]
        out_rows.append(
            {
                "Player": rec.get(COL_PLAYER, ""),
                "Team": rec.get(COL_TEAM, ""),
                "Position": rec.get(COL_POS, ""),
                "Similarity (0–1)": round(score, 3),
            }
        )

    st.dataframe(pd.DataFrame(out_rows), use_container_width=True)


def render_analysis_block(
    label: str,
    df_all: pd.DataFrame,
    key_prefix: str,
    *,
    dea_block,
    export_buttons,
    _winsorise,
    _zscore,
    metric_direction,
    use_elo_norm: bool = False,
    use_tier_norm: bool = False,
) -> None:
    """Core analysis UI. Works on any concatenated dataframe `df_all`."""

    st.subheader(f"{label} league analysis")

    # same logic that you already have inside render_country_tab,
    # starting from COL_PLAYER = ... down to export_buttons(...)
    COL_PLAYER = next((c for c in df_all.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM = next((c for c in df_all.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")
    COL_POS = next((c for c in df_all.columns if c.lower() in {"position", "pos"}), "Position")


    COL_AGE = next((c for c in df_all.columns if c.lower() == "age"), "Age")
    COL_MIN = next((c for c in df_all.columns if "minute" in c.lower()), "Minutes played")
    COL_MV = next((c for c in df_all.columns if "market value" in c.lower() or c.lower() == "mv"), "Market value")
    COL_CONTRACT = next((c for c in df_all.columns if "contract" in c.lower()), "Contract expires")

    # remove exact duplicates coming from the same file and tier
    subset_cols = [c for c in [COL_PLAYER, COL_TEAM, COL_POS, "__tier", "__source_file"] if c in df_all.columns]
    if subset_cols:
        df_all = df_all.drop_duplicates(subset=subset_cols).reset_index(drop=True)


    if COL_MV in df_all.columns:
        df_all["_mv_eur"] = pd.to_numeric(df_all[COL_MV].map(parse_market_value), errors="coerce")
    else:
        df_all["_mv_eur"] = math.nan

    if COL_MIN in df_all.columns:
        df_all["_mins"] = pd.to_numeric(df_all[COL_MIN].map(parse_minutes), errors="coerce")
    else:
        df_all["_mins"] = math.nan

    if COL_CONTRACT in df_all.columns:
        df_all["_contract_dt"] = pd.to_datetime(df_all[COL_CONTRACT].map(parse_date_any), errors="coerce")
    else:
        df_all["_contract_dt"] = pd.NaT

    if "Height" in df_all.columns:
        df_all["_height_m"] = pd.to_numeric(df_all["Height"].map(_parse_height_m), errors="coerce")
    else:
        df_all["_height_m"] = math.nan

    BASE_COLS = [COL_PLAYER, COL_TEAM, "Foot", COL_POS, COL_AGE, COL_MV, COL_CONTRACT, "__tier", "__source_file"]
    
    # Attach Elo factor per team once, so it is available for weighting later
    df_all = _attach_elo_factor(df_all)
    elo_col = df_all["Elo"] if "Elo" in df_all.columns else pd.Series([pd.NA] * len(df_all), index=df_all.index)
    elo_num = pd.to_numeric(elo_col, errors="coerce")
    st.caption(f"Elo matched: {elo_num.notna().mean():.1%}")

    f1, f2, f3 = st.columns(3)
    q_name = f1.text_input("Search name", placeholder="Type part of a name…", key=f"{key_prefix}_qname")

    teams = sorted(df_all[COL_TEAM].dropna().astype(str).unique().tolist()) if COL_TEAM in df_all.columns else []
    sel_team = f2.multiselect("Teams", teams, key=f"{key_prefix}_teams")
    sel_pos = f3.multiselect("Positions (Wyscout style)", POS_CHOICES, key=f"{key_prefix}_pos")

    g1, g2 = st.columns(2)
    if COL_AGE in df_all.columns:
        age_series = pd.to_numeric(df_all[COL_AGE], errors="coerce")
        if age_series.notna().any():
            amin, amax = int(age_series.min()), int(age_series.max())
            age_rng = g1.slider(
                "Age range",
                value=(amin, amax),
                min_value=100,
                max_value=amax,
                key=f"{key_prefix}_age",
            )
        else:
            age_rng = None
    else:
        age_rng = None

    if pd.to_numeric(df_all["_mins"], errors="coerce").notna().any():
        mmin = int(pd.to_numeric(df_all["_mins"], errors="coerce").min())
        mmax = int(pd.to_numeric(df_all["_mins"], errors="coerce").max())
        mins_rng = g2.slider(
            "Minutes played",
            value=(mmin, mmax),
            min_value=mmin,
            max_value=mmax,
            step=10,
            key=f"{key_prefix}_mins",
        )
    else:
        mins_rng = None

    h1, h2 = st.columns(2)
    if pd.to_numeric(df_all["_height_m"], errors="coerce").notna().any():
        hmin = float(pd.to_numeric(df_all["_height_m"], errors="coerce").min())
        hmax = float(pd.to_numeric(df_all["_height_m"], errors="coerce").max())
        height_rng = h1.slider(
            "Height (m)",
            value=(round(hmin, 2), round(hmax, 2)),
            min_value=0.50,
            max_value=2.50,
            step=0.01,
            key=f"{key_prefix}_height",
        )
    else:
        height_rng = None

    j1, j2 = st.columns(2)
    if pd.to_numeric(df_all["_mv_eur"], errors="coerce").notna().any():
        mv_min = int(pd.to_numeric(df_all["_mv_eur"], errors="coerce").min())
        mv_max = int(pd.to_numeric(df_all["_mv_eur"], errors="coerce").max())
        mv_rng = j1.slider(
            "Market value (€)",
            value=(mv_min, mv_max),
            min_value=mv_min,
            max_value=mv_max,
            step=50_000,
            key=f"{key_prefix}_mv",
        )
    else:
        mv_rng = None

    if pd.to_datetime(df_all["_contract_dt"], errors="coerce").notna().any():
        cmin = pd.to_datetime(df_all["_contract_dt"]).min().date()
        cmax = pd.to_datetime(df_all["_contract_dt"]).max().date()
        contract_rng = j2.date_input(
            "Contract expires (range)",
            value=(cmin, cmax),
            format="YYYY-MM-DD",
            key=f"{key_prefix}_contract",
        )
    else:
        contract_rng = None

    helper_cols = {"_mv_eur", "_mins", "_contract_dt", "_height_m"}
    present_base = [c for c in BASE_COLS if c in df_all.columns]
    kpi_candidates = [c for c in df_all.columns if c not in present_base and c not in helper_cols]

    show_kpis = st.multiselect(
        "Pick KPI columns",
        options=kpi_candidates,
        default=[],                           # empty by default
        key=f"{key_prefix}_kpis",
    )

    view = df_all.copy()
    # -----------------------------
    # Expose current cohort + KPI set for other blocks (Moneyball, graphs, etc.)
    # -----------------------------
    if "feat_cols" not in locals():
        feat_cols = []

    st.session_state[f"{key_prefix}__cohort_view"] = view
    st.session_state[f"{key_prefix}__feat_cols"] = list(feat_cols)

    # Prefer the KPIs the user actually selected, else fall back to feat_cols
    st.session_state[f"{key_prefix}__kpi_cols"] = list(show_kpis) if show_kpis else list(feat_cols)

    # league normalisation must happen before scoring and percentiles
    if use_tier_norm and kpi_cols:
        cohort_view = _attach_tier_factor(cohort_view)
        cohort_view = _apply_league_factor_to_kpis(
            cohort_view, kpi_cols, "__tier_factor", metric_direction=metric_direction
        )

    elif use_elo_norm and kpi_cols:
        cohort_view = _attach_elo_factor(cohort_view)
        cohort_view = _apply_league_factor_to_kpis(
            cohort_view, kpi_cols, "__elo_factor", metric_direction=metric_direction
        )

    if q_name and COL_PLAYER in view.columns:
        view = view[view[COL_PLAYER].astype(str).str.contains(q_name, case=False, na=False)]

    if sel_team and COL_TEAM in view.columns:
        view = view[view[COL_TEAM].astype(str).isin(sel_team)]

    if sel_pos and COL_POS in view.columns:
        pos_series = view[COL_POS].astype(str).str.upper()
        mask = pd.Series(False, index=pos_series.index)
        for token in sel_pos:
            mask = mask | pos_series.str.contains(rf"\b{_re.escape(token.upper())}\b", regex=True)
        view = view[mask]

    if age_rng and COL_AGE in view.columns:
        ages = pd.to_numeric(view[COL_AGE], errors="coerce")
        view = view[(ages >= age_rng[0]) & (ages <= age_rng[1])]

    if mins_rng:
        mins_series = pd.to_numeric(view["_mins"], errors="coerce")
        view = view[(mins_series >= mins_rng[0]) & (mins_series <= mins_rng[1])]

    if mv_rng:
        mv_series = pd.to_numeric(view["_mv_eur"], errors="coerce")
        view = view[(mv_series >= mv_rng[0]) & (mv_series <= mv_rng[1])]

    if contract_rng:
        start_dt = pd.to_datetime(contract_rng[0])
        end_dt = pd.to_datetime(contract_rng[1])
        mask = (pd.to_datetime(view["_contract_dt"], errors="coerce") >= start_dt) & (
            pd.to_datetime(view["_contract_dt"], errors="coerce") <= end_dt
        )
        view = view[mask]

    if height_rng:
        hseries = pd.to_numeric(view["_height_m"], errors="coerce")
        view = view[(hseries >= height_rng[0]) & (hseries <= height_rng[1])]

    method = st.selectbox(
        "Statistical method",
        ["Z-score", "PCA (2D)", "DEA (outputs only)", "DEA (outputs / inputs)"],
        key=f"{key_prefix}_method",
    )

    dea_inputs = []
    if method.endswith("(outputs / inputs)"):
        dea_inputs = st.multiselect(
            "Inputs (DEA)",
            options=kpi_candidates,
            key=f"{key_prefix}_dea_inputs",
            help="If empty, a dummy input=1 is used",
        )

    run = st.button(f"Run analysis ({label})", type="primary", key=f"{key_prefix}_run")

    st.caption(f"Rows (after filters): {len(view)} / {len(df_all)}")

    if not show_kpis:
        st.info("Pick at least one KPI to analyse.")
        return

    if not run:
        return

    if method == "Z-score":
        mat = view[show_kpis].apply(pd.to_numeric, errors="coerce")
        zs = []
        for c in mat.columns:
            s = _winsorise(mat[c])
            z = _zscore(s)
            if not metric_direction(c):
                z = -z
            zs.append(z)
        score = np.nanmean(np.vstack(zs), axis=0) if zs else np.full(len(mat), math.nan)

    elif method.startswith("PCA"):
        try:
            from sklearn.preprocessing import StandardScaler
            from sklearn.decomposition import PCA

            X = view[show_kpis].apply(pd.to_numeric, errors="coerce")
            X = X.dropna(how="all")
            Xf = X.fillna(X.mean(numeric_only=True))
            Z = StandardScaler().fit_transform(Xf.values)
            pcs = PCA(n_components=1).fit_transform(Z).ravel()
            score = pd.Series(pcs, index=Xf.index).reindex(view.index)
        except Exception:
            st.warning("Install scikit-learn for PCA.")
            score = pd.Series([math.nan] * len(view), index=view.index)

    elif method.startswith("DEA"):
        dea_out = dea_block(view, outputs=show_kpis, inputs=dea_inputs if dea_inputs else None)
        score = dea_out.set_index(dea_out.index)["DEA_efficiency"].reindex(view.index)
    else:
        score = pd.Series([math.nan] * len(view), index=view.index)

    # Apply league-strength weighting to the score if requested
    if use_elo_norm and "_elo_factor" in view.columns:
        # Gentle, symmetric adjustment around 1.0
        elo_weight = 0.10  # 0.10 = max ~10% swing for big Elo differences
        f = pd.to_numeric(view["_elo_factor"], errors="coerce").fillna(1.0)
        score = score * (1.0 + elo_weight * (f - 1.0))


    id_cols = [c for c in ["Player", "Team", "Position", COL_AGE, "__tier"] if c in view.columns]
    if "__league_key" in view.columns:
        id_cols.insert(2, "__league_key")
    raw_cols = [c for c in show_kpis if c in view.columns]
    out = view[id_cols + raw_cols].copy()
    # Keep Elo factor visible for context if present
    if "_elo_factor" in view.columns:
        out["_elo_factor"] = view["_elo_factor"]
    out["Score"] = score
    out["Rank"] = out["Score"].rank(ascending=False, method="min")
    out = out.sort_values(["Rank", "Score"], ascending=[True, False])

    st.dataframe(out, use_container_width=True, hide_index=True)
    export_buttons(out, key_suf=f"_{key_prefix}_analysis_raw")

    # Optional Marc Lamberts style U21 emergence view for this cohort
    render_u21_emergence_block(df_all, view, key_prefix)

def render_u21_emergence_block(
    df_all: pd.DataFrame,
    df_filtered: pd.DataFrame,
    key_prefix: str,
) -> None:
    """
    Marc Lamberts style U21 emergence view for the current cohort.

    df_all      = full dataset for this league selection (before filters)
    df_filtered = already filtered view used for the main table
    key_prefix  = same key_prefix as the league tab (for Streamlit keys)
    """
    st.markdown("----")
    with st.expander("U21 emergence check", expanded=False):
        if df_filtered.empty:
            st.info("No data in the current cohort.")
            st.stop()


        df = df_filtered.copy()

        # Age
        if "Age" not in df.columns or pd.to_numeric(df["Age"], errors="coerce").isna().all():
            if "DOB" in df.columns and _COMPUTE_AGE_SERIES_FOR_DA is not None:
                df["Age"] = _COMPUTE_AGE_SERIES_FOR_DA(df)
            else:
                st.info("No Age or DOB column available to build U21 pool.")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.stop()



        ages_all = pd.to_numeric(df["Age"], errors="coerce")

        # Minutes
        if "Minutes played" in df.columns:
            df["_mins"] = pd.to_numeric(df["Minutes played"], errors="coerce")
        else:
            df["_mins"] = pd.to_numeric(df.get("_mins", pd.Series(dtype=float)), errors="coerce")

        if df["_mins"].notna().sum() == 0:
            st.info("No minutes column available to build U21 pool.")
            st.dataframe(df, use_container_width=True, hide_index=True)
            return

        mins_series = df["_mins"]
        mins_max = int(mins_series.max())
        default_gate = min(300, mins_max)

        min_mins = st.slider(
            "Minimum minutes for U21 gate",
            min_value=0,
            max_value=mins_max,
            value=default_gate,
            step=30,
            key=f"{key_prefix}_u21_min_mins",
        )

        # U21 gate
        df_u21 = df[(ages_all.notna()) & (ages_all <= 21) & (mins_series >= min_mins)]

        if df_u21.empty:
            st.info("No U21 players match the minutes gate in this cohort.")
            st.stop()

            # ----- Optional ClubElo normalisation -----
            if use_elo_norm:
                # add _elo_factor per team/league, cached from clubelo_cache.csv
                df_all = _attach_elo_factor(df_all)
            else:
                # neutral factor so later code can always assume the column exists
                if "_elo_factor" not in df_all.columns:
                    df_all["_elo_factor"] = 1.0

        # Ensure league key
        if "__league_key" not in df_all.columns:
            def _mk_key(r):
                nation = str(r.get("__nation", "")).strip()
                league = str(r.get("League", "") or r.get("Competition", "") or "").strip()
                tier = str(r.get("__tier", "")).strip()
                parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
                return " · ".join(parts) if parts else "Unknown"
            df_all["__league_key"] = df_all.apply(_mk_key, axis=1)
        if "__league_key" not in df_u21.columns:
            df_u21 = df_u21.merge(
                df_all[["__league_key"]].drop_duplicates(),
                left_index=True,
                right_index=True,
                how="left",
            )

        # Normalise minutes per league using full dataset
        apps_candidates = [
            c for c in df_all.columns
            if c.lower() in {"appearances", "apps", "matches", "games", "matches played"}
        ]
        if apps_candidates:
            apps_col = apps_candidates[0]
            df_apps = df_all.copy()
            df_apps["_apps"] = pd.to_numeric(df_apps[apps_col], errors="coerce")

            max_apps_per_league = df_apps.groupby("__league_key")["_apps"].max()
            max_minutes_per_league = max_apps_per_league * 90.0

            df_u21["__max_minutes_league"] = df_u21["__league_key"].map(max_minutes_per_league)
            df_u21["u21_norm_minutes_share"] = (
                df_u21["_mins"] / df_u21["__max_minutes_league"]
            )
        else:
            df_u21["u21_norm_minutes_share"] = pd.NA

        # Metric columns (robust names)
        col_g90 = _find_metric_col(df_u21, ["goals per 90", "goals p90", "goals/90", "goals_per_90"])
        col_xg90 = _find_metric_col(df_u21, ["xg per 90", "xg p90", "xg/90", "expected goals per 90"])
        col_sh90 = _find_metric_col(df_u21, ["shots per 90", "shots p90", "shots/90"])
        col_sot_pct = _find_metric_col(df_u21, ["shots on target %", "shots on target, %", "sot %"])

        needed = [col_g90, col_xg90, col_sh90, col_sot_pct]
        if any(c is None for c in needed):
            st.warning(
                "Cannot build Emergence index because one of "
                "Goals per 90, xG per 90, Shots per 90 or Shots on target % is missing."
            )
            st.dataframe(df_u21, use_container_width=True, hide_index=True)
            return


        g = pd.to_numeric(df_u21[col_g90], errors="coerce")
        xg = pd.to_numeric(df_u21[col_xg90], errors="coerce")
        sh = pd.to_numeric(df_u21[col_sh90], errors="coerce")
        sot = pd.to_numeric(df_u21[col_sot_pct], errors="coerce") / 100.0

        sh = sh.replace(0, np.nan)
        conv = g / sh
        xg_acc = g - xg
        shoot_eff = conv * sot

        feats = pd.DataFrame(
            {
                "G90": g,
                "xG90": xg,
                "Shots90": sh,
                "SoT": sot,
                "Conv": conv,
                "xGAcc": xg_acc,
                "ShootEff": shoot_eff,
            },
            index=df_u21.index,
        )

        def _z(s: pd.Series) -> pd.Series:
            m = s.mean(skipna=True)
            sd = s.std(skipna=True)
            if sd == 0 or np.isnan(sd):
                return pd.Series(0.0, index=s.index)
            return (s - m) / sd

        # Correlation based weights with goals per 90 as target
        target = feats["G90"]
        weights: dict[str, float] = {}
        for col in ["xG90", "Shots90", "SoT", "Conv", "xGAcc", "ShootEff"]:
            if feats[col].notna().sum() > 2:
                corr = target.corr(feats[col])
                if pd.isna(corr):
                    corr = 0.0
            else:
                corr = 0.0
            weights[col] = abs(corr)

        if sum(weights.values()) == 0:
            for k in weights:
                weights[k] = 1.0

        wsum = sum(weights.values())
        bps_vals = np.zeros(len(feats))
        for col, w in weights.items():
            bps_vals += _z(feats[col]).fillna(0.0).values * w
        bps_vals = bps_vals / wsum

        df_u21["BPS"] = bps_vals

        # Emergence index with age weighting inside U21 band
        ages_u21 = pd.to_numeric(df_u21["Age"], errors="coerce")
        age_factor = (23 - ages_u21).clip(lower=0) / 6.0
        df_u21["EmergenceIndex"] = _z(df_u21["BPS"]) * age_factor

        # Group so each player appears once per team and league
        COL_PLAYER = next(
            (c for c in df_u21.columns if c.lower() in {"player", "name", "player name"}),
            "Player",
        )
        COL_TEAM = next(
            (c for c in df_u21.columns if c.lower() in {"team", "club", "current team", "squad"}),
            "Team",
        )

        group_cols = [COL_PLAYER, COL_TEAM, "__league_key", "Age"]
        agg_cols = ["_mins", "u21_norm_minutes_share", "BPS", "EmergenceIndex"]

        df_group = (
            df_u21[group_cols + agg_cols]
            .groupby(group_cols, as_index=False)
            .agg({
                "_mins": "max",
                "u21_norm_minutes_share": "max",
                "BPS": "mean",
                "EmergenceIndex": "mean",
            })
        )

        if df_group.empty:
            st.info("No U21 rows left after grouping.")
            st.stop()


        metric_mode = st.radio(
            "Minutes metric for table",
            ["Normalised share", "Raw minutes"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}_u21_min_metric",
        )

        metric_col = "u21_norm_minutes_share" if metric_mode == "Normalised share" else "_mins"
        metric_title = "Share of possible league minutes" if metric_mode == "Normalised share" else "Minutes played"

        maxN = int(len(df_group))
        if maxN == 0:
            st.info("No U21 players left after grouping.")
            return

        maxN = len(df_group)
        maxN_eff = min(maxN, 50)

        if maxN_eff <= 1:
            # Only one U21 player passed the filters, no need for a slider
            topN = maxN_eff
            st.caption("Only one U21 player passed the U21 minutes gate in this cohort.")
        elif maxN_eff <= 5:
            # 2–5 players, show all of them without a slider
            topN = maxN_eff
            st.caption(f"Only {maxN_eff} U21 players passed the U21 minutes gate in this cohort.")
        else:
            # 6+ players, allow a slider from 5 up to maxN_eff
            minN_eff = 5
            topN = st.slider(
                "Number of players to show",
                min_value=minN_eff,
                max_value=maxN_eff,
                value=maxN_eff,
                step=1,
                key=f"{key_prefix}_u21_topN",
            )




        df_rank = df_group.sort_values("EmergenceIndex", ascending=False).head(topN)
        df_rank["Rank"] = range(1, len(df_rank) + 1)

        import altair as alt

        chart_data = df_rank[[COL_PLAYER, COL_TEAM, "Age", "__league_key", "BPS", "EmergenceIndex", metric_col]].copy()
        chart_data = chart_data.rename(columns={COL_PLAYER: "Player", metric_col: metric_title})

        chart = (
            alt.Chart(chart_data)
            .mark_bar()
            .encode(
                y=alt.Y("Player:N", sort="-x"),
                x=alt.X("EmergenceIndex:Q", title="Emergence index"),
                color=alt.Color("__league_key:N", title="League"),
                tooltip=[
                    alt.Tooltip("Player:N", title="Player"),
                    alt.Tooltip(f"{COL_TEAM}:N", title="Team"),
                    alt.Tooltip("Age:Q", title="Age"),
                    alt.Tooltip(metric_title + ":Q", title=metric_title, format=".3f"),
                    alt.Tooltip("BPS:Q", title="Base performance", format=".2f"),
                    alt.Tooltip("EmergenceIndex:Q", title="Emergence index", format=".2f"),
                    alt.Tooltip("__league_key:N", title="League"),
                ],
            )
            .properties(height=30 * len(chart_data), width="container")
        )
        st.altair_chart(chart, use_container_width=True)

        st.markdown("#### U21 ranking table for this cohort")
        df_rank["_mins_raw"] = df_rank["_mins"]
        df_rank["_mins_norm_share"] = df_rank["u21_norm_minutes_share"]

        display_cols = [
            "Rank",
            COL_PLAYER,
            COL_TEAM,
            "Age",
            "__league_key",
            "_mins_raw",
            "_mins_norm_share",
            "BPS",
            "EmergenceIndex",
        ]
        st.dataframe(df_rank[display_cols], use_container_width=True, hide_index=True)
        if _EXPORT_BUTTONS_FOR_DA is not None:
            _EXPORT_BUTTONS_FOR_DA(df_rank[display_cols], key_suf=f"_{key_prefix}_u21_emergence")



def render_country_tab(
    label: str,
    folder: str,
    file_prefix: str,
    key_prefix: str,
    *,
    dea_block,
    export_buttons,
    _winsorise,
    _zscore,
    metric_direction,
) -> None:
    ti1, ti2, ti3 = st.columns(3)
    t1 = ti1.checkbox("Tier 1", value=True, key=f"{key_prefix}_t1")
    t2 = ti2.checkbox("Tier 2", value=True, key=f"{key_prefix}_t2")
    t3 = ti3.checkbox("Tier 3", value=True, key=f"{key_prefix}_t3")
    tiers = [i for i, flag in zip([1, 2, 3], [t1, t2, t3]) if flag]

    frames = _collect_country_frames(folder, file_prefix, tiers)
    if not frames:
        st.error(f"No data found for {label} ({'–'.join(map(str, tiers))}).")
        st.stop()

    df_all = pd.concat(frames, ignore_index=True, sort=False)
    kpi_ready = bool(st.session_state.get(f"{key_prefix}__kpi_cols"))  # or your local kpi_cols list

    tier_norm = st.checkbox(
        "Normalise KPIs by league tier strength",
        key=f"da_tier_norm_{key_prefix}_{SUF}",
        value=False,
        disabled=not kpi_ready,
        help="Applies league tier coefficients to selected KPIs before radar, similarity, roles, traits, responsibilities.",
    )

    elo_norm = st.checkbox(
        "Normalise KPIs by ClubElo strength",
        key=f"da_elo_norm_{key_prefix}_{SUF}",
        value=False,
        disabled=not kpi_ready,
        help="Applies ClubElo factor to selected KPIs before scoring.",
    )

    render_analysis_block(
        label=label,
        df_all=df_all,
        key_prefix=key_prefix,
        dea_block=dea_block,
        export_buttons=export_buttons,
        _winsorise=_winsorise,
        _zscore=_zscore,
        metric_direction=metric_direction,
        use_elo_norm=elo_norm,
        use_tier_norm=tier_norm,
    )





def render_data_analysis_page(
    *,
    wyscout_folders,
    dea_block,
    export_buttons,
    _winsorise,
    _zscore,
    metric_direction,
    compute_age_series,
    _load_presets,
    _save_presets,
    _parse_list,
    _sanitize_defaults,
) -> None:
    """
    Public entry point that the main app calls when nav == '📊 Data analysis'.
    All heavy analysis helpers are supplied from the main module.
    """
   
    # default graph flags so they are always defined for this function
    force_positive: bool = True
    show_medians: bool = False
    show_trend: bool = False

    # expose helpers to module-level code (U21 block) via globals
    global _COMPUTE_AGE_SERIES_FOR_DA, _EXPORT_BUTTONS_FOR_DA
    global _LOAD_PRESETS_FOR_DA, _PARSE_LIST_FOR_DA

    _COMPUTE_AGE_SERIES_FOR_DA = compute_age_series
    _EXPORT_BUTTONS_FOR_DA = export_buttons
    _LOAD_PRESETS_FOR_DA = _load_presets
    _PARSE_LIST_FOR_DA = _parse_list


    # defaults for graph controls so they are always defined
    st.session_state.setdefault("g_pos_axes", True)
    st.session_state.setdefault("g_show_medians", False)
    st.session_state.setdefault("g_show_trend", False)
    # keep last 5 searches for Leagues and Graphs tabs
    st.session_state.setdefault("da_league_history", [])
    st.session_state.setdefault("g_graph_history", [])


    _render_data_analysis_styles()

    SUF = _safe_focus_suf()

    # Shared league normalisation (canonical key is already used in Leagues tab)
    SHARED_ELO_KEY = f"da_elo_norm_{SUF}"

    ELO_KEYS = {
        "leagues": SHARED_ELO_KEY,
        "graphs":  f"da_elo_norm_graphs_{SUF}",
        "search":  f"da_elo_norm_search_{SUF}",
        "compare": f"da_elo_norm_compare_{SUF}",
    }

    # Default
    if SHARED_ELO_KEY not in st.session_state:
        st.session_state[SHARED_ELO_KEY] = False

    # If any other tab key changed last run, promote it to shared
    for k in (ELO_KEYS["graphs"], ELO_KEYS["search"], ELO_KEYS["compare"]):
        if k in st.session_state and bool(st.session_state[k]) != bool(st.session_state[SHARED_ELO_KEY]):
            st.session_state[SHARED_ELO_KEY] = bool(st.session_state[k])
            break

    # Pre sync all widget keys before any checkbox widgets are created
    for k in ELO_KEYS.values():
        st.session_state[k] = bool(st.session_state[SHARED_ELO_KEY])


    STATE_KEY = f"da_league_norm_{SUF}"
    WIDGET_KEYS = {
        "leagues":  f"da_league_norm_leagues_{SUF}",
        "graphs":   f"da_league_norm_graphs_{SUF}",
        "search":   f"da_league_norm_search_{SUF}",
        "compare":  f"da_league_norm_compare_{SUF}",
    }

    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = False


    # nation folders discovered from your existing helper
    nation_dirs = wyscout_folders()
    if not nation_dirs:
        st.info("No nation folders found under WYS_ROOT_DIR yet.")
        return

    def _discover_divisions() -> pd.DataFrame:
        rows = []
        for folder in nation_dirs:
            prefix = os.path.basename(folder)
            nation_label = prefix
            frames = _collect_country_frames(folder, prefix, [1, 2, 3])
            for df in frames:
                tier = int(df["__tier"].iloc[0]) if "__tier" in df.columns else 0
                src = str(df["__source_file"].iloc[0]) if "__source_file" in df.columns else ""
                league_name = f"{nation_label} T{tier}"
                rows.append(
                    {
                        "__nation": nation_label,
                        "__league": league_name,
                        "__tier": tier,
                        "__league_key": f"{nation_label} · T{tier}",
                        "__folder": folder,
                        "__prefix": prefix,
                        "__src": src,
                    }
                )
        return pd.DataFrame(rows).drop_duplicates()

    overview_div_df = _discover_divisions()
    _ = update_clubelo_cache_if_needed()

    _render_data_analysis_header(
        nation_dirs=nation_dirs,
        div_df=overview_div_df,
        use_elo_norm=bool(st.session_state.get(SHARED_ELO_KEY, False)),
    )

    # -------------------------------------------------------------------
    # NATION SELECTION PANEL
    # -------------------------------------------------------------------
    nation_names = [os.path.basename(p) for p in nation_dirs]
    tab_labels = ["League context", "Data visualiser", "Player profile", "Player comparison", "Position search", "Team analysis"]
    
    jump_to = st.session_state.get("da_jump_to")

    if jump_to == "search":
        st.session_state["da_jump_to"] = None

        # Optional: a simple way back to the full Data analysis layout
        if st.button("Back to Data analysis"):
            st.rerun()

        # Render the exact same profile view as your Search tab
        render_player_search_tab(
            nation_dirs=wyscout_folders(),
            compute_age_series=compute_age_series,
            _load_presets=_load_presets,
            _parse_list=_parse_list,
            _sanitize_defaults=_sanitize_defaults,
            use_league_norm=bool(st.session_state.get("da_elo_norm_" + _safe_focus_suf(), False)),
        )
        return

    tabs = st.tabs(tab_labels)
    tab = {lab: tabs[i] for i, lab in enumerate(tab_labels)}


    # 1) LEAGUE ANALYSIS TAB
    with tab["League context"]:
        _render_data_tab_intro("League context", "Build the comparison universe first. This tab is where you choose the markets, tiers and strength adjustments before ranking players.")

        div_df = overview_div_df.copy()
        if div_df.empty:
            st.info("No league tier files found.")
        else:
            # recent searches for this tab
            league_history: list[dict] = st.session_state.get("da_league_history", [])
            if league_history:
                st.markdown("#### Recent league searches")
                for i, item in enumerate(reversed(league_history)):
                    label = item.get("label", "Previous search")
                    if st.button(label, key=f"da_hist_{i}"):
                        # restore previous selection before widgets are created
                        st.session_state[f"da_leagues_{SUF}"] = item.get("sel_divs", [])
                        st.session_state[f"da_include_all_leagues_{SUF}"] = item.get(
                            "include_all_leagues", False
                        )
                        st.session_state[f"da_top5_{SUF}"] = item.get("include_top5", False)
                        st.session_state[f"da_next7_{SUF}"] = item.get("include_next7", False)

                        # force presets to re apply cleanly on rerun
                        st.session_state.pop(f"da_div_preset_applied_{SUF}", None)

                        st.rerun()
            div_options = div_df["__league_key"].sort_values().unique().tolist()

            ms_key = f"da_leagues_{SUF}"
            top5_key = f"da_top5_{SUF}"
            next7_key = f"da_next7_{SUF}"
            all_key = f"da_include_all_leagues_{SUF}"
            applied_key = f"da_div_preset_applied_{SUF}"

            leagues_col, presets_col = st.columns([3, 1])

            with presets_col:
                include_top5 = st.checkbox("Top 5 leagues", key=top5_key, value=st.session_state.get(top5_key, False))
                include_next7 = st.checkbox("Next 7 leagues", key=next7_key, value=st.session_state.get(next7_key, False))
                include_all_leagues = st.checkbox("All leagues", key=all_key, value=st.session_state.get(all_key, False))
            include_all_leagues_da = include_all_leagues


            preset_state = (bool(include_top5), bool(include_next7), bool(include_all_leagues))

            # Only push preset selections when the preset state changes
            if st.session_state.get(applied_key) != preset_state:
                st.session_state[applied_key] = preset_state

                suggested: list[str] = []
                if include_top5:
                    suggested += _tier1_divs_for_nations(div_options, TOP5_NATIONS)
                if include_next7:
                    suggested += _tier1_divs_for_nations(div_options, NEXT7_NATIONS)

                if suggested:
                    st.session_state[ms_key] = _dedupe_keep_order(suggested)
                elif include_all_leagues:
                    st.session_state[ms_key] = []

            with leagues_col:
                sel_divs = st.multiselect(
                    "Peer Leagues / Tiers for League Analysis",
                    options=div_options,
                    key=ms_key,
                )

            # Safe defaults so we never hit NameError
            include_all_leagues_da = bool(st.session_state.get(f"da_include_all_leagues_{SUF}", False))
            sel_divs = st.session_state.get(f"da_leagues_{SUF}", [])

            # decide which leagues to load
            if include_all_leagues_da:
                chosen = div_df
            elif sel_divs:
                chosen = div_df[div_df["__league_key"].isin(sel_divs)]
            else:
                chosen = pd.DataFrame(columns=div_df.columns)

            if chosen.empty:
                st.info("Select at least one league tier above or tick 'All leagues'.")
            else:
                frames: list[pd.DataFrame] = []
                for _, row in chosen.iterrows():
                    folder = row["__folder"]
                    prefix = row["__prefix"]
                    tier = int(row["__tier"] or 0)
                    tiers = [tier] if tier else [1, 2, 3]
                    frames += _collect_country_frames(folder, prefix, tiers)

                if not frames:
                    st.info("No data for the selected leagues.")
                else:
                    df_all = pd.concat(frames, ignore_index=True, sort=False)

                    if include_all_leagues_da:
                        label = "All leagues"
                    else:
                        label = " / ".join(sorted(set(sel_divs)))
                    
                    # somewhere after you have built df_all and label for the Leagues tab:

                    elo_norm = st.checkbox(
                        "Adjust for league strength (ClubElo)",
                        value=False,
                        key=ELO_KEYS["leagues"],
                        help="Scales metrics by a league strength factor derived from ClubElo ratings.",
                    )

                    kpi_ready = bool(st.session_state.get(f"{key_prefix}__kpi_cols"))  # or your local kpi_cols list

                    tier_norm = st.checkbox(
                        "Normalise KPIs by league tier strength",
                        key=f"da_tier_norm_{key_prefix}_{SUF}",
                        value=False,
                        disabled=not kpi_ready,
                        help="Applies league tier coefficients to selected KPIs before radar, similarity, roles, traits, responsibilities.",
                    )

                    elo_norm = st.checkbox(
                        "Normalise KPIs by ClubElo strength",
                        key=f"da_elo_norm_{key_prefix}_{SUF}",
                        value=False,
                        disabled=not kpi_ready,
                        help="Applies ClubElo factor to selected KPIs before scoring.",
                    )


                    render_analysis_block(
                        label=label,
                        df_all=df_all,
                        key_prefix=f"multi_{SUF}",
                        dea_block=dea_block,
                        export_buttons=export_buttons,
                        _winsorise=_winsorise,
                        _zscore=_zscore,
                        metric_direction=metric_direction,
                        use_elo_norm=elo_norm,
                        use_tier_norm=tier_norm,
                    )
                    
                    #----------------------------------------------
                    # -----------------------------
                    # Moneyball (uses the cohort built inside render_analysis_block)
                    # -----------------------------
                    cohort_view = st.session_state.get(f"multi_{SUF}__cohort_view", None)
                    kpi_cols = st.session_state.get(f"multi_{SUF}__kpi_cols", [])

                    if cohort_view is not None and hasattr(cohort_view, "empty") and (not cohort_view.empty) and kpi_cols:
                        _debug_moneyball_inputs("Leagues tab", cohort_view, kpi_cols)
                        with st.expander("Moneyball", expanded=False):
                            try:
                                render_moneyball_block(
                                    df=cohort_view,
                                    kpi_cols=kpi_cols,
                                    metric_direction=metric_direction,
                                    title=f"Moneyball shortlist ({label})",
                                    key_prefix=f"multi_{SUF}_moneyball_leagues",
                                )
                            except Exception as e:
                                st.exception(e)
                                st.write("DEBUG cohort shape:", getattr(cohort_view, "shape", None))
                                st.write("DEBUG KPI count:", len(kpi_cols))
                                st.write("DEBUG KPIs:", kpi_cols[:30])
                                st.write("DEBUG columns sample:", list(cohort_view.columns)[:60])
                    else:
                        st.caption("Run the analysis block above to generate the cohort and KPI set for Moneyball.")


                    # update league search history
                    league_history: list[dict] = st.session_state.get("da_league_history", [])

                    entry = {
                        "sel_divs": list(sel_divs),
                        "include_all_leagues": bool(include_all_leagues_da),
                        "label": label or "League search",
                    }
                    entry["include_top5"] = bool(st.session_state.get(f"da_top5_{SUF}", False))
                    entry["include_next7"] = bool(st.session_state.get(f"da_next7_{SUF}", False))

                    if not league_history or league_history[-1] != entry:
                        league_history.append(entry)
                        # keep only last 5
                        if len(league_history) > 5:
                            league_history = league_history[-5:]
                        st.session_state["da_league_history"] = league_history




    # 2) graphs tab uses all nations
    with tab["Data visualiser"]:
        _render_data_tab_intro(
            "Data visualiser",
            "Turn selected KPIs into visual outlier checks. Use this when you want a quick picture of who separates from the market before opening profiles.",
        )
        st.subheader("Visual lab")

        _ = st.checkbox(
            "Adjust for league strength (ClubElo)",
            value=False,
            key=ELO_KEYS["graphs"],
            help="Scales metrics by a league strength factor derived from ClubElo ratings.",
        )

        elo_norm = bool(st.session_state[SHARED_ELO_KEY])

        div_df = overview_div_df.copy()

        # always define frames so later code is safe
        frames: list[pd.DataFrame] = []

        if div_df.empty:
            st.info("No divisions found.")
        else:
            # recent graph searches
            graph_history: list[dict] = st.session_state.get("g_graph_history", [])
            if graph_history:
                st.markdown("#### Recent visual searches")
                for i, item in enumerate(reversed(graph_history)):
                    label = item.get("label", "Previous visual search")
                    if st.button(label, key=f"g_hist_{i}"):
                        # restore previous filters before widgets are created
                        st.session_state[f"co_divs_{SUF}"] = item.get("sel_divs", [])
                        st.session_state[f"g_include_all_leagues_{SUF}"] = item.get(
                            "include_all_leagues", False
                        )
                        st.session_state[f"g_top5_{SUF}"] = item.get("include_top5", False)
                        st.session_state[f"g_next7_{SUF}"] = item.get("include_next7", False)

                        # force presets to re apply cleanly
                        st.session_state.pop(f"g_div_preset_applied_{SUF}", None)
                        st.session_state[f"co_divs_{SUF}"] = item.get("sel_divs", [])
                        st.session_state[f"g_include_all_leagues_{SUF}"] = item.get("include_all_leagues", False)

                        st.session_state[f"g_visual_mode_{SUF}"] = item.get(
                            "visual_mode",
                            "Quadrant matrix",
                        )
                        st.session_state["g_preset"] = item.get("sel_preset", "— None —")
                        st.session_state["g_positions"] = item.get("positions", [])
                        if "mins" in item and item["mins"]:
                            st.session_state["g_mins"] = tuple(item["mins"])
                        if "ages" in item and item["ages"]:
                            st.session_state["g_age"] = tuple(item["ages"])
                        st.session_state["g_kpis"] = item.get("kpis", [])
                        if "x_col" in item:
                            st.session_state["g_x2"] = item["x_col"]
                        if "y_col" in item:
                            st.session_state["g_y2"] = item["y_col"]
                        st.session_state["g_pos_axes"] = item.get(
                            "force_positive", st.session_state.get("g_pos_axes", True)
                        )
                        st.session_state["g_show_medians"] = item.get(
                            "show_medians",
                            st.session_state.get("g_show_medians", False),
                        )
                        st.session_state["g_show_trend"] = item.get(
                            "show_trend",
                            st.session_state.get("g_show_trend", False),
                        )
                        st.rerun()

            # one option per league / tier
            div_options = (
                div_df["__league_key"]
                .sort_values()
                .unique()
                .tolist()
            )

            ms_key = f"co_divs_{SUF}"
            top5_key = f"g_top5_{SUF}"
            next7_key = f"g_next7_{SUF}"
            all_key = f"g_include_all_leagues_{SUF}"
            applied_key = f"g_div_preset_applied_{SUF}"

            leagues_col, presets_col = st.columns([3, 1])

            with presets_col:
                include_top5 = st.checkbox("Top 5 leagues", key=top5_key, value=st.session_state.get(top5_key, False))
                include_next7 = st.checkbox("Next 7 leagues", key=next7_key, value=st.session_state.get(next7_key, False))
                include_all_leagues = st.checkbox("All leagues", key=all_key, value=st.session_state.get(all_key, False))
            include_all_leagues_da = include_all_leagues

            preset_state = (bool(include_top5), bool(include_next7), bool(include_all_leagues))

            if st.session_state.get(applied_key) != preset_state:
                st.session_state[applied_key] = preset_state

                suggested: list[str] = []
                if include_top5:
                    suggested += _tier1_divs_for_nations(div_options, TOP5_NATIONS)
                if include_next7:
                    suggested += _tier1_divs_for_nations(div_options, NEXT7_NATIONS)

                if suggested:
                    st.session_state[ms_key] = _dedupe_keep_order(suggested)
                elif include_all_leagues:
                    st.session_state[ms_key] = []

            with leagues_col:
                sel_divs = st.multiselect(
                    "Peer Leagues / Tiers for Visual Lab",
                    options=div_options,
                    key=ms_key,
                )

            # decide what to load
            if include_all_leagues:
                # every league row in div_df
                chosen_divs = div_df
            elif sel_divs:
                # only selected leagues
                chosen_divs = div_df[div_df["__league_key"].isin(sel_divs)]
            else:
                # nothing selected and checkbox off
                chosen_divs = pd.DataFrame(columns=div_df.columns)

            # build frames for the chosen divisions
            if not chosen_divs.empty:
                for _, row in chosen_divs.iterrows():
                    folder = row["__folder"]
                    prefix = row["__prefix"]
                    tier = int(row["__tier"] or 0)
                    tiers = [tier] if tier else [1, 2, 3]
                    frames += _collect_country_frames(folder, prefix, tiers)

        # SAFE: always load presets first
        presets_df = _load_presets()

        if not frames:
            st.info("No data for the chosen divisions.")
            # create empty dfG to avoid further errors
            dfG = pd.DataFrame()
        else:
            dfG = pd.concat(frames, ignore_index=True, sort=False)
            subset_cols = [
                c
                for c in ["Player", "Team", "Position", "__tier", "__source_file"]
                if c in dfG.columns
            ]
            if subset_cols:
                dfG = (
                    dfG.drop_duplicates(subset=subset_cols)
                    .reset_index(drop=True)
                )

        preset_names = ["— None —"] + sorted(
            presets_df["Profile"].dropna().astype(str).unique().tolist()
        )
        preset_left, preset_right = st.columns([2, 1])

        sel_preset = preset_left.selectbox(
            "Preset (Role profile preset)",
            options=preset_names,
            index=0,
            key="g_preset",
        )

        preset_kpis, preset_positions = [], []
        if sel_preset != "— None —":
            prow = presets_df[presets_df["Profile"] == sel_preset]
            if not prow.empty:
                preset_kpis = _parse_list(prow.iloc[0].get("KPIs", ""))
                preset_positions = _parse_list(prow.iloc[0].get("Positions", ""))

        if st.session_state.get("g_preset_last") != sel_preset:
            st.session_state["g_preset_last"] = sel_preset
            if sel_preset != "— None —":
                st.session_state["g_positions"] = preset_positions[:]
                st.session_state["g_kpis"] = preset_kpis[:]
            else:
                st.session_state.setdefault("g_positions", [])
                st.session_state.setdefault("g_kpis", [])

        if "__league_key" not in dfG.columns:
            def _mk_key(r):
                nation = str(r.get("__nation", "")).strip()
                league = str(r.get("League", "") or r.get("Competition", "") or "").strip()
                tier = str(r.get("__tier", "")).strip()
                parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
                return " · ".join(parts) if parts else "Unknown"

            dfG["__league_key"] = dfG.apply(_mk_key, axis=1)

        COL_PLAYER = next(
            (c for c in dfG.columns if c.lower() in {"player", "name", "player name"}),
            "Player",
        )
        COL_TEAM = next(
            (c for c in dfG.columns if c.lower() in {"team", "club", "current team", "squad"}),
            "Team",
        )

        if "Age" not in dfG.columns or pd.to_numeric(dfG["Age"], errors="coerce").isna().all():
            if "DOB" in dfG.columns:
                dfG["Age"] = compute_age_series(dfG)
            else:
                dfG["Age"] = pd.NA

        pos_all = POS_CHOICES if "POS_CHOICES" in globals() else sorted(
            dfG.get("Position", pd.Series([], dtype=str)).dropna().unique().tolist()
        )

        def _sanitize_positions(lst, options):
            lst = lst or []
            valid = [p for p in lst if p in options]
            missing = [p for p in lst if p not in options]
            return valid, missing

        valid_preset_positions, missing_preset_positions = _sanitize_positions(
            preset_positions,
            pos_all,
        )

        if st.session_state.get("g_preset_last_pos") != sel_preset:
            st.session_state["g_preset_last_pos"] = sel_preset
            if sel_preset != "— None —":
                st.session_state["g_positions"] = valid_preset_positions[:]

        if sel_preset != "— None —" and missing_preset_positions:
            st.caption(
                f"Dropped positions not in options: {', '.join(missing_preset_positions)}"
            )

        fcol1, fcol2 = st.columns([2, 1])
        sel_positions = fcol1.multiselect(
            "Positions (Wyscout style)",
            options=pos_all,
            default=st.session_state.get("g_positions", valid_preset_positions)
            or valid_preset_positions,
            key="g_positions",
        )

        if "Minutes played" in dfG.columns:
            mins_series = pd.to_numeric(dfG["Minutes played"], errors="coerce")
        else:
            if "_mins" not in dfG.columns:
                dfG["_mins"] = pd.to_numeric(
                    dfG.get("Minutes played", pd.Series(dtype=str)).map(parse_minutes),
                    errors="coerce",
                )
            mins_series = pd.to_numeric(dfG.get("_mins", pd.Series(dtype=float)), errors="coerce")

        if mins_series.notna().any():
            mn = int(max(0, float(mins_series.min())))
            mx = int(float(mins_series.max()))
            sel_min, sel_max = fcol2.slider(
                "Minutes played",
                value=(mn, mx),
                min_value=mn,
                max_value=mx,
                step=10,
                key="g_mins",
            )
        else:
            sel_min, sel_max = None, None

        # Age slider
        if "Age" in dfG.columns:
            age_series = pd.to_numeric(dfG["Age"], errors="coerce")
            age_series = age_series[age_series.notna()]
            if not age_series.empty:
                a_min = int(age_series.min())
                a_max = int(age_series.max())
                if a_min == a_max:
                    a_min = max(0, a_min - 1)
                    a_max = a_max + 1
                sel_age_min, sel_age_max = fcol2.slider(
                    "Age",
                    value=(a_min, a_max),
                    min_value=a_min,
                    max_value=a_max,
                    step=1,
                    key="g_age",
                )
            else:
                sel_age_min, sel_age_max = None, None
        else:
            sel_age_min, sel_age_max = None, None

        dfV = dfG.copy()

        if sel_positions and "Position" in dfV.columns:
            s = dfV["Position"].astype(str).str.upper()
            mask = pd.Series(False, index=s.index)
            for token in sel_positions:
                mask = mask | s.str.contains(rf"\b{_re.escape(token.upper())}\b", regex=True)
            dfV = dfV[mask]

        if sel_min is not None and sel_max is not None:
            mins_series_v = mins_series.reindex(dfV.index)
            dfV = dfV[(mins_series_v >= sel_min) & (mins_series_v <= sel_max)]

        if (
            "Age" in dfV.columns
            and sel_age_min is not None
            and sel_age_max is not None
        ):
            ages_v = pd.to_numeric(dfV["Age"], errors="coerce")
            dfV = dfV[(ages_v >= sel_age_min) & (ages_v <= sel_age_max)]

        numeric_cols_G = sorted(
            [
                c
                for c in dfV.columns
                if pd.api.types.is_numeric_dtype(pd.to_numeric(dfV[c], errors="coerce"))
            ]
        )

        valid_preset_kpis, missing_preset_kpis = _sanitize_defaults(
            preset_kpis,
            numeric_cols_G,
        )

        st.session_state["g_kpis"] = [
            k for k in st.session_state.get("g_kpis", []) if k in numeric_cols_G
        ]

        if st.session_state.get("g_preset_last_sanitized") != sel_preset:
            st.session_state["g_preset_last_sanitized"] = sel_preset
            if sel_preset != "— None —":
                st.session_state["g_kpis"] = valid_preset_kpis[:]

        if sel_preset != "— None —" and missing_preset_kpis:
            st.caption(
                f"Dropped {len(missing_preset_kpis)} preset KPI(s) not present in this dataset: "
                f"{', '.join(missing_preset_kpis)}"
            )

        visual_modes = ["Quadrant matrix", "Distribution view", "Outlier scatter"]
        visual_mode = st.radio(
            "Visual lab",
            visual_modes,
            index=0,
            horizontal=True,
            key=f"g_visual_mode_{SUF}",
            help="Choose the visual type first, then select the KPI set that feeds it.",
        )

        if visual_mode == "Quadrant matrix":
            st.caption("Best for separating player types across two KPI axes or two composite KPI groups.")
        elif visual_mode == "Distribution view":
            st.caption("Best for checking where each player sits inside the selected market by league tier or position.")
        else:
            st.caption("Best for a cleaner scatter view when you only want to spot outliers without quadrant interpretation.")

        kpi_limit = 12 if visual_mode == "Distribution view" else 30
        kpi_help = "Pick one or more KPIs for the distribution charts." if visual_mode == "Distribution view" else "Pick two KPIs for a direct matrix, or more than two to build composite axes."

        kpi_col, apply_col = st.columns([3, 1])
        kpG = kpi_col.multiselect(
            "KPIs",
            numeric_cols_G,
            default=st.session_state.get("g_kpis", valid_preset_kpis) or valid_preset_kpis,
            max_selections=kpi_limit,
            key="g_kpis",
            help=kpi_help,
        )

        if sel_preset != "— None —":
            if apply_col.button("Apply preset", key="g_apply_preset"):
                st.session_state["g_kpis"] = [k for k in preset_kpis if k in numeric_cols_G]
                st.rerun()

        def _short_axis_label(label: str, max_chars: int = 28) -> str:
            s = str(label or "").strip()
            if len(s) <= max_chars:
                return s
            return s[: max_chars - 1].rstrip() + "…"

        def _metric_is_higher_better(metric: str) -> bool:
            try:
                return bool(metric_direction(metric))
            except Exception:
                return True

        def _safe_numeric_frame(df_in: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
            out = df_in.copy()
            for col in cols:
                if col in out.columns:
                    out[col] = pd.to_numeric(out[col], errors="coerce")
            return out

        def _unique_cols(cols: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for col in cols:
                if col in seen:
                    continue
                seen.add(col)
                out.append(col)
            return out

        def _composite(df_in: pd.DataFrame, cols: list[str], w_str: str) -> pd.Series:
            if not cols:
                return pd.Series(index=df_in.index, dtype=float)

            mat = df_in[cols].apply(pd.to_numeric, errors="coerce").copy()
            for c in cols:
                mat[c] = _winsorise(mat[c])
                if not _metric_is_higher_better(c):
                    mat[c] = -mat[c]
                mat[c] = _zscore(mat[c])

            try:
                weights = [
                    float(x.strip())
                    for x in (w_str or "").split(",")
                    if x.strip() != ""
                ]
                if len(weights) != len(cols):
                    weights = [1.0] * len(cols)
            except Exception:
                weights = [1.0] * len(cols)

            weight_sum = sum(abs(w) for w in weights)
            if weight_sum == 0:
                weights = [1.0] * len(cols)
                weight_sum = float(len(cols))

            comp = (mat.values * np.array(weights)).sum(axis=1) / weight_sum
            return pd.Series(comp, index=mat.index)

        def _quadrant_label_frame(
            df_plot: pd.DataFrame,
            x_field: str,
            y_field: str,
            x_label: str,
            y_label: str,
        ) -> tuple[pd.DataFrame, float, float]:
            x_med = float(df_plot[x_field].median())
            y_med = float(df_plot[y_field].median())

            x_min = float(df_plot[x_field].min())
            x_max = float(df_plot[x_field].max())
            y_min = float(df_plot[y_field].min())
            y_max = float(df_plot[y_field].max())

            if x_min == x_max:
                x_min -= 0.5
                x_max += 0.5
            if y_min == y_max:
                y_min -= 0.5
                y_max += 0.5

            x_low = (x_min + x_med) / 2.0
            x_high = (x_med + x_max) / 2.0
            y_low = (y_min + y_med) / 2.0
            y_high = (y_med + y_max) / 2.0

            x_txt = _short_axis_label(x_label)
            y_txt = _short_axis_label(y_label)

            labels = pd.DataFrame(
                [
                    {x_field: x_low, y_field: y_high, "__quad_label": f"High {y_txt} | Low {x_txt}"},
                    {x_field: x_high, y_field: y_high, "__quad_label": f"High {y_txt} | High {x_txt}"},
                    {x_field: x_low, y_field: y_low, "__quad_label": f"Low {y_txt} | Low {x_txt}"},
                    {x_field: x_high, y_field: y_low, "__quad_label": f"Low {y_txt} | High {x_txt}"},
                ]
            )
            return labels, x_med, y_med

        def _scatter_layers(
            df_plot: pd.DataFrame,
            *,
            x_field: str,
            y_field: str,
            x_title: str,
            y_title: str,
            colour_title: str,
            show_quadrants: bool,
            show_median_lines: bool,
            show_trend_line: bool,
        ):
            tooltip_fields = [
                alt.Tooltip(COL_PLAYER, title="Player"),
                alt.Tooltip(COL_TEAM, title="Team"),
                alt.Tooltip("Age:Q", title="Age"),
                alt.Tooltip(x_field + ":Q", title=x_title, format=".3f"),
                alt.Tooltip(y_field + ":Q", title=y_title, format=".3f"),
                alt.Tooltip("__league_key:N", title="League"),
            ]

            base_scatter = (
                alt.Chart(df_plot.reset_index(drop=True))
                .mark_circle(size=70, opacity=0.85)
                .encode(
                    x=alt.X(x_field, type="quantitative", title=x_title),
                    y=alt.Y(y_field, type="quantitative", title=y_title),
                    color=alt.Color("__league_key:N", title=colour_title),
                    tooltip=tooltip_fields,
                )
                .interactive()
            )

            layers = [base_scatter]

            if show_quadrants or show_median_lines:
                labels, x_med, y_med = _quadrant_label_frame(
                    df_plot,
                    x_field,
                    y_field,
                    x_title,
                    y_title,
                )

                x_rule = (
                    alt.Chart(pd.DataFrame({x_field: [x_med]}))
                    .mark_rule(strokeDash=[4, 4], strokeWidth=1.5)
                    .encode(x=alt.X(x_field, type="quantitative"))
                )
                y_rule = (
                    alt.Chart(pd.DataFrame({y_field: [y_med]}))
                    .mark_rule(strokeDash=[4, 4], strokeWidth=1.5)
                    .encode(y=alt.Y(y_field, type="quantitative"))
                )
                layers.extend([x_rule, y_rule])

                if show_quadrants:
                    label_layer = (
                        alt.Chart(labels)
                        .mark_text(
                            align="center",
                            baseline="middle",
                            opacity=0.55,
                            fontSize=12,
                            fontWeight="bold",
                        )
                        .encode(
                            x=alt.X(x_field, type="quantitative"),
                            y=alt.Y(y_field, type="quantitative"),
                            text=alt.Text("__quad_label:N"),
                        )
                    )
                    layers.append(label_layer)

            if show_trend_line and not df_plot.empty:
                trend = (
                    alt.Chart(df_plot.reset_index(drop=True))
                    .transform_regression(x_field, y_field)
                    .mark_line()
                    .encode(
                        x=alt.X(x_field, type="quantitative"),
                        y=alt.Y(y_field, type="quantitative"),
                    )
                )
                layers.append(trend)

            return alt.layer(*layers).resolve_scale(color="independent").properties(height=560)

        def _rank_table(
            df_in: pd.DataFrame,
            rank_kpis: list[str],
            *,
            score_label: str = "Score (z avg)",
            limit: int = 100,
        ) -> pd.DataFrame:
            base_cols = [c for c in [COL_PLAYER, COL_TEAM, "Age", "__league_key", "Position"] if c in df_in.columns and c not in rank_kpis]
            out = df_in[_unique_cols(base_cols + rank_kpis)].copy()
            for c in rank_kpis:
                out[c] = pd.to_numeric(out[c], errors="coerce")

            if not rank_kpis:
                return out

            score_frame = pd.DataFrame(index=out.index)
            for c in rank_kpis:
                s = _winsorise(out[c])
                if not _metric_is_higher_better(c):
                    s = -s
                score_frame[c] = _zscore(s)

            out[score_label] = score_frame[rank_kpis].mean(axis=1, skipna=True)
            out = out.dropna(subset=[score_label])
            out["Rank"] = out[score_label].rank(ascending=False, method="min").astype(int)

            ordered_cols = ["Rank"] + base_cols + [score_label] + rank_kpis
            ordered_cols = [c for c in ordered_cols if c in out.columns]
            return out.sort_values(["Rank", score_label], ascending=[True, False]).head(limit)[ordered_cols]

        def _record_visual_history(
            *,
            x_col: str | None = None,
            y_col: str | None = None,
        ) -> None:
            graph_history: list[dict] = st.session_state.get("g_graph_history", [])

            entry: dict = {
                "sel_divs": list(sel_divs),
                "include_all_leagues": bool(include_all_leagues),
                "visual_mode": visual_mode,
                "sel_preset": sel_preset,
                "positions": list(sel_positions),
                "mins": (sel_min, sel_max),
                "ages": (sel_age_min, sel_age_max),
                "kpis": list(kpG),
                "force_positive": bool(st.session_state.get("g_pos_axes", True)),
                "show_medians": bool(st.session_state.get("g_show_medians", False)),
                "show_trend": bool(st.session_state.get("g_show_trend", False)),
                "include_top5": bool(st.session_state.get(f"g_top5_{SUF}", False)),
                "include_next7": bool(st.session_state.get(f"g_next7_{SUF}", False)),
            }
            if x_col:
                entry["x_col"] = x_col
            if y_col:
                entry["y_col"] = y_col

            label_parts: list[str] = [visual_mode]
            if include_all_leagues:
                label_parts.append("All leagues")
            elif sel_divs:
                label_parts.append(f"{len(sel_divs)} leagues")

            if sel_preset != "— None —":
                label_parts.append(sel_preset)

            if sel_positions:
                label_parts.append("/".join(sorted(sel_positions)))

            entry["label"] = " | ".join(label_parts) or "Visual search"

            if not graph_history or graph_history[-1] != entry:
                graph_history.append(entry)
                if len(graph_history) > 5:
                    graph_history = graph_history[-5:]
                st.session_state["g_graph_history"] = graph_history

        def _render_rankings(rank_kpis: list[str], key_suf: str) -> None:
            if not rank_kpis:
                st.info("Pick at least one KPI above to compute rankings.")
                return

            rank_table = _rank_table(dfV, rank_kpis, limit=100)
            if rank_table.empty:
                st.info("No ranking table available for the selected KPI set.")
                return

            st.markdown("### Ranking table")
            st.dataframe(rank_table, use_container_width=True, hide_index=True)
            export_buttons(rank_table, key_suf=key_suf)

        def _render_two_axis_visual(
            *,
            show_quadrants: bool,
            allow_trend: bool,
        ) -> None:
            if len(kpG) == 2:
                c1, c2 = st.columns(2)
                x_col = c1.selectbox("X axis", kpG, index=0, key="g_x2")
                y_col = c2.selectbox("Y axis", kpG, index=1, key="g_y2")

                base_cols = [COL_PLAYER, COL_TEAM, "Age", "__league_key", x_col, y_col]
                base_cols = _unique_cols([c for c in base_cols if c in dfV.columns])
                dfp = dfV[base_cols].copy()
                dfp[x_col] = pd.to_numeric(dfp[x_col], errors="coerce")
                dfp[y_col] = pd.to_numeric(dfp[y_col], errors="coerce")
                dfp = dfp.dropna(subset=[x_col, y_col])

                if dfp.empty:
                    st.info("No rows left after removing blank values for the selected axes.")
                    return

                if force_positive:
                    minx, miny = float(dfp[x_col].min()), float(dfp[y_col].min())
                    if minx < 0:
                        dfp[x_col] -= minx
                    if miny < 0:
                        dfp[y_col] -= miny

                chart = _scatter_layers(
                    dfp,
                    x_field=x_col,
                    y_field=y_col,
                    x_title=x_col,
                    y_title=y_col,
                    colour_title="League",
                    show_quadrants=show_quadrants,
                    show_median_lines=True if show_quadrants else show_medians,
                    show_trend_line=allow_trend and show_trend,
                )
                st.altair_chart(chart, use_container_width=True)
                _record_visual_history(x_col=x_col, y_col=y_col)
                _render_rankings(kpG[:], key_suf="_graph_two_axis")
                return

            if len(kpG) > 2:
                st.caption("Select two composite axes. The app z scores each KPI, applies optional weights, then averages.")
                left, right = st.columns(2)
                x_kpis = left.multiselect("X composite KPIs", kpG, key="g_xk")
                y_kpis = right.multiselect("Y composite KPIs", kpG, key="g_yk")
                w_left = left.text_input(
                    "X weights, comma separated",
                    key="g_xw",
                    placeholder="1,1,1",
                )
                w_right = right.text_input(
                    "Y weights, comma separated",
                    key="g_yw",
                    placeholder="1,1,1",
                )

                if not x_kpis or not y_kpis:
                    st.info("Pick at least one KPI for each composite axis.")
                    return

                mat = dfV.copy()
                base_cols = [c for c in [COL_PLAYER, COL_TEAM, "Age", "__league_key"] if c in mat.columns]
                dfp = mat[base_cols].copy()
                dfp["X"] = _composite(mat, x_kpis, w_left)
                dfp["Y"] = _composite(mat, y_kpis, w_right)
                dfp = dfp.dropna(subset=["X", "Y"])

                if dfp.empty:
                    st.info("No rows left after creating the composite axes.")
                    return

                if force_positive:
                    minx, miny = float(dfp["X"].min()), float(dfp["Y"].min())
                    if minx < 0:
                        dfp["X"] -= minx
                    if miny < 0:
                        dfp["Y"] -= miny

                chart = _scatter_layers(
                    dfp,
                    x_field="X",
                    y_field="Y",
                    x_title=f"Composite X ({', '.join(x_kpis)})",
                    y_title=f"Composite Y ({', '.join(y_kpis)})",
                    colour_title="League / Tier",
                    show_quadrants=show_quadrants,
                    show_median_lines=True if show_quadrants else show_medians,
                    show_trend_line=allow_trend and show_trend,
                )
                st.altair_chart(chart, use_container_width=True)
                _record_visual_history(x_col="Composite X", y_col="Composite Y")
                _render_rankings(kpG[:], key_suf="_graph_composite")
                return

            st.info("Pick at least two KPIs for this visual mode.")

        def _position_group_value(value: str) -> str:
            raw = str(value or "").replace("/", ",").replace(";", ",").replace("|", ",")
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            return parts[0] if parts else "Unknown"

        def _render_distribution_view() -> None:
            if not kpG:
                st.info("Pick at least one KPI to build the distribution view.")
                return

            group_choices = ["League / Tier"]
            if "Position" in dfV.columns:
                group_choices.append("Position")

            group_by = st.selectbox(
                "Group distribution by",
                options=group_choices,
                index=0,
                key=f"g_distribution_group_{SUF}",
            )

            st.caption("Each chart shows the market spread with box plots and every player as a dot.")

            for metric in kpG[:12]:
                base_cols = [COL_PLAYER, COL_TEAM, "Age", "__league_key"]
                if "Position" in dfV.columns:
                    base_cols.append("Position")
                base_cols = [c for c in base_cols if c in dfV.columns and c != metric]

                dfd = dfV[_unique_cols(base_cols + [metric])].copy()
                dfd["__metric_value"] = pd.to_numeric(dfd[metric], errors="coerce")
                dfd = dfd.dropna(subset=["__metric_value"])

                if dfd.empty:
                    st.info(f"No valid values for {metric}.")
                    continue

                if group_by == "Position" and "Position" in dfd.columns:
                    dfd["__dist_group"] = dfd["Position"].map(_position_group_value)
                    group_title = "Position"
                else:
                    dfd["__dist_group"] = dfd["__league_key"].fillna("Unknown").astype(str)
                    group_title = "League / Tier"

                tooltip_fields = [
                    alt.Tooltip(COL_PLAYER, title="Player"),
                    alt.Tooltip(COL_TEAM, title="Team"),
                    alt.Tooltip("Age:Q", title="Age"),
                    alt.Tooltip("__dist_group:N", title=group_title),
                    alt.Tooltip("__metric_value:Q", title=metric, format=".3f"),
                ]
                if "Position" in dfd.columns:
                    tooltip_fields.insert(3, alt.Tooltip("Position:N", title="Position"))

                box = (
                    alt.Chart(dfd)
                    .mark_boxplot(size=34)
                    .encode(
                        x=alt.X("__dist_group:N", title=group_title, sort="-y"),
                        y=alt.Y("__metric_value:Q", title=metric),
                    )
                )
                dots = (
                    alt.Chart(dfd)
                    .mark_circle(size=45, opacity=0.55)
                    .encode(
                        x=alt.X("__dist_group:N", title=group_title, sort="-y"),
                        y=alt.Y("__metric_value:Q", title=metric),
                        tooltip=tooltip_fields,
                    )
                    .interactive()
                )

                st.markdown(f"#### {metric}")
                st.altair_chart((box + dots).properties(height=390), use_container_width=True)

                higher_is_better = _metric_is_higher_better(metric)
                rank_cols = [c for c in [COL_PLAYER, COL_TEAM, "Age", "__league_key", "Position"] if c in dfd.columns]
                table = dfd[rank_cols + ["__metric_value"]].copy()
                table = table.sort_values("__metric_value", ascending=not higher_is_better).reset_index(drop=True)
                table.insert(0, "Rank", range(1, len(table) + 1))
                table = table.rename(columns={"__metric_value": metric})

                st.markdown("##### Best ranked players")
                st.dataframe(table.head(30), use_container_width=True, hide_index=True)

            _record_visual_history()

        control_cols = st.columns([1, 1, 1])
        with control_cols[0]:
            if visual_mode in {"Quadrant matrix", "Outlier scatter"}:
                force_positive = st.checkbox(
                    "Force positive axes",
                    value=st.session_state.get("g_pos_axes", True),
                    key="g_pos_axes",
                    help="Shifts the visual axes above zero when selected KPIs contain negative values.",
                )
        with control_cols[1]:
            if visual_mode == "Quadrant matrix":
                show_medians = True
                st.caption("Median split lines are always shown in quadrant mode.")
            elif visual_mode == "Outlier scatter":
                show_medians = st.checkbox(
                    "Show median lines",
                    value=st.session_state.get("g_show_medians", False),
                    key="g_show_medians",
                )
        with control_cols[2]:
            if visual_mode == "Outlier scatter":
                show_trend = st.checkbox(
                    "Show trend line",
                    value=st.session_state.get("g_show_trend", False),
                    key="g_show_trend",
                )

        pos_all  # keep for preset manager later

        if visual_mode == "Distribution view":
            _render_distribution_view()
        elif visual_mode == "Quadrant matrix":
            _render_two_axis_visual(show_quadrants=True, allow_trend=False)
        else:
            _render_two_axis_visual(show_quadrants=False, allow_trend=True)

        if kpG:
            with st.expander("U21 emergence (Visual Lab)", expanded=False):
                try:
                    st.write("DEBUG dfV shape:", dfV.shape)
                    if "Age" in dfV.columns:
                        ages_tmp = pd.to_numeric(dfV["Age"], errors="coerce")
                        st.write("DEBUG U21 count (17 to 23):", int(((ages_tmp >= 17) & (ages_tmp <= 23)).sum()))

                    render_u21_emergence_block_from_df(
                        st,
                        df_in=dfV,
                        key_prefix=f"g_{SUF}_u21",
                        export_buttons=export_buttons,
                    )
                except Exception as e:
                    st.exception(e)

            kpi_cols_graph = kpG[:]

            if "__league_key" in dfV.columns and "League" not in dfV.columns:
                dfV = dfV.copy()
                dfV["League"] = dfV["__league_key"]

            with st.expander("Moneyball debug", expanded=False):
                _debug_moneyball_inputs("Visual Lab", dfV, kpi_cols_graph)

            with st.expander("Moneyball (Visual Lab)", expanded=False):
                try:
                    render_moneyball_block(
                        df=dfV,
                        kpi_cols=kpi_cols_graph,
                        metric_direction=metric_direction,
                        title="Moneyball shortlist (Visual Lab)",
                        key_prefix=f"g_{SUF}_moneyball",
                    )
                except Exception as e:
                    st.exception(e)
                    st.write("DEBUG dfV shape:", getattr(dfV, "shape", None))
                    st.write("DEBUG KPI count:", len(kpi_cols_graph))
                    st.write("DEBUG KPIs:", kpi_cols_graph[:30])
                    st.write("DEBUG columns sample:", list(dfV.columns)[:60])

        # Preset manager stays here so it has access to pos_all and numeric_cols_G
        st.markdown("----")
        st.markdown("### KPI Presets Manager")

        with st.expander("Create / Edit / Import / Export KPI presets", expanded=False):
            st.markdown("#### New preset")
            ncol1, ncol2 = st.columns([2, 3])
            new_name = ncol1.text_input(
                "Profile name",
                key="kp_new_name",
                placeholder="e.g. 9 / 9A (CF)",
            )
            new_positions = ncol1.multiselect(
                "Positions for this profile",
                options=pos_all,
                key="kp_new_positions",
            )
            new_kpis = ncol2.multiselect(
                "KPIs for this profile",
                options=numeric_cols_G,
                key="kp_new_kpis",
            )
            new_notes = st.text_area(
                "Notes (optional)",
                key="kp_new_notes",
                placeholder="Role, age band, references…",
            )

            if st.button("Save new preset", type="primary", key="kp_save_new"):
                if not new_name.strip():
                    st.warning("Give the preset a name.")
                elif not new_kpis:
                    st.warning("Choose at least one KPI.")
                else:
                    dfp = _load_presets()
                    row = {
                        "Profile": new_name.strip(),
                        "KPIs": " | ".join(new_kpis),
                        "Positions": " | ".join(new_positions),
                        "Notes": new_notes,
                    }
                    mask = dfp["Profile"].astype(str).str.lower() == new_name.strip().lower()
                    if mask.any():
                        dfp.loc[mask, :] = row
                    else:
                        dfp = pd.concat([dfp, pd.DataFrame([row])], ignore_index=True)
                    _save_presets(dfp)
                    st.success(f"Saved preset '{new_name}'.")
                    st.cache_data.clear()
                    st.experimental_rerun()

            st.markdown("#### Existing presets")
            dfp = _load_presets().copy()
            st.dataframe(dfp, use_container_width=True, hide_index=True)

            ecol1, ecol2, _ = st.columns([1, 1, 2])

            csv_bytes = dfp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            ecol1.download_button(
                "Export presets (CSV)",
                data=csv_bytes,
                file_name="Role_Profile_KPIs.csv",
                mime="text/csv",
                key="kp_export",
            )

            uploaded = ecol2.file_uploader(
                "Import presets (CSV)",
                type=["csv"],
                key="kp_import",
            )
            if uploaded is not None:
                try:
                    content = uploaded.getvalue().decode("utf-8-sig", errors="ignore")
                    newdf = pd.read_csv(io.StringIO(content), dtype=str).fillna("")
                    required = {"Profile", "KPIs"}
                    if not required.issubset(set(map(str, newdf.columns))):
                        st.warning(
                            "Invalid file: needs columns Profile, KPIs (Positions and Notes optional)."
                        )
                    else:
                        for c in ["Positions", "Notes"]:
                            if c not in newdf.columns:
                                newdf[c] = ""
                        _save_presets(newdf[["Profile", "KPIs", "Positions", "Notes"]])
                        st.success("Imported presets.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to import: {e}")
    
    with tab["Player profile"]:
        _render_data_tab_intro("Player profile", "Search one player, check his role relevant profile, compare him to the right cohort and move from raw data into scouting evidence.")
        _ = st.checkbox(
            "Adjust for league strength (ClubElo)",
            value=False,
            key=ELO_KEYS["search"],
            help="Scales metrics by a league strength factor derived from ClubElo ratings.",
        )
        elo_norm = bool(st.session_state[SHARED_ELO_KEY])
        
        tier_norm_search = st.checkbox(
            "Normalise player KPIs by league tier strength",
            key="da_tier_norm_search",
            value=False,
        )
        render_player_search_tab(
            nation_dirs=nation_dirs,
            compute_age_series=compute_age_series,
            _load_presets=_load_presets,
            _parse_list=_parse_list,
            _sanitize_defaults=_sanitize_defaults,
            use_league_norm=elo_norm,
        )

    with tab["Player comparison"]:
        _render_data_tab_intro("Player comparison", "Use this for shortlist meetings. Keep two to four players in the same role context and compare their percentile profile clearly.")
        _ = st.checkbox(
            "Adjust for league strength (ClubElo)",
            value=False,
            key=ELO_KEYS["compare"],
            help="Scales metrics by a league strength factor derived from ClubElo ratings.",
        )
        elo_norm = bool(st.session_state[SHARED_ELO_KEY])

        render_player_comparison_tab(
            nation_dirs=nation_dirs,
            key_prefix=f"cmp_{SUF}",
            use_league_norm=elo_norm,
        )

    with tab["Position search"]:
        _render_data_tab_intro("Position search", "Start from a role need instead of a known player. Filter by position and let the data surface realistic names for further video work.")
        tier_norm_pos = st.checkbox(
            "Normalise player KPIs by league tier strength",
            key="da_tier_norm_pos_search",
            value=True,
        )

        render_position_search_tab(
            nation_dirs=nation_dirs,
            compute_age_series=compute_age_series,
            use_tier_norm=tier_norm_pos,
        )
    
    with tab["Team analysis"]:
        _render_data_tab_intro("Team analysis", "Read teams as scouting environments. Use this to understand player context, team strength and where outputs are coming from.")
        st.subheader("Team analysis")

        # Build the global Wyscout master (cached by your @st.cache_data decorator)
        master_df = _build_global_wyscout_master(nation_dirs)
        if master_df is None or master_df.empty:
            st.info("No league data available.")
        else:
            # Ensure Age exists (same pattern you use elsewhere)
            if "Age" not in master_df.columns or pd.to_numeric(master_df["Age"], errors="coerce").isna().all():
                if "DOB" in master_df.columns and compute_age_series is not None:
                    master_df = master_df.copy()
                    master_df["Age"] = compute_age_series(master_df)
                else:
                    master_df = master_df.copy()
                    master_df["Age"] = pd.NA

            # Load your scouting DB from the active db_csv path stored by the main app
            df_scout_db = pd.DataFrame()
            db_csv_path = st.session_state.get("db_csv")
            if db_csv_path and os.path.exists(db_csv_path):
                try:
                    df_scout_db = pd.read_csv(db_csv_path, dtype=str).fillna("")
                except Exception as e:
                    st.warning(f"Could not read scouting DB CSV: {e}")

            # Render the module
            render_team_analysis_tab(master_df, df_scout_db)
        
def render_player_search_tab(
    *,
    nation_dirs: list[str],
    compute_age_series,
    _load_presets,
    _parse_list,
    _sanitize_defaults, 
    use_league_norm: bool = False
) -> None:
    """
    Search a single player across the global Wyscout master and show:
      - cohort comparison vs league
      - Reference cohort comparison
      - radar chart
      - metric breakdown with percentile bars
    """

    st.subheader("Player data profile search")

    if not nation_dirs:
        st.info("No Wyscout league folders found yet.")
        return

    master = _build_global_wyscout_master(nation_dirs)
    if master.empty:
        st.info("No league data available.")
        return
    
    if use_league_norm:
        master = _attach_league_strength(master)


    # Canonical columns
    COL_PLAYER = next((c for c in master.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM   = next((c for c in master.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")
    COL_POS    = next((c for c in master.columns if c.lower() in {"position", "pos"}), "Position")

    # Age – compute if needed
    if "Age" not in master.columns or pd.to_numeric(master["Age"], errors="coerce").isna().all():
        if "DOB" in master.columns and compute_age_series is not None:
            master["Age"] = compute_age_series(master)
        else:
            master["Age"] = pd.NA

    # Minutes helper column
    if "Minutes played" in master.columns:
        master["_mins"] = pd.to_numeric(
            master["Minutes played"].map(parse_minutes),
            errors="coerce",
        )
    else:
        master["_mins"] = pd.to_numeric(
            master.get("_mins", pd.Series(dtype=float)),
            errors="coerce",
        )
    # After you set master["_mins"] ...
    master["Minutes"] = master["_mins"]


    # Total available minutes per league (for minutes share)
    apps_candidates = [

        c for c in master.columns

        if c.lower() in {"appearances", "apps", "matches", "games", "matches played"}

    ]

    max_minutes_per_league = pd.Series(dtype=float)

    if apps_candidates:

        apps_col = apps_candidates[0]

        master["_apps"] = pd.to_numeric(master[apps_col], errors="coerce")

        if "__league_key" not in master.columns:

            def _mk_key(r):

                nation = str(r.get("__nation", "")).strip()

                league = str(r.get("League", "") or r.get("Competition", "") or "").strip()

                tier = str(r.get("__tier", "")).strip()

                parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]

                return " · ".join(parts) if parts else "Unknown"

            master["__league_key"] = master.apply(_mk_key, axis=1)

        max_apps_per_league = master.groupby("__league_key")["_apps"].max()

        max_minutes_per_league = max_apps_per_league * 90.0

    # Build a disambiguation label for the player picker:
    # Name · Team · LeagueKey
    league_series = master.get("__league_key", pd.Series([""] * len(master)))

    # Name with and without accents, so search works whether user types them or not
    name_series = master[COL_PLAYER].astype(str).str.strip()
    name_ascii = name_series.apply(_strip_accents)

    # Only show both forms if they are actually different
    name_display = name_series.where(
        name_series == name_ascii,
        name_series + " / " + name_ascii,
    )

    team_series = master[COL_TEAM].astype(str).fillna("").str.strip()
    league_txt = league_series.astype(str).fillna("").str.strip()

    master["__player_pick_label"] = (
        name_display
        + " · "
        + team_series
        + " · "
        + league_txt
    )


    # ---------------- Player picker ----------------

    player_labels = (
        master["__player_pick_label"]
        .dropna()
        .astype(str)
        .sort_values()
        .unique()
        .tolist()
    )

    def _resolve_pick_label_from_plain(
        *,
        master_df: pd.DataFrame,
        ws_id: str | None,
        player_plain: str | None,
        team_plain: str | None,
    ) -> str | None:
        ws_id = str(ws_id or "").strip()
        player_plain = str(player_plain or "").strip()
        team_plain = str(team_plain or "").strip()

        # 1) Wyscout id exact match
        if ws_id:
            for c in ["Wyscout Player ID", "Wyscout Id", "Player ID", "player_id", "wyscout_id"]:
                if c in master_df.columns:
                    m = master_df[master_df[c].astype(str).str.strip() == ws_id]
                    if not m.empty and "__player_pick_label" in m.columns:
                        # pick the row with most minutes if duplicates
                        if "Minutes played" in m.columns:
                            mins = pd.to_numeric(m["Minutes played"], errors="coerce").fillna(0.0)
                            return str(m.loc[mins.idxmax(), "__player_pick_label"])
                        return str(m.iloc[0]["__player_pick_label"])

        # 2) Name and team match
        if player_plain and "__player_pick_label" in master_df.columns:
            name_col = next((c for c in master_df.columns if str(c).lower() in {"player", "player name", "name"}), None)
            team_col = next((c for c in master_df.columns if str(c).lower() in {"team", "club", "squad"}), None)

            if name_col:
                m = master_df[master_df[name_col].astype(str).str.strip().str.casefold() == player_plain.casefold()]
                if team_plain and team_col and not m.empty:
                    mt = m[m[team_col].astype(str).str.strip().str.casefold() == team_plain.casefold()]
                    if not mt.empty:
                        m = mt

                if not m.empty:
                    if "Minutes played" in m.columns:
                        mins = pd.to_numeric(m["Minutes played"], errors="coerce").fillna(0.0)
                        return str(m.loc[mins.idxmax(), "__player_pick_label"])
                    return str(m.iloc[0]["__player_pick_label"])

        return None


    goto_label = st.session_state.pop("goto_player_name", None)

    goto_plain = st.session_state.pop("goto_player_plain", None)
    goto_team = st.session_state.pop("goto_team_plain", None)
    goto_ws = st.session_state.pop("goto_ws_id_plain", None)

    target_label = None

    if goto_label and goto_label in player_labels:
        target_label = goto_label
    else:
        target_label = _resolve_pick_label_from_plain(
            master_df=master,
            ws_id=goto_ws,
            player_plain=goto_plain,
            team_plain=goto_team,
        )

    if target_label and target_label in player_labels:
        st.session_state["search_player_name"] = target_label

    top_row = st.columns([2, 2, 2])
    with top_row[0]:
        sel_player = st.selectbox(
            "Player",
            options=[""] + player_labels,
            index=0,
            help="Start typing to search across all leagues.",
            key="search_player_name",
        )


    # Track current and previous player for quick navigation
    prev_player = st.session_state.get("current_player_name")

    if sel_player:
        if prev_player != sel_player:
            if prev_player:
                # remember where we came from
                st.session_state["previous_player_name"] = prev_player
            st.session_state["current_player_name"] = sel_player

    # Optional: quick "back" button to jump to the previous player
    prev_btn_col, _, _ = st.columns([1, 2, 2])
    with prev_btn_col:
        prev_name = st.session_state.get("previous_player_name")
        if prev_name:
            if st.button(f"Back to {prev_name}", key="btn_back_player"):
                st.session_state["goto_player_name"] = prev_name
                st.rerun()


    if not sel_player:
        st.caption("Select a player to see their profile.")
        return

    # All rows for this player across leagues / tiers
    player_rows = master[master["__player_pick_label"].astype(str) == sel_player].copy()
    if player_rows.empty:
        st.warning("No rows found for that player (after cleaning).")
        return

    # Choose the "main" row for this player:
    # highest minutes, then highest tier as tiebreaker
    if "Minutes played" in player_rows.columns:
        player_rows["_mins_tmp"] = pd.to_numeric(
            player_rows["Minutes played"], errors="coerce"
        )
    else:
        player_rows["_mins_tmp"] = pd.to_numeric(
            player_rows.get("_mins", pd.Series(dtype=float)), errors="coerce"
        )

    if "__tier" in player_rows.columns:
        sort_cols = ["_mins_tmp", "__tier"]
        ascending = [False, True]         # more minutes, then Tier 1 over Tier 2/3
    else:
        sort_cols = ["_mins_tmp"]
        ascending = [False]

    player_rows_sorted = player_rows.sort_values(
        sort_cols, ascending=ascending
    )

    target_row = player_rows_sorted.iloc[0]


    # Positions dropdown (handles multi-pos strings)
    raw_pos = str(target_row.get(COL_POS, "") or "")
    raw_pos = str(target_row.get(COL_POS, "") or "").strip()
    if not raw_pos:
        st.warning(f"No position found in column '{COL_POS}' for this player. Check your master file headers.")

    pos_tokens = [p.strip() for p in raw_pos.replace("/", ",").split(",") if p.strip()]
    if not pos_tokens:
        pos_tokens = ["All"]
    else:
        pos_tokens = pos_tokens + ["All"]   # add All at the end

    with top_row[2]:
        sel_role = st.selectbox(
            "Position for comparison",
            options=pos_tokens,
            index=0,  # default = first position
            key="search_player_role",
        )

    # ---------------- Comparison cohort (league) ----------------

    league_key = str(target_row.get("__league_key", "") or "Unknown")
    all_leagues = (
        master["__league_key"]
        .dropna()
        .astype(str)
        .sort_values()
        .unique()
        .tolist()
    )

    st.markdown("### Comparison cohort")

    coh_col1, coh_col2 = st.columns([2, 1])
    with coh_col1:
           
        default_cohorts = [league_key] if league_key in all_leagues else []

        # Track last player+role combination specifically for the cohort picker
        cohort_key = f"{sel_player}::{sel_role}"
        last_cohort_key = st.session_state.get("search_last_player_role_cohort", None)

        if last_cohort_key != cohort_key:
            # Player or role changed since last time: reset leagues to this player's league
            st.session_state["search_last_player_role_cohort"] = cohort_key
            st.session_state["search_cohort_leagues"] = default_cohorts

        sel_cohorts = st.multiselect(
            "League / tier cohort(s)",
            options=all_leagues,
            default=default_cohorts,
            key="search_cohort_leagues",
            help="You can combine multiple leagues into one comparison group.",
        )

    with coh_col2:
        min_mins = coh_col2.number_input(
            "Min minutes in cohort",
            min_value=0,
            max_value=4000,
            value=210,
            step=90,
            key="search_min_mins",
        )

    if not sel_cohorts:
        st.info("Pick at least one league for the comparison cohort.")
        return

    cohort = master[master["__league_key"].astype(str).isin(sel_cohorts)].copy()

    if "_mins" in cohort.columns:
        cohort = cohort[pd.to_numeric(cohort["_mins"], errors="coerce") >= float(min_mins)]
    else:
        cohort["_mins"] = pd.NA


    if sel_role != "All" and COL_POS in cohort.columns:
        s = cohort[COL_POS].astype(str).str.upper()
        mask = s.str.contains(rf"\b{_re.escape(sel_role.upper())}\b", regex=True)
        cohort = cohort[mask]

    # ---------------- Reference comparison cohort ----------------

    reference_df = _load_reference_players_default()
    if not reference_df.empty:
        # normalise column names a bit
        reference_cols_lower = {c.lower(): c for c in reference_df.columns}
        reference_player_col = reference_cols_lower.get("player", next(iter(reference_df.columns)))
        reference_team_col   = reference_cols_lower.get("team", reference_cols_lower.get("club", reference_player_col))
        reference_pos_col    = reference_cols_lower.get("position", reference_cols_lower.get("pos", None))

        if reference_pos_col is not None and sel_role != "All":
            reference_pos_series = reference_df[reference_pos_col].astype(str).str.upper()
            reference_mask = reference_pos_series.str.contains(rf"\b{_re.escape(sel_role.upper())}\b", regex=True)
            reference_cohort = reference_df[reference_mask].copy()
        else:
            reference_cohort = reference_df.copy()
    else:
        reference_cohort = pd.DataFrame()

    st.markdown("### Secondary comparison")

    valid_compare_modes = {"Reference player", "Tier 1 positional peers"}
    if st.session_state.get("search_compare_mode") not in (None, *valid_compare_modes):
        st.session_state["search_compare_mode"] = "Tier 1 positional peers"

    compare_mode = st.radio(
        "Comparison reference",
        ["Reference player", "Tier 1 positional peers"],
        index=0,
        horizontal=True,
        key="search_compare_mode",
    )

    selected_reference_player = None
    tier1_cohort = pd.DataFrame()

    if compare_mode == "Reference player":
        if reference_cohort.empty:
            st.caption("No Reference positional cohort found in the reference players CSV.")
        else:
            reference_names = (
                reference_cohort[reference_player_col]
                .dropna()
                .astype(str)
                .sort_values()
                .unique()
                .tolist()
            )
            selected_reference_player = st.selectbox(
                "Reference player to compare with",
                options=[""] + reference_names,
                index=0,
                key="search_reference_player_name",
            )
    elif compare_mode == "Tier 1 positional peers":
        tier1_cohort = _tier_one_benchmark_cohort(master)
        if sel_role != "All" and COL_POS in tier1_cohort.columns:
            s_tier1 = tier1_cohort[COL_POS].astype(str).str.upper()
            m_tier1 = s_tier1.str.contains(rf"\b{_re.escape(sel_role.upper())}\b", regex=True)
            tier1_cohort = tier1_cohort[m_tier1]

    # ---------------- Metric focus (presets + KPIs) ----------------

    st.markdown("### Metric focus")
    presets_df = _load_presets().copy()
    preset_names = ["— None —"] + sorted(
        presets_df["Profile"].dropna().astype(str).unique().tolist()
    )

    pcol1, pcol2 = st.columns([2, 3])

    # auto-pick preset from position
    auto_preset = None
    if sel_role not in (None, "", "All"):
        pos_str = presets_df["Positions"].astype(str)
        pattern = rf"\b{_re.escape(sel_role)}\b"
        mask = pos_str.str.contains(pattern, case=False, regex=True)
        candidates = presets_df.loc[mask, "Profile"].astype(str).tolist()
        if candidates:
            auto_preset = candidates[0]

    # key to detect player/role change
    cur_key = f"{sel_player}::{sel_role}"
    last_key = st.session_state.get("search_last_player_role", None)

    # reset preset when player or role changes
    if last_key != cur_key:
        st.session_state["search_last_player_role"] = cur_key
        st.session_state["search_preset"] = auto_preset or "— None —"
        # we will also reset KPIs later once we know which ones are valid
        # reset league cohort picker so new player gets their own league default
        st.session_state.pop("search_cohort_leagues", None)

    sel_preset = pcol1.selectbox(
        "Preset (Role profile preset)",
        options=preset_names,
        key="search_preset",
    )

    preset_kpis: list[str] = []
    if sel_preset != "— None —":
        prow = presets_df[presets_df["Profile"] == sel_preset]
        if not prow.empty:
            preset_kpis = _parse_list(prow.iloc[0].get("KPIs", ""))

        # Fallback to hard-coded KPI packs if CSV is missing / messy
        if not preset_kpis and sel_preset in ROLE_KPI_PACKS:
            preset_kpis = ROLE_KPI_PACKS[sel_preset][:]


    # numeric-ish KPI columns available in this cohort
    helper_cols = {COL_PLAYER, COL_TEAM, COL_POS, "_mins", "Minutes played", "Age", "__league_key"}

    numeric_cols: list[str] = []
    for c in sorted(cohort.columns):
        if c in helper_cols:
            continue
        try:
            vals = pd.to_numeric(cohort[c], errors="coerce")
        except Exception:
            continue
        if vals.notna().any():
            numeric_cols.append(c)


    valid_preset_kpis, missing_preset_kpis = _sanitize_defaults(
        preset_kpis,
        numeric_cols,
    )

    if sel_preset != "— None —" and missing_preset_kpis:
        st.caption(
            f"Dropped {len(missing_preset_kpis)} preset KPI(s) not present in this cohort: "
            + ", ".join(missing_preset_kpis)
        )

    # if we do not have KPIs stored yet, initialise them from the preset
    if "search_kpis" not in st.session_state:
        st.session_state["search_kpis"] = valid_preset_kpis


    # Reset selected KPIs when preset changes
    last_preset = st.session_state.get("search_last_preset")
    if last_preset != sel_preset:
        st.session_state["search_last_preset"] = sel_preset
        st.session_state["search_kpis"] = valid_preset_kpis

    sel_kpis = pcol2.multiselect(
        "KPIs for pizza chart / sliders",
        options=numeric_cols,
        default=st.session_state.get("search_kpis", valid_preset_kpis) or valid_preset_kpis,
        max_selections=30,
        key="search_kpis",
    )


    if not sel_kpis:
        st.info(
            "Pick at least one KPI above if you want the radar and metric breakdown. "
            "Similarity and general deductions still use the full stat profile."
        )

    # Decide if player is a GK – affects which phase groups we show
    is_gk = "GK" in str(raw_pos).upper()

    # Phase to metric-name mapping – you can edit / extend these lists
    phases: dict[str, list[str]] = {
        "Attacking": [
            "Goals per 90",
            "Non-penalty goals per 90",
            "xG per 90",
            "Shots per 90",
            "Shots on target, %",
            "Shot assists per 90",
            "Second assists per 90",
            "Third assists per 90",
            "Goal conversion, %",
            "xG per shot",
            "xA per 90",
            "Assists per 90",
            "Crosses per 90",
            "Accurate crosses, %",
            "Touches in box per 90",
            "Offensive duels per 90",
            "Offensive duels won, %",
            "Dribbles per 90",
            "Successful dribbles, %",
            "Successful attacking actions per 90",
            "Accelerations per 90",
        ],
        "Possession": [
            "Passes per 90",
            "Accurate passes, %",
            "Forward passes per 90",
            "Accurate forward passes, %",
            "Back passes per 90",
            "Short / medium passes per 90",
            "Accurate short / medium passes, %",
            "Long passes per 90",
            "Accurate long passes, %",
            "Through passes per 90",
            "Accurate through passes, %",
            "Average pass length, m",
            "Average long pass length, m",
            "Progressive passes per 90",
            "Accurate progressive passes, %",
            "Passes to final third per 90",
            "Accurate passes to final third, %",
            "Passes to penalty area per 90",
            "Accurate passes to penaly area, %",
            "Progressive runs per 90",
            "Deep completions per 90",
            "Deep completed crosses per 90",
            "Smart passes per 90",
            "Accurate smart passes, %",
            "Key passes per 90",
        ],
        "Defending": [
            "Successful defensive actions per 90",
            "Defensive duels per 90",
            "Defensive duels won, %",
            "Aerial duels per 90",
            "Aerial duels won, %",
            "Interceptions per 90",
            "PAdj Interceptions",
            "Shots blocked per 90",
            "Sliding tackles per 90",
            "PAdj Sliding tackles",
            "Fouls per 90",
            "Yellow cards per 90",
        ],
        "Set pieces": [
            "Crosses per 90",
            "Accurate crosses, %",
            "Crosses to goalie box per 90",
            "Head goals per 90",
            "Shots from free kicks per 90",
        ],
    }

    # Extra phase for goalkeepers
    if is_gk:
        phases["Goalkeeping"] = [
            "Save rate, %",
            "Goals conceded per 90",
            "Clean sheets, %",
            "Exits per 90",
            "Exits missed, %",
            "Aerial duels per 90",
            "Aerial duels won, %",
            "Passes per 90",
            "Accurate passes, %",
            "Launches per 90",
            "Accurate launches, %",
        ]

    

    # All metrics we want to support in this profile:
    #  - KPI pack used for radar + Metric breakdown
    #  - Full metrics by phase lists
    phase_metrics: set[str] = {m for items in phases.values() for m in items}
    profile_metrics: list[str] = sorted(set(sel_kpis) | phase_metrics)


    # ---------------- Percentiles for target player ----------------

    player_vals: dict[str, float] = {}
    league_pcts: dict[str, float] = {}
    secondary_pcts: dict[str, float] = {}
    secondary_label = None

    for m in sel_kpis:
        raw_val = pd.to_numeric(target_row.get(m, float("nan")), errors="coerce")
        if pd.isna(raw_val):
            player_vals[m] = np.nan
            league_pcts[m] = np.nan
            secondary_pcts[m] = np.nan
            continue

        player_vals[m] = float(raw_val)
        league_pcts[m] = _percentile_rank(cohort[m], raw_val) if m in cohort.columns else float("nan")

        if compare_mode == "Reference player" and selected_reference_player and not reference_cohort.empty:
            ref_row = reference_cohort[reference_cohort[reference_player_col].astype(str) == selected_reference_player]
            if not ref_row.empty and m in reference_cohort.columns:
                ref_val = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")
                secondary_pcts[m] = _percentile_rank(reference_cohort[m], ref_val)
                secondary_label = f"Reference: {selected_reference_player}"
            else:
                secondary_pcts[m] = float("nan")

        elif compare_mode == "Tier 1 positional peers" and not tier1_cohort.empty and m in tier1_cohort.columns:
            secondary_pcts[m] = _percentile_rank(tier1_cohort[m], raw_val)
            secondary_label = "Tier 1 positional peers"
        else:
            secondary_pcts[m] = float("nan")


    # ---------------- Header + radar ----------------

    st.markdown("---")
    header_cols = st.columns([2, 3])

    with header_cols[0]:
        st.markdown(f"### {sel_player}")

        tier_txt = (

            f"T{int(target_row.get('__tier'))}"

            if "__tier" in target_row.index and pd.notna(target_row["__tier"])

            else "T?"

        )

        # Minutes for this main row

        mins_val = float(target_row.get("_mins_tmp", float("nan")))

        mins_text = f"{int(round(mins_val))} mins" if not math.isnan(mins_val) else "n/a"

        # Share of available league minutes

        share_text = ""

        if "__league_key" in target_row.index and not max_minutes_per_league.empty:

            lk = str(target_row["__league_key"])

            avail = float(max_minutes_per_league.get(lk, float("nan")))

            if not math.isnan(avail) and avail > 0:

                pct = 100.0 * mins_val / avail

                share_text = f" • {pct:.1f} percent of available league minutes"

        st.caption(

            f"{target_row.get(COL_TEAM,'')} • {raw_pos} • {league_key} ({tier_txt}) • "

            f"Age: {target_row.get('Age','')} • Minutes: {mins_text}{share_text}"

        )

        st.metric("League cohort size", len(cohort))
        if not reference_cohort.empty:
            st.metric("Reference cohort size", len(reference_cohort))

        if not reference_cohort.empty:
            st.markdown("#### Reference players in this role")
            cols_to_show = [c for c in ["Player", "Team", "Position", "Age", "Minutes played"] if c in reference_cohort.columns]
            if cols_to_show:
                st.dataframe(
                    reference_cohort[cols_to_show]
                    .drop_duplicates()
                    .sort_values("Player"),
                    use_container_width=True,
                    hide_index=True,
                )
      
        if compare_mode == "Reference player" and selected_reference_player and not reference_cohort.empty:
            ref_row = reference_cohort[reference_cohort["Player"].astype(str) == selected_reference_player]
            if not ref_row.empty:
                st.markdown("#### Raw KPI comparison (FM-style)")

                reference_vals: dict[str, float] = {}
                for m in sel_kpis:
                    reference_vals[m] = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")

                # Wide table: one row per metric, two value columns with bars
                comp_records = []
                for m in sel_kpis:
                    comp_records.append(
                        {
                            "Metric": m,
                            sel_player: player_vals.get(m, np.nan),
                            selected_reference_player: reference_vals.get(m, np.nan),
                        }
                    )

                comp_df = pd.DataFrame(comp_records)
                for col in [sel_player, selected_reference_player]:
                    comp_df[col] = pd.to_numeric(comp_df[col], errors="coerce")

                st.dataframe(
                    comp_df.set_index("Metric")
                        .style.format("{:.2f}")
                        .bar(subset=[sel_player, selected_reference_player], axis=1),
                    use_container_width=True,
                )


    with header_cols[1]:
        labels = sel_kpis
        league_vals = [league_pcts[m] if not np.isnan(league_pcts[m]) else 0.0 for m in labels]
        secondary_vals = [secondary_pcts[m] if not np.isnan(secondary_pcts[m]) else 0.0 for m in labels]

        labels_loop = labels + labels[:1]
        league_loop = league_vals + league_vals[:1]
        secondary_loop = secondary_vals + secondary_vals[:1]

        fig = go.Figure()

        # Main polygon = selected player vs league
        fig.add_trace(
            go.Scatterpolar(
                r=league_loop,
                theta=labels_loop,
                fill="toself",
                name=f"{sel_player} – league percentile",
                line=dict(width=2, color="rgba(0, 204, 204, 1.0)"),
                fillcolor="rgba(0, 204, 204, 0.55)",
                hovertemplate="%{theta}: %{r:.1f} percentile<extra></extra>",
            )
        )

        # Secondary polygon: Reference player or DK T1 cohort
        if secondary_label is not None:
            fig.add_trace(
                go.Scatterpolar(
                    r=secondary_loop,
                    theta=labels_loop,
                    fill="toself",
                    name=secondary_label,
                    line=dict(width=2, color="rgba(255, 255, 255, 0.9)"),
                    fillcolor="rgba(255, 255, 255, 0.25)",
                    hovertemplate="%{theta}: %{r:.1f} percentile<extra></extra>",
                )
            )

        fig.update_layout(
            title=f"{sel_player} vs {secondary_label or 'league cohort'}",
            paper_bgcolor="#050608",
            plot_bgcolor="#050608",
            font=dict(color="#f5f5f5", size=12),
            polar=dict(
                bgcolor="#050608",
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    dtick=25,
                    gridcolor="rgba(255,255,255,0.18)",
                    gridwidth=1,
                    showline=False,
                    tickfont=dict(size=10),
                ),
                angularaxis=dict(
                    gridcolor="rgba(255,255,255,0.10)",
                    gridwidth=1,
                    tickfont=dict(size=11),
                ),
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5,
            ),
            margin=dict(l=10, r=10, t=40, b=10),
            height=460,
        )

        st.plotly_chart(fig, use_container_width=True)


        
    # ---------------- Player type + positional responsibilities (same as Player Reports) ----------------

    # Use the selected league cohort as the comparison base
    # Ensure the player row exists in the cohort table
    ws_id = str(target_row.get("Wyscout Player ID", "") or "").strip()
    if not ws_id:
        ws_id = f"noid_search_{sel_player}".replace(" ", "_")

    # ---------------- Player type + positional responsibilities (same as Player Reports) ----------------

    ws_id = str(target_row.get("Wyscout Player ID", "") or "").strip()
    if not ws_id:
        ws_id = f"noid_search_{sel_player}".replace(" ", "_")

    # If target_row is not literally a row from `cohort`, rebind it by Wyscout ID or Player name
    target_row_in_cohort = target_row
    if isinstance(cohort, pd.DataFrame) and not cohort.empty:
        if "Wyscout Player ID" in cohort.columns and str(target_row.get("Wyscout Player ID", "") or "").strip():
            m = cohort[cohort["Wyscout Player ID"].astype(str) == str(target_row.get("Wyscout Player ID"))]
            if not m.empty:
                target_row_in_cohort = m.iloc[0]
        else:
            m = cohort[cohort[COL_PLAYER].astype(str) == str(target_row.get(COL_PLAYER, ""))]
            if not m.empty:
                target_row_in_cohort = m.iloc[0]

    # Priority: chosen preset profile, else the player's own first Wyscout position token
    preset_profile_key = None
    if sel_preset and sel_preset != "— None —":
        preset_profile_key = _preset_label_to_profile_key(sel_preset)

    raw_pos = str(target_row_in_cohort.get(COL_POS, "") or target_row.get(COL_POS, "") or "")
    pos_tokens_tmp = [p.strip() for p in raw_pos.replace("/", ",").split(",") if p.strip()]
    player_first_pos = pos_tokens_tmp[0] if pos_tokens_tmp else ""

    position_text_for_block = preset_profile_key or _normalise_pos_text(player_first_pos)
    if not str(position_text_for_block or "").strip():
        st.warning("No position found for this player row. Check the Position column in the Wyscout master.")
        return

    with st.expander("Debug info: profile key inference", expanded=False):
        st.caption(
            f"Profile debug: preset={sel_preset} → key={preset_profile_key} | "
            f"player_first_pos={player_first_pos} | position_text_for_block={position_text_for_block}"
        )
    
    render_player_type_and_responsibilities_blocks(
    cohort_df=cohort,
    target_row=target_row_in_cohort,          # actually use the rebound row
    position_text=position_text_for_block,    # use preset key or player first position
    ws_id=ws_id,
    )

    # ---------------- Gaps panel (same as Player Reports) ----------------
    st.markdown("---")
    # Stable Streamlit key prefix for this Search tab instance
    _ws = str(ws_id or "noid").strip()
    if not _ws or _ws.lower() in {"nan", "none"}:
        _ws = "noid"
    _ws = "".join(ch if ch.isalnum() else "_" for ch in _ws)[:40]
    key_prefix = f"da_search_{_ws}"

    render_search_tab_gap_panel(
        cohort_df=cohort,
        target_row=target_row_in_cohort,
        position_text=position_text_for_block,
        key_prefix=f"{key_prefix}_gaps",
        top_n=8,
        resp_floor=50.0,
    )
    gap_payload = calculate_search_tab_gaps(
        cohort_df=cohort,
        target_row=target_row_in_cohort,
        position_text=position_text_for_block,
        top_n=8,
        resp_floor=50.0,
    )

    if gap_payload:
        render_weakness_visuals(gap_payload)

    # ---------------- Previous Season Trend ----------------
    # Pass the selected KPIs and the logic to find the folder
    st.markdown("---")
    render_season_trend_block(
        current_row=target_row_in_cohort, 
        kpis=sel_kpis, 
        wys_root_func=None # We calculate inside the function for simplicity
    )



    # ---------------- Metric breakdown table ----------------
    st.markdown("### Metric breakdown")
    

    rows_html = []
    rows_html.append(
        """
        <style>
        .metric-table {
            width:100%;
            border-collapse:collapse;
            font-size:13px;
            color:#f5f5f5;
        }
        .metric-table thead tr {
            background:rgba(255,255,255,0.06);
        }
        .metric-table th,
        .metric-table td {
            padding:6px 8px;
            vertical-align:middle;
        }
        .metric-table th {
            text-align:center;
            font-weight:600;
            letter-spacing:0.02em;
        }
        .metric-table tbody tr:nth-child(odd) {
            background:rgba(255,255,255,0.02);
        }
        .metric-table tbody tr:nth-child(even) {
            background:rgba(255,255,255,0.04);
        }
        .metric-mname {
            white-space:nowrap;
        }
        .metric-raw {
            text-align:center;
            font-variant-numeric:tabular-nums;
        }
        </style>
        <table class="metric-table">
        <thead>
            <tr>
            <th>Metric</th>
            <th>Player value</th>
            <th>League percentile</th>
            <th>Comparison percentile</th>
            </tr>
        </thead>
        <tbody>
        """
    )

    
    for m in sel_kpis:
        raw = player_vals.get(m, np.nan)
        try:
            raw_txt = f"{raw:.2f}" if not np.isnan(raw) else "—"
        except Exception:
            raw_txt = str(raw) if raw not in (None, "") else "—"

        lp = league_pcts.get(m, float("nan"))
        sp = secondary_pcts.get(m, float("nan"))

        lp_html = _pct_bar_html(lp) if not np.isnan(lp) else "—"
        sp_html = _pct_bar_html(sp) if not np.isnan(sp) else "—"


        rows_html.append(
            f"""
            <tr>
              <td class="metric-mname">{m}</td>
              <td class="metric-raw">{raw_txt}</td>
              <td>{lp_html}</td>
              <td>{sp_html}</td>
            </tr>
            """
        )

    rows_html.append("</tbody></table>")

    # render as a full HTML block so tags are not shown as text
    components.html(
        "\n".join(rows_html),
        height=80 + 32 * len(sel_kpis),   # rough auto-height
        scrolling=True,
    )
    
    # ---------------- Full metrics by phase ----------------
    st.markdown("### Full metrics by phase")

    phase_html_parts: list[str] = []
    total_rows = 0

    # reuse the same table styling as the Metric breakdown block
    phase_html_parts.append(
        """
        <style>
        .metric-table {
            width:100%;
            border-collapse:collapse;
            font-size:13px;
            color:#f5f5f5;
        }
        .metric-table thead tr {
            background:rgba(255,255,255,0.06);
        }
        .metric-table th,
        .metric-table td {
            padding:6px 8px;
            vertical-align:middle;
        }
        .metric-table th {
            text-align:center;
            font-weight:600;
            letter-spacing:0.02em;
        }
        .metric-table tbody tr:nth-child(odd) {
            background:rgba(255,255,255,0.02);
        }
        .metric-table tbody tr:nth-child(even) {
            background:rgba(255,255,255,0.04);
        }
        .metric-mname {
            white-space:nowrap;
        }
        .metric-raw {
            text-align:center;
            font-variant-numeric:tabular-nums;
        }
        </style>
        """
    )


    # Make sure we have raw values and percentiles for every metric
    # that appears in the phase groups, not just in sel_kpis.
    phase_metrics: set[str] = {m for group in phases.values() for m in group}

    for m in phase_metrics:
        # If we already computed this metric as part of sel_kpis, skip it
        if m in player_vals:
            continue

        raw_val = pd.to_numeric(target_row.get(m, float("nan")), errors="coerce")

        if pd.isna(raw_val):
            player_vals[m] = np.nan
            league_pcts[m] = np.nan
            secondary_pcts[m] = np.nan
            continue

        player_vals[m] = float(raw_val)

        # Default: percentile vs positional peers in this league cohort
        if m in cohort.columns:
            league_pcts[m] = _percentile_rank(cohort[m], raw_val)
        else:
            league_pcts[m] = float("nan")

        # Secondary comparison
        if compare_mode == "Reference player" and selected_reference_player and not reference_cohort.empty:
            ref_row = reference_cohort[reference_cohort[reference_player_col].astype(str) == selected_reference_player]
            if not ref_row.empty and m in reference_cohort.columns:
                ref_val = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")
                secondary_pcts[m] = _percentile_rank(reference_cohort[m], ref_val)
                secondary_label = f"Reference: {selected_reference_player}"
            else:
                secondary_pcts[m] = float("nan")
        elif compare_mode == "Tier 1 positional peers" and not tier1_cohort.empty and m in tier1_cohort.columns:
            secondary_pcts[m] = _percentile_rank(tier1_cohort[m], raw_val)
            secondary_label = "Tier 1 positional peers"
        else:
            secondary_pcts[m] = float("nan")


    for phase_name, items in phases.items():
        if not items:
            continue

        # Phase heading
        phase_html_parts.append(
            f"<h4 style='margin-top:1.2rem; margin-bottom:0.25rem;'>{phase_name}</h4>"
        )

        # Table header reusing the same styling as the main metric breakdown
        phase_html_parts.append(
            """
            <table class="metric-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Player value</th>
                  <th>League percentile</th>
                  <th>Comparison percentile</th>
                </tr>
              </thead>
              <tbody>
            """
        )


        for m in sorted(items):
            total_rows += 1
            metric_name = m
            raw = player_vals.get(metric_name, np.nan)
            league_pct = league_pcts.get(metric_name, float("nan"))
            comp_pct = secondary_pcts.get(metric_name, float("nan"))
            # Raw value formatting, same logic as the breakdown table
            raw_txt = "—"
            if isinstance(raw, (int, float)):
                if not math.isnan(raw):
                    raw_txt = f"{raw:.2f}"
            else:
                try:
                    rv = float(raw)
                    if not math.isnan(rv):
                        raw_txt = f"{rv:.2f}"
                except Exception:
                    if raw not in (None, ""):
                        raw_txt = str(raw)

            lp = league_pcts.get(m, float("nan"))
            sp = secondary_pcts.get(m, float("nan"))

            lp_html = _pct_bar_html(lp) if not math.isnan(lp) else "—"
            sp_html = _pct_bar_html(sp) if not math.isnan(sp) else "—"

            phase_html_parts.append(
                f"""
                <tr>
                  <td class="metric-mname">{m}</td>
                  <td class="metric-raw">{raw_txt}</td>
                  <td>{lp_html}</td>
                  <td>{sp_html}</td>
                </tr>
                """
            )

        phase_html_parts.append("</tbody></table>")

    if phase_html_parts:
        components.html(
            "\n".join(phase_html_parts),
            height=min(900, 140 + 28 * total_rows),
            scrolling=True,
        )

    # ---------------- General deductions and archetype ----------------

    st.markdown("### General deductions")

    deductions: list[str] = []

    # Minutes and usage within cohort
    mins_val = float(target_row.get("_mins", float("nan"))) if "_mins" in target_row.index else float("nan")
    cohort_mins = cohort.get("_mins", pd.Series(dtype=float))

    if not np.isnan(mins_val) and len(cohort_mins) > 0:
        median_mins = float(np.nanmedian(cohort_mins))
        if median_mins > 0:
            share_vs_median = mins_val / median_mins
            deductions.append(
                f"Domestic minutes at {mins_val:.0f}, which is {share_vs_median:.1f} times the median usage in this league cohort."
            )
        else:
            deductions.append(f"Domestic minutes at {mins_val:.0f} for this season.")

        if mins_val < max(600, median_mins * 0.5):
            deductions.append("Lower league usage than the typical cohort sample, so sample size needs context in video work.")

    # League percentile strengths and development areas
    low_metrics  = [m for m, p in league_pcts.items() if not np.isnan(p) and p < 20]
    high_metrics = [m for m, p in league_pcts.items() if not np.isnan(p) and p > 80]

    if high_metrics:
        deductions.append("80+ percentile scoring in: " + ", ".join(high_metrics))

    if low_metrics:
        deductions.append("<20 percentile scoring in: " + ", ".join(low_metrics))

    # Archetype inference based on position and key stats
    pos_text = str(target_row.get(COL_POS, "") or "")
    archetypes = _infer_archetypes_for_row(pos_text, target_row, league_pcts)

    if archetypes:
        # Just show the primary one, but include explanation
        main_name, main_note = archetypes[0]
        deductions.append(f"Archetype: {main_name}. {main_note}")

        # If you want to see secondary archetypes as well, uncomment below
        # for extra_name, extra_note in archetypes[1:]:
        #     deductions.append(f"Secondary archetype: {extra_name}. {extra_note}")

    if not deductions:
        st.caption("No strong general deductions from the current metric selection.")
    else:
        for text in deductions:
            st.write(f"• {text}")


    # ---------------- Similar players (cosine similarity) ----------------
    st.markdown("### Similar players by data profile")

    # We also want to reuse these in the export later if needed
    sim_all: pd.DataFrame | None = None
    sim_three: pd.DataFrame | None = None

    # Use all numeric KPIs available in the cohort for similarity, not just the selected preset ones
    sim_kpis = [m for m in numeric_cols if m in master.columns]


    if not sim_kpis:
        st.caption(
            "No overlapping numeric KPIs found in the global database for similarity search."
        )
    else:
        pool = master.copy()

        # Optional positional filter – only when a specific role is selected
        if sel_role not in (None, "", "All") and COL_POS in pool.columns:
            s_pool = pool[COL_POS].astype(str).str.upper()
            m_pool = s_pool.str.contains(
                rf"\b{_re.escape(sel_role.upper())}\b", regex=True
            )
            pool = pool[m_pool]

        # After any positional filter, check if we still have a pool
        if pool.empty:
            st.caption("No comparison pool available for similarity search.")
        else:
            # Aggregate per player–team–league, keep position and nation if present
            group_cols = [COL_PLAYER, COL_TEAM]
            if COL_POS in pool.columns:
                group_cols.append(COL_POS)
            if "__league_key" in pool.columns:
                group_cols.append("__league_key")
            if "__nation" in pool.columns:
                group_cols.append("__nation")

            agg_dict: dict[str, str] = {k: "mean" for k in sim_kpis}
            if "Age" in pool.columns:
                agg_dict["Age"] = "mean"

            num_cols = sim_kpis + (["Age"] if "Age" in pool.columns else [])

            df_agg = pool[group_cols + num_cols].copy()

            # Force numeric
            for c in sim_kpis:
                df_agg[c] = pd.to_numeric(df_agg[c], errors="coerce")
            if "Age" in df_agg.columns:
                df_agg["Age"] = pd.to_numeric(df_agg["Age"], errors="coerce")

            pool_group = (
                df_agg
                .groupby(group_cols, as_index=False)
                .agg(agg_dict)
            )

            if pool_group.empty:
                st.caption("No comparison pool available for similarity search.")
            else:
                # Drop the current player itself from the pool
                cur_name   = str(target_row.get(COL_PLAYER, "") or "")
                cur_team   = str(target_row.get(COL_TEAM, "") or "")
                cur_pos    = str(target_row.get(COL_POS, "") or "")
                cur_league = str(target_row.get("__league_key", "") or "")

                if "__league_key" in pool_group.columns:
                    mask_same = (
                        (pool_group[COL_PLAYER].astype(str) == cur_name)
                        & (pool_group[COL_TEAM].astype(str) == cur_team)
                        & (pool_group["__league_key"].astype(str) == cur_league)
                    )
                elif COL_POS in pool_group.columns:
                    mask_same = (
                        (pool_group[COL_PLAYER].astype(str) == cur_name)
                        & (pool_group[COL_TEAM].astype(str) == cur_team)
                        & (pool_group[COL_POS].astype(str) == cur_pos)
                    )
                else:
                    mask_same = pool_group[COL_PLAYER].astype(str) == cur_name

                pool_group = pool_group[~mask_same].copy()

                # ---- Similarity prep: safer KPI set, impute, standardise ----
                # Put this right after: feat_cols = sim_kpis

                # 1) Remove obvious non profile columns if they slipped into numeric_cols
                feat_cols = list(sim_kpis)
                EXCLUDE_SIM_COLS = {
                    "Minutes", "_mins", "Mins", "90s", "Apps", "Matches", "Games",
                    "Season", "Year", "Market value", "Contract expires", "Height", "Weight",
                    "On loan"
                }
                feat_cols = [c for c in feat_cols if c not in EXCLUDE_SIM_COLS]

                # 2) Build player pool matrix and target vector as floats
                X = pool_group[feat_cols].apply(pd.to_numeric, errors="coerce")
                t = pd.to_numeric(target_row[feat_cols], errors="coerce")

                # 3) Impute missing using pool means (not zero)
                mu = X.mean(axis=0, skipna=True)
                X = X.fillna(mu)
                t = t.fillna(mu)

                # 4) Z score standardisation using pool statistics
                sigma = X.std(axis=0, ddof=0).replace(0, 1.0)
                Xz = (X - mu) / sigma
                tz = ((t - mu) / sigma).to_numpy()

                feats = Xz.to_numpy()
                target_vec = tz

                

                tv_norm = np.linalg.norm(target_vec)
                if tv_norm == 0.0 or feats.size == 0:
                    st.caption("Not enough numeric variation to compute similarity.")
                else:
                    denom = np.linalg.norm(feats, axis=1) * tv_norm + 1e-9
                    sims = (feats @ target_vec) / denom

                    pool_group["Similarity"] = sims
                    pool_group["Similarity"] = pool_group["Similarity"].round(3)
                    cohort_df = pool_group
                    # Keep a copy for later (export etc.)
                    sim_all = pool_group.copy()
                    # Stage 2 rerank using roles, traits, responsibilities
                    st.markdown("#### Refine matches using roles, traits, responsibilities")
                    key_prefix = "sim_rtr"
                    shortlist_n = st.slider(
                        "Shortlist size from stage 1",
                        min_value=10,
                        max_value=200,
                        value=50,
                        step=10,
                        key=f"{key_prefix}_rtr_shortlist_n",
                    )

                    use_rtr_rerank = st.checkbox(
                        "Use roles traits responsibilities rerank",
                        value=True,
                        key=f"{key_prefix}_use_rtr_rerank",
                    )

                    df_stage1 = pool_group.sort_values("Similarity", ascending=False).copy()
                    # ------------------------------------------------------------
                    # RTR: derive the internal profile_key in the Search tab scope
                    # Priority: chosen preset profile, else player's first Wyscout position token
                    # ------------------------------------------------------------

                    # sel_preset should already exist (your preset dropdown). If not, set it to None.
                    sel_preset = locals().get("sel_preset", None)

                    preset_profile_key = None
                    if sel_preset and sel_preset != "— None —":
                        preset_profile_key = _preset_label_to_profile_key(sel_preset)

                    raw_pos = str(
                        (target_row_in_cohort.get(COL_POS, "") if "target_row_in_cohort" in locals() else "")
                        or target_row.get(COL_POS, "")
                        or ""
                    )

                    pos_tokens_tmp = [p.strip() for p in raw_pos.replace("/", ",").split(",") if p.strip()]
                    player_first_pos = pos_tokens_tmp[0] if pos_tokens_tmp else ""

                    # This is the actual key your Roles/Traits/Responsibilities logic expects (eg: "6", "8", "CB", "WF", "CF")
                    profile_key = preset_profile_key or _text_to_profile_key(player_first_pos)

                    # Optional safety so the UI does not crash if a weird position comes in
                    if not profile_key:
                        st.warning(f"Unmapped position for RTR scoring. preset='{sel_preset}' raw_pos='{raw_pos}'")

                    if use_rtr_rerank:
                        df_stage2 = rerank_candidates_by_rtr(
                            profile_key=profile_key,
                            cohort_df=cohort,
                            target_row=target_row,
                            candidates_df=df_stage1,
                            shortlist_n=shortlist_n,
                        )

                        st.dataframe(
                            df_stage2[
                                [
                                    "Player",
                                    "Team",
                                    "Age",
                                    "Minutes",
                                    "Similarity",
                                    "RTR_Sim",
                                    "RoleSim",
                                    "TraitSim",
                                    "RespSim",
                                ]
                            ].head(25),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.dataframe(
                            df_stage1[
                                [
                                    "Player",
                                    "Team",
                                    "Age",
                                    "Minutes",
                                    "Similarity",
                                ]
                            ].head(25),
                            use_container_width=True,
                            hide_index=True,
                        )

                    # Comparison radar + player type blocks
                    # Name of the searched player (the one you selected in the Search tab)
                    target_name = str(target_row.get(COL_PLAYER, target_row.get("Player", "Selected player")))
                    target_team = str(target_row.get(COL_TEAM, target_row.get("Team", "")))
                    target_label = f"{target_name} | {target_team}".strip(" |")

                    st.markdown(f"#### Compare: {target_name} vs top player matches")

                    source_df = df_stage2 if (use_rtr_rerank and "df_stage2" in locals()) else df_stage1
                    top_for_pick = source_df.head(15).copy()

                    default_picks = top_for_pick["Player"].head(5).tolist() if "Player" in top_for_pick.columns else []

                    picked_players = st.multiselect(
                        "Select players to compare",
                        options=top_for_pick["Player"].tolist(),
                        default=default_picks,
                        key=f"{key_prefix}_picked_compare",
                    )

                    # Build rows for radar
                    picked_rows = []
                    picked_labels = []

                    if picked_players:
                        df_pick = source_df[source_df["Player"].isin(picked_players)].copy()

                        for _idx, r in df_pick.iterrows():
                            picked_rows.append(r)
                            picked_labels.append(f"{r.get('Player','')} | {r.get('Team','')}")

                        # Always include target first
                        radar_rows = [target_row] + picked_rows
                        radar_labels = [f"{target_row.get('Player','Target')} | {target_row.get('Team','')}"] + picked_labels

                        # Use the same KPI list you already use for the profile
                        # If you already have sel_kpis in this scope, keep it.
                        # Otherwise set sel_kpis = <your selected KPI columns list>
                        render_kpi_radar_compare(
                            cohort_df=cohort_df,
                            rows=radar_rows,
                            labels=radar_labels,
                            kpis=sel_kpis,
                            title="KPI percentile radar (vs cohort)",
                            key_prefix=f"{key_prefix}_kpi_compare",
                        )

                        st.markdown("#### Roles, traits, responsibilities (target vs selected)")

                        # ------------------------------------------------------------
                        # Roles, traits, responsibilities (target vs selected)
                        # Better layout for 3+ players: Tabs or 2 column grid
                        # Put this right after:
                        # st.markdown("#### Roles, traits, responsibilities (target vs selected)")
                        # ------------------------------------------------------------

                        cards = [("Target", target_row, f"{key_prefix}_target_pt")]

                        for i, r in enumerate(picked_rows, start=1):
                            nm = str(r.get("Player", "")).strip() or f"Player {i}"
                            cards.append((nm, r, f"{key_prefix}_pick_{i}_pt"))

                        n_cards = len(cards)

                        view_mode = st.radio(
                            "View",
                            options=["Auto", "Tabs", "Grid"],
                            index=0,
                            horizontal=True,
                            key=f"{key_prefix}_rtr_view_mode",
                        )

                        if view_mode == "Auto":
                            # Up to 3 columns is still readable (Target + 2 picked)
                            use_tabs = n_cards > 3
                            use_grid = False
                        elif view_mode == "Tabs":
                            use_tabs = True
                            use_grid = False
                        else:
                            use_tabs = False
                            use_grid = True

                        if use_tabs:
                            tab_labels = [c[0] for c in cards]
                            tabs = st.tabs(tab_labels)

                            for tab, (lbl, row, kp) in zip(tabs, cards):
                                with tab:
                                    if lbl != "Target":
                                        st.markdown(f"**{lbl}**")
                                    else:
                                        st.markdown("**Target**")

                                    render_player_type_and_responsibilities_blocks(
                                        cohort_df=cohort_df,
                                        target_row=row,
                                        position_text=profile_key,
                                        ws_id=str(row.get("Wyscout Id", "")),
                                        key_prefix=kp,
                                    )

                        elif use_grid:
                            # 2 cards per row, wraps nicely for 3+
                            per_row = 2
                            for start in range(0, n_cards, per_row):
                                row_cards = cards[start : start + per_row]
                                row_cols = st.columns(len(row_cards))

                                for col, (lbl, row, kp) in zip(row_cols, row_cards):
                                    with col:
                                        st.markdown(f"**{lbl}**" if lbl else "**Player**")

                                        render_player_type_and_responsibilities_blocks(
                                            cohort_df=cohort_df,
                                            target_row=row,
                                            position_text=profile_key,
                                            ws_id=str(row.get("Wyscout Id", "")),
                                            key_prefix=kp,
                                        )

                        else:
                            # Original side by side behaviour, only used when n_cards <= 3
                            cols = st.columns(n_cards)

                            for col, (lbl, row, kp) in zip(cols, cards):
                                with col:
                                    st.markdown(f"**{lbl}**" if lbl else "**Player**")

                                    render_player_type_and_responsibilities_blocks(
                                        cohort_df=cohort_df,
                                        target_row=row,
                                        position_text=profile_key,
                                        ws_id=str(row.get("Wyscout Id", "")),
                                        key_prefix=kp,
                                    )
                    # ------------------------------------------------------------

                    _render_similarity_section(
                        sim_all,
                        title="Similar players – overall database",
                        top_overall=5,
                        top_u22=3,
                        key_prefix="sim_all",
                        current_player=sel_player,
                    )

                    # Restrict to Belgium / Netherlands / France subset
                    sim_three = _restrict_to_three_nations(sim_all)

                    _render_similarity_section(
                        sim_three,
                        title="Similar players – Belgium / Netherlands / France",
                        top_overall=5,
                        top_u22=3,
                        key_prefix="sim_three",
                        current_player=sel_player,
                    )

    #---------------- Budget alternatives (Moneyball) ----------------
    st.markdown("#### Budget alternatives (Moneyball)")
    st.caption(f"Budget pool rows: {len(source_df)} | cols: {len(source_df.columns)}")

    # 1) Budget slider (uses the same df built by similarity)
    mv_col = "Market value" if "Market value" in source_df.columns else None
    if mv_col is None:
        st.info("Market value column not found in this pool.")
    else:
        parser = globals().get("_mb_parse_value_eur")
        if callable(parser):
            mv = source_df[mv_col].apply(parser)
        else:
            mv = pd.to_numeric(source_df[mv_col], errors="coerce")
        mv = pd.to_numeric(mv, errors="coerce")
        mv = mv.where(mv > 0)

        if mv.notna().any():
            mv_max = int(mv.max())

            budget_max = st.slider(
                "Budget max (€)",
                min_value=0,
                max_value=mv_max,
                value=min(mv_max, 10_000_000),
                step=250_000,
                key=f"{key_prefix}_budget_max",
            )

            df_budget = source_df.copy()
            df_budget["_mv_eur"] = mv
            df_budget = df_budget[df_budget["_mv_eur"].notna() & (df_budget["_mv_eur"] <= budget_max)].copy()

            if df_budget.empty:
                st.info("No players match the budget filter.")
            else:
                # 2) Exact Moneyball renderer (same as Leagues/Graphs)
                render_moneyball_block(
                    df=df_budget,
                    kpi_cols=sel_kpis,                 # use the same KPI list your similarity section used
                    metric_direction=globals().get("metric_direction", {}), # same dict you use elsewhere
                    title="Budget shortlist (Moneyball)",
                    key_prefix=f"{key_prefix}_budget_mb",
                )
        else:
            st.info("Market values are missing or zero in this pool.")


    # Export current profile to PDF
    if st.button("Export this profile to PDF", key="export_player_pdf"):
        try:
            _export_player_report_pdf(
                sel_player=sel_player,
                target_row=target_row,
                league_key=league_key,
                raw_pos=raw_pos,
                minutes_text=mins_text,
                minutes_share_text=share_text,
                player_vals=player_vals,
                league_pcts=league_pcts,
                secondary_pcts=secondary_pcts,
                secondary_label=secondary_label,
                sim_all=sim_all,
                sim_three=sim_three,
            )
            st.success(
                "Saved PDF to "
                r"G:\My Drive\Reference Club\Databases\Scouting Workspace\Data Reports"
            )
        except Exception as e:
            st.error(f"Failed to export PDF: {e}")