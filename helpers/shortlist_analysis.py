from __future__ import annotations

import difflib
import hashlib

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

def _open_report_or_data_profile(
    *,
    ws_id: str,
    player_name: str,
    team_name: str,
    scout_df: pd.DataFrame,
) -> None:
    # 1) Try scouting DB first (opens written report if it exists)
    focus_row_id = _find_row_id_in_scout_db(
        scout_df,
        ws_id=ws_id,
        player_name=player_name,
        team_name=team_name,
    )

    if focus_row_id:
        st.session_state["profile_focus_id"] = str(focus_row_id)
        st.session_state["nav"] = "Player Intelligence"
        st.rerun()

    # 2) Fallback: open the Recruitment Data Workspace Search profile flow
    # Clear any old report focus so the Player reports page does not hijack later
    st.session_state["profile_focus_id"] = None

    # This is the important part: pass intent + a plain name your Search tab can resolve
    st.session_state["da_jump_to"] = "search"
    st.session_state["goto_player_plain"] = str(player_name or "").strip()
    st.session_state["goto_team_plain"] = str(team_name or "").strip()
    st.session_state["goto_ws_id_plain"] = str(ws_id or "").strip()

    st.session_state["nav"] = "Recruitment Data Workspace"
    st.rerun()


def render_team_analysis_tab(master_df, df_scout_db):
    """
    Generalised Team Analysis dashboard for the Reference scouting app.

    Parameters
    ----------
    master_df : pd.DataFrame
        Concatenated Wyscout master dataset (player rows + KPI columns).
    df_scout_db : pd.DataFrame
        Internal scouting DB used for deep linking into Player reports.
    """

    # Profile defs and scoring helpers already used elsewhere in your app
    from helpers.profile_defs import POSITION_ROLES, role_group_from_profile
    from helpers.recruitment_data_analysis import _text_to_profile_key

    try:
        from helpers.recruitment_data_analysis import _score_bundle
    except Exception:
        _score_bundle = None

    try:
        from helpers.recruitment_data_analysis import _percentile_rank
    except Exception:
        _percentile_rank = None

    # -------------------------
    # Small internal utilities
    # -------------------------
    def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
        if df is None or df.empty:
            return None
        cols = list(df.columns)
        low = {str(c).strip().lower(): c for c in cols}
        for name in candidates:
            key = str(name).strip().lower()
            if key in low:
                return low[key]
        return None

    def _safe_str(x) -> str:
        if x is None:
            return ""
        s = str(x).strip()
        if s.lower() in {"nan", "none"}:
            return ""
        return s

    def _to_num(s: pd.Series) -> pd.Series:
        x = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
        return x

    def _minutes_series(df: pd.DataFrame, mins_col: str | None) -> pd.Series:
        if not mins_col or mins_col not in df.columns:
            return pd.Series(np.nan, index=df.index, dtype="float64")
        return _to_num(df[mins_col])

    def _age_series(df: pd.DataFrame, age_col: str | None) -> pd.Series:
        if not age_col or age_col not in df.columns:
            return pd.Series(np.nan, index=df.index, dtype="float64")
        return _to_num(df[age_col])

    def _norm_wsid(v) -> str:
        s = _safe_str(v)
        if not s:
            return ""
        try:
            return str(int(float(s)))
        except Exception:
            return s

    def _ws_id_col(df: pd.DataFrame) -> str | None:
        return _pick_col(
            df,
            [
                "Wyscout Player ID",
                "Wyscout player id",
                "Wyscout ID",
                "Wyscout Id",
                "player_id",
                "Player ID",
                "Player Id",
            ],
        )

    def _get_percentile(series: pd.Series, value: float) -> float:
        if _percentile_rank is not None:
            try:
                return float(_percentile_rank(series, value))
            except Exception:
                pass
        s = _to_num(series).dropna()
        if s.empty or not np.isfinite(value):
            return float("nan")
        return float((s <= float(value)).mean() * 100.0)

    def _find_row_id_in_scout_db(
        scout_df: pd.DataFrame,
        *,
        ws_id: str,
        player_name: str,
        team_name: str,
    ) -> str | None:
        if scout_df is None or scout_df.empty:
            return None

        row_id_col = _pick_col(scout_df, ["Row ID", "RowID", "row_id", "id"])
        if not row_id_col:
            return None

        scout_ws_col = _ws_id_col(scout_df)
        scout_name_col = _pick_col(scout_df, ["Name", "Player", "Player name"])
        scout_team_col = _pick_col(scout_df, ["Player Current Team", "Team", "Club", "Current Team"])

        ws_id_n = _norm_wsid(ws_id)
        player_name_n = _safe_str(player_name).casefold()
        team_name_n = _safe_str(team_name).casefold()

        if scout_ws_col and ws_id_n:
            s = scout_df[scout_ws_col].astype(str).map(_norm_wsid)
            m = scout_df[s == ws_id_n]
            if not m.empty:
                return _safe_str(m.iloc[0][row_id_col]) or None

        if scout_name_col and player_name_n:
            name_s = scout_df[scout_name_col].astype(str).str.strip().str.casefold()
            m = scout_df[name_s == player_name_n]
            if scout_team_col and team_name_n and not m.empty:
                team_s = m[scout_team_col].astype(str).str.strip().str.casefold()
                m2 = m[team_s == team_name_n]
                if not m2.empty:
                    return _safe_str(m2.iloc[0][row_id_col]) or None
            if not m.empty:
                return _safe_str(m.iloc[0][row_id_col]) or None

        return None

    def _open_player_report(
        *,
        ws_id: str,
        player_name: str,
        team_name: str,
        scout_df: pd.DataFrame,
    ) -> None:
        focus_row_id = _find_row_id_in_scout_db(
            scout_df,
            ws_id=ws_id,
            player_name=player_name,
            team_name=team_name,
        )

        if focus_row_id:
            st.session_state["profile_focus_id"] = str(focus_row_id)
        else:
            st.session_state["profile_focus_id"] = None
            st.session_state["rep_search"] = player_name
            if team_name:
                st.session_state["rep_team"] = team_name

        st.session_state["nav"] = "Player Intelligence"
        try:
            st.session_state.nav = "Player Intelligence"
        except Exception:
            pass

        st.rerun()

    # -------------------------
    # Preconditions
    # -------------------------
    if master_df is None or getattr(master_df, "empty", True):
        st.info("No data available.")
        return

    player_col = _pick_col(master_df, ["Player", "Name", "Player name"])
    team_col = _pick_col(master_df, ["Team", "Squad", "Club"])
    pos_col = _pick_col(master_df, ["Position", "Primary position", "Primary Position"])
    mins_col = _pick_col(master_df, ["Minutes played", "Minutes", "Mins", "Min"])
    age_col = _pick_col(master_df, ["Age"])

    if not player_col or not team_col or not pos_col:
        st.warning("Team Analysis needs Player, Team, and Position columns in master_df.")
        return

    if _score_bundle is None:
        st.warning("Role scoring helper (_score_bundle) is not available. Fix the import and rerun.")
        return

    # -------------------------
    # Team selection
    # -------------------------
    teams = sorted(
        [t for t in master_df[team_col].dropna().astype(str).unique().tolist() if str(t).strip()]
    )
    if not teams:
        st.info("No teams found.")
        return

    st.subheader("Team Analysis")

    sel_team = st.selectbox("Select team", options=teams, index=0, key="ta_team")
    team_df = master_df[master_df[team_col].astype(str) == str(sel_team)].copy()

    if team_df.empty:
        st.info("No players found for this team.")
        return

    mins_s = _minutes_series(team_df, mins_col)
    age_s = _age_series(team_df, age_col)

    total_squad = int(team_df[player_col].dropna().shape[0])
    avg_age = float(np.nanmean(age_s.to_numpy(dtype="float64"))) if age_s.notna().any() else np.nan
    top_mins_player = ""
    if mins_s.notna().any():
        idx_max = mins_s.idxmax()
        top_mins_player = _safe_str(team_df.loc[idx_max, player_col])

    c1, c2, c3 = st.columns(3)
    c1.metric("Squad size", f"{total_squad}")
    c2.metric("Average age", f"{avg_age:.1f}" if np.isfinite(avg_age) else "n/a")
    c3.metric("Most minutes", top_mins_player or "n/a")

    # -------------------------
    # Squad Age and Minutes
    # -------------------------
    st.markdown("### Squad Age and Minutes")

    if age_col and px is not None:
        league_age = _age_series(master_df, age_col)
        comp = pd.DataFrame(
            {
                "Group": (["Selected team"] * len(team_df)) + (["League average"] * len(master_df)),
                "Age": pd.concat([age_s, league_age], ignore_index=True),
            }
        ).dropna(subset=["Age"])

        if not comp.empty:
            fig_box = px.box(
                comp,
                x="Group",
                y="Age",
                points="all",
                title="Age distribution: selected team vs league",
            )
            fig_box.update_layout(
                height=420,
                margin=dict(l=10, r=10, t=60, b=10),
            )
            st.plotly_chart(fig_box, use_container_width=True)
            st.caption("Box plot compares the selected team age profile against the wider league.")

    if age_col and mins_col and px is not None:
        df_sc = team_df[[player_col, pos_col]].copy()
        df_sc["Age"] = _age_series(team_df, age_col)
        df_sc["Minutes"] = _minutes_series(team_df, mins_col)
        df_sc = df_sc.dropna(subset=["Age", "Minutes"])

        if not df_sc.empty:
            fig_sc = px.scatter(
                df_sc,
                x="Age",
                y="Minutes",
                title="Age vs Minutes (squad usage map)",
                hover_data={player_col: True, pos_col: True, "Age": True, "Minutes": True},
            )
            fig_sc.update_layout(
                height=460,
                margin=dict(l=10, r=10, t=60, b=10),
            )
            st.plotly_chart(fig_sc, use_container_width=True)
            st.caption("Scatter plot shows squad usage by age and minutes.")

    # -------------------------
    # Tactical Footprint PCA
    # -------------------------
    st.markdown("### Tactical Footprint (PCA)")

    style_metrics = [
        "Passes per 90",
        "Progressive passes per 90",
        "Long passes per 90",
        "Crosses per 90",
        "Touches in box per 90",
        "Shots per 90",
        "xG per 90",
        "Successful defensive actions per 90",
        "Defensive duels per 90",
        "Defensive duels won, %",
    ]
    style_metrics = [m for m in style_metrics if m in master_df.columns]

    if len(style_metrics) < 5:
        st.caption("Not enough style metrics found in this dataset to run PCA.")
    else:
        try:
            from sklearn.decomposition import PCA
            from sklearn.preprocessing import StandardScaler
        except Exception:
            st.warning("scikit-learn is required for the PCA section.")
        else:
            mins_all = _minutes_series(master_df, mins_col)
            team_style_rows = []

            work = master_df[[team_col] + style_metrics].copy()
            w = mins_all.where(mins_all.notna() & (mins_all > 0), 0.0)

            for tname, g in work.groupby(team_col, dropna=False):
                idx = g.index
                wt = w.reindex(idx).fillna(0.0).to_numpy(dtype="float64")
                wt_sum = float(np.sum(wt))

                row = {"Team": _safe_str(tname)}
                for m in style_metrics:
                    v = _to_num(g[m]).to_numpy(dtype="float64")
                    if wt_sum <= 0.0:
                        row[m] = float(np.nanmean(v)) if np.isfinite(np.nanmean(v)) else np.nan
                    else:
                        mask = np.isfinite(v) & np.isfinite(wt)
                        if not np.any(mask):
                            row[m] = np.nan
                        else:
                            row[m] = float(np.sum(v[mask] * wt[mask]) / np.sum(wt[mask]))
                team_style_rows.append(row)

            team_style = pd.DataFrame(team_style_rows).dropna(subset=["Team"]).copy()
            if team_style.empty:
                st.caption("Team aggregation failed for PCA.")
            else:
                X = team_style[style_metrics].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
                X = X.fillna(X.median(numeric_only=True))

                Z = StandardScaler().fit_transform(X.to_numpy(dtype="float64"))
                pca = PCA(n_components=2, random_state=7)
                pcs = pca.fit_transform(Z)

                pca_df = pd.DataFrame(
                    {
                        "Team": team_style["Team"].astype(str).values,
                        "PC1": pcs[:, 0],
                        "PC2": pcs[:, 1],
                    }
                )
                pca_df["Selected"] = np.where(pca_df["Team"] == str(sel_team), "Selected team", "Other teams")

                if px is not None:
                    fig_pca = px.scatter(
                        pca_df,
                        x="PC1",
                        y="PC2",
                        hover_data={"Team": True, "PC1": True, "PC2": True},
                        symbol="Selected",
                        title="Team style map (PCA)",
                        opacity=0.9,
                    )
                    fig_pca.update_layout(
                        xaxis_title="PC1 (possession and progression)",
                        yaxis_title="PC2 (directness and threat)",
                        height=520,
                        margin=dict(l=10, r=10, t=60, b=10),
                    )
                    st.plotly_chart(fig_pca, use_container_width=True)
                    st.caption("Style map places the selected team against league peers using aggregated team metrics.")

                with st.expander("Style metrics used (team aggregated)", expanded=False):
                    st.dataframe(team_style[["Team"] + style_metrics], use_container_width=True, hide_index=True)

    # -------------------------
    # Automatic player role assignment
    # -------------------------
    st.markdown("### Squad roles (automatic)")

    st.session_state.setdefault("ta_role_min_minutes", 180.0)
    if mins_col:
        st.number_input(
            "Minimum minutes for role fit percentage",
            min_value=0,
            max_value=5000,
            value=int(st.session_state["ta_role_min_minutes"]),
            step=30,
            key="ta_role_min_minutes",
        )
    min_minutes_gate = float(st.session_state.get("ta_role_min_minutes", 180.0))

    master_pk = master_df[[pos_col]].copy()
    master_pk["_profile_key"] = master_pk[pos_col].astype(str).map(lambda x: _safe_str(_text_to_profile_key(_safe_str(x))))

    team_scored = team_df.copy()
    team_scored["Top Tactical Role"] = ""
    team_scored["Role Fit %"] = np.nan

    for idx, row in team_scored.iterrows():
        pos_txt = _safe_str(row.get(pos_col, ""))
        profile_key = _safe_str(_text_to_profile_key(pos_txt))
        if not profile_key:
            continue

        role_group = role_group_from_profile(profile_key)
        role_defs = POSITION_ROLES.get(role_group, {}) or {}
        if not role_defs:
            continue

        cohort_mask = master_pk["_profile_key"].astype(str) == profile_key
        cohort_df = master_df.loc[cohort_mask.values].copy()
        if cohort_df.empty:
            cohort_df = master_df

        mins_val = np.nan
        if mins_col and mins_col in team_scored.columns:
            mins_val = float(pd.to_numeric(row.get(mins_col), errors="coerce"))

        best_role = ""
        best_score = -1.0

        for role_name, rules in role_defs.items():
            sc, _detail = _score_bundle(rules, min_kpis=3, cohort_df=cohort_df, target_row=row)
            scf = float(sc) if pd.notna(sc) else -1.0
            if scf > best_score:
                best_score = scf
                best_role = role_name

        team_scored.at[idx, "Top Tactical Role"] = best_role
        if np.isfinite(mins_val) and mins_val >= min_minutes_gate and best_score >= 0:
            team_scored.at[idx, "Role Fit %"] = float(best_score)
        else:
            team_scored.at[idx, "Role Fit %"] = np.nan

    show_cols = [player_col, team_col, pos_col]
    if age_col:
        show_cols.append(age_col)
    if mins_col:
        show_cols.append(mins_col)
    show_cols += ["Top Tactical Role", "Role Fit %"]
    show_cols = [c for c in show_cols if c in team_scored.columns]

    st.dataframe(
        team_scored[show_cols].sort_values("Role Fit %", ascending=False, na_position="last"),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Role Fit %": st.column_config.ProgressColumn(
                "Role Fit %",
                help="Role score from _score_bundle (0 to 100). Blank when minutes are under the gate.",
                min_value=0.0,
                max_value=100.0,
                format="%.0f",
            ),
            "Top Tactical Role": st.column_config.TextColumn("Top Tactical Role"),
        },
    )

    # -------------------------
    # Deep dive
    # -------------------------
    st.markdown("### Player Deep Dive")

    squad_names = team_scored[player_col].dropna().astype(str).tolist()
    if not squad_names:
        st.info("No players available to inspect.")
        return

    sel_player = st.selectbox("Select player", options=squad_names, index=0, key="ta_deep_player")

    prow_df = team_scored[team_scored[player_col].astype(str) == str(sel_player)]
    if prow_df.empty:
        st.info("Player not found in the squad.")
        return
    prow = prow_df.iloc[0]

    top_role = _safe_str(prow.get("Top Tactical Role", ""))
    pos_txt = _safe_str(prow.get(pos_col, ""))
    profile_key = _safe_str(_text_to_profile_key(pos_txt))
    role_group = role_group_from_profile(profile_key) if profile_key else None
    role_defs = POSITION_ROLES.get(role_group, {}) if role_group else {}
    role_rules = role_defs.get(top_role, []) if (role_defs and top_role) else []

    role_kpis: list[str] = []
    for rule in role_rules:
        try:
            metric_name = rule[0]
            if metric_name and metric_name in master_df.columns:
                role_kpis.append(metric_name)
        except Exception:
            continue
    role_kpis = list(dict.fromkeys(role_kpis))

    left, right = st.columns([2, 1], gap="large")

    with left:
        if go is None or not role_kpis:
            st.caption("No role KPI pack found for this assigned role in the current dataset.")
        else:
            pct_vals = []
            raw_vals = []
            for m in role_kpis:
                rv = float(pd.to_numeric(prow.get(m, np.nan), errors="coerce"))
                raw_vals.append(rv)
                if m in master_df.columns and np.isfinite(rv):
                    pct_vals.append(_get_percentile(master_df[m], rv))
                else:
                    pct_vals.append(np.nan)

            thetas = role_kpis + [role_kpis[0]]
            rs = [0.0 if not np.isfinite(v) else float(v) for v in pct_vals]
            rs = rs + [rs[0]]

            fig = go.Figure()
            fig.add_trace(
                go.Scatterpolar(
                    r=rs,
                    theta=thetas,
                    fill="toself",
                    name="Percentile vs global",
                )
            )
            fig.update_layout(
                title=f"{sel_player} | {top_role} KPI radar (global percentiles)",
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                height=520,
                margin=dict(l=10, r=10, t=70, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Radar shows how the selected player compares across role KPIs.")

            df_k = pd.DataFrame({"Metric": role_kpis, "Raw": raw_vals, "Percentile": pct_vals})
            st.dataframe(df_k, use_container_width=True, hide_index=True)

    with right:
        st.markdown("#### Open report")

        ws_col_master = _ws_id_col(master_df)
        ws_id = _norm_wsid(prow.get(ws_col_master, "")) if ws_col_master else ""
        team_name = _safe_str(prow.get(team_col, ""))

        st.caption(
            "If a matching scouting report exists, this opens it directly. "
            "Otherwise it opens Player reports with filters prefilled."
        )

        if st.button("Open Full Scouting Report", type="primary", key="ta_open_report"):
            # 1) Try open a saved scouting report (Player reports detail expects Row ID, not Wyscout id)
            row_id = _find_row_id_in_scout_db(
                scout_df=df_scout_db if isinstance(df_scout_db, pd.DataFrame) else pd.DataFrame(),
                ws_id=ws_id,
                player_name=_safe_str(sel_player),
                team_name=team_name,
            )

            if row_id:
                st.session_state["profile_focus_id"] = str(row_id)
                st.session_state["nav"] = "Player Intelligence"
                st.rerun()

            # 2) Otherwise open the Recruitment Data Workspace player data profile (Search tab behaviour)
            st.session_state["profile_focus_id"] = None
            st.session_state["da_jump_to"] = "search"
            st.session_state["goto_ws_id_plain"] = ws_id
            st.session_state["goto_player_plain"] = _safe_str(sel_player)
            st.session_state["goto_team_plain"] = team_name
            st.session_state["nav"] = "Recruitment Data Workspace"
            st.rerun()