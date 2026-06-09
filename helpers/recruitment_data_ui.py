# helpers/recruitment_data_ui.py

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st


def _da_escape(value) -> str:
    """Small HTML escape helper for custom Streamlit cards."""
    if value is None:
        return ""
    return _html.escape(str(value), quote=True)


def _da_fmt_int(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def _render_data_analysis_styles() -> None:
    """Professional visual shell for the data analysis workspace."""
    st.markdown(
        """
        <style>
        .da-hero {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.82));
            border-radius: 24px;
            padding: 24px 26px;
            margin: 4px 0 18px 0;
            box-shadow: 0 18px 44px rgba(2, 6, 23, 0.32);
        }
        .da-hero-kicker {
            color: #93c5fd;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .da-hero-title {
            color: #f8fafc;
            font-size: 2.1rem;
            line-height: 1.12;
            font-weight: 850;
            margin-bottom: 8px;
        }
        .da-hero-text {
            color: #cbd5e1;
            font-size: 0.98rem;
            max-width: 980px;
        }
        .da-status-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 14px 0 18px 0;
        }
        .da-status-card {
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(15, 23, 42, 0.62);
            border-radius: 18px;
            padding: 14px 16px;
            min-height: 96px;
        }
        .da-status-label {
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .da-status-value {
            color: #f8fafc;
            font-size: 1.55rem;
            font-weight: 850;
            line-height: 1.1;
        }
        .da-status-note {
            color: #cbd5e1;
            font-size: 0.82rem;
            margin-top: 5px;
        }
        .da-workflow-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 6px 0 20px 0;
        }
        .da-workflow-card {
            border: 1px solid rgba(148, 163, 184, 0.14);
            background: rgba(2, 6, 23, 0.42);
            border-radius: 18px;
            padding: 14px 15px;
        }
        .da-workflow-step {
            color: #38bdf8;
            font-size: 0.72rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
        }
        .da-workflow-title {
            color: #f8fafc;
            font-size: 0.98rem;
            font-weight: 800;
            margin-bottom: 5px;
        }
        .da-workflow-text {
            color: #cbd5e1;
            font-size: 0.84rem;
            line-height: 1.35;
        }
        .da-tab-intro {
            border: 1px solid rgba(148, 163, 184, 0.16);
            background: rgba(15, 23, 42, 0.46);
            border-radius: 18px;
            padding: 14px 16px;
            margin: 8px 0 16px 0;
        }
        .da-tab-title {
            color: #f8fafc;
            font-size: 1.05rem;
            font-weight: 850;
            margin-bottom: 4px;
        }
        .da-tab-text {
            color: #cbd5e1;
            font-size: 0.9rem;
            line-height: 1.4;
        }
        .da-scout-note {
            border-left: 4px solid #38bdf8;
            background: rgba(14, 165, 233, 0.08);
            color: #cbd5e1;
            border-radius: 14px;
            padding: 11px 14px;
            margin: 10px 0 18px 0;
            font-size: 0.88rem;
        }

        .da-filter-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 8px 0 14px 0;
        }
        .da-filter-chip {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.58);
            color: #dbeafe;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 0.82rem;
            font-weight: 720;
        }
        .da-reliability-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 5px 9px;
            border: 1px solid rgba(148, 163, 184, 0.24);
            background: rgba(15, 23, 42, 0.62);
            color: #dbeafe;
            font-size: 0.80rem;
            font-weight: 760;
            margin: 4px 6px 4px 0;
        }
        div[data-testid="stTabs"] button p {
            font-weight: 800;
            font-size: 0.92rem;
        }
        div[data-testid="stMetric"] {
            background: rgba(15, 23, 42, 0.42);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 16px;
            padding: 10px 12px;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 14px;
            overflow: hidden;
        }
        @media (max-width: 1200px) {
            .da-status-grid, .da-workflow-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .da-hero-title { font-size: 1.75rem; }
        }
        @media (max-width: 760px) {
            .da-status-grid, .da-workflow-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_data_analysis_header(*, nation_dirs: list[str], div_df: pd.DataFrame, use_elo_norm: bool) -> None:
    markets = len(nation_dirs or [])
    league_files = 0 if div_df is None or div_df.empty else len(div_df)
    tier_one = 0
    tier_two_three = 0
    if div_df is not None and not div_df.empty and "__tier" in div_df.columns:
        tiers = pd.to_numeric(div_df["__tier"], errors="coerce")
        tier_one = int(tiers.eq(1).sum())
        tier_two_three = int(tiers.isin([2, 3]).sum())

    norm_status = "On" if use_elo_norm else "Off"

    st.markdown(
        f"""
        <div class="da-hero">
            <div class="da-hero-kicker">Recruitment data workspace</div>
            <div class="da-hero-title">Data analysis built for scouting decisions</div>
            <div class="da-hero-text">
                Use this page to search by leagues, find outliers, open player profiles, compare shortlist options and check team context. The aim is not to replace video scouting, but to reduce noise before you spend time watching clips and full matches.
            </div>
        </div>
        <div class="da-status-grid">
            <div class="da-status-card">
                <div class="da-status-label">Markets loaded</div>
                <div class="da-status-value">{_da_fmt_int(markets)}</div>
                <div class="da-status-note">Folders discovered from the Wyscout root</div>
            </div>
            <div class="da-status-card">
                <div class="da-status-label">League tier files</div>
                <div class="da-status-value">{_da_fmt_int(league_files)}</div>
                <div class="da-status-note">Available comparison pools</div>
            </div>
            <div class="da-status-card">
                <div class="da-status-label">Tier one pools</div>
                <div class="da-status-value">{_da_fmt_int(tier_one)}</div>
                <div class="da-status-note">Primary benchmark leagues</div>
            </div>
            <div class="da-status-card">
                <div class="da-status-label">ClubElo adjustment</div>
                <div class="da-status-value">{_da_escape(norm_status)}</div>
                <div class="da-status-note">Shared between ranking tabs</div>
            </div>
        </div>
        <div class="da-workflow-grid">
            <div class="da-workflow-card">
                <div class="da-workflow-step">Step 1</div>
                <div class="da-workflow-title">Set the context</div>
                <div class="da-workflow-text">Start with the leagues and tiers you want to search so every player is judged against the right market.</div>
            </div>
            <div class="da-workflow-card">
                <div class="da-workflow-step">Step 2</div>
                <div class="da-workflow-title">Spot the outliers</div>
                <div class="da-workflow-text">Use role KPIs and visual plots to find players who stand apart from their cohort.</div>
            </div>
            <div class="da-workflow-card">
                <div class="da-workflow-step">Step 3</div>
                <div class="da-workflow-title">Open the profile</div>
                <div class="da-workflow-text">Move from numbers into player level evidence, responsibilities and metric breakdowns.</div>
            </div>
            <div class="da-workflow-card">
                <div class="da-workflow-step">Step 4</div>
                <div class="da-workflow-title">Compare shortlist options</div>
                <div class="da-workflow-text">Compare players side by side before deciding who deserves video time or a report.</div>
            </div>
        </div>
        <div class="da-scout-note">
            Scouting note: keep this page as the first filter. The final recommendation should still come from video, role fit, physical profile, character context and target level judgement.
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_data_tab_intro(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="da-tab-intro">
            <div class="da-tab-title">{_da_escape(title)}</div>
            <div class="da-tab-text">{_da_escape(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )