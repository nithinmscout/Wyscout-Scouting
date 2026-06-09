# helpers/player_reports_page.py

from __future__ import annotations
from logging import root
from pathlib import Path
import difflib
import streamlit as st
import pandas as pd
import unicodedata
import csv, json
import os, io, re, datetime as dt, base64, uuid, csv
from datetime import datetime, date
import streamlit.components.v1 as components
import math
import numpy as np
import glob
try:
    import plotly.graph_objects as go
except Exception:
    go = None

from helpers.profile_defs import POSITION_ROLES, GLOBAL_TRAITS, RESPONSIBILITIES,ROLE_DEFINITIONS,TRAIT_DEFINITIONS, RESPONSIBILITY_DEFINITIONS
from helpers.profile_defs import _to_num, role_group_from_profile, _dot_rating_row, norm_col_name, _resolve_metric_col, _weighted_mean, _metric_percentile
from helpers.profile_defs import _compute_responsibility_scores, _render_responsibilities_bar, _render_breakdown_radial
CORE_INDEX_ORDER = [
    "Threat",
    "Creation",
    "Progression",
    "Defensive disruption",
]


def _pr_debug_mode_enabled() -> bool:
    return bool(st.session_state.get("debug_mode", False))


def _pr_display_value(value, fallback: str = "Not added") -> str:
    try:
        if value is None or pd.isna(value):
            return fallback
    except Exception:
        if value is None:
            return fallback
    s = str(value).strip()
    if not s or s.casefold() in {"nan", "none", "nat"}:
        return fallback
    return s


def _pr_escape(value) -> str:
    s = _pr_display_value(value)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


def _pr_status_colour(status: str) -> str:
    return {
        "Green": "#22c55e",
        "Purple": "#a855f7",
        "Blue": "#3b82f6",
        "Red": "#ef4444",
        "Grey": "#94a3b8",
        "Gray": "#94a3b8",
    }.get(str(status).strip(), "#64748b")


def _render_shortlist_status_legend() -> None:
    st.markdown(
        """
        <div class="ux-status-legend">
            <div class="ux-status-pill"><span class="ux-status-dot" style="background:#22c55e;"></span><b>Green</b><br>Strong target</div>
            <div class="ux-status-pill"><span class="ux-status-dot" style="background:#a855f7;"></span><b>Purple</b><br>High potential</div>
            <div class="ux-status-pill"><span class="ux-status-dot" style="background:#3b82f6;"></span><b>Blue</b><br>Monitor</div>
            <div class="ux-status-pill"><span class="ux-status-dot" style="background:#ef4444;"></span><b>Red</b><br>Low fit or reject</div>
            <div class="ux-status-pill"><span class="ux-status-dot" style="background:#94a3b8;"></span><b>Grey</b><br>Parked</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_player_context_bar(row: pd.Series, visible_team: str) -> None:
    name = _pr_display_value(row.get("Name", ""))
    status = _pr_display_value(row.get("Shortlist Status", ""), "No status")
    ws_id = str(row.get("Wyscout Player ID", "") or "").strip()
    report_path = str(row.get("Full Report Path", "") or "").strip()

    chips = [
        ("Club", visible_team),
        ("Age", row.get("Age", "")),
        ("Position", row.get("Position", "")),
        ("Foot", row.get("Dominant Foot", "")),
        ("Current", row.get("Current Rating (1-4)", "")),
        ("Potential", row.get("Potential Rating (1-4)", "")),
        ("Status", status),
        ("Wyscout", "Linked" if ws_id else "Not linked"),
        ("Report", "Uploaded" if report_path else "Not uploaded"),
    ]

    chip_html = []
    for label, value in chips:
        if label == "Status":
            chip_html.append(
                f"<span class='ux-chip' style='border-color:{_pr_status_colour(status)}55;'>"
                f"<span class='ux-status-dot' style='background:{_pr_status_colour(status)};'></span>"
                f"{_pr_escape(label)}: {_pr_escape(value)}</span>"
            )
        else:
            chip_html.append(f"<span class='ux-chip'>{_pr_escape(label)}: {_pr_escape(value)}</span>")

    st.markdown(
        f"""
        <div class="ux-context-bar">
            <div class="ux-context-title">{_pr_escape(name)}</div>
            <div class="ux-context-meta">{''.join(chip_html)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_filter_chips(chips: list[tuple[str, object]]) -> None:
    html_parts = []
    for label, value in chips:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            value_txt = ", ".join([str(v) for v in value if str(v).strip()])
        else:
            value_txt = str(value).strip()
        if not value_txt:
            continue
        html_parts.append(f"<span class='ux-chip'>{_pr_escape(label)}: {_pr_escape(value_txt)}</span>")

    if not html_parts:
        html_parts.append("<span class='ux-chip ux-chip-muted'>No active filters</span>")

    st.markdown(
        "<div class='ux-chip-row'>" + "".join(html_parts) + "</div>",
        unsafe_allow_html=True,
    )


def _render_empty_player_results() -> None:
    st.markdown(
        """
        <div class="ux-empty-state">
            <div class="ux-empty-title">No players match this screen.</div>
            <div class="ux-empty-text">
                Try widening the age range, clearing the role filter, removing one status filter or searching across all teams.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _norm_wsid(v) -> str:
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        return str(int(float(s)))  # turns 12345.0 into 12345
    except Exception:
        return s

def _safe_to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

def _ensure_player_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure df has a 'Player' column by aliasing common name columns.
    """
    if df is None or df.empty:
        return df

    if "Player" in df.columns:
        return df

    candidates = [
        "Name",
        "Player name",
        "Player Name",
        "player",
        "player_name",
        "PlayerName",
    ]
    for c in candidates:
        if c in df.columns:
            df = df.copy()
            df["Player"] = df[c].astype(str)
            return df

    return df

def _ensure_division_label(master: pd.DataFrame) -> pd.DataFrame:
    """
    Ensures master has __division built from __nation + __tier (or file digits fallback).
    """
    if master is None or master.empty:
        return master

    def _division_label(nation: str, tier, src: str) -> str:
        t = str(tier).strip() if tier is not None else ""
        if not t or t == "0":
            try:
                base = str(src).split("/")[-1].split("\\")[-1]
                digits = "".join(ch for ch in base if ch.isdigit())
                t = digits[-1] if digits else "1"
            except Exception:
                t = "1"
        nm = str(nation).strip()
        return f"{nm}{t}"

    if "__division" not in master.columns:
        master = master.copy()
        master["__division"] = master.apply(
            lambda rr: _division_label(
                str(rr.get("__nation", "")),
                rr.get("__tier", ""),
                str(rr.get("__source_file", "")),
            ),
            axis=1,
        )
    return master


def parse_eur_value(s: str):
    """Parse strings like '€2.5m', '€250k', '2,000,000', '2.5 million' → float euros."""
    if not s:
        return None
    txt = str(s).lower().replace("€", "").replace("eur", "").strip()
    txt = txt.replace(",", "")
    mult = 1.0

    if "million" in txt:
        try:
            return float(txt.split()[0]) * 1_000_000
        except:
            pass

    if txt.endswith("m"):
        mult = 1_000_000.0
        txt = txt[:-1]
    elif txt.endswith("k"):
        mult = 1_000.0
        txt = txt[:-1]

    try:
        return float(txt) * mult
    except:
        return None


def fmt_eur_compact(v):
    """Format float euros → '€50k', '€0.1m', '€1m', '€10m'."""
    if v is None:
        return ""
    try:
        v = float(v)
    except:
        return ""

    if v >= 1_000_000:
        val = round(v / 1_000_000, 2)
        if val >= 10:
            val = round(val, 0)
            val = int(val)
        return f"€{val}m"

    if v >= 1_000:
        val = round(v / 1_000, 0)
        val = int(val)
        return f"€{val}k"

    if v > 0:
        val = round(v / 1_000, 1)
        return f"€{val}k"

    return "€0"

def _tidy_person_name(name: str) -> str:
    if not name:
        return ""
    s = " ".join(str(name).strip().split())
    parts = [p.capitalize() if p.islower() else p for p in s.split(" ")]
    return " ".join(parts)

def wyscoutfolders() -> list[str]:
    """
    Return the folders for Belgium/Dutch/France Wyscout exports.
    Works cross-platform by detecting the root from Reference2.py's ROOT variable.
    Falls back to environment variable if needed.
    """
    # Try to get the root from the main module first
    try:
        # 1) Try environment variable (set by Reference2.py at startup)
        root = os.environ.get("WYSROOTDIR") or os.environ.get("SCOUTING_APP_ROOT")

        if not root:
            # 2) Fallback: walk up from current file to find "Reference Club"
            current = Path(__file__).resolve()
            for parent in [current] + list(current.parents):
                if "Reference" in parent.name or "Scouting" in parent.name:  # More flexible matching
                    # Found the "Scouting Workspace" folder, go up one more level
                    root = str(parent.parent)
                    break
            
        if not root:
            # 3) Last resort: use repo root
            root = str(Path(__file__).resolve().parent.parent)
    except ImportError:
        # Repo-relative fallback (same as Reference2.py resolve_root)
        here = Path(__file__).resolve().parent.parent  # go up to project root
        root = str(here)
        if not root:
            # Last resort: try to find 'Reference Club' folder by walking up from cwd
            cwd = os.getcwd()
            for parent in [cwd] + [os.path.dirname(p) for p in [cwd] * 10]:
                candidate = os.path.join(parent, "Reference Club", "Databases", "Scouting Workspace25-26")
                if os.path.isdir(candidate):
                    root = candidate
                    break
            else:
                # Cross-platform fallback: use repo root if env var missing
                root = str(Path(__file__).resolve().parent.parent)

    
    # Build the three market folders under root
    folders = [
        os.path.join(root, "Belgium"),
        os.path.join(root, "Dutch"),
        os.path.join(root, "France"),
    ]
    
    # Validate and filter to only existing directories
    existing = [f for f in folders if os.path.isdir(f)]
    
    return existing


@st.cache_data(show_spinner=False)
def load_wyscout_master() -> pd.DataFrame:
    frames = []
    for folder in wyscoutfolders():
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if not fn.lower().endswith(".csv"):
                continue
            path = os.path.join(folder, fn)
            try:
                df = pd.read_csv(path)
            except Exception as e:
                # collect read errors for the debug expander
                errs = st.session_state.setdefault("wyscout_read_errors", [])
                errs.append(f"CSV read failed: {path} | {repr(e)}")
                continue


            # add provenance columns used by your UI
            df["__source_file"] = fn
            # infer nation/tier however you do it
            df["__nation"] = os.path.basename(folder).strip()
            df["__tier"] = ""
            frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

def _load_player_cohort_from_wyscout(*args, **kwargs):
    """
    Cohort loader used by the Player Report "Data" block.

    Supports BOTH calling styles:
      A) New UI style (keywords):
         _load_player_cohort_from_wyscout(player_row=..., nation_dirs=..., parse_division=...)
         Returns: (cohort_df, cohort_label)

      B) Legacy style (positional):
         _load_player_cohort_from_wyscout(master, sel_divisions, min_minutes, age_min, age_max)
         Returns: (cohort_df, cohort_label)
    """

    # ----------------------------
    # Helper to filter a master df
    # ----------------------------
    def _filter_master(master_df: pd.DataFrame, sel_divisions, min_minutes, age_min, age_max):
        if master_df is None or master_df.empty:
            return master_df

        master_df = _ensure_division_label(master_df)

        mins = pd.to_numeric(master_df.get("Minutes played", 0), errors="coerce").fillna(0)

        ages = _safe_to_num(
            master_df.get("Age", pd.Series([np.nan] * len(master_df), index=master_df.index))
        )

        if sel_divisions and "__division" in master_df.columns:
            mask_div = master_df["__division"].isin(sel_divisions)
        else:
            mask_div = pd.Series(True, index=master_df.index)

        mask_mins = mins >= float(min_minutes)
        mask_age = (ages >= float(age_min)) & (ages <= float(age_max))

        return master_df[mask_div & mask_mins & mask_age].copy()

    # ---------------------------------------
    # Style B: legacy positional call support
    # ---------------------------------------
    if len(args) >= 5 and isinstance(args[0], pd.DataFrame):
        master = args[0]
        sel_divisions = args[1] or []
        min_minutes = int(args[2])
        age_min = int(args[3])
        age_max = int(args[4])

        cohort = _filter_master(master, sel_divisions, min_minutes, age_min, age_max)
        div_txt = ", ".join(map(str, sel_divisions)) if sel_divisions else "All divisions"
        label = f"{div_txt} | mins ≥ {min_minutes} | age {age_min}-{age_max}"
        return cohort, label

    # ---------------------------------------
    # Style A: new keyword call support (UI)
    # ---------------------------------------
    player_row = kwargs.get("player_row", None)
    parse_division = kwargs.get("parse_division", None)

    master = kwargs.get("master", None)
    if master is None:
        # your helper already uses load_wyscout_master() elsewhere in the same file
        master = load_wyscout_master()

    if master is None or master.empty:
        return master, "No Wyscout master loaded"

    master = _ensure_division_label(master)

    # Defaults (use session_state if you later add sliders)
    min_minutes = int(kwargs.get("min_minutes", st.session_state.get("cohort_min_minutes", 360)))
    age_min = int(kwargs.get("age_min", st.session_state.get("cohort_age_min", 15)))
    age_max = int(kwargs.get("age_max", st.session_state.get("cohort_age_max", 40)))

    # Infer division from the selected player row (must match master["__division"])
    inferred_div = ""

    if player_row is not None:
        # If your scouting DB row already has a __division label, use it
        inferred_div = str(player_row.get("__division", "")).strip()

        # Else build it from (Playing Nation, Division) using your parse_division helper
        if not inferred_div and callable(parse_division):
            try:
                nat_hint, tier_hint = parse_division(
                    str(player_row.get("Playing Nation", "")),
                    str(player_row.get("Division", "")),
                )
                nat_hint = str(nat_hint or "").strip()
                tier_hint = str(tier_hint or "").strip()
                inferred_div = f"{nat_hint}{tier_hint}" if nat_hint and tier_hint else ""
            except Exception:
                inferred_div = ""

    # Only keep inferred_div if it actually exists in the master __division list
    valid_divs = set(master["__division"].dropna().astype(str).str.strip().unique().tolist())
    if inferred_div not in valid_divs:
        inferred_div = ""

    sel_divisions = kwargs.get("sel_divisions", None)
    if sel_divisions is None:
        sel_divisions = [inferred_div] if inferred_div else []
    else:
        # sanitize any externally passed divisions too
        sel_divisions = [str(d).strip() for d in sel_divisions if str(d).strip() in valid_divs]


    cohort = _filter_master(master, sel_divisions, min_minutes, age_min, age_max)

    div_txt = ", ".join(map(str, sel_divisions)) if sel_divisions else "All divisions"
    label = f"{div_txt} | mins ≥ {min_minutes} | age {age_min}-{age_max}"

    return cohort, label


def overall_score_from_clusters(row: pd.Series, packs: dict, weights: dict) -> float:
    """
    Weighted mean of cluster means of z-scores.
    Expects each metric to have a derived column: <metric>__z
    """
    vals = []
    wts = []
    for cluster, metrics in packs.items():
        zvals = []
        for m in metrics:
            zcol = f"{m}__z"
            if zcol in row.index and pd.notna(row[zcol]):
                try:
                    zvals.append(float(row[zcol]))
                except Exception:
                    pass
        if zvals:
            vals.append(float(np.mean(zvals)))
            wts.append(float(weights.get(cluster, 1.0)))

    if not vals:
        return float("nan")
    return float(np.average(vals, weights=wts))


def prepare_cohort_analysis(
    master: pd.DataFrame,
    target_player_name: str | None,
    target_wyscout_id: str | None,
    cohort_type: str,
    role_profile: str | None,
    general_group: str | None,
    min_minutes: int,
    age_min: int,
    age_max: int,
) -> tuple[pd.DataFrame, dict, dict, pd.Series]:
    """
    Builds ztab (cohort table) plus packs and weights and resolves the target_row.

    Cohort selection logic:
    If cohort_type == "ROLE_PROFILE" then we filter by Position containing the chosen role_profile (string contains).
    Else we filter by a simple macro group mapping using Position text when _group is not available.

    Then we compute z-scores and percentiles for a practical set of metrics that exist in your export.
    """

    if master is None or master.empty:
        return pd.DataFrame(), {}, {}, pd.Series(dtype=object)

    ztab = master.copy()
    ztab = _ensure_division_label(ztab)

    pos_col = "Position" if "Position" in ztab.columns else None

    def _pos_contains(role_code: str) -> pd.Series:
        if not pos_col or not role_code:
            return pd.Series(True, index=ztab.index)
        rc = role_code.strip().casefold()
        return ztab[pos_col].astype(str).str.casefold().str.contains(rc, na=False)

    def _macro_group_from_position(pos_text: str) -> str:
        t = str(pos_text or "").casefold()
        if "gk" in t:
            return "GK"
        if any(x in t for x in ["2", "3", "rb", "lb", "rwb", "lwb", "fb", "wb"]):
            return "FB"
        if any(x in t for x in ["4", "5", "cb", "rcb", "lcb", "ccb"]):
            return "CB"
        if "6" in t or "dm" in t:
            return "DM"
        if "8" in t or "cm" in t:
            return "CM"
        if "10" in t or "am" in t or "cam" in t:
            return "AM"
        if any(x in t for x in ["rwf", "lwf", "wf", "7a", "11a"]):
            return "WF"
        if any(x in t for x in ["11", "7", "rw", "lw", "rm", "lm", "wm", "w"]):
            return "WM"
        if any(x in t for x in ["9", "cf", "st", "tm"]):
            return "CF"
        return "WM"

    if cohort_type == "ROLE_PROFILE":
        mask_role = _pos_contains(role_profile or "")
        ztab = ztab[mask_role].copy()
    else:
        if "_group" in ztab.columns and general_group:
            ztab = ztab[ztab["_group"].astype(str) == str(general_group)].copy()
        elif general_group and pos_col:
            ztab = ztab[ztab[pos_col].astype(str).map(_macro_group_from_position) == str(general_group)].copy()

    if ztab.empty:
        return pd.DataFrame(), {}, {}, pd.Series(dtype=object)

    candidate_metrics = [
        "Successful attacking actions per 90",
        "Goals per 90",
        "Non-penalty goals per 90",
        "xG per 90",
        "Assists per 90",
        "xA per 90",
        "Shot assists per 90",
        "Key passes per 90",
        "Smart passes per 90",
        "Progressive runs per 90",
        "Progressive passes per 90",
        "Passes to final third per 90",
        "Passes to penalty area per 90",
        "Deep completions per 90",
        "Dribbles per 90",
        "Successful dribbles, %",
        "Touches in box per 90",
        "Successful defensive actions per 90",
        "Defensive duels per 90",
        "Defensive duels won, %",
        "Interceptions per 90",
        "PAdj Interceptions",
        "Sliding tackles per 90",
        "PAdj Sliding tackles",
        "Shots blocked per 90",
        "Aerial duels per 90",
        "Aerial duels won, %",
        "Duels per 90",
        "Duels won, %",
        "Fouls per 90",
        "Yellow cards per 90",
        "Red cards per 90",
    ]

    metrics = [m for m in candidate_metrics if m in ztab.columns]

    if not metrics:
        return ztab, {}, {}, pd.Series(dtype=object)

    negative_metrics = {"Fouls per 90", "Yellow cards per 90", "Red cards per 90"}

    for m in metrics:
        s = _safe_to_num(ztab[m])
        if m in negative_metrics:
            s = -s

        mu = float(s.mean(skipna=True)) if s.notna().any() else float("nan")
        sd = float(s.std(ddof=0, skipna=True)) if s.notna().any() else float("nan")
        if not sd or (isinstance(sd, float) and (math.isnan(sd) or sd == 0.0)):
            z = pd.Series([np.nan] * len(s), index=s.index)
        else:
            z = (s - mu) / sd

        ztab[f"{m}__mu"] = mu
        ztab[f"{m}__sd"] = sd
        ztab[f"{m}__z"] = z

        rnk = s.rank(pct=True, ascending=True)
        ztab[f"{m}__pct"] = (rnk * 100.0)

        ztab[f"{m}__rank"] = s.rank(ascending=False, method="min")

    packs = {
        "Threat": [m for m in ["Goals per 90", "Non-penalty goals per 90", "xG per 90", "Touches in box per 90"] if m in metrics],
        "Creativity": [m for m in ["Assists per 90", "xA per 90", "Key passes per 90", "Shot assists per 90", "Smart passes per 90"] if m in metrics],
        "Progression": [m for m in ["Progressive runs per 90", "Progressive passes per 90", "Deep completions per 90", "Passes to final third per 90", "Passes to penalty area per 90"] if m in metrics],
        "Ball winning": [m for m in ["Successful defensive actions per 90", "Interceptions per 90", "PAdj Interceptions", "Sliding tackles per 90", "PAdj Sliding tackles", "Shots blocked per 90"] if m in metrics],
        "Duelling": [m for m in ["Defensive duels per 90", "Defensive duels won, %", "Aerial duels per 90", "Aerial duels won, %", "Duels per 90", "Duels won, %"] if m in metrics],
        "Discipline": [m for m in ["Fouls per 90", "Yellow cards per 90", "Red cards per 90"] if m in metrics],
    }
    packs = {k: v for k, v in packs.items() if v}

    weights = {k: 1.0 for k in packs.keys()}

    ztab["__overall_score"] = ztab.apply(lambda row: overall_score_from_clusters(row, packs, weights), axis=1)
    ztab["__overall_rank"] = ztab["__overall_score"].rank(ascending=False, method="min")
    ztab["__overall_pct"] = ztab["__overall_score"].rank(pct=True, ascending=True) * 100.0

    target_row = pd.Series(dtype=object)
    if target_wyscout_id and "Wyscout Player ID" in ztab.columns:
        hit = ztab[ztab["Wyscout Player ID"].astype(str) == str(target_wyscout_id)]
        if not hit.empty:
            target_row = hit.iloc[0]
    if target_row.empty and target_player_name:
        name_col = "Player" if "Player" in ztab.columns else ("Name" if "Name" in ztab.columns else None)
        if name_col:
            hit = ztab[ztab[name_col].astype(str).str.casefold() == str(target_player_name).casefold()]
            if not hit.empty:
                target_row = hit.iloc[0]

    return ztab, packs, weights, target_row


def _infer_profile_key(pos_text: str) -> str:
    t = (pos_text or "").strip().lower()

    # GK
    if "gk" in t:
        return "GK"

    # Centre backs
    if any(x in t for x in ["cb", "rcb", "lcb"]):
        return "CB"

    # Full backs / wing backs
    if any(x in t for x in ["rb", "lb", "rwb", "lwb"]):
        return "WB"

    # Defensive midfielders (#6)
    if any(x in t for x in ["dmf", "rdmf", "ldmf", "dm", "6"]):
        return "6"

    # Central midfielders (#8)
    if any(x in t for x in ["cmf", "rcmf", "lcmf", "cm", "8"]):
        return "8"

    # Attacking midfielders (#10)
    if any(x in t for x in ["amf", "am", "cam", "10"]):
        return "10"

    # Wide forwards (RWF/LWF) vs classic wide players (RW/LW/RM/LM)
    if any(x in t for x in ["rwf", "lwf", "wf"]):
        return "WF"
    if any(x in t for x in ["rw", "lw", "rm", "lm", "ramf", "lamf", "wm", "w"]):
        return "WM"

    # Strikers
    if any(x in t for x in ["tm"]):
        return "TM"
    if any(x in t for x in ["cf", "st", "ss", "9"]):
        return "CF"

    # Safe default
    return "CF"


def render_player_report_indexes_block(
    *,
    player_row: pd.Series,
    full_df: pd.DataFrame,
    nation_dirs,
    parse_division,
):
    """
    Player type section.
    Reuses the same cohort table and player row used by positional responsibilities.

    Inputs come from session state:
      - cohort_df_current: ztab (cohort table with raw metrics + __z/__pct columns)
      - ws_row_current: the target player row from that same table
    """

    st.subheader("Player type")

    if go is None:
        st.info("Plotly is not available, cannot render bar charts.")
        return

    cohort_df = st.session_state.get("cohort_df_current", pd.DataFrame())
    ws_row = st.session_state.get("ws_row_current", pd.Series(dtype=object))

    if cohort_df is None or cohort_df.empty or ws_row is None or ws_row.empty:
        st.info("Build the cohort in the Data section first, then this player type panel will populate.")
        return

    # Determine position key using the same logic as responsibilities
    pos_text = str(ws_row.get("Position", "")).strip()
    if not pos_text:
        pos_text = str(player_row.get("Position", "")).strip()

    profile_key = _infer_profile_key(pos_text)

    # Map to role groups used below
    role_group = role_group_from_profile(profile_key)
    role_defs = POSITION_ROLES.get(role_group, {})

    # KPI rule tuple:
    #


    # ---------------------------------------------------------------------
    # 1) ADD THESE DICTIONARIES (place near POSITION_ROLES / GLOBAL_TRAITS)
    # ---------------------------------------------------------------------

    ################################################################################


    def _metric_goodness_pct(metric_name: str, higher_is_better: bool) -> tuple[float, float, str]:
        """
        Returns (cdf_score_0_to_100, raw_player_value, resolved_column)

        cdf_score is computed from a robust z score (median, MAD) mapped through a normal CDF:
        score = 100 * Phi(z)

        Low minutes are shrunk towards cohort median before z scoring.
        """

        resolved = _resolve_metric_col(cohort_df, metric_name)
        if not resolved:
            return float("nan"), float("nan"), ""

        pv_raw = _to_num(ws_row.get(resolved, float("nan")))
        if pv_raw != pv_raw:
            return float("nan"), float("nan"), resolved

        # Minutes shrinkage, shrink towards cohort median for low minutes players
        mins = _to_num(ws_row.get("Minutes played", ws_row.get("Minutes", float("nan"))))
        if mins != mins:
            mins = _to_num(player_row.get("Minutes played", player_row.get("Minutes", 0.0)))
        mins = float(mins) if mins == mins else 0.0

        ser = pd.to_numeric(cohort_df[resolved], errors="coerce")
        ser = ser.replace([np.inf, -np.inf], np.nan).dropna()
        if ser.empty:
            return float("nan"), pv_raw, resolved

        med = float(ser.median())
        mad = float((ser - med).abs().median())

        # Shrinkage weight
        m0 = 900.0
        w = mins / (mins + m0) if (mins + m0) > 0 else 0.0
        x_shrunk = (w * pv_raw) + ((1.0 - w) * med)

        # Robust scale, fallback if MAD is zero
        scale = 1.4826 * mad
        if not (scale > 0):
            sd = float(ser.std(ddof=0))
            scale = sd if sd > 0 else 1.0

        z = (x_shrunk - med) / scale

        # Make the direction always "higher is better"
        if not higher_is_better:
            z = -z

        # Cap extremes so one KPI cannot dominate the chart
        z = max(-3.0, min(3.0, float(z)))

        # Normal CDF via erf
        phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        score = 100.0 * phi

        return float(score), float(pv_raw), resolved


    def _score_bundle(bundle_rules: list[tuple[str, float, bool, float]], min_kpis: int = 3):
        met = []
        total_w = 0.0
        met_w = 0.0
        evaluated = 0

        for metric_name, thr, hib, w in bundle_rules:
            g, pv, resolved = _metric_goodness_pct(metric_name, hib)
            if g != g:
                continue

            evaluated += 1
            total_w += float(w)
            hit = bool(g >= float(thr))
            if hit:
                met_w += float(w)

            met.append(
                {
                    "metric": metric_name,
                    "resolved": resolved,
                    "goodness_pct": float(g),
                    "threshold": float(thr),
                    "player_value": pv,
                    "hit": hit,
                    "weight": float(w),
                }
            )

        if evaluated < min_kpis or total_w <= 0:
            return float("nan"), met

        score = (met_w / total_w) * 100.0
        return float(score), met

    def _render_hbar(
        title: str,
        rows: list[tuple[str, float]],
        *,
        defs: dict[str, str] | None = None,
        height_base: int = 260,
    ):
        if not rows:
            st.info(f"No scores available for {title}.")
            return

        rows = sorted(rows, key=lambda x: x[1], reverse=True)
        names = [r[0] for r in rows]
        vals = [float(r[1]) for r in rows]

        # definitions per bar
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
        st.plotly_chart(fig, use_container_width=True)
    # ---------------------------------------------------------------------
    # Compute position roles
    role_defs = POSITION_ROLES.get(role_group, {})
    role_scores = []
    role_detail = {}

    for role_name, rules in role_defs.items():
        score, detail = _score_bundle(rules, min_kpis=3)
        if score == score:
            role_scores.append((role_name, score))
            role_detail[role_name] = detail

    # Compute global traits
    trait_scores = []
    trait_detail = {}
    for trait_name, rules in GLOBAL_TRAITS.items():
        score, detail = _score_bundle(rules, min_kpis=3)
        if score == score:
            trait_scores.append((trait_name, score))
            trait_detail[trait_name] = detail

    # Display
    left, right = st.columns([1, 1])

    with left:
        st.caption(f"Position: {pos_text}   |   Role group: {role_group}")
        _render_hbar("Position roles", role_scores, defs=ROLE_DEFINITIONS)

    with right:
        _render_hbar("Cross position traits", trait_scores, defs=TRAIT_DEFINITIONS)

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
                st.dataframe(pd.DataFrame(hits)[["metric", "player_value", "goodness_pct", "threshold"]], use_container_width=True, hide_index=True)
            if misses:
                st.write("Missed KPIs:")
                st.dataframe(pd.DataFrame(misses)[["metric", "player_value", "goodness_pct", "threshold"]], use_container_width=True, hide_index=True)

        st.markdown("### Cross position traits")
        for name, sc in sorted(trait_scores, key=lambda x: x[1], reverse=True)[:show_top_n]:
            st.markdown(f"**{name}**  \nScore: {sc:.0f}")
            dd = trait_detail.get(name, [])
            hits = [x for x in dd if x.get("hit")]
            misses = [x for x in dd if not x.get("hit")]
            if hits:
                st.write("Hit KPIs:")
                st.dataframe(pd.DataFrame(hits)[["metric", "player_value", "goodness_pct", "threshold"]], use_container_width=True, hide_index=True)
            if misses:
                st.write("Missed KPIs:")
                st.dataframe(pd.DataFrame(misses)[["metric", "player_value", "goodness_pct", "threshold"]], use_container_width=True, hide_index=True)


def render_player_reports_page(
    *,
    load_db,
    safe_write_db,
    PHOTO_DIR,
    DEFAULT_DB_CSV,
    compute_age_series,
    ROLE_ORDER,
    normalize_roles_to_options,
    _idx_by_row_id,
    load_wyscout_master,
    try_auto_attach_wyscout_id,
    find_wyscout_candidates,
    _sort_newest_first,
    wyscoutfolders,
    _parse_division,
    render_player_card,
    ROW_ID_COL,
    _safe_unlink,
    profile_editor,
    log_df_identity=None,
    scrape_transfermarkt=None,
    scrape_transfermarkt_from_reep_register=None,
    download_image_to_disk=None,
    _embed_pdf_data_uri=None,
    _render_pdf_as_images=None,
    app_root=None,
    wys_root=None,
):
    
    PHOTODIR = PHOTO_DIR
    def resolve_photo_src(row: pd.Series, photodir: str) -> str | None:
        raw = str(row.get("Photo Path", "") or "").strip()
        url = str(row.get("Photo URL", "") or "").strip()

        # 1) If it looks like a URL, Streamlit can load it directly
        if url.startswith("http://") or url.startswith("https://"):
            return url

        if raw:
            # 2) Normalise Windows slashes -> cross-platform
            raw_norm = os.path.normpath(raw.replace("\\", os.sep).replace("/", os.sep))

            # 3) If it's already a valid absolute path, use it
            if os.path.isabs(raw_norm) and os.path.exists(raw_norm):
                return raw_norm

            # 3b) If it's a RELATIVE path like "Scouting Workspace\player photos\...",
            # resolve it relative to ROOT (from environment or repo root)
            from pathlib import Path
            absolute_candidate = Path(app_root) / raw_norm
            if absolute_candidate.exists():
                return str(absolute_candidate)


            # 4) If it's relative (or points to old "Scouting Workspace\\player photos\\"),
            # force it into PHOTODIR by taking only the filename
            fname = os.path.basename(raw_norm)
            cand = os.path.join(str(photodir), fname)
            if os.path.exists(cand):
                return cand

        # 5) Final fallback: try name-based lookup in PHOTODIR
        safename = re.sub(r"[^\w\- ]+", "", str(row.get("Name", "player")).strip())
        candjpg = os.path.join(str(photodir), f"{safename}.jpg")
        candpng = os.path.join(str(photodir), f"{safename}.png")
        if os.path.exists(candjpg):
            return candjpg
        if os.path.exists(candpng):
            return candpng

        return None
    
    if app_root is None:
        app_root = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent))
    else:
        app_root = Path(app_root)

    if wys_root is None:
        wys_root = Path(os.environ.get("WYSROOTDIR", app_root / "Scouting Workspace" / "25 26"))
    else:
        wys_root = Path(wys_root)

    def _split_positions(pos_text: str) -> list[str]:
        raw = str(pos_text or "").replace("/", ",").replace(";", ",")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        out, seen = [], set()
        for p in parts:
            key = p.casefold()
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _infer_profile_key_from_pos(pos_text: str) -> str:
        return _infer_profile_key(pos_text)

    def _log_save_identity(label: str, data_frame: pd.DataFrame) -> None:
        if callable(log_df_identity):
            log_df_identity(label, data_frame)

    # keep the rest of your page code exactly the same

    """
    Player reports page, moved out of main file.
    The function arguments are dependencies provided by main to avoid circular imports.
    """

    st.title("Player reporting")

    df = load_db(st.session_state.db_csv).copy()
    df = _sort_newest_first(df)

    focus_idx = None
    focus_id = st.session_state.get("profile_focus_id")
    if focus_id:
        focus_idx = _idx_by_row_id(df, focus_id)


    def select_or_add(label: str, options: list[str], current: str, key: str) -> str:
        base = [""] + sorted([x for x in set(options) if x]) + ["Add new…"]
        if current and current not in base:
            base = [current] + base
        choice = st.selectbox(label, base, index=(base.index(current) if current in base else 0), key=key)
        if choice == "Add new…":
            return st.text_input(f"New {label.lower()}", key=f"{key}_new")
        return choice

    # ---- Filters (same as your main file)
    def _reset_player_report_filters() -> None:
        for key, value in {
            "rep_search": "",
            "rep_team": "",
            "rep_role": "",
            "rep_nat": "",
            "rep_verdict": "",
        }.items():
            st.session_state[key] = value

    filter_title_col, filter_reset_col = st.columns([5, 1])
    with filter_title_col:
        st.markdown("#### Player filters")
    with filter_reset_col:
        if st.button("Reset filters", key="rep_reset_filters", use_container_width=True):
            _reset_player_report_filters()
            st.rerun()

    fcols = st.columns([2, 2, 2, 2, 2, 2])
    name_q = fcols[0].text_input("Search name", key="rep_search")
    f_team = fcols[1].selectbox("Team", [""] + sorted(df["Player Current Team"].unique().tolist()), key="rep_team")
    f_role = fcols[2].selectbox("Role (contains)", [""] + ROLE_ORDER, key="rep_role")
    f_nation = fcols[3].selectbox("Playing Nation", [""] + sorted(df["Playing Nation"].unique().tolist()), key="rep_nat")
    f_verdict = fcols[4].selectbox("Verdict", [""] + sorted(df["Verdict"].unique().tolist()), key="rep_verdict")

    age_series_rep_all = compute_age_series(df)
    amin = int(age_series_rep_all.dropna().min()) if age_series_rep_all.notna().any() else 15
    amax = int(age_series_rep_all.dropna().max()) if age_series_rep_all.notna().any() else 40

    if amin == amax:
        amin = max(amin - 1, 15)
        amax = amax + 1

    age_min_rep, age_max_rep = fcols[5].slider(
        "Age",
        min_value=amin,
        max_value=amax,
        value=(amin, amax),
        key="rep_age",
    )

    _render_filter_chips(
        [
            ("Name", name_q),
            ("Team", f_team),
            ("Role", f_role),
            ("Playing nation", f_nation),
            ("Verdict", f_verdict),
            ("Age", f"{age_min_rep} to {age_max_rep}" if (age_min_rep, age_max_rep) != (amin, amax) else ""),
        ]
    )

    #Make sure roots are paths
    if app_root is None:
        app_root = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent))
    else:
        app_root = Path(app_root)

    if wys_root is None:
        wys_root = Path(os.environ.get("WYSROOTDIR", app_root / "Scouting Workspace" / "25 26"))
    else:
        wys_root = Path(wys_root)

    # Wyscout debug info
    if _pr_debug_mode_enabled():
        with st.expander("Paths and Wyscout debug", expanded=False):
            APP_ROOT = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent))
            WYS_ROOT_LOCAL = Path(os.environ.get("WYSROOTDIR", APP_ROOT / "Scouting Workspace" / "25 26"))
            PHOTO_DIR_LOCAL = APP_ROOT / "Scouting Workspace" / "player photos"

            debug_lines = [
                f"ROOT: {APP_ROOT}",
                f"WYS_ROOT: {WYS_ROOT_LOCAL}",
                f"PHOTO_DIR: {PHOTO_DIR_LOCAL}",
                f"cwd: {os.getcwd()}",
                f"ROOT exists: {APP_ROOT.exists()}",
                f"WYS_ROOT exists: {WYS_ROOT_LOCAL.exists()}",
                f"PHOTO_DIR exists: {PHOTO_DIR_LOCAL.exists()}",
            ]
            st.code("\n".join(debug_lines))
            base = app_root / "Scouting Workspace"
            st.code(f"Base scouting dir: {base}\nexists: {base.exists()}")

            if base.exists():
                try:
                    kids = sorted([p.name for p in base.iterdir() if p.is_dir()])
                    st.write("Subfolders under Scouting Workspace:")
                    st.write(kids)
                except Exception as e:
                    st.warning(f"Could not list base folder: {e}")

            # Check expected nation folders
            for nation in ["Belgium", "Dutch", "France"]:
                p = wys_root / nation
                st.code(f"{nation} path: {p}\nexists: {p.exists()}")
                if p.exists():
                    csvs = sorted(glob.glob(str(p / "*.csv")))
                    st.write(f"{nation} csv count: {len(csvs)}")
                    if csvs:
                        st.write("First few files:")
                        st.write([Path(x).name for x in csvs[:5]])
            st.markdown("#### CSV read errors")
            errs = st.session_state.get("wyscout_read_errors", [])
            if errs:
                # show the latest 20 to keep it readable
                st.code("\n".join(errs[-20:]))
                if st.button("Clear CSV read errors", key="clear_wyscout_read_errors"):
                    st.session_state["wyscout_read_errors"] = []
            else:
                st.caption("No CSV read errors logged.")

    # ===== DETAIL PAGE =====
    # Force the page to start at top when opening a profile
    components.html("<script>window.parent.scrollTo(0,0)</script>", height=0)

    
    if focus_idx is not None and focus_idx in df.index:
        r = df.loc[focus_idx]
        st.markdown("<script>window.scrollTo(0, 0);</script>", unsafe_allow_html=True)

        back_col, _sp = st.columns([1,9])
        with back_col:
            if st.button("← Back to list", use_container_width=True, key="rep_back"):
                st.session_state.profile_focus_id = None
                st.rerun()

        st.markdown("---")

        on_loan_context = str(r.get("On loan", "")).strip().lower() in {"yes", "true", "1"}
        loan_club_context = str(r.get("Loan Club", "")).strip()
        parent_club_context = str(r.get("Parent Club", "")).strip()
        team_context = str(r.get("Player Current Team", "")).strip()
        visible_team_context = (
            f"{loan_club_context} to {parent_club_context}"
            if on_loan_context and loan_club_context and parent_club_context
            else (loan_club_context or team_context)
        )
        _render_player_context_bar(r, visible_team_context)

        tab_general, tab_data, tab_notes = st.tabs(["General", "Data", "Scouting notes"])

        with tab_general:
            # --- Player details box, with edit control only at top right
            on_loan = str(r.get("On loan", "")).strip().lower() in {"yes", "true", "1"}
            loan_club = str(r.get("Loan Club", "")).strip()
            parent_club = str(r.get("Parent Club", "")).strip()
            team = str(r.get("Player Current Team", "")).strip()
            visible_team = f"{loan_club} → {parent_club}" if on_loan and loan_club and parent_club else (loan_club or team)

            st.markdown(
                """
                <style>
                .player-detail-grid {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 10px;
                    margin-top: 10px;
                }
                .player-detail-item {
                    border: 1px solid rgba(148, 163, 184, 0.18);
                    border-radius: 14px;
                    background: rgba(15, 23, 42, 0.42);
                    padding: 10px 12px;
                    min-height: 68px;
                }
                .player-detail-label {
                    color: #94a3b8;
                    font-size: 0.74rem;
                    font-weight: 750;
                    text-transform: uppercase;
                    letter-spacing: 0.07em;
                    margin-bottom: 5px;
                }
                .player-detail-value {
                    color: #f8fafc;
                    font-size: 0.96rem;
                    font-weight: 760;
                    overflow-wrap: anywhere;
                }
                .player-detail-muted {
                    color: #94a3b8;
                    font-size: 0.88rem;
                    margin-top: 2px;
                }
                @media (max-width: 1200px) {
                    .player-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                }
                @media (max-width: 700px) {
                    .player-detail-grid { grid-template-columns: 1fr; }
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            def _display_value(value) -> str:
                try:
                    if value is None or pd.isna(value):
                        return "Not added"
                except Exception:
                    if value is None:
                        return "Not added"
                s = str(value).strip()
                if not s or s.casefold() in {"nan", "none", "nat"}:
                    return "Not added"
                return s

            def _escape_html(value) -> str:
                s = _display_value(value)
                return (
                    s.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;")
                     .replace('"', "&quot;")
                     .replace("'", "&#39;")
                )

            def _detail_item(label: str, value) -> str:
                return (
                    "<div class='player-detail-item'>"
                    f"<div class='player-detail-label'>{_escape_html(label)}</div>"
                    f"<div class='player-detail-value'>{_escape_html(value)}</div>"
                    "</div>"
                )

            edit_key = f"edit_player_details_{focus_idx}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            try:
                detail_box = st.container(border=True)
            except TypeError:
                detail_box = st.container()

            with detail_box:
                head_left, head_right = st.columns([5, 1])
                with head_left:
                    st.subheader(_display_value(r.get("Name", "")))
                    st.caption(
                        f"{_display_value(visible_team)} | {_display_value(r.get('Position', ''))}"
                        f" | Age: {_display_value(r.get('Age', ''))}"
                    )
                with head_right:
                    toggle_label = "Close edit" if st.session_state[edit_key] else "Edit details"
                    if st.button(toggle_label, key=f"toggle_player_details_{focus_idx}", use_container_width=True):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()

                img_col, detail_col = st.columns([1, 3])
                with img_col:
                    imgsrc = resolve_photo_src(r, PHOTODIR)
                    if imgsrc:
                        st.image(imgsrc, width=220)
                    else:
                        st.caption("No photo")

                with detail_col:
                    detail_pairs = [
                        ("Current club", visible_team),
                        ("Division", r.get("Division", "")),
                        ("Playing nation", r.get("Playing Nation", "")),
                        ("Citizenship", r.get("Player Nationality", "")),
                        ("Height", r.get("Player Height", "")),
                        ("Dominant foot", r.get("Dominant Foot", "")),
                        ("TM value", r.get("TM Value", "")),
                        ("Highest TM value", r.get("Highest TM Value", "")),
                        ("Contract until", r.get("Contract Until", "")),
                        ("Agency", r.get("Agency", "")),
                        ("Current ability", r.get("Current Rating (1-4)", "")),
                        ("Potential ability", r.get("Potential Rating (1-4)", "")),
                        ("Shortlist status", r.get("Shortlist Status", "")),
                        ("Verdict", r.get("Verdict", "")),
                        ("Watched", r.get("Watched", "")),
                        ("Age group", r.get("Age Group", "")),
                    ]
                    detail_html = "<div class='player-detail-grid'>" + "".join(_detail_item(k, v) for k, v in detail_pairs) + "</div>"
                    st.markdown(detail_html, unsafe_allow_html=True)

                with st.expander("Transfermarkt details", expanded=False):
                    ws_hint = str(r.get("Wyscout Player ID", "") or "").strip()
                    tm_saved = str(r.get("Transfermarkt URL", r.get("Source", "")) or "").strip()
                    st.caption(f"Wyscout ID: {ws_hint or 'not linked'}" + (f" | Transfermarkt saved: {tm_saved}" if tm_saved else ""))

                    fetch_tm = st.button("Fetch Transfermarkt details", key=f"tm_fetch_{focus_idx}", use_container_width=True)
                    if fetch_tm:
                        ws_id_for_tm = str(df.at[focus_idx, "Wyscout Player ID"] if "Wyscout Player ID" in df.columns else "").strip()
                        tm_saved_url = str(
                            r.get("Transfermarkt URL", r.get("Source", ""))
                            if isinstance(r, pd.Series)
                            else ""
                        ).strip()

                        data, msg = {}, ""

                        if ws_id_for_tm and callable(scrape_transfermarkt_from_reep_register):
                            data, msg = scrape_transfermarkt_from_reep_register(ws_id_for_tm)
                        elif callable(scrape_transfermarkt) and tm_saved_url.startswith(("http://", "https://")):
                            data, msg = scrape_transfermarkt(tm_saved_url)
                        elif not ws_id_for_tm:
                            st.warning("Save or auto attach the Wyscout Player ID first. If no Reep register fetcher is available, add a saved Transfermarkt URL for this player.")
                        elif scrape_transfermarkt_from_reep_register is None:
                            st.warning("The Reep register Transfermarkt fetcher was not passed into the player reports page. Add a saved Transfermarkt URL to use the standard Transfermarkt scraper.")
                        else:
                            st.warning("No Transfermarkt fetcher is available for this player.")

                        TM_KEYMAP = {
                            "Positions": "Position",
                            "Position(s)": "Position",
                            "Highest market value": "Highest TM Value",
                            "Highest Market Value": "Highest TM Value",
                            "Market value": "TM Value",
                            "Contract expires": "Contract Until",
                            "Contract until": "Contract Until",
                            "Nationality": "Player Nationality",
                            "Citizenship": "Player Nationality",
                        }

                        normalized = {}
                        for k, v in (data or {}).items():
                            kk = TM_KEYMAP.get(k, k)
                            normalized[kk] = v

                        data = normalized

                        if msg:
                            st.info(msg)

                        if data:
                            for k in data.keys():
                                if k not in df.columns:
                                    df[k] = ""

                            for k, v in data.items():
                                if k == "Name":
                                    if not str(df.at[focus_idx, k]).strip():
                                        df.at[focus_idx, k] = _tidy_person_name(v)
                                elif k in {"Transfermarkt Details JSON", "Transfermarkt URL", "Transfermarkt ID", "Source", "Photo URL"}:
                                    df.at[focus_idx, k] = str(v or "").strip()
                                elif k == "TM Value":
                                    existing = str(df.at[focus_idx, "TM Value"]).strip() if "TM Value" in df.columns else ""
                                    if not existing:
                                        df.at[focus_idx, "TM Value"] = v
                                elif k == "Contract Until":
                                    if not str(df.at[focus_idx, "Contract Until"]).strip():
                                        df.at[focus_idx, "Contract Until"] = v
                                elif k in df.columns and not str(df.at[focus_idx, k]).strip():
                                    df.at[focus_idx, k] = v

                            if "Photo Path" in df.columns and str(df.at[focus_idx, "Photo Path"]).strip() == "":
                                pu = str(df.at[focus_idx, "Photo URL"] if "Photo URL" in df.columns else "").strip()
                                if pu and callable(download_image_to_disk):
                                    try:
                                        saved = download_image_to_disk(pu, df.at[focus_idx, "Name"])
                                        if saved:
                                            df.at[focus_idx, "Photo Path"] = saved
                                    except Exception:
                                        pass

                            df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            _log_save_identity("About to save", df)
                            safe_write_db(st.session_state.db_csv, df)
                            st.success("Transfermarkt details saved.")
                            st.cache_data.clear()
                            st.rerun()

                def _clean_pool(vals):
                    out = []
                    for v in vals:
                        s = str(v).strip()
                        if not s:
                            continue
                        if s.casefold() in {"nan", "none"}:
                            continue
                        out.append(s)
                    return sorted(set(out), key=str.casefold)

                existing_teams      = _clean_pool(df.get("Player Current Team", pd.Series(dtype=str)).astype(str).tolist())
                existing_agencies   = _clean_pool(df.get("Agency", pd.Series(dtype=str)).astype(str).tolist())
                existing_divisions  = _clean_pool(df.get("Division", pd.Series(dtype=str)).astype(str).tolist())
                existing_age_groups = _clean_pool(df.get("Age Group", pd.Series(dtype=str)).astype(str).tolist())
                existing_cits       = _clean_pool(df.get("Player Nationality", pd.Series(dtype=str)).astype(str).tolist())
                existing_play_nats  = _clean_pool(df.get("Playing Nation", pd.Series(dtype=str)).astype(str).tolist())

                def add_new_dropdown_static(label: str,
                                    options: list[str],
                                    current_value: str,
                                    key_prefix: str) -> str:
                    opts = ["select"] + options + ["Add new"]
                    cur = str(current_value or "").strip()
                    if cur and cur not in opts:
                        opts.insert(1, cur)
                    try:
                        idx = opts.index(cur) if cur in opts else 0
                    except Exception:
                        idx = 0

                    choice = st.selectbox(label, opts, index=idx, key=f"{key_prefix}__sel")
                    new_txt = st.text_input(
                        f"Add new {label.lower()}",
                        value="",
                        key=f"{key_prefix}__new",
                    )

                    if choice == "Add new" and new_txt.strip():
                        return new_txt.strip()
                    if choice not in {"select", "Add new"}:
                        return choice
                    return cur

                if st.session_state[edit_key]:
                    st.markdown("#### Edit player details")
                    with st.form(key=f"gen_{focus_idx}", clear_on_submit=False):
                        g1, g2, g3 = st.columns(3)
                        name_val = g1.text_input("Name", value=r.get("Name", ""))

                        cur_roles = normalize_roles_to_options(r.get("Position", ""))
                        pos_sel = g2.multiselect(
                            "Positions, first is primary",
                            ROLE_ORDER,
                            default=cur_roles,
                            key=f"pos_sel_{focus_idx}"
                        )
                        pos_val = ", ".join(pos_sel)

                        foot_val = g3.selectbox(
                            "Dominant Foot",
                            ["", "Right", "Left", "Both"],
                            index=(["", "Right", "Left", "Both"].index(r.get("Dominant Foot", ""))
                                if r.get("Dominant Foot", "") in ["", "Right", "Left", "Both"] else 0),
                            key=f"foot_{focus_idx}"
                        )

                        p1, p2, p3 = st.columns(3)
                        with p1:
                            team_val = add_new_dropdown_static(
                                "Player Current Team",
                                existing_teams,
                                str(r.get("Player Current Team", "")),
                                f"detail_team_{focus_idx}"
                            )
                        with p2:
                            division_val = add_new_dropdown_static(
                                "Division",
                                existing_divisions,
                                str(r.get("Division", "")),
                                f"detail_div_{focus_idx}"
                            )
                        with p3:
                            age_group_val = add_new_dropdown_static(
                                "Age Group",
                                existing_age_groups,
                                str(r.get("Age Group", "")),
                                f"detail_agegrp_{focus_idx}"
                            )

                        q1, q2, q3 = st.columns(3)
                        with q1:
                            agency_val = add_new_dropdown_static(
                                "Agency",
                                existing_agencies,
                                str(r.get("Agency", "")),
                                f"detail_ag_{focus_idx}"
                            )
                        with q2:
                            nat_val = add_new_dropdown_static(
                                "Player Nationality",
                                existing_cits,
                                str(r.get("Player Nationality", "")),
                                f"detail_cit_{focus_idx}"
                            )
                        with q3:
                            play_nat_val = add_new_dropdown_static(
                                "Playing Nation",
                                existing_play_nats,
                                str(r.get("Playing Nation", "")),
                                f"detail_plnat_{focus_idx}"
                            )

                        h1, h2, h3 = st.columns(3)

                        height_txt = (r.get("Player Height", "") or "").lower().replace("m", "").strip()
                        try:
                            height_default = float(height_txt) if height_txt else 0.0
                        except Exception:
                            height_default = 0.0

                        height_val_num = h1.number_input(
                            "Player Height in metres",
                            min_value=0.0,
                            max_value=2.5,
                            step=0.01,
                            value=height_default,
                            key=f"height_{focus_idx}"
                        )

                        dob_raw = r.get("DOB", "")
                        dob_default = None
                        try:
                            if dob_raw:
                                y, m, d = map(int, dob_raw.split("-"))
                                dob_default = date(y, m, d)
                        except Exception:
                            ...

                        dob_in = h2.date_input(
                            "DOB",
                            value=dob_default,
                            format="YYYY-MM-DD",
                            min_value=date(1900, 1, 1),
                            max_value=date(2100, 12, 31),
                            key=f"dob_{focus_idx}"
                        )

                        age_val = h3.text_input("Age", value=r.get("Age", ""), key=f"age_{focus_idx}")

                        with st.expander("Contract and value", expanded=False):
                            c1, c2 = st.columns(2)

                            year_presets = [2026, 2027, 2028, 2029, 2030, 2031]
                            preset_labels = [f"06/{str(y)[-2:]}" for y in year_presets]
                            preset_dates = [f"{y}-06-30" for y in year_presets]

                            cur_contract = str(r.get("Contract Until", "")).strip()
                            preset_index = 0
                            if cur_contract in preset_dates:
                                preset_index = preset_dates.index(cur_contract) + 1

                            preset_choice = c1.selectbox(
                                "Contract Until preset",
                                ["none"] + preset_labels,
                                index=preset_index,
                                key=f"detail_contract_preset_{focus_idx}"
                            )
                            preset_date = preset_dates[preset_labels.index(preset_choice)] if preset_choice != "none" else ""

                            contract_default = None
                            try:
                                if cur_contract:
                                    y, m, d = map(int, cur_contract.split("-"))
                                    contract_default = date(y, m, d)
                            except Exception:
                                ...

                            custom_contract = c2.date_input(
                                "or pick a date",
                                value=contract_default,
                                format="YYYY-MM-DD",
                                min_value=date(1900, 1, 1),
                                max_value=date(2100, 12, 31),
                                key=f"detail_contract_date_{focus_idx}"
                            )

                            contract_val = preset_date or (custom_contract.strftime("%Y-%m-%d") if custom_contract else "")

                            t1, t2, t3 = st.columns(3)
                            tm_val = t1.text_input("TM Value", value=r.get("TM Value", ""), key=f"tm_{focus_idx}")
                            tm_hi_val = t2.text_input("Highest TM Value", value=r.get("Highest TM Value", ""), key=f"tmhi_{focus_idx}")
                            source_val = str(r.get("Transfermarkt URL", r.get("Source", "")) or "").strip()
                            t3.text_input("Transfermarkt URL", value=source_val, key=f"source_{focus_idx}", disabled=True, help="Filled by the Reep register Transfermarkt fetch.")

                        with st.expander("Status and ratings", expanded=False):
                            wcol1, wcol2, wcol3 = st.columns(3)

                            verdict_options = [
                                "",
                                "1 - Avg/Lower PLAYER in Bottom Tier League",
                                "1.5 - Good Pl in Bottom Tier League / Avg Pl in Low Tier Leagues",
                                "2 - Good Pl in Low Tier League / Avg Pl in Mid Tier Leagues",
                                "2.5 - Good Pl in Mid Tier League / Avg Pl in High Tier Leagues",
                                "3 - Good Pl in High Tier League / Avg Pl in Top Tier Leagues",
                                "3.5 - Good Pl in Top Tiera",
                                "4 - World-Class Talent"
                            ]
                            cur_verdict = r.get("Verdict", "")
                            verdict_idx = verdict_options.index(cur_verdict) if cur_verdict in verdict_options else 0
                            verdict_val = wcol1.selectbox("Verdict", verdict_options, index=verdict_idx, key=f"verdict_{focus_idx}")

                            watched_presets = [
                                "",
                                "needs deep dive",
                                "Namechecked",
                                "Monitor",
                                "full report done",
                                "Longlisted",
                                "Unlikely",
                                "Data",
                                "Assigned for review",
                                "Needs more development to be considered",
                                "Custom"
                            ]
                            cur_watched = r.get("Watched", "")
                            watched_idx = watched_presets.index(cur_watched) if cur_watched in watched_presets else (
                                watched_presets.index("Custom") if cur_watched else 0
                            )
                            watched_sel = wcol2.selectbox("Watched", watched_presets, index=watched_idx, key=f"watched_{focus_idx}")
                            watched_custom2 = st.text_input(
                                "Custom watched note",
                                value=(cur_watched if cur_watched not in watched_presets else ""),
                                key=f"watched_custom_{focus_idx}"
                            ) if watched_sel == "Custom" else ""
                            watched_val = watched_custom2 if watched_sel == "Custom" else watched_sel

                            shortlist_status_options = ["", "Green", "Purple", "Red", "Blue", "Grey"]
                            cur_color = str(r.get("Shortlist Status", "")).strip()
                            color_idx = shortlist_status_options.index(cur_color) if cur_color in shortlist_status_options else 0
                            shortlist_status_val = wcol3.selectbox("Shortlist Status", shortlist_status_options, index=color_idx, key=f"shortlist_status_{focus_idx}")

                            r1, r2 = st.columns(2)
                            cr_default = 0.0
                            try:
                                cr_default = float(r.get("Current Rating (1-4)", "") or 0.0)
                            except Exception:
                                ...
                            pr_default = 0.0
                            try:
                                pr_default = float(r.get("Potential Rating (1-4)", "") or 0.0)
                            except Exception:
                                ...

                            cr_slider = r1.slider("Current Ability", min_value=0.0, max_value=4.0, step=0.5, value=cr_default, key=f"cr_slider_{focus_idx}")
                            pr_slider = r2.slider("Potential Ability", min_value=0.0, max_value=4.0, step=0.5, value=pr_default, key=f"pr_slider_{focus_idx}")

                        saved_general = st.form_submit_button("Save details")

                        if saved_general:
                            tm_compact = fmt_eur_compact(parse_eur_value(tm_val)) if tm_val else ""
                            tm_hi_compact = fmt_eur_compact(parse_eur_value(tm_hi_val)) if tm_hi_val else tm_hi_val

                            df.at[focus_idx, "Name"] = _tidy_person_name(name_val.strip())
                            df.at[focus_idx, "Player Current Team"] = team_val.strip()
                            df.at[focus_idx, "Position"] = pos_val.strip()
                            df.at[focus_idx, "Division"] = division_val.strip()
                            df.at[focus_idx, "Age Group"] = age_group_val.strip()
                            df.at[focus_idx, "Agency"] = agency_val.strip()
                            df.at[focus_idx, "Contract Until"] = contract_val.strip()
                            df.at[focus_idx, "Dominant Foot"] = foot_val.strip()
                            df.at[focus_idx, "Player Height"] = (f"{height_val_num:.2f} m" if height_val_num > 0 else "")
                            df.at[focus_idx, "Player Nationality"] = nat_val.strip()
                            df.at[focus_idx, "Playing Nation"] = play_nat_val.strip()
                            df.at[focus_idx, "TM Value"] = tm_compact
                            df.at[focus_idx, "Highest TM Value"] = tm_hi_compact
                            df.at[focus_idx, "Source"] = source_val.strip()
                            df.at[focus_idx, "Shortlist Status"] = shortlist_status_val.strip()
                            df.at[focus_idx, "Verdict"] = verdict_val.strip()
                            df.at[focus_idx, "Watched"] = watched_val.strip()
                            df.at[focus_idx, "Current Rating (1-4)"] = str(cr_slider) if cr_slider > 0 else ""
                            df.at[focus_idx, "Potential Rating (1-4)"] = str(pr_slider) if pr_slider > 0 else ""

                            if dob_in:
                                df.at[focus_idx, "DOB"] = dob_in.strftime("%Y-%m-%d")
                                try:
                                    today = date.today()
                                    age_calc = today.year - dob_in.year - ((today.month, today.day) < (dob_in.month, dob_in.day))
                                    df.at[focus_idx, "Age"] = str(age_calc)
                                except Exception:
                                    df.at[focus_idx, "Age"] = str(age_val).strip()
                            else:
                                df.at[focus_idx, "Age"] = str(age_val).strip()

                            df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            _log_save_identity("About to save", df)
                            safe_write_db(st.session_state.db_csv, df)
                            st.session_state[edit_key] = False
                            st.success("Player details saved.")
                            st.cache_data.clear()
                            st.rerun()

            st.markdown("---")


        with tab_data:
            # =========================
            # 📈 Wyscout link + Data panel (put this inside the DETAIL PAGE for the selected player)
            # Place after your "General details" form, before notes/KPIs
            # =========================

            st.markdown("---")
            with st.expander("Wyscout linkage", expanded=False):
                st.subheader("🔗 Wyscout linkage")

                # Reload current row (in case details were just saved)
                r = df.loc[focus_idx]
                st.markdown("<script>window.scrollTo(0, 0);</script>", unsafe_allow_html=True)
                master = load_wyscout_master()
                m = load_wyscout_master()
                if _pr_debug_mode_enabled():
                    with st.expander("Wyscout loader debug", expanded=False):
                        # DEBUG BLOCK
                        st.caption(f"Wyscout rows loaded: {len(m)} | nations={sorted(m['__nation'].dropna().unique().tolist()) if not m.empty else '—'}")
                        st.write(f"🔍 DEBUG: SCOUTING_APP_ROOT env = {os.environ.get('SCOUTING_APP_ROOT', '')}")
                        st.write(f"🔍 DEBUG: __file__ = {__file__}")
                        st.caption("Folders discovered:")
                        for p in wyscoutfolders():
                            st.write("•", p)
                            try:
                                st.caption("   Files: " + ", ".join(sorted([f for f in os.listdir(p) if f.lower().endswith('.csv')])[:8]) + (" …" if len(os.listdir(p)) > 8 else ""))
                            except Exception:
                                pass
                        m = load_wyscout_master()
                        st.caption(f"Wyscout rows loaded: {len(m)}")
                        if not m.empty:
                            st.caption("Nations: " + ", ".join(sorted(m['__nation'].dropna().unique().tolist())))
                            st.dataframe(m.head(10), use_container_width=True, hide_index=True)

                ws_id_cur = str(r.get("Wyscout Player ID","")).strip()
                ws_id_in = st.text_input("Wyscout Player ID", value=ws_id_cur, key=f"wsid_{focus_idx}",
                                        help="If you know it already, paste the Wyscout ID used in your exports (or leave blank and use auto/manual below).")

                cols_lk = st.columns([1,1,2])
                with cols_lk[0]:
                    if st.button("💾 Save ID", key=f"save_wsid_{focus_idx}"):
                        df.at[focus_idx, "Wyscout Player ID"] = ws_id_in.strip()
                        df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        _log_save_identity("About to save", df)  # must be the full DB
                        safe_write_db(st.session_state.db_csv, df)
                        st.success("Wyscout Player ID saved.")
                        st.cache_data.clear()

                with cols_lk[1]:
                    if master.empty:
                        st.caption("No Wyscout data loaded.")
                    else:
                        if st.button("🤖 Auto-attach", key=f"auto_wsid_{focus_idx}"):
                            wsid, cands = try_auto_attach_wyscout_id(master, r, score_threshold=0.70)
                            st.session_state[f"ws_cands_{focus_idx}"] = cands
                            if wsid:
                                df.at[focus_idx, "Wyscout Player ID"] = wsid
                                df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                _log_save_identity("About to save", df)  # must be the full DB
                                safe_write_db(st.session_state.db_csv, df)
                                st.success(f"Linked automatically: {wsid}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.info("No high-confidence match (≥ 0.70). Pick manually below.")

                with cols_lk[2]:
                    st.caption("If auto-match fails, use the manual picker below.")

                # Manual picker scoped by nation/tier and fuzzy-sorted
                if not master.empty:
                    nat_hint = str(r.get("Playing Nation", "")).strip()

                    # Try to infer tier from your DB "Division" field (keep it optional)
                    tier_hint = None
                    div_raw = str(r.get("Division", "")).strip()
                    digits = "".join(ch for ch in div_raw if ch.isdigit())
                    if digits:
                        try:
                            tier_hint = int(digits[-1])
                        except Exception:
                            tier_hint = None

                    team_hint = r.get("Player Current Team","")
                    cand_df = st.session_state.get(f"ws_cands_{focus_idx}")
                    if cand_df is None or cand_df.empty:
                        # build now
                        cand_df = find_wyscout_candidates(master, r.get("Name",""), team_hint, nat_hint, tier_hint, top_k=100)
                        st.session_state[f"ws_cands_{focus_idx}"] = cand_df

                    if cand_df is None or cand_df.empty:
                        st.caption("No candidates found in Wyscout tables for the current nation/tier filter.")
                    else:
                        # compact label: "Score · Player — Team (Position, mins) [nation/file]"
                        cand_df = cand_df.copy()
                        cand_df["__label"] = cand_df.apply(
                            lambda rr: f"{rr['__score']:.2f} · {rr['Player']} — {rr['Team']} ({rr['Position']}, {rr['Minutes played']}) [{rr['__nation']}/{rr['__source_file']}]",
                            axis=1
                        )
                        # Preselect existing id if present
                        pre_idx = 0
                        if ws_id_cur:
                            hit = cand_df.index[cand_df["Wyscout Player ID"].apply(_norm_wsid) == _norm_wsid(ws_id_cur)]
                            pre_idx = int(hit[0]) if len(hit) else 0
                        pick = st.selectbox("Manual pick (sorted by similarity)", cand_df["__label"].tolist(), index=pre_idx, key=f"ws_pick_{focus_idx}")
                        if st.button("Link selected", key=f"ws_link_sel_{focus_idx}"):
                            row_sel = cand_df.iloc[cand_df["__label"].tolist().index(pick)]
                            wsid = str(row_sel["Wyscout Player ID"])
                            df.at[focus_idx, "Wyscout Player ID"] = wsid
                            df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            _log_save_identity("About to save", df)  # must be the full DB
                            safe_write_db(st.session_state.db_csv, df)
                            st.success(f"Linked manually: {wsid}")
                            st.cache_data.clear()
                            st.rerun()


            st.markdown("---")
            st.subheader("📈 Data — cohort comparison")
        
            # Always define these BEFORE any reference later in the function
            player_row = pd.Series(dtype=object)          # will later hold the player row from ztab
            ws_row = pd.Series(dtype=object)              # will hold the player row from master (Wyscout)
            target_row = pd.Series(dtype=object)          # from prepare_cohort_analysis
            target_row_filtered = pd.Series(dtype=object) # rebound row in filtered ztab
            cohort_df = pd.DataFrame()

            # Prevent old packs/ztab leaking across role/group switches (this is why CF can show CB tables)
            for k in (f"cohort_ztab_{focus_idx}", f"cohort_packs_{focus_idx}", f"cohort_weights_{focus_idx}"):
                st.session_state.pop(k, None)

            # 2) Cohort controls
            master = load_wyscout_master()
        
            if master.empty:
                st.info("No Wyscout data loaded yet. Add your Belgium/Dutch/France CSVs to the folders used by your Data analysis section.")
            else:
                # ---- Division picker (Belgium1 / Dutch2 / France3) + minutes + age ----
                # Build one label per file/tier in the master table, like your Analysis tab
                def _division_label(nation: str, tier: int | str, src: str) -> str:
                    t = str(tier).strip()
                    if not t or t == "0":
                        try:
                            base = os.path.basename(str(src))
                            digits = "".join(ch for ch in base if ch.isdigit())
                            t = digits[-1] if digits else "1"
                        except Exception:
                            t = "1"
                    nm = str(nation).strip()
                    return f"{nm}{t}"


                div_rows = []
                for _, rr in master.iterrows():
                    nation = str(rr.get("__nation","")).strip()
                    tier   = rr.get("__tier", "")
                    src    = rr.get("__source_file","")
                    if nation:
                        div_rows.append({
                            "__nation": nation,
                            "__tier": tier,
                            "__src": src,
                            "__division": _division_label(nation, tier, src)
                        })

                div_df = pd.DataFrame(div_rows).drop_duplicates()
                if div_df.empty:
                    st.info("No divisions discovered in Wyscout master.")
                    st.stop()

                # Attach the computed division label onto master so we can filter by it
                if "__division" not in master.columns:
                    master["__division"] = master.apply(
                        lambda rr: _division_label(
                            str(rr.get("__nation","")), rr.get("__tier",""), str(rr.get("__source_file",""))
                        ),
                        axis=1
                    )


                div_options = sorted(div_df["__division"].unique().tolist())

                # Default divisions to the player's own division label (fallback: all)
                nat_hint, tier_hint = _parse_division(r.get("Playing Nation",""), r.get("Division",""))
                player_div = _division_label(nat_hint, tier_hint, "") if nat_hint else ""

                import re

                player_nat_raw = str(r.get("Playing Nation", "")).strip()
                canon_nat = str(nat_hint or player_nat_raw).strip()

                ALIASES = {
                    "netherlands": ["dutch", "nl"],
                    "england": ["eng"],
                    "united states": ["usa", "us", "america"],
                }

                def _norm_key(s: str) -> str:
                    return str(s or "").strip().casefold().replace(" ", "")

                def _match_div_option(nation: str, tier_num: int) -> str:
                    if not nation or not tier_num:
                        return ""
                    nkey = _norm_key(nation)
                    targets = [nkey] + [_norm_key(a) for a in ALIASES.get(nkey, [])]

                    for d in div_options:
                        ds = str(d).strip()
                        m = re.search(r"(\d+)\s*$", ds)
                        if not m:
                            continue
                        pref = _norm_key(ds[: m.start()])
                        t = int(m.group(1))
                        if (t == int(tier_num)) and (pref in targets):
                            return d
                    return ""

                # This is the correct match to the player actual tier, used for debug and any hinting
                player_div_opt = _match_div_option(canon_nat, int(tier_hint) if tier_hint else 0)

                # Default behaviour you asked for: only Tier 1 of the player nation
                tier1_opt = _match_div_option(canon_nat, 1)
                default_divs = [tier1_opt] if tier1_opt else []

                # Fallback if tier1 file does not exist for that nation
                if not default_divs:
                    default_divs = div_options


                # Fallback: if we can't infer, default to all (so we never end up with an empty table by accident)
                if not default_divs:
                    default_divs = div_options

                import re

                TOP5_NATIONS = ["England", "Spain", "Germany", "Italy", "France"]
                NEXT7_NATIONS = ["Netherlands", "Portugal", "Belgium", "Turkey", "Scotland", "Austria", "Switzerland"]  # edit if you want

                def _div_prefix_tier(div_label: str):
                    s = str(div_label).strip()
                    m = re.match(r"^(.+?)(\d+)$", s)
                    if not m:
                        return s.casefold(), None
                    pref = m.group(1).strip().casefold()
                    tier = int(m.group(2))
                    return pref, tier

                def _tier1_from_nations(div_options, nations):
                    want = set(n.casefold() for n in nations)
                    out = []
                    for d in div_options:
                        pref, tier = _div_prefix_tier(d)
                        if pref in want and tier == 1:
                            out.append(d)
                    return out

                cb1, cb2 = st.columns(2)
                preset_top5 = cb1.checkbox("Top 5 leagues (Tier 1)", value=False, key=f"preset_top5_{focus_idx}")
                preset_next7 = cb2.checkbox("Next 7 leagues (Tier 1)", value=False, key=f"preset_next7_{focus_idx}")

                ms_key = f"co_divs_{focus_idx}"
                applied_key = f"co_preset_applied_{focus_idx}"
                preset_state = (preset_top5, preset_next7)

                if st.session_state.get(applied_key) != preset_state:
                    suggested = []
                    if preset_top5:
                        suggested += _tier1_from_nations(div_options, TOP5_NATIONS)
                    if preset_next7:
                        suggested += _tier1_from_nations(div_options, NEXT7_NATIONS)

                    if not suggested:
                        suggested = default_divs

                    st.session_state[ms_key] = list(dict.fromkeys(suggested))  # de duplicate, keep order
                    st.session_state[applied_key] = preset_state

                sel_divisions = st.multiselect(
                    "Peer Leagues / Tiers for Comparison",
                    options=div_options,
                    default=st.session_state.get(ms_key, default_divs),
                    key=ms_key
                )




                min_minutes = st.slider(
                    "Minutes threshold", min_value=0, max_value=1800, value=230, step=30, key=f"co_min_{focus_idx}"
                )

                # Age range (cohort filter)
                age_series_master = pd.to_numeric(master.get("Age", pd.Series(dtype=str)), errors="coerce")
                amin = int(age_series_master.dropna().min()) if age_series_master.notna().any() else 15
                amax = int(age_series_master.dropna().max()) if age_series_master.notna().any() else 40

                # guard: avoid min == max for range slider
                if amin == amax:
                    amin = max(amin - 1, 15)
                    amax = amax + 1

                age_min, age_max = st.slider(
                    "Age range for cohort",
                    min_value=amin,
                    max_value=amax,
                    value=(amin, amax),
                    key=f"co_age_{focus_idx}",
                )


                # Filter the master table by chosen divisions + minutes + age **before** you build the cohort (ztab)
                if "__division" in master.columns:
                    mask_div = master["__division"].isin(sel_divisions) if sel_divisions else pd.Series([True]*len(master), index=master.index)
                else:
                    mask_div = pd.Series([True]*len(master), index=master.index)



                mask_mins = pd.to_numeric(master.get("Minutes played", 0), errors="coerce").fillna(0) >= min_minutes
                mask_age  = (pd.to_numeric(master.get("Age", 0), errors="coerce").fillna(0) >= age_min) & \
                            (pd.to_numeric(master.get("Age", 0), errors="coerce").fillna(0) <= age_max)

                master_filtered = master[mask_div & mask_mins & mask_age].copy()
                st.caption(f"master rows: {len(master)} | filtered rows: {len(master_filtered)} | sel_divisions={len(sel_divisions)} | nat_hint={nat_hint or '—'} | tier_hint={tier_hint}")

                # make sure __division exists on the cohort table later (useful for leader annotations)
            

                ct_left, ct_right = st.columns([1,2])
                cohort_choice = ct_left.radio("Cohort", ["Role profile peers", "General group peers"],index=1,
                horizontal=False, key=f"co_type_{focus_idx}")

                # Role profile default from this player's first stored role (if any)
                player_roles = normalize_roles_to_options(r.get("Position",""))
                default_role = player_roles[0] if player_roles else ""
                # General group default guessed from role label
                grp_opts = ["GK","FB","CB","DM","CM","AM","WM","WF","CF"]
                # crude guess
                # Use Wyscout position to guess the group, not the DB role label
                ws_pos_for_default = ""
                if isinstance(player_row, pd.Series) and not player_row.empty:
                    ws_pos_for_default = str(player_row.get("Position", ""))
                elif isinstance(ws_row, pd.Series) and not ws_row.empty:
                    ws_pos_for_default = str(ws_row.get("Position", ""))

                pos0 = _split_positions(ws_pos_for_default)[0] if ws_pos_for_default else ""
                prof0 = _infer_profile_key_from_pos(pos0) if pos0 else ""

                prof_to_grp = {
                    "GK": "GK",
                    "CB": "CB",
                    "FB": "FB",
                    "DM": "DM",
                    "CM": "CM",
                    "AM": "AM",
                    "W": "W",
                    "WF": "W",
                    "CF": "CF",
                    "TM": "CF",
                }
                # Prefer DB first role (your Position field like "11a - LWF"), fall back to Wyscout position inference
                db_roles = normalize_roles_to_options(r.get("Position", ""))
                db_primary = db_roles[0] if db_roles else ""

                def _db_role_to_group(role_code: str) -> str:
                    t = str(role_code or "").casefold()
                    if t.startswith("1") or "gk" in t: return "GK"
                    if t.startswith("2") or t.startswith("3") or any(x in t for x in ["rb","lb","rwb","lwb"]): return "FB"
                    if t.startswith("4") or t.startswith("5") or "cb" in t: return "CB"
                    if t.startswith("6") or "dm" in t: return "DM"
                    if t.startswith("8") or "cm" in t: return "CM"
                    if t.startswith("10") or any(x in t for x in ["am","cam"]): return "AM"
                    if any(x in t for x in ["rwf","lwf","wf","7a","11a"]): return "WF"
                    if t.startswith("7") or t.startswith("11") or any(x in t for x in ["rw","lw","rm","lm","wm","w"]): return "WM"
                    if t.startswith("9") or any(x in t for x in ["cf","st","tm"]): return "CF"
                    return "WM"

                guess_grp = _db_role_to_group(db_primary) if db_primary else prof_to_grp.get(prof0, "WM")




                if cohort_choice == "Role profile peers":
                    role_profile = ct_right.selectbox("Role profile", ROLE_ORDER, index=(ROLE_ORDER.index(default_role) if default_role in ROLE_ORDER else 0), key=f"co_reference_{focus_idx}")
                    general_group = None
                    cohort_type_key = "ROLE_PROFILE"
                else:
                    general_group = ct_right.selectbox("Group", grp_opts, index=(grp_opts.index(guess_grp) if guess_grp in grp_opts else grp_opts.index("WM")), key=f"co_grp_{focus_idx}")
                    role_profile = None
                    cohort_type_key = "GROUP"

                     
                # --- Force-include target player into the filtered cohort (so we can compare vs any role) ---

                target_ws_id = str(r.get("Wyscout Player ID","")).strip() or None
                target_name  = str(r.get("Name","")).strip() or None

                # Force include the target player row even if he is outside selected divisions
                if target_ws_id and "Wyscout Player ID" in master.columns:
                    in_filtered = False
                    if "Wyscout Player ID" in master_filtered.columns:
                        in_filtered = (master_filtered["Wyscout Player ID"].astype(str) == str(target_ws_id)).any()

                    if not in_filtered:
                        tr = master[master["Wyscout Player ID"].astype(str) == str(target_ws_id)].copy()
                        if not tr.empty:
                            master_filtered = pd.concat([master_filtered, tr], ignore_index=True, sort=False)
                            master_filtered = master_filtered.drop_duplicates(subset=["Wyscout Player ID"], keep="last")


                import unicodedata, re

                def _norm(s: str) -> str:
                    s = unicodedata.normalize("NFKD", str(s or ""))
                    s = "".join(ch for ch in s if not unicodedata.combining(ch))
                    s = s.casefold().strip()
                    return re.sub(r"[\W_]+", "", s.casefold().strip())

                # 1) Find the player in the full master (not the filtered one)
                player_row_df = pd.DataFrame()
                if target_ws_id and "Wyscout Player ID" in master.columns:
                    mask = master["Wyscout Player ID"].apply(_norm_wsid) == _norm_wsid(target_ws_id)
                    player_row_df = master.loc[mask].copy()
                else:
                    # pick whichever name column exists
                    name_col = next((c for c in master.columns if c.lower() in {"player","name","player name"}), None)
                    if name_col and target_name:
                        nm = _norm(target_name)
                        mask = master[name_col].astype(str).map(_norm) == nm
                        player_row_df = master.loc[mask].copy()

                # 2) If found, append to master_filtered (align columns + avoid duplicates)
                if not player_row_df.empty:
                    # Make sure all columns exist; add missing cols so we can align
                    for col in master_filtered.columns:
                        if col not in player_row_df.columns:
                            player_row_df[col] = pd.NA
                    # Align order
                    player_row_df = player_row_df[master_filtered.columns]

                    # Ensure a unique key for dedup—prefer Wyscout ID, else (Player, Team)
                    if "Wyscout Player ID" in master_filtered.columns:
                        dedup_cols = ["Wyscout Player ID"]
                    else:
                        dedup_cols = [c for c in ["Player", "Team"] if c in master_filtered.columns]
                        if not dedup_cols:
                            dedup_cols = master_filtered.columns[:1].tolist()  # last resort

                    # If he’s already inside, don’t duplicate
                    if not pd.concat([master_filtered[dedup_cols], player_row_df[dedup_cols]]).duplicated().tail(1).iloc[0]:
                        master_filtered = pd.concat([master_filtered, player_row_df], ignore_index=True)

                    # 3) If you’re comparing against a different role/group than his native role,
                    #    make sure the *target row* won’t be dropped by cohort building:
                    #
                    #    Many build_cohort() implementations keep only rows whose role/group matches.
                    #    To guarantee inclusion, tag the target row with the chosen cohort group/role.
                    #    (Adjust these column names if your build_cohort expects something else.)
                    #
                    #    - For Role profile cohorts, we’ll set "_group" to the appropriate macro group.
                    #    - For general groups, we’ll set "_group" directly to the radio choice.

                    def _role_to_group(role_code: str) -> str:
                        # crude mapping; tweak to your project’s logic
                        if role_code.startswith("GK"): return "GK"
                        if role_code in {"2", "3", "2 - RB/RWB", "3 - LB/LWB"}: return "FB"
                        if role_code in {"4", "5L", "5R", "4 - CCB"}: return "CB"
                        if role_code in {"6"}: return "DM"
                        if role_code in {"8"}: return "CM"
                        code = str(role_code or "").strip().upper()
                        if code in {"AMF", "10 - CAM", "10A", "SS"}: return "AM"
                        if code in {"LWF", "RWF", "WF", "11A", "7A", "11A - LWF", "7A - RWF"}: return "WF"
                        if code in {"LW", "RW", "LM", "RM", "WM", "11", "7", "11 - LM", "7 - RM"}: return "WM"
                        if code in {"CF", "ST", "9", "9A", "9 - AF", "9A - TM"}: return "CF"
                        return "WM"  # fallback

            
                # Ensure ALL rows have _group so cohort filters work
                if "_group" not in master_filtered.columns:
                    master_filtered["_group"] = ""

                def _wyscout_pos_to_group(pos: str) -> str:
                    p = str(pos or "").casefold()

                    if "gk" in p:
                        return "GK"
                    if any(x in p for x in ["cb", "lcb", "rcb", "centre back", "center back"]):
                        return "CB"
                    if any(x in p for x in ["lb", "rb", "lwb", "rwb", "fullback", "wingback"]):
                        return "FB"
                    if any(x in p for x in ["dm", "dmc", "defensive midfield"]):
                        return "DM"
                    if any(x in p for x in ["cm", "mc", "central midfield"]):
                        return "CM"
                    if any(x in p for x in ["am", "amc", "attacking midfield", "cam"]):
                        return "AM"
                    if any(x in p for x in ["lwf", "rwf", "wide forward"]):
                        return "WF"
                    if any(x in p for x in ["lw", "rw", "lm", "rm", "wing", "wide"]):
                        return "WM"
                    if any(x in p for x in ["cf", "st", "forward", "striker"]):
                        return "CF"

                    return ""

                # Map group from whatever column your master actually has
                pos_col = "Position" if "Position" in master_filtered.columns else ("Role" if "Role" in master_filtered.columns else None)
                if pos_col:
                    if "_group" not in master_filtered.columns:
                        master_filtered["_group"] = ""
                    mapped = master_filtered[pos_col].astype(str).map(_wyscout_pos_to_group)
                    blank = master_filtered["_group"].astype(str).str.strip().eq("")
                    master_filtered.loc[blank, "_group"] = mapped.loc[blank]

                # After mapping, force the target player to belong to the chosen cohort group
                if target_ws_id and "Wyscout Player ID" in master_filtered.columns and "_group" in master_filtered.columns:
                    tmask = master_filtered["Wyscout Player ID"].astype(str) == str(target_ws_id)
                    if tmask.any():
                        if cohort_choice == "Role profile peers":
                            master_filtered.loc[tmask, "_group"] = _role_to_group(role_profile)
                        else:
                            master_filtered.loc[tmask, "_group"] = str(general_group)


                # --- Step 2: run analysis as usual ---
                ztab, packs, weights, target_row = prepare_cohort_analysis(
                    master=master_filtered,
                    target_player_name=target_name,
                    target_wyscout_id=target_ws_id,
                    cohort_type=cohort_type_key,
                    role_profile=role_profile,
                    general_group=general_group,
                    min_minutes=int(min_minutes),
                    age_min=int(age_min),
                    age_max=int(age_max)
                )

                st.caption(f"ztab rows: {0 if ztab is None else len(ztab)} | packs={0 if not packs else len(packs)}")
                # IMPORTANT: make responsibilities use the same cohort table we just built
                cohort_df = ztab
                st.session_state["cohort_df_current"] = ztab

                # Ensure ztab has __division by merging from master_filtered using a safe join key
                def _pick_join_key(ztab: pd.DataFrame, master_filtered: pd.DataFrame) -> str | None:
                    # Prefer stable IDs
                    for k in ["Wyscout Player ID", "Player ID", "wyId", "Id"]:
                        if k in ztab.columns and k in master_filtered.columns:
                            return k
                    # Then common name columns
                    for k in ["Player", "Name", "Player Name"]:
                        if k in ztab.columns and k in master_filtered.columns:
                            return k
                    return None

                if "__division" not in ztab.columns:
                    join_key = _pick_join_key(ztab, master_filtered)
                    if join_key is not None and "__division" in master_filtered.columns:
                        ztab = ztab.merge(
                            master_filtered[[join_key, "__division"]].drop_duplicates(subset=[join_key]),
                            on=join_key,
                            how="left"
                        )
                    else:
                        # Avoid crashing: create the column even if we can't merge
                        ztab["__division"] = ""

                        
           

                # Ensure we’re reading rank/percentile from the DIVISION-FILTERED table
                def _rebind_target_row_from_filtered(ztab: pd.DataFrame, old_row: pd.Series) -> pd.Series:
                    if ztab.empty or old_row is None or old_row.empty:
                        return pd.Series(dtype=object)
                    # Prefer unique Wyscout ID, fall back to exact Player name
                    if "Wyscout Player ID" in ztab.columns and pd.notna(old_row.get("Wyscout Player ID", pd.NA)):
                        key_col = "Wyscout Player ID"
                        key_val = str(old_row.get("Wyscout Player ID"))
                        match = ztab[ztab[key_col].astype(str) == key_val]
                    else:
                        key_col = "Player"
                        key_val = str(old_row.get("Player", ""))
                        match = ztab[ztab[key_col].astype(str) == key_val]
                    return match.iloc[0] if not match.empty else pd.Series(dtype=object)

                # Rebind to filtered table
                target_row_filtered = _rebind_target_row_from_filtered(ztab, target_row)
                target_row = target_row_filtered

                # make Player type + responsibilities use the same cohort + target row
                st.session_state["cohort_df_current"] = ztab
                st.session_state["ws_row_current"] = target_row_filtered if isinstance(target_row_filtered, pd.Series) else pd.Series(dtype=object)

           
                csum1, csum2, csum3 = st.columns([1,1,2])
        
                csum1.metric("Cohort size", len(ztab))

                if target_row_filtered.empty:
                    csum2.metric("Overall score", "—")
                    csum3.caption("This player was not matched in the selected Division cohort. You can still browse the cohort below.")
                else:
                    try:
                        sc = float(target_row_filtered.get("__overall_score", float("nan")))
                        rk = target_row_filtered.get("__overall_rank", pd.NA)
                        pc = target_row_filtered.get("__overall_pct", pd.NA)

                        # Render
                        csum2.metric("Overall score", f"{sc:.2f}" if pd.notna(sc) else "—")
                        if pd.notna(rk) and pd.notna(pc):
                            csum3.caption(f"Overall rank: **{int(rk)} / {len(ztab)}** • Percentile: **{float(pc):.1f}%**")
                        else:
                            csum3.caption("—")
                    except Exception:
                        csum2.metric("Overall score", "—")
                        csum3.caption("—")

                # Stash into session for Part 3 rich rendering (colour bars etc.)
                st.session_state[f"cohort_ztab_{focus_idx}"] = ztab
                st.session_state[f"cohort_packs_{focus_idx}"] = packs
                st.session_state[f"cohort_weights_{focus_idx}"] = weights
            
                # --- Ensure overall columns exist on the CURRENT ztab ---
                if ztab is not None and isinstance(ztab, pd.DataFrame) and not ztab.empty:
                    # 1) Compute overall score if missing
                    if "__overall_score" not in ztab.columns:
                        if packs and weights:
                            # compute per-row overall score using your existing helper
                            ztab["__overall_score"] = ztab.apply(
                                lambda row: overall_score_from_clusters(row, packs, weights),
                                axis=1
                            )
                        else:
                            # still create the column to avoid KeyError; fill with NaN
                            ztab["__overall_score"] = float("nan")

                    # 2) Compute rank and percentile if missing
                    if "__overall_rank" not in ztab.columns and "__overall_score" in ztab.columns:
                        ztab["__overall_rank"] = ztab["__overall_score"].rank(ascending=False, method="min")
                    if "__overall_pct" not in ztab.columns and "__overall_score" in ztab.columns:
                        # higher score => better rank; invert if you prefer
                        ztab["__overall_pct"] = ztab["__overall_score"].rank(pct=True, ascending=True) * 100.0

                    # Update session copies so the rich-rendering section sees them too
                    st.session_state[f"cohort_ztab_{focus_idx}"] = ztab

                preview_cols = [c for c in ["Player","Team","Position","Age","Minutes played","__overall_score","__overall_rank","__overall_pct"] if c in ztab.columns]

                df_prev = ztab.copy()
                if "__overall_score" in df_prev.columns:
                    df_prev = df_prev.sort_values("__overall_score", ascending=False)

                st.dataframe(
                    df_prev[preview_cols].head(25),
                    use_container_width=True,
                    hide_index=True
                )

            
            # =========================
            # 📈 Data (rich rendering) — place this immediately after Part 2
            # =========================

            st.markdown("---")

            # Pull what Part 2 stashed
            ztab = st.session_state.get(f"cohort_ztab_{focus_idx}")
            packs = st.session_state.get(f"cohort_packs_{focus_idx}")
            weights = st.session_state.get(f"cohort_weights_{focus_idx}")

            if ztab is None or not isinstance(ztab, pd.DataFrame) or not packs:
                st.info("Pick a cohort above to view detailed metrics.")
            else:
                # Identify target row again (prefer Wyscout ID, else name)
                r = df.loc[focus_idx]
                target_ws_id = str(r.get("Wyscout Player ID","")).strip() or None
                target_name  = str(r.get("Name","")).strip() or None

                if target_ws_id and "Wyscout Player ID" in ztab.columns:
                    mask = ztab.get("Wyscout Player ID", pd.Series([""]*len(ztab))).apply(_norm_wsid) == _norm_wsid(target_ws_id)
                elif target_name and "Player" in ztab.columns:
                    mask = ztab["Player"].astype(str).str.casefold() == target_name.casefold()
                else:
                    mask = pd.Series([False]*len(ztab), index=ztab.index)

                player_row = ztab[mask].iloc[0] if mask.any() else None

                # ------- tiny helpers for colour bars and safe numbers -------
                def _pct_bar(p):
                    """Return HTML bar (green good → red bad) for a percentile (0..100)."""
                    try:
                        val = float(p)
                    except Exception:
                        return "<span>NA</span>"
                    val = max(0.0, min(100.0, val))
                    # map 0..100 to red→green
                    # hue 0=red, 120=green
                    hue = int(120 * (val / 100.0))
                    return f"""
                    <div style="display:flex;align-items:center;gap:8px;">
                    <div style="flex:1;height:8px;background:linear-gradient(90deg,hsl({hue},70%,45%) {val}%, rgba(255,255,255,0.12) {val}%);border-radius:6px;"></div>
                    <div style="min-width:50px;text-align:right;font-size:12px;opacity:.9;">{val:.1f}%</div>
                    </div>
                    """

                def _fmt_raw(x):
                    if x is None or (isinstance(x, float) and pd.isna(x)):
                        return "NA"
                    # percentage columns end with '%' in your schema
                    return f"{x:.2f}" if isinstance(x, (int, float)) else str(x)

                def _metric_exists(m):
                    # ensure metric and its computed columns exist
                    return (m in ztab.columns) and (f"{m}__pct" in ztab.columns) and (f"{m}__rank" in ztab.columns) and (f"{m}__z" in ztab.columns)

                # ------- TOP 5 strengths for this player -------
                st.subheader("🏅 Top 5 strengths in this cohort")
                if target_row.empty:
                    st.caption("This player is not in the cohort (no Wyscout ID or exact name match). Showing cohort leaders for now.")

                    def _safe_idxmax(series: pd.Series):
                        s = pd.to_numeric(series, errors="coerce")
                        if s.notna().any():
                            return s.idxmax()
                        return None

                    cohort_tops = []
                    if packs and not ztab.empty:
                        for cluster, metrics in packs.items():
                            for m in metrics:
                                zcol = f"{m}__z"
                                if zcol in ztab.columns:
                                    def _safe_idxmax(series: pd.Series):
                                        s = pd.to_numeric(series, errors="coerce")
                                        if s.notna().any():
                                            return s.idxmax()
                                        return None
                                    zmax_idx = _safe_idxmax(ztab[zcol])
                                    if zmax_idx is None:
                                        continue
                                    row = ztab.loc[zmax_idx]

                                    who = row.get("Player", "")
                                    nat = row.get("__division", row.get("__nation", ""))
                                    zsc = float(row[zcol]) if pd.notna(row[zcol]) else float("nan")
                                    cohort_tops.append((cluster, m, zsc, who, nat))
                    cohort_tops.sort(key=lambda x: (-(x[2] if pd.notna(x[2]) else -1e9)))
                    for cluster, m, zsc, who, nat in cohort_tops[:5]:
                        if pd.notna(zsc):
                            st.markdown(f"**{m}** · {who} ({nat}) — z {zsc:+.2f}")


                else:
                    # Helpers
                    def _ordinal(n: int) -> str:
                        if pd.isna(n): return "—"
                        n = int(n)
                        return f"{n}{'th' if 11<=n%100<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

                    def _fmt_raw_compact(x):
                        if pd.isna(x): return "—"
                        xf = float(x)
                        if abs(xf) >= 100: return f"{xf:,.0f}"
                        if abs(xf) >= 10:  return f"{xf:,.1f}"
                        return f"{xf:,.2f}"

                    # Build candidate strengths by percentile (fallback to raw if pct missing)
                    cand = []
                    for cluster, metrics in packs.items():
                        for m in metrics:
                            pcol = f"{m}__pct"
                            if m in ztab.columns:
                                raw_val = target_row.get(m, np.nan)
                                # rank high→low by raw value if percentiles missing
                                if pcol in ztab.columns and pd.notna(target_row.get(pcol, np.nan)):
                                    pct_val = float(target_row[pcol])
                                    # rank by percentile
                                    rank = int((ztab[pcol] > pct_val).sum() + 1)
                                else:
                                    # rank by raw metric
                                    try:
                                        rank = int((pd.to_numeric(ztab[m], errors="coerce") > pd.to_numeric(raw_val)).sum() + 1)
                                    except Exception:
                                        rank = None
                                    pct_val = np.nan
                                # skip if no raw value
                                if pd.isna(raw_val): 
                                    continue
                                cand.append({
                                    "cluster": cluster,
                                    "metric": m,
                                    "raw": raw_val,
                                    "rank": rank,
                                    "pct": pct_val
                                })

                    # Sort strengths by percentile first (desc), fallback to z/rank signal if needed
                    cand.sort(key=lambda d: (-(d["pct"] if pd.notna(d["pct"]) else -1), d["rank"] if d["rank"] is not None else 9999))

                    # Render top 5
                    # ... after you sorted `cand` and before you render the top 5 lines:

                    for item in cand[:5]:
                        m = item["metric"]
                        raw_s = _fmt_raw_compact(item["raw"])
                        rk_s  = _ordinal(item["rank"]) if item["rank"] else "—"

                        # Find best ranking column available
                        zcol = f"{m}__z"; pcol = f"{m}__pct"
                        if zcol in ztab.columns:
                            leaders = (ztab[["Player","__division", zcol]]
                                    .dropna(subset=[zcol])
                                    .sort_values(zcol, ascending=False)
                                    .head(3))
                            lead_txt = " | ".join([f"{row.Player} ({row['__division']})" for _, row in leaders.iterrows()])
                        elif pcol in ztab.columns:
                            leaders = (ztab[["Player","__division", pcol]]
                                    .dropna(subset=[pcol])
                                    .sort_values(pcol, ascending=False)
                                    .head(3))
                            lead_txt = " | ".join([f"{row.Player} ({row['__division']})" for _, row in leaders.iterrows()])
                        else:
                            lead_txt = "—"

                        if pd.notna(item.get("pct", np.nan)):
                            st.markdown(f"**{m}** — {rk_s} in cohort • {raw_s} ({item['pct']:.1f}%)  \n*Leaders:* {lead_txt}")
                        else:
                            st.markdown(f"**{m}** — {rk_s} in cohort • {raw_s}  \n*Leaders:* {lead_txt}")



                st.markdown("---")
                st.markdown("""
                <style>
                .table-compact { border-collapse: collapse; width:100%; }
                .table-compact thead th { position: sticky; top: 0; background: #0f1116; z-index: 1; text-align:left; border-bottom: 1px solid rgba(255,255,255,.08); }
                .table-compact td, .table-compact th { padding: 6px 8px; font-size: 12px; white-space: nowrap; }
                .table-compact tr:nth-child(even){ background: rgba(255,255,255,0.03); }
                .metric-label { font-weight: 600; }
                .pctbar { height: 10px; border-radius: 6px; background: rgba(255,255,255,.08); overflow: hidden; }
                .pctbar > div { height: 100%; }
                .right { text-align: right; }
                .dim { opacity: .75; }
                </style>
                """, unsafe_allow_html=True)
                def _fmt_raw(x):
                    if pd.isna(x): return "—"
                    try:
                        xf = float(x)
                        # choose a compact formatting: 2 decimals for small, 1 for medium, none for large ints
                        if abs(xf) >= 100: return f"{xf:,.0f}"
                        if abs(xf) >= 10:  return f"{xf:,.1f}"
                        return f"{xf:,.2f}"
                    except Exception:
                        return str(x)

                def _fmt_pct(x):
                    if pd.isna(x): return "—"
                    try:
                        return f"{float(x):.1f}%"
                    except Exception:
                        return str(x)

                def _pct_bar(pct: float) -> str:
                    # clamp 0..100
                    try:
                        val = max(0.0, min(100.0, float(pct)))
                    except Exception:
                        val = 0.0
                    # map 0..100 to red→green using hue 0..120
                    hue = int(120 * (val / 100.0))
                    return f"""
                    <div style="display:flex;align-items:center;gap:8px;">
                    <div style="flex:1;height:8px;border-radius:6px;
                                background:linear-gradient(90deg,hsl({hue},70%,45%) {val}%, rgba(255,255,255,0.12) {val}%);">
                    </div>
                    <div style="min-width:50px;text-align:right;font-size:12px;opacity:.9;">{val:.1f}%</div>
                    </div>
                    """
                # -----------------------------
                # Data section (injection point)
                # -----------------------------
                st.subheader("What type of player is this with respect to position")

                # ----------------------------
                # 1) Index definitions
                # ----------------------------

                INDEX_DEFS = {
                    "Threat": [
                        ("xG per 90", 0.30, +1),
                        ("Shots per 90", 0.15, +1),
                        ("Touches in box per 90", 0.20, +1),
                        ("Non-penalty goals per 90", 0.20, +1),
                        ("Goal conversion, %", 0.15, +1),
                    ],
                    "Creation": [
                        ("xA per 90", 0.25, +1),
                        ("Key passes per 90", 0.20, +1),
                        ("Shot assists per 90", 0.15, +1),
                        ("Passes to penalty area per 90", 0.15, +1),
                        ("Through passes per 90", 0.15, +1),
                        ("Smart passes per 90", 0.10, +1),
                    ],
                    "Progression": [
                        ("Progressive passes per 90", 0.25, +1),
                        ("Accurate progressive passes, %", 0.15, +1),
                        ("Progressive runs per 90", 0.20, +1),
                        ("Forward passes per 90", 0.20, +1),
                        ("Accurate forward passes, %", 0.10, +1),
                        ("Deep completions per 90", 0.10, +1),
                    ],
                    "Defensive disruption": [
                        ("Successful defensive actions per 90", 0.25, +1),
                        ("PAdj Interceptions", 0.20, +1),
                        ("PAdj Sliding tackles", 0.15, +1),
                        ("Defensive duels won, %", 0.15, +1),
                        ("Shots blocked per 90", 0.10, +1),
                        ("Fouls per 90", 0.15, -1),
                    ],
                    "Duel power": [
                        ("Duels per 90", 0.20, +1),
                        ("Duels won, %", 0.25, +1),
                        ("Aerial duels per 90", 0.15, +1),
                        ("Aerial duels won, %", 0.25, +1),
                        ("Accelerations per 90", 0.15, +1),
                    ],
                    "Set pieces": [
                        ("Corners per 90", 0.30, +1),
                        ("Direct free kicks per 90", 0.25, +1),
                        ("Direct free kicks on target, %", 0.20, +1),
                        ("Head goals per 90", 0.10, +1),
                        ("Aerial duels won, %", 0.15, +1),
                    ],
                }

                CORE_INDEX_ORDER = ["Threat", "Creation", "Progression", "Defensive disruption", "Duel power"]


                # ----------------------------
                # 2) Robust z score utilities
                # ----------------------------

                def _robust_z(series: pd.Series) -> pd.Series:
                    s = pd.to_numeric(series, errors="coerce")
                    s = s.replace([np.inf, -np.inf], np.nan)
                    med = np.nanmedian(s.values)
                    mad = np.nanmedian(np.abs(s.values - med))
                    if mad and mad > 0:
                        z = (s - med) / (1.4826 * mad)
                    else:
                        mu = np.nanmean(s.values)
                        sd = np.nanstd(s.values)
                        z = (s - mu) / sd if sd and sd > 0 else s * 0.0
                    return z.clip(-3.0, 3.0)


                def _compute_index_scores_for_cohort(
                    cohort_df: pd.DataFrame,
                    *,
                    index_defs: dict[str, list[tuple[str, float, int]]],
                ) -> pd.DataFrame:
                    out = cohort_df.copy()

                    for idx_name, items in index_defs.items():
                        # keep only metrics that exist
                        items_present = [(m, w, d) for (m, w, d) in items if m in out.columns]
                        if not items_present:
                            out[f"idx_{idx_name}"] = np.nan
                            continue

                        # build weighted robust z sum
                        z_sum = None
                        w_sum = 0.0

                        for metric, weight, direction in items_present:
                            z = _robust_z(out[metric]) * float(direction)
                            if z_sum is None:
                                z_sum = weight * z
                            else:
                                z_sum = z_sum + (weight * z)
                            w_sum += abs(float(weight))

                        if z_sum is None or w_sum == 0:
                            out[f"idx_{idx_name}"] = np.nan
                        else:
                            out[f"idx_{idx_name}"] = (z_sum / w_sum)

                    return out


                def _index_percentiles(
                    cohort_scored: pd.DataFrame,
                    *,
                    index_names: list[str],
                ) -> dict[str, pd.Series]:
                    pcts = {}
                    for name in index_names:
                        col = f"idx_{name}"
                        if col not in cohort_scored.columns:
                            pcts[name] = pd.Series([np.nan] * len(cohort_scored), index=cohort_scored.index)
                            continue
                        vals = pd.to_numeric(cohort_scored[col], errors="coerce")
                        # percentile rank on the index itself
                        pcts[name] = vals.rank(pct=True) * 100.0
                    return pcts

                # ----------------------------
                # ----------------------------
                # 4) Visual components
                # ----------------------------

                def _render_index_cards(pct_map: dict[str, float]) -> None:
                    cols = st.columns(len(CORE_INDEX_ORDER))
                    for i, name in enumerate(CORE_INDEX_ORDER):
                        v = pct_map.get(name, np.nan)
                        with cols[i]:
                            if v is None or (isinstance(v, float) and math.isnan(v)):
                                st.metric(name, "NA")
                            else:
                                st.metric(name, f"{v:.0f}", help="Percentile within selected cohort (0 to 100).")


                def _render_index_radar(pct_map: dict[str, float]) -> None:
                    if go is None:
                        st.caption("Plotly not available, radar skipped.")
                        return

                    labels = CORE_INDEX_ORDER
                    r = []
                    for name in labels:
                        v = pct_map.get(name, np.nan)
                        r.append(0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
                    labels_loop = labels + labels[:1]
                    r_loop = r + r[:1]

                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatterpolar(
                            r=r_loop,
                            theta=labels_loop,
                            fill="toself",
                            name="Index profile",
                            line=dict(width=2),
                            opacity=0.75,
                            hovertemplate="%{theta}: %{r:.0f}<extra></extra>",
                        )
                    )
                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                        showlegend=False,
                        margin=dict(l=30, r=30, t=30, b=30),
                        height=420,
                    )
                    st.plotly_chart(fig, use_container_width=True)


                def _render_index_distributions(
                    cohort_scored: pd.DataFrame,
                    *,
                    player_row_idx: int,
                ) -> None:
                    if go is None:
                        return

                    st.markdown("#### Cohort context")
                    cols = st.columns(2)

                    for j, name in enumerate(["Threat", "Creation", "Progression", "Defensive disruption"]):
                        col = f"idx_{name}"
                        if col not in cohort_scored.columns:
                            continue
                        vals = pd.to_numeric(cohort_scored[col], errors="coerce").dropna()
                        if vals.empty:
                            continue

                        player_val = pd.to_numeric(cohort_scored.loc[player_row_idx, col], errors="coerce")

                        fig = go.Figure()
                        fig.add_trace(go.Violin(y=vals, name="Cohort", box_visible=True, meanline_visible=True))
                        if not (player_val is None or (isinstance(player_val, float) and math.isnan(player_val))):
                            fig.add_trace(go.Scatter(y=[player_val], mode="markers", name="Player", marker=dict(size=10)))
                        fig.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20), title=name)
                        with cols[j % 2]:
                            st.plotly_chart(fig, use_container_width=True)

                nation_dirs = wyscoutfolders()

                render_player_report_indexes_block(
                    player_row=r,
                    full_df=df,
                    nation_dirs=nation_dirs,
                    parse_division=_parse_division,
                )
                # ------- Positional Responsibilities -------
                st.subheader("Positional Responsibilities")

                # Use Wyscout row if you have it, otherwise fall back to the DB row
                # IMPORTANT: responsibilities must be computed from Wyscout metric columns
                # make ws_row available in this scope
                ws_row = st.session_state.get("ws_row_current", pd.Series(dtype=object))
                # make ws_row available in this scope
            

                def _as_series(x):
                    if isinstance(x, pd.Series):
                        return x
                    if isinstance(x, dict):
                        return pd.Series(x)
                    if x is None:
                        return pd.Series(dtype=object)
                    try:
                        return pd.Series(x)
                    except Exception:
                        return pd.Series(dtype=object)

                # prefer Wyscout row (from the cohort block) when available
                ws_row_for_resp = _as_series(ws_row)

                if isinstance(ws_row, pd.Series) and not ws_row.empty:
                    ws_row_for_resp = ws_row
                elif isinstance(player_row, pd.Series) and not player_row.empty:
                    ws_row_for_resp = player_row
                else:
                    ws_row_for_resp = pd.Series(dtype=object)

                # if still empty, stop cleanly
                if ws_row_for_resp.empty:
                    st.info("Select a player above to view positional responsibilities.")
                    return

                # safe ws_id for widget keys
                ws_id = str(ws_row_for_resp.get("Wyscout Player ID", "") or "").strip()
                if not ws_id:
                    ws_id = str(player_row.get("Wyscout Player ID", "") if isinstance(player_row, pd.Series) else "").strip()
                if not ws_id:
                    ws_id = f"noid_{st.session_state.get('focus_idx', 'x')}"



                def _split_positions(pos_text: str) -> list[str]:
                    raw = str(pos_text or "").replace("/", ",").replace(";", ",")
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    out, seen = [], set()
                    for p in parts:
                        k = p.casefold()
                        if k not in seen:
                            seen.add(k)
                            out.append(p)
                    return out

                ws_positions = _split_positions(ws_row_for_resp.get("Position", ""))

                if len(ws_positions) >= 2:
                    chosen_pos = st.selectbox(
                        "Wyscout position",
                        ws_positions,
                        index=0,
                        key=f"ws_pos_choice_resp_{ws_id}",
                    )
                elif len(ws_positions) == 1:
                    chosen_pos = ws_positions[0]
                else:
                    chosen_pos = str(player_row.get("Position", ""))  # fallback

                profile_key = _infer_profile_key(chosen_pos)
                with st.expander("DEBUG positional responsibilities", expanded=False):

                    cdf = None
                    try:
                        cdf = cohort_df
                    except Exception:
                        cdf = st.session_state.get("cohort_df_current", pd.DataFrame())

                    prow = ws_row_for_resp if isinstance(ws_row_for_resp, pd.Series) else pd.Series(dtype=object)

                    st.write("chosen_pos", chosen_pos)
                    st.write("profile_key", profile_key)
                    st.write("ws_id", ws_id)
                    st.write("cohort_df shape", getattr(cdf, "shape", None))
                    st.write("player_row name", getattr(prow, "name", None))
                    st.write("player_row cols", int(len(prow.index)) if isinstance(prow, pd.Series) else None)

                    if cdf is None or (hasattr(cdf, "empty") and cdf.empty):
                        st.error("cohort_df is empty inside the responsibilities block")
                    else:
                        cols_list = [str(c) for c in cdf.columns]
                        st.write("cohort_df columns count", int(len(cols_list)))
                        st.write("cohort_df columns sample", cols_list[:60])

                        pct_cols = [c for c in cols_list if c.endswith("__pct")]
                        z_cols = [c for c in cols_list if c.endswith("__z")]
                        st.write("columns ending __pct", int(len(pct_cols)))
                        st.write("columns ending __z", int(len(z_cols)))
                        st.write("sample __pct cols", pct_cols[:25])
                        st.write("sample __z cols", z_cols[:25])

                    spec = RESPONSIBILITIES.get(profile_key, RESPONSIBILITIES.get("CF", {}))
                    st.write("spec keys", list(spec.keys()))

                    rows = []
                    for resp_name, metric_list in spec.items():
                        for metric_col, higher_is_better, w in metric_list:
                            real_col = None
                            close = []
                            pv = np.nan
                            nn = 0
                            vmin = np.nan
                            vmax = np.nan
                            pct = np.nan

                            if cdf is not None and (not hasattr(cdf, "empty") or not cdf.empty):
                                real_col = _resolve_metric_col(cdf, metric_col)
                                cols_list = [str(c) for c in cdf.columns]
                                close = difflib.get_close_matches(str(metric_col), cols_list, n=5, cutoff=0.55)

                                if real_col is not None and real_col in cdf.columns:
                                    pv = _to_num(prow.get(real_col, np.nan))
                                    ser = pd.to_numeric(cdf[real_col], errors="coerce")
                                    nn = int(ser.notna().sum())
                                    if nn:
                                        vmin = float(ser.min())
                                        vmax = float(ser.max())
                                        if not (isinstance(pv, float) and math.isnan(pv)):
                                            pct = float(_metric_percentile(cdf, real_col, pv, higher_is_better))

                            rows.append(
                                {
                                    "responsibility": str(resp_name),
                                    "metric_requested": str(metric_col),
                                    "resolved_column": "" if real_col is None else str(real_col),
                                    "higher_is_better": bool(higher_is_better),
                                    "weight": float(w),
                                    "player_value": pv,
                                    "cohort_non_null": nn,
                                    "cohort_min": vmin,
                                    "cohort_max": vmax,
                                    "metric_percentile": pct,
                                    "close_matches": ", ".join([str(x) for x in close]),
                                }
                            )

                    dbg = pd.DataFrame(rows)
                    st.dataframe(dbg, use_container_width=True, hide_index=True)

                    if "resolved_column" in dbg.columns:
                        unresolved = dbg[dbg["resolved_column"].astype(str).str.len() == 0]
                        if len(unresolved) > 0:
                            st.warning("Some metrics are not resolving to any column. Fix naming or add aliases in _resolve_metric_col.")

                # Compute responsibility scores (percentiles vs cohort) using the correct Wyscout columns
                resp_scores, resp_breakdown = _compute_responsibility_scores(
                    cohort_df=cohort_df,
                    player_row=ws_row_for_resp,
                    profile_key=profile_key,
                )

                # Left side dot ratings, right side bar chart
                left_resp, right_resp = st.columns([1, 1])

                with left_resp:
                    st.caption(f"Profile: {profile_key}   |   Position: {chosen_pos}")
                    for name, val in resp_scores.items():
                        _dot_rating_row(name, val, dots=10)

                with right_resp:
                    _render_responsibilities_bar(resp_scores)

                # Optional: breakdown per responsibility (click to expand)
                st.subheader("Responsibility metric breakdown")

                if resp_breakdown and isinstance(resp_breakdown, dict):
                    resp_names = list(resp_breakdown.keys())

                    chosen_resp = st.selectbox(
                        "Select responsibility",
                        options=resp_names,
                        key="pr_resp_breakdown_pick",
                    )

                    metric_map = resp_breakdown.get(chosen_resp, {}) or {}
                    if isinstance(metric_map, dict) and metric_map:
                        _render_breakdown_radial(
                            metric_map,
                            title=f"{chosen_resp} | metric percentiles (vs cohort)",
                        )
                    else:
                        st.info("No metric breakdown available for this responsibility.")
                else:
                    st.info("No responsibility breakdown available.")


                st.markdown("---")
                st.subheader("📊 Metric tables")
                # ------- Per-cluster metric tables with coloured percentiles -------
                # Build a dynamic Set-pieces cluster from available columns
                sp_keys = []
                TOKS = [
                    "set piece", "set-piece", "corners", "corner",
                    "free kick", "freekick", "throw-in", "throw in",
                    "penalty", "pens", "penalties"
                ]
                # Known Wyscout-ish column names to catch when the free-text search fails
                SP_WHITELIST = [
                    "Corner kicks", "Corner kicks accurate", "Corner assist",
                    "Free kicks", "Free kicks on target", "Free kick shots",
                    "Penalty goals", "Penalty attempts", "xG from set pieces",
                    "xA from set pieces", "Shots from set pieces", "Goals from set pieces",
                    "Throw-in to shot", "Throw-ins leading to chances"
                ]

                for c in ztab.columns:
                    # percentiles or z columns are derived; keep just the base metric name
                    base = str(c)
                    if base.endswith("__pct") or base.endswith("__z") or base.endswith("__rank") or base.endswith("__mu") or base.endswith("__sd"):
                        continue
                    cs = base.casefold()
                    hit = any(tok in cs for tok in TOKS) or base in SP_WHITELIST
                    if hit and pd.api.types.is_numeric_dtype(pd.to_numeric(ztab[base], errors="coerce")):
                        sp_keys.append(base)

                packs_ext = dict(packs)
                if sp_keys:
                    packs_ext["Set-pieces"] = sorted(set(sp_keys))


                for cluster_name, metrics in packs_ext.items():
                    rows_html = []
                    for m in metrics:
                        zcol  = f"{m}__z"
                        pcol  = f"{m}__pct"
                        mucol = f"{m}__mu"   # remove if you don’t have these
                        sdcol = f"{m}__sd"   # remove if you don’t have these

                        raw = player_row.get(m, np.nan) if player_row is not None else np.nan
                        pct = player_row.get(pcol, np.nan) if player_row is not None else np.nan
                        zsc = player_row.get(zcol, np.nan) if player_row is not None else np.nan


                        # optional cohort mu/sd columns
                        mu    = ztab[mucol].iloc[0] if mucol in ztab.columns and len(ztab) else np.nan
                        sd    = ztab[sdcol].iloc[0] if sdcol in ztab.columns and len(ztab) else np.nan

                        bar = _pct_bar(pct) if pd.notna(pct) else _pct_bar(0)

                        if pcol in ztab.columns and pd.notna(pct):
                            rank = int((ztab[pcol] > pct).sum() + 1)
                        elif zcol in ztab.columns and pd.notna(zsc):
                            rank = int((ztab[zcol] > zsc).sum() + 1)
                        else:
                            rank = None

                        rows_html.append(
                            "<tr>"
                            f"<td class='metric-label'>{m}</td>"
                            f"<td class='right'>{_fmt_raw(raw)}</td>"
                            f"<td style='min-width:160px'>{bar}</td>"
                            f"<td class='right dim'>{_fmt_pct(pct)}</td>"
                            f"<td class='right'>{rank if rank else '—'}</td>"
                            f"<td class='right dim'>{_fmt_raw(mu)}</td>"
                            f"<td class='right dim'>{_fmt_raw(sd)}</td>"
                            "</tr>"
                        )

                    html = (
                        f"<div class='dim' style='margin-top:8px;margin-bottom:4px'>{cluster_name}</div>"
                        "<table class='table-compact'>"
                        "<thead>"
                        "<tr><th>Metric</th><th>Player</th><th>Percentile</th><th class='right'>%</th><th class='right'>Rank</th><th class='right'>μ</th><th class='right'>σ</th></tr>"
                        "</thead><tbody>"
                        + "".join(rows_html) +
                        "</tbody></table>"
                    )
                    st.markdown(html, unsafe_allow_html=True)

                st.markdown("---")
           
                if not target_row_filtered.empty:
                    with st.expander("View full stats for this player (all metrics)", expanded=False):
                        # Build rows for ALL numeric base metrics that exist for this cohort
                        # Keep the same columns and bar as your compact tables above
                        rows_html = []
                        # collect base metrics (skip derived suffixes)
                        base_metrics = []
                        for c in ztab.columns:
                            if any(c.endswith(suf) for suf in ["__pct","__z","__rank","__mu","__sd"]):
                                continue
                            # only numeric
                            if pd.api.types.is_numeric_dtype(pd.to_numeric(ztab[c], errors="coerce")):
                                base_metrics.append(c)
                        base_metrics = sorted(set(base_metrics))

                        for m in base_metrics:
                            zcol  = f"{m}__z"
                            pcol  = f"{m}__pct"
                            mucol = f"{m}__mu"
                            sdcol = f"{m}__sd"

                            row_src = target_row_filtered  # IMPORTANT: use the filtered rebound row

                            # Raw value for this player
                            raw = row_src.get(m, np.nan) if (row_src is not None and not row_src.empty) else np.nan

                            # Cohort series for this metric
                            s = pd.to_numeric(ztab.get(m, pd.Series(dtype=float)), errors="coerce")

                            # Compute mu/sd even if you never precomputed __mu/__sd
                            if mucol in ztab.columns and len(ztab):
                                mu = pd.to_numeric(ztab[mucol].iloc[0], errors="coerce")
                            else:
                                mu = s.mean(skipna=True)

                            if sdcol in ztab.columns and len(ztab):
                                sd = pd.to_numeric(ztab[sdcol].iloc[0], errors="coerce")
                            else:
                                sd = s.std(skipna=True)

                            # Prefer stored pct if it exists for this metric, otherwise compute it on the fly
                            pct = row_src.get(pcol, np.nan) if (pcol in ztab.columns and row_src is not None and not row_src.empty) else np.nan
                            if pd.isna(pct):
                                if pd.notna(raw) and s.notna().any():
                                    n = int(s.notna().sum())
                                    pct = (s.le(float(raw)).sum() / n) * 100.0 if n > 0 else np.nan

                            # Same idea for z score
                            zsc = row_src.get(zcol, np.nan) if (zcol in ztab.columns and row_src is not None and not row_src.empty) else np.nan
                            if pd.isna(zsc):
                                try:
                                    if pd.notna(raw) and pd.notna(sd) and float(sd) != 0.0:
                                        zsc = (float(raw) - float(mu)) / float(sd)
                                except Exception:
                                    zsc = np.nan

                            # Rank based on raw when pct/z is missing
                            rank = None
                            try:
                                if pd.notna(raw) and s.notna().any():
                                    rank = int(s.gt(float(raw)).sum() + 1)
                            except Exception:
                                rank = None

                            # Bar should reflect computed pct now
                            bar = _pct_bar(pct) if pd.notna(pct) else _pct_bar(0)

                            rows_html.append(
                                "<tr>"
                                f"<td class='metric-label'>{m}</td>"
                                f"<td class='right'>{_fmt_raw(raw)}</td>"
                                f"<td style='min-width:160px'>{bar}</td>"
                                f"<td class='right dim'>{_fmt_pct(pct) if pd.notna(pct) else '—'}</td>"
                                f"<td class='right'>{rank if rank else '—'}</td>"
                                f"<td class='right dim'>{_fmt_raw(mu)}</td>"
                                f"<td class='right dim'>{_fmt_raw(sd)}</td>"
                                "</tr>"
                            )

                        html = (
                            "<table class='table-compact'>"
                            "<thead>"
                            "<tr><th>Metric</th><th>Player</th><th>Percentile</th><th class='right'>%</th><th class='right'>Rank</th><th class='right'>μ</th><th class='right'>σ</th></tr>"
                            "</thead><tbody>"
                            + "".join(rows_html) +
                            "</tbody></table>"
                        )
                        st.markdown(html, unsafe_allow_html=True)
                else:
                    st.caption("Player not matched in this filtered cohort — you can still browse cohort tables and leaders above.")

                # ------- Cohort exports (so you can analyse in Excel if you like) -------
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Download cohort (CSV)", key=f"dl_cohort_csv_{focus_idx}"):
                        st.download_button(
                            "Save CSV",
                            data=ztab.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"cohort_{focus_idx}.csv",
                            mime="text/csv",
                            key=f"dl_cohort_csv_btn_{focus_idx}"
                        )
                with c2:
                    try:
                        with pd.ExcelWriter(io.BytesIO(), engine="xlsxwriter") as w:
                            ztab.to_excel(w, index=False, sheet_name="Cohort")
                            xldata = w.book.filename.getvalue()  # type: ignore
                        st.download_button(
                            "Download cohort (Excel)",
                            data=xldata,
                            file_name=f"cohort_{focus_idx}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_cohort_xlsx_btn_{focus_idx}"
                        )
                    except Exception:
                        st.caption("Install xlsxwriter for Excel export. CSV export always works.")

            # ===== LIST PAGE =====
        

        with tab_notes:
            # --- Scouting notes & KPIs
            st.markdown("---")
            st.subheader("📝 Scouting notes & KPIs")
            df = profile_editor(df, focus_idx)

            # --- Full report files
            st.markdown("---")
            st.subheader("📄 Full report")
            REPORTS_DIR = os.path.join("Scouting Workspace", "full reports done")
            os.makedirs(REPORTS_DIR, exist_ok=True)

            # reload r in case we saved something above
            r = df.loc[focus_idx]
            cur_pdf_path = str(r.get("Full Report Path", "")).strip()

            up_col, info_col = st.columns([2,3])
            with up_col:
                up_pdf = st.file_uploader("Upload/replace full report (PDF)", type=["pdf"], key=f"upload_pdf_{focus_idx}")
                if up_pdf is not None:
                    date_str = dt.datetime.now().strftime("%Y-%m-%d")
                    safe_name = re.sub(r"[^\w\-. ]", "_", r.get("Name","Unnamed")).strip("_") or "Report"
                    save_path = os.path.join(REPORTS_DIR, f"{safe_name} - {date_str}.pdf")
                    try:
                        with open(save_path, "wb") as f:
                            f.write(up_pdf.read())
                        df.at[focus_idx, "Full Report Path"] = save_path
                        df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        _log_save_identity("About to save", df)  # must be the full DB
                        safe_write_db(st.session_state.db_csv, df)
                        st.success("Full report saved.")
                        cur_pdf_path = save_path
                    except Exception as e:
                        st.error(f"Failed to save PDF: {e}")

            with info_col:
                if cur_pdf_path and os.path.exists(cur_pdf_path):
                    st.caption(f"Saved at: `{cur_pdf_path}`")
                    with open(cur_pdf_path, "rb") as f:
                        st.download_button("Download PDF", data=f.read(),
                                        file_name=os.path.basename(cur_pdf_path),
                                        mime="application/pdf",
                                        key=f"dl_pdf_{focus_idx}")
                else:
                    st.info("No report uploaded yet.")

            # ---- PDF preview
            if cur_pdf_path and os.path.exists(cur_pdf_path):
                mode = st.radio(
                    "Preview mode",
                    ["Image pages (compatible)", "Embedded (may be blocked by ad blockers)"],
                    index=0,
                    horizontal=True,
                    key=f"pdf_mode_{focus_idx}"
                )

                if mode.startswith("Image"):
                    max_pages = st.slider("Pages to render", 1, 40, 20, key=f"pdf_pages_{focus_idx}")
                    dpi = st.slider("Render DPI", 110, 200, 160, key=f"pdf_dpi_{focus_idx}")
                    if callable(_render_pdf_as_images):
                        _render_pdf_as_images(cur_pdf_path, max_pages=max_pages, dpi=dpi)
                    else:
                        st.warning("PDF image renderer was not passed into the player reports page.")
                else:
                    if callable(_embed_pdf_data_uri):
                        ok = _embed_pdf_data_uri(cur_pdf_path, height=900)
                        if not ok:
                            st.info("If the embed is blocked by your browser, switch preview mode to **Image pages** above.")
                    else:
                        st.warning("PDF embed renderer was not passed into the player reports page.")

            st.markdown("---")
            with st.expander("⚠️ Danger zone", expanded=False):
                st.markdown(
                    "This will **permanently delete** the player from your database and "
                    "remove any saved files for this player (Full Report, Photo Path). "
                    "**This cannot be undone.**"
                )

                confirm = st.checkbox("I understand this cannot be undone.", key=f"del_ok_{focus_idx}")
                confirm_text = st.text_input("Type DELETE to confirm", key=f"del_txt_{focus_idx}")

                delete_disabled = not (confirm and confirm_text.strip().upper() == "DELETE")
                if st.button("🗑️ Permanently delete player", type="primary", disabled=delete_disabled, key=f"del_btn_{focus_idx}"):

                    # Determine Row ID of the focused player
                    rid = None
                    if focus_idx is not None and ROW_ID_COL in df.columns:
                        rid = str(df.at[focus_idx, ROW_ID_COL])
                    if not rid:
                        rid = str(st.session_state.get("profile_focus_id") or "")

                    if not rid:
                        st.error("Could not determine the player's Row ID.")
                        st.stop()

                    # Try to remove files for the open row if present
                    try:
                        if focus_idx is not None:
                            row_current = df.loc[focus_idx]
                            for col in ["Full Report Path", "Photo Path"]:
                                _safe_unlink(str(row_current.get(col, "")).strip())
                    except Exception:
                        pass

                    # Reload and delete strictly by Row ID
                    df_latest = load_db(st.session_state.db_csv).copy()
                    if ROW_ID_COL in df_latest.columns:
                        df_latest = df_latest[df_latest[ROW_ID_COL].astype(str) != rid].copy()
                        safe_write_db(st.session_state.db_csv, df_latest)
                        st.cache_data.clear()
                        st.success("Player deleted.")
                        st.session_state.profile_focus_id = None
                        st.rerun()
                    else:
                        st.error("Row ID column missing from database; cannot safely delete.")

    # ===== CARD GRID (list view)
    else:
        view = df.copy()
        if name_q:   view = view[view["Name"].str.contains(name_q, case=False, na=False)]
        if f_team:   view = view[view["Player Current Team"] == f_team]
        if f_nation: view = view[view["Playing Nation"] == f_nation]
        if f_verdict:view = view[view["Verdict"] == f_verdict]
        if f_role:
            view = view[view["Position"].apply(lambda x: f_role.lower() in [p.strip().lower() for p in (x or "").split(",")])]
        age_series_view = compute_age_series(view)
        view = view[(age_series_view >= age_min_rep) & (age_series_view <= age_max_rep)]

        view = _sort_newest_first(view)

        st.caption(f"Showing {len(view)} players")
        _render_shortlist_status_legend()

        if view.empty:
            _render_empty_player_results()
            return

        cards_per_row = 3
        idxs = view.index.tolist()
        for start in range(0, len(idxs), cards_per_row):
            cols = st.columns(cards_per_row)
            for col, idx in zip(cols, idxs[start:start+cards_per_row]):
               with col:
                   row = view.loc[idx]
                   render_player_card(row, key_prefix=f"rep_{idx}", show_more=False)
                   if st.button("Open report", key=f"open_{idx}", use_container_width=True):
                       st.session_state.profile_focus_id = str(view.loc[idx, ROW_ID_COL])
                       st.rerun()