# helpers/recruitment_data_wrangling.py

from __future__ import annotations

import os
import io
import csv
import glob
import urllib.parse
import math
import re as _re
import re
import numpy as np
import pandas as pd
import streamlit as st
import unicodedata
import difflib
import textwrap
import altair as alt
import plotly.graph_objects as go
from datetime import date
import requests
from pathlib import Path

try:
    import plotly.graph_objects as go
except Exception:
    go = None

from helpers.profile_defs import (
    POSITION_ROLES, GLOBAL_TRAITS, RESPONSIBILITIES,
    ROLE_DEFINITIONS, TRAIT_DEFINITIONS, RESPONSIBILITY_DEFINITIONS,
    TIER_STRENGTH
)
from helpers.profile_defs import (
    _to_num, role_group_from_profile, norm_col_name, _resolve_metric_col,
    _weighted_mean, _metric_percentile, _compute_responsibility_scores
)
from helpers.profile_defs import LEAGUE_TIER_LABEL, tier_strength_coef

ENCODING_CANDIDATES = [
    "utf-8-sig",
    "cp1252",
    "latin1",
    "utf-16",
    "utf-16le",
    "utf-16be",
]

def _strip_accents(text: str) -> str:
    """
    Turn 'İlkay Gündoğan' into 'Ilkay Gundogan' using Unicode decomposition.
    Keeps letters, drops only accent marks.
    """
    if text is None:
        return ""
    text = str(text)
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))

WYSROOTDIR = os.environ.get("WYSROOTDIR") or os.environ.get("SCOUTING_APP_ROOT") or str(Path(__file__).resolve().parent.parent)

THREE_NATION_FILTER = {
    "belgium",
    "belgian",
    "dutch",
    "netherlands",
    "holland",
    "france",
    "french",
}

# Path to your Reference squad stats for this season
REFERENCE_PLAYERS_PATH = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent)) / "Reference_players_25_26.csv"

CLUBELO_DIR = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent)) / "Club Elo Ratings"
CLUBELO_DIR.mkdir(parents=True, exist_ok=True)

###############################################################
# Club Elo integration and caching
################################################################

def _clubelo_latest_path() -> Path:
    return CLUBELO_DIR / "clubelo_latest.csv"

def _clubelo_dated_path(d: str) -> Path:
    return CLUBELO_DIR / f"clubelo_{d}.csv"


def fetch_today():
    today = date.today().isoformat()
    url = f"http://api.clubelo.com/{today}"
    resp = requests.get(url)
    resp.raise_for_status()
    # ClubElo returns CSV text directly
    df = pd.read_csv(io.StringIO(resp.text))

    # Normalise column names from ClubElo export
    df.columns = [c.strip() for c in df.columns]

    # ClubElo commonly uses "Club" for name; keep Elo column
    if "Club" in df.columns and "Team" not in df.columns:
        df = df.rename(columns={"Club": "Team"})

    # Safety: ensure required columns exist
    if "Team" not in df.columns:
        raise RuntimeError(f"ClubElo CSV missing Team/Club column. Columns: {list(df.columns)}")
    if "Elo" not in df.columns:
        raise RuntimeError(f"ClubElo CSV missing Elo column. Columns: {list(df.columns)}")

    today = date.today().isoformat()
    dated_path = CLUBELO_DIR / f"clubelo_{today}.csv"

    df.to_csv(dated_path, index=False)
    df.to_csv(_clubelo_latest_path(), index=False)



if __name__ == "__main__":
    fetch_today()
    print(f"Updated ClubElo cache at {_clubelo_latest_path()}")

def update_clubelo_cache_if_needed(max_age_hours: int = 24) -> bool:
    """
    Returns True if cache exists (after possible update).
    Returns False if still missing/unreadable.
    """
    latest = _clubelo_latest_path()
    today = date.today().isoformat()
    dated = _clubelo_dated_path(today)

    # If today's file already exists, keep it as latest
    if dated.exists():
        try:
            df = pd.read_csv(dated)
            df.to_csv(latest, index=False)
            return True
        except Exception:
            pass

    # If latest exists and is fresh enough, don't re-fetch
    if latest.exists():
        try:
            age_hours = (pd.Timestamp.now() - pd.Timestamp(latest.stat().st_mtime, unit="s")).total_seconds() / 3600
            if age_hours <= max_age_hours:
                return True
        except Exception:
            return True

    # Fetch from ClubElo API
    url = f"http://api.clubelo.com/{today}"
    headers = {"User-Agent": "Mozilla/5.0"}  # helps if servers block python-requests UA
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        # Keep old latest if it exists
        st.warning(f"ClubElo fetch failed: {e}")
        return latest.exists()

    st.caption(f"ClubElo status: {r.status_code}, first 100 chars: {r.text[:100]}")

    # Normalize expected columns
    df.columns = [c.strip() for c in df.columns]
    if "Club" in df.columns and "Team" not in df.columns:
        df = df.rename(columns={"Club": "Team"})
    if "Team" not in df.columns or "Elo" not in df.columns:
        st.warning(f"ClubElo CSV missing Team/Elo. Columns: {list(df.columns)}")
        return False

    # Save: dated + latest
    try:
        df.to_csv(dated, index=False)
        df.to_csv(latest, index=False)
        return True
    except Exception as e:
        st.warning(f"Could not save ClubElo cache: {e}")
        return False


def _club_key(name: str) -> str:
    if name is None:
        return ""

    s = _strip_accents(str(name)).lower()
    s = s.replace("&", "and")

    # remove bracketed stuff like "(Reserves)" or "(Women)"
    s = _re.sub(r"\(.*?\)", " ", s)

    # tokenise on non-alphanum
    toks = [t for t in _re.split(r"[^a-z0-9]+", s) if t]

    # drop very common meaningless tokens
    drop = {
        "fc","cf","sc","ac","as","sv","fk","ksc","kv","kvc","krc","kaa","rsc",
        "team","club","de","la","le","du","us",
        "u17","u18","u19","u20","u21","u23",
        "ii","iii","b","reserves","reserve","women","w","academy"
    }
    toks = [t for t in toks if t not in drop]

    key = "".join(toks)

    # explicit aliases (safe, no acronym guessing)
    aliases = {
        "parissaintgermain": "parissg",
        "psg": "parissg",
        "manchestercity": "mancity",
        "manchesterunited": "manutd",
        "internazionale": "inter",
    }
    return aliases.get(key, key)


@st.cache_data(show_spinner=False)
def _load_clubelo_cache(
    path: str = str(_clubelo_latest_path())
) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=["Team", "Elo"])

    # enforce expected columns
    if "Team" not in df.columns:
        df["Team"] = ""
    if "Elo" not in df.columns:
        df["Elo"] = pd.NA
    df["_club_key"] = df["Team"].map(_club_key)
    return df

    

def _attach_elo_factor(df: pd.DataFrame) -> pd.DataFrame:
    if "Team" not in df.columns:
        # nothing we can do, return as is
        df["_elo_factor"] = 1.0
        return df

    df_out = df.copy()
    clubelo = _load_clubelo_cache()
    
    with st.expander("ClubElo Debug", expanded=False):
        st.caption(f"ClubElo rows: {len(clubelo)}")
        st.caption(f"ClubElo cols: {list(clubelo.columns)[:8]}")
        st.caption(f"ClubElo non-null Team: {clubelo['Team'].astype(str).str.strip().ne('').mean():.1%}")
        st.caption(f"ClubElo non-null Elo: {pd.to_numeric(clubelo['Elo'], errors='coerce').notna().mean():.1%}")
        st.caption(f"ClubElo path: {_clubelo_latest_path()}")
        st.caption(f"ClubElo latest exists: {_clubelo_latest_path().exists()}")
        

    if clubelo.empty:
        df_out["_elo_factor"] = 1.0
        return df_out

    df_out["_club_key"] = df_out["Team"].map(_club_key)
    merged = df_out.merge(clubelo[["_club_key", "Elo"]], on="_club_key", how="left")

    # choose a baseline Elo so that average factor is around 1.0
    valid = merged["Elo"].dropna()
    baseline = float(valid.mean()) if not valid.empty else 1500.0

    merged["_elo_factor"] = merged["Elo"].fillna(baseline) / baseline
    # build a lookup for fuzzy fallback
    club_map = dict(zip(clubelo["_club_key"], clubelo["Elo"]))

    def _fuzzy_elo(k: str):
        if not k:
            return pd.NA
        if k in club_map:
            return club_map[k]
        matches = difflib.get_close_matches(k, list(club_map.keys()), n=2, cutoff=0.94)
        if len(matches) == 1:
            return club_map[matches[0]]
        if len(matches) == 2 and matches[0] != matches[1]:
            # require clear winner: second match must be noticeably worse
            # (difflib doesn’t give scores, so simplest safe rule is: reject if 2 candidates)
            return pd.NA
        return pd.NA

    missing = merged["Elo"].isna()
    merged.loc[missing, "Elo"] = merged.loc[missing, "_club_key"].map(_fuzzy_elo)
    unmatched = merged.loc[merged["Elo"].isna(), "Team"].dropna().astype(str).value_counts().reset_index()
    unmatched.columns = ["Team", "Count"]
    unmatched_path = CLUBELO_DIR / "wyscout_unmatched_teams.csv"
    unmatched.to_csv(unmatched_path, index=False, encoding="utf-8-sig")
    st.caption(f"Saved unmatched teams to: {unmatched_path}")
    return merged

def _attach_tier_factor(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "_tier_factor" in df.columns:
        return df

    out = df.copy()
    league_key_col = "__league_key" if "__league_key" in out.columns else None
    nation_col = "__nation" if "__nation" in out.columns else None

    def _row_factor(r):
        lk = str(r.get(league_key_col, "")) if league_key_col else ""
        nt = str(r.get(nation_col, "")) if nation_col else ""
        return league_tier_factor_from_row(lk, nt)

    out["_tier_factor"] = out.apply(_row_factor, axis=1).astype(float)
    return out


def _apply_league_normalisation(
    df: pd.DataFrame,
    metric_cols: list[str],
    use_elo: bool,
    use_tier: bool,
    metric_direction_func,
) -> pd.DataFrame:
    """
    Normalises KPI values first, then your existing z score, percentiles, roles,
    responsibilities, radar, similarity run as usual on the adjusted KPIs.

    Rule:
    higher better metrics get multiplied by factor
    lower better metrics get divided by factor
    """
    if df is None or df.empty or not metric_cols:
        return df
    if not use_elo and not use_tier:
        return df

    out = df.copy()

    factor = pd.Series(1.0, index=out.index, dtype="float64")

    if use_elo:
        out = _attach_elo_factor(out)
        if "_elo_factor" in out.columns:
            factor = factor * pd.to_numeric(out["_elo_factor"], errors="coerce").fillna(1.0)

    if use_tier:
        out = _attach_tier_factor(out)
        if "_tier_factor" in out.columns:
            factor = factor * pd.to_numeric(out["_tier_factor"], errors="coerce").fillna(1.0)

    factor = factor.clip(0.35, 1.35)

    for c in metric_cols:
        if c not in out.columns:
            continue
        s = pd.to_numeric(out[c], errors="coerce")
        if metric_direction_func(c):  # higher is better
            out[c] = s * factor
        else:  # lower is better
            out[c] = s / factor

        # optional safety for percentage style metrics
        if "%" in str(c):
            out[c] = pd.to_numeric(out[c], errors="coerce").clip(0, 100)

    return out
    
def _norm_league_key_for_tier(x) -> str:
    # Data analysis league keys may look like "Belgium · T1".
    # Profile definitions use the same idea without the separator.
    s = "" if x is None else str(x)
    s = _re.sub(r"\s*·\s*", " ", s).strip()
    return s


def _tier_one_benchmark_cohort(master_df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Return a neutral tier one benchmark cohort from the loaded league data.
    It uses explicit tier columns first, then league key labels such as "T1".
    If no tier signal exists, it falls back to the full master dataframe.
    """
    import pandas as pd

    if master_df is None or master_df.empty:
        return pd.DataFrame()

    mask = pd.Series(False, index=master_df.index)
    found_signal = False

    for col in ["Tier", "__tier", "League tier", "Level"]:
        if col in master_df.columns:
            tier_vals = pd.to_numeric(master_df[col], errors="coerce")
            mask |= tier_vals.eq(1).fillna(False)
            found_signal = True

    for col in ["__league_key", "__league", "__league_tier_label"]:
        if col in master_df.columns:
            league_txt = master_df[col].astype(str)
            mask |= league_txt.str.contains(r"(^|[\s·|_/])T?1($|[\s·|_/])", case=False, regex=True, na=False)
            found_signal = True

    if found_signal and mask.any():
        return master_df[mask].copy()

    return master_df.copy()


def _attach_tier_factor(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Adds __tier_factor column using LEAGUE_TIER_LABEL + tier_strength_coef.
    Falls back to 0.50 when unmapped.
    """
    import pandas as pd

    if df is None or df.empty:
        return df
    if "__tier_factor" in df.columns:
        return df

    out = df.copy()

    if "__league" in out.columns:
        raw_keys = out["__league"]
    elif "__league_key" in out.columns:
        raw_keys = out["__league_key"]
    elif "__nation" in out.columns and "__tier" in out.columns:
        raw_keys = out["__nation"].astype(str) + " T" + out["__tier"].astype(str)
    else:
        out["__tier_factor"] = 0.50
        return out

    def _coef(k):
        kk = _norm_league_key_for_tier(k)
        tier_label = LEAGUE_TIER_LABEL.get(kk)
        if not tier_label:
            return 0.50
        try:
            return float(tier_strength_coef(tier_label))
        except Exception:
            return 0.50

    out["__tier_factor"] = raw_keys.map(_coef).astype(float)
    return out


def _apply_league_factor_to_kpis(
    df: "pd.DataFrame",
    kpi_cols: list,
    factor_col: str,
    metric_direction=None,
) -> "pd.DataFrame":
    """
    Applies factor to KPI columns.
    Higher is better KPIs get multiplied by factor.
    Lower is better KPIs get divided by factor (so weak league inflates negatives).
    """
    import pandas as pd

    if df is None or df.empty or not kpi_cols:
        return df

    out = df.copy()
    f = pd.to_numeric(out.get(factor_col), errors="coerce").fillna(1.0)
    f = f.clip(lower=0.10)  # avoid divide by zero behaviour

    def _dir(col):
        if metric_direction is None:
            return None
        try:
            if isinstance(metric_direction, dict):
                return metric_direction.get(col)
            return metric_direction(col)
        except Exception:
            return None

    for c in kpi_cols:
        if c not in out.columns:
            continue
        s = pd.to_numeric(out[c], errors="coerce")

        d = _dir(c)
        lower_is_better = (d == -1) or (d is False) or (str(d).lower() in {"lower", "lower_is_better", "min"})
        if lower_is_better:
            out[c] = s / f
        else:
            out[c] = s * f

    return out


################################################################################
# ---- Position text normalisation for Search tab ----

_POSITION_ALIAS_MAP = {
    # common full text variants -> Wyscout short codes
    "GOALKEEPER": "GK",
    "CENTER BACK": "CB",
    "CENTRE BACK": "CB",
    "CENTRAL DEFENDER": "CB",
    "RIGHT BACK": "RB",
    "LEFT BACK": "LB",
    "WING BACK": "RWB",  # generic fallback
    "FULL BACK": "RB",   # generic fallback
    "DEFENSIVE MIDFIELDER": "DMF",
    "DEFENSIVE MIDFIELD": "DMF",
    "HOLDING MIDFIELDER": "DMF",
    "CENTRAL MIDFIELDER": "CMF",
    "CENTRE MIDFIELDER": "CMF",
    "MIDFIELDER": "CMF",  # generic fallback
    "ATTACKING MIDFIELDER": "AMF",
    "ATTACKING MIDFIELD": "AMF",
    "LEFT WINGER": "LW",
    "RIGHT WINGER": "RW",
    "WIDE FORWARD": "WF",
    "FORWARD": "CF",
    "STRIKER": "CF",
    "CENTRE FORWARD": "CF",
    "CENTER FORWARD": "CF",
}

def _normalise_pos_text(txt: str) -> str:
    t = (txt or "").strip()
    if not t:
        return ""
    up = t.upper()
    return _POSITION_ALIAS_MAP.get(up, up)

WS_POS_TO_ROLE_PROFILE = {
    "GK": "GK",
    "RB": "RB", "RWB": "RWB",
    "LB": "LB", "LWB": "LWB",
    "CB": "CB", "RCB": "RCB", "LCB": "LCB",
    "DMF": "DMF", "RDMF": "RDMF", "LDMF": "LDMF",
    "CMF": "CMF", "RCMF": "RCMF", "LCMF": "LCMF",
    "AMF": "AMF", "RAMF": "RAMF", "LAMF": "LAMF",
    "RM": "RMF", "RMF": "RMF", "RW": "RW", "RWF": "RWF",
    "LM": "LMF", "LMF": "LMF", "LW": "LW", "LWF": "LWF",
    "CF": "CF", "ST": "CF", "SS": "SS",
}
import re

# Keep the dropdown clean and consistent
WS_POS_ORDER = [
    "GK",
    "CB", "LCB", "RCB",
    "LB", "LWB",
    "RB", "RWB",
    "DMF", "LDMF", "RDMF",
    "CMF", "LCMF", "RCMF",
    "AMF", 
    "LAMF", "RAMF",
    "LM", "RM",
    "LW", "LWF",
    "RW", "RWF",
    "SS",
    "CF", "ST",
]

# What counts as "can play this position too" (simple and practical)
WS_POS_COMPAT = {
    "GK": {"GK"},

    "CB": {"CB", "LCB", "RCB"},
    "LCB": {"CB", "LCB"},
    "RCB": {"CB", "RCB"},

    "LB": {"LB", "LWB"},
    "LWB": {"LB", "LWB"},
    "RB": {"RB", "RWB"},
    "RWB": {"RB", "RWB"},

    "DMF": {"DMF", "LDMF", "RDMF"},
    "LDMF": {"DMF", "LDMF", "RDMF"},
    "RDMF": {"DMF", "LDMF", "RDMF"},

    # Central midfield is deliberately side flexible.
    # Selecting LCMF also includes RCMF and CMF, and vice versa.
    "CMF": {"CMF", "LCMF", "RCMF"},
    "LCMF": {"CMF", "LCMF", "RCMF"},
    "RCMF": {"CMF", "LCMF", "RCMF"},

    # Attacking midfield is also side flexible.
    # This is kept separate from true wing roles.
    "AMF": {"AMF", "LAMF", "RAMF"},
    "LAMF": {"AMF", "LAMF", "RAMF"},
    "RAMF": {"AMF", "LAMF", "RAMF"},

    "LM": {"LM", "LAMF"},
    "RM": {"RM", "RAMF"},

    # True wing roles stay side specific.
    "LW": {"LW", "LWF"},
    "LWF": {"LW", "LWF"},
    "RW": {"RW", "RWF"},
    "RWF": {"RW", "RWF"},

    "SS": {"SS", "AMF", "CF", "ST"},
    "CF": {"CF", "ST", "SS"},
    "ST": {"ST", "CF", "SS"},
}

_WS_POS_CODE_RE = re.compile(
    r"\b(GK|RCB|LCB|CB|RWB|LWB|RB|LB|RDMF|LDMF|DMF|RCMF|LCMF|CMF|RAMF|LAMF|AMF|RWF|LWF|RW|LW|RM|LM|SS|CF|ST)\b"
)

def _ws_pos_tokens(pos_value) -> set[str]:
    """
    Returns a set of Wyscout short codes found in a Position cell.
    Handles strings like: "LW, LWF" and also full text like "Left Back".
    """
    if pos_value is None:
        return set()

    up = str(pos_value).strip().upper()
    if not up:
        return set()

    tokens = set()

    # 1) Extract any recognised short codes anywhere in the string
    tokens.update(_WS_POS_CODE_RE.findall(up))

    # 2) Also split into chunks and normalise full text variants (uses your existing alias map)
    for chunk in re.split(r"[;,/|]+", up):
        c = _normalise_pos_text(chunk.strip())
        if c in WS_POS_TO_ROLE_PROFILE:
            tokens.add(c)

    return tokens

# Preset dropdown labels are Role profile names, not Wyscout position strings.
# Map them explicitly to the internal profile keys used by ROLES and RESPONSIBILITIES.
_ROLE_PRESET_LABEL_TO_PROFILE_KEY: dict[str, str | None] = {
    "GK": "GK",

    "6": "6",
    "DMF": "6",
    "LDMF/RDMF": "6",

    "8": "8",
    "CMF": "8",
    "LCMF/RCMF": "8",

    "10": "10",
    "AMF": "10",
    "LAMF/RAMF": "10",
    "SS": "10",

    "CBS": "CB",
    "CBs": "CB",
    "CB": "CB",
    "LCB/RCB": "CB",

    "FB/WB": "FB",
    "FBWB": "FB",
    "FB / WB": "FB",
    "LB/RB": "FB",
    "LWB/RWB": "FB",

    "7 - RM": "WM",
    "7-RM": "WM",
    "7 RM": "WM",
    "11 - LM": "WM",
    "11-LM": "WM",
    "11 LM": "WM",
    "7 / 11": "WM",
    "7/11": "WM",
    "7": "WM",
    "11": "WM",
    "LM/RM": "WM",
    "WM": "WM",

    "WF": "WF",
    "LW/RW": "WF",
    "LWF/RWF": "WF",
    "LW/RW/LWF/RWF": "WF",
    "7A / 11A": "WF",
    "7A/11A": "WF",
    "7A /11A": "WF",
    "7A/ 11A": "WF",

    "9 - AF": "CF",
    "9-AF": "CF",
    "9 AF": "CF",
    "CF": "CF",
    "ST": "CF",
    "CF/ST": "CF",

    "9 - TM": "CF",
    "9-TM": "CF",
    "9 TM": "CF",

    "T1": None,
}

def _preset_label_to_profile_key(label: str | None) -> str | None:
    if not label:
        return None

    t = str(label).strip()
    if not t:
        return None

    # Normalise spacing
    t_sp = " ".join(t.split())

    # Direct lookup
    if t_sp in _ROLE_PRESET_LABEL_TO_PROFILE_KEY:
        return _ROLE_PRESET_LABEL_TO_PROFILE_KEY[t_sp]

    # Uppercase variants
    t_up = t_sp.upper()
    if t_up in _ROLE_PRESET_LABEL_TO_PROFILE_KEY:
        return _ROLE_PRESET_LABEL_TO_PROFILE_KEY[t_up]

    # Compact variants, useful for "7A / 11A"
    t_comp = t_up.replace(" ", "")
    for k, v in _ROLE_PRESET_LABEL_TO_PROFILE_KEY.items():
        if k.upper().replace(" ", "") == t_comp:
            return v

    # Fall back to your existing text parser (Wyscout like "DMF", "LCB", etc.)
    return _text_to_profile_key(t_sp)

def _text_to_profile_key(txt: str) -> str | None:
    """
    Returns one of: GK, CB, FB, 6, 8, 10, WM, WF, CF
    Accepts Wyscout short codes and common full text labels.
    Also handles typical preset naming like '8 / 8A', '9', '11', etc.
    """
    t = _normalise_pos_text(txt)

    if not t:
        return None

    # already a profile key
    if t in {"GK", "CB", "FB", "6", "8", "10", "WM", "WF", "CF"}:
        return t

    # goalkeepers
    if _re.search(r"\bGK\b|GOALKEEPER", t):
        return "GK"

    # centre backs
    if _re.search(r"\bCB\b|\bLCB\b|\bRCB\b|CENT(RE|ER)\s+BACK|CENTRAL\s+DEFEND", t):
        return "CB"

    # full backs and wing backs
    if _re.search(r"\bFB\b|\bLB\b|\bRB\b|\bLWB\b|\bRWB\b|FULL\s*BACK|WING\s*BACK", t):
        return "FB"

    # defensive midfield
    if _re.search(r"\bDMF\b|\bLDMF\b|\bRDMF\b|DEFENSIVE\s+MID|HOLDING\s+MID|\b6\b", t):
        return "6"

    # central midfield
    if _re.search(r"\bCMF\b|\bLCMF\b|\bRCMF\b|CENT(RAL|RE)\s+MID|MIDFIELDER|\b8\b", t):
        return "8"

    # attacking midfield
    if _re.search(r"\bAMF\b|ATTACKING\s+MID|\b10\b", t):
        return "10"

    # wide midfielder
    if _re.search(r"\bWM\b|\bRM\b|\bLM\b|\bRAMF\b|\bLAMF\b|WIDE\s+MID|WIDE\s+MIDFIELDER|WINGER|\b7\b|\b11\b", t):
        return "WM"

    # wide forward
    if _re.search(r"\bWF\b|\bRW\b|\bLW\b|\bRWF\b|\bLWF\b|WIDE\s+FORWARD|\b7A\b|\b11A\b", t):
        return "WF"

    # centre forwards
    if _re.search(r"\bCF\b|STRIKER|CENT(RE|ER)\s+FORWARD|\b9\b", t):
        return "CF"

    return None

# -------- Position to profile key --------

def _infer_profile_key(pos_text: str) -> str:
    t = (pos_text or "").strip().lower()

    if "gk" in t:
        return "GK"

    if any(x in t for x in ["cb", "rcb", "lcb", "ccb"]):
        return "CB"

    if any(x in t for x in ["rb", "lb", "rwb", "lwb", "wb"]):
        return "FB"

    if any(x in t for x in ["dmf", "rdmf", "ldmf", "dm", "6"]):
        return "6"

    if any(x in t for x in ["cmf", "rcmf", "lcmf", "cm", "8"]):
        return "8"

    # LAMF and RAMF are treated as attacking midfield search profiles here.
    # True LW and RW roles are handled separately as wide forward profiles.
    if any(x in t for x in ["amf", "ramf", "lamf", "am", "cam", "10"]):
        return "10"

    if any(x in t for x in ["rwf", "lwf", "rw", "lw", "wf", "7a", "11a"]):
        return "WF"

    if any(x in t for x in ["rm", "lm", "wm", "7", "11", "w"]):
        return "WM"

    if any(x in t for x in ["tm"]):
        return "TM"

    if any(x in t for x in ["cf", "st", "ss", "9"]):
        return "CF"

    k = _text_to_profile_key(pos_text)
    return k or ""

#================================================================================
# ---- League / nation helpers ----
#================================================================================

TOP5_NATIONS = ["England", "Spain", "Germany", "Italy", "France"]
NEXT7_NATIONS = ["Portugal", "Netherlands", "Belgium", "Turkey", "Austria", "Scotland", "Switzerland"]

def _leaguekey_parts(label: str):
    """
    Supports your league keys like:
      "England · T1"
      "England T1"
      "England1"
      "England 1"
    Returns (nation_prefix_casefold, tier_int_or_None)
    """
    import re
    s = (label or "").strip()

    m = re.match(r"^(.*?)\s*·\s*T(\d+)\s*$", s)
    if m:
        return m.group(1).strip().casefold(), int(m.group(2))

    m = re.match(r"^(.*?)\s*T(\d+)\s*$", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().casefold(), int(m.group(2))

    m = re.match(r"^(.+?)\s*(\d+)\s*$", s)
    if m:
        return m.group(1).strip().casefold(), int(m.group(2))

    return s.casefold(), None

def _tier1_divs_for_nations(div_options: list[str], nations: list[str]) -> list[str]:
    wanted = {n.casefold() for n in nations}
    out: list[str] = []
    for opt in div_options:
        pref, tier = _leaguekey_parts(opt)
        if tier == 1 and pref in wanted:
            out.append(opt)
    return out

def _dedupe_keep_order(xs: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


################################################################################

# -------- Core scoring helpers --------
def _unpack_rule(rule):
    """
    Accepts either:
      (metric_col, higher_is_better, weight)
      (metric_col, threshold_percentile, higher_is_better, weight)

    Returns:
      metric_col, higher_is_better, weight
    """
    if rule is None:
        return None, None, None

    if isinstance(rule, (list, tuple)):
        if len(rule) == 3:
            metric_col, higher_is_better, w = rule
            return metric_col, bool(higher_is_better), float(w)
        if len(rule) == 4:
            metric_col, _threshold, higher_is_better, w = rule
            return metric_col, bool(higher_is_better), float(w)

    raise ValueError(f"Bad rule format (expected 3 or 4 items): {rule}")

def _zscore_series(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    mu = x.mean(skipna=True)
    sd = x.std(skipna=True)
    if sd is None or sd == 0 or np.isnan(sd):
        return pd.Series(np.nan, index=x.index)
    return (x - mu) / sd


def _ensure_z_and_pct(ztab: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    ztab = ztab.copy()
    for m in metrics:
        if m not in ztab.columns:
            continue
        zcol = f"{m}__z"
        pcol = f"{m}__pct"
        if zcol not in ztab.columns:
            ztab[zcol] = _zscore_series(ztab[m])
        if pcol not in ztab.columns:
            ztab[pcol] = ztab[zcol].rank(pct=True) * 100.0
    return ztab


def _score_from_spec_z(ztab: pd.DataFrame, player_row: pd.Series, metric_list: list[tuple[str, bool, float]]) -> float:
    num = 0.0
    den = 0.0
    for rule in metric_list:
        metric_col, higher_is_better, w = _unpack_rule(rule)
        if metric_col is None:
            continue

        zcol = f"{metric_col}__z"
        if zcol not in ztab.columns:
            continue
        sign = 1.0 if higher_is_better else -1.0
        zval = pd.to_numeric(player_row.get(zcol, np.nan), errors="coerce")
        if pd.isna(zval):
            continue
        num += float(zval) * sign * float(w)
        den += float(w)
    if den == 0:
        return float("nan")
    return num / den


def _compute_label_scores(ztab: pd.DataFrame, player_row: pd.Series, spec: dict[str, list[tuple[str, bool, float]]]) -> dict[str, float]:
    # Ensure z columns exist for all metrics in spec
    needed = []
    for _, metric_list in spec.items():
        for rule in metric_list:
            metric_col, _, _ = _unpack_rule(rule)
            if metric_col is not None:
                needed.append(metric_col)


    needed = sorted(set(needed))

    ztab = _ensure_z_and_pct(ztab, needed)

    # compute z score per label, then convert to percentile within cohort
    label_z = {}
    for label, metric_list in spec.items():
        label_z[label] = _score_from_spec_z(ztab, player_row, metric_list)

    # percentile conversion
    out = {}
    for label, zval in label_z.items():
        if pd.isna(zval):
            out[label] = float("nan")
            continue
        # build series for percentile
        s = pd.Series(index=ztab.index, dtype=float)
        for idx in ztab.index:
            s.loc[idx] = _score_from_spec_z(ztab.loc[[idx]].assign(**{}), ztab.loc[idx], spec[label])  # safe
        # fallback if above is too slow or weird: rank player vs cohort by recomputing using ztab rows
        # improved approach:
        vals = []
        for idx in ztab.index:
            vals.append(_score_from_spec_z(ztab, ztab.loc[idx], spec[label]))
        pct = pd.Series(vals).rank(pct=True).iloc[int(np.argmin(np.abs(ztab.index.to_numpy() - player_row.name)))] if len(vals) == len(ztab) else np.nan
        # safer direct rank:
        vser = pd.Series(vals)
        out[label] = float(vser.rank(pct=True).iloc[vser.index[vser.index == vser.index][0]]) if len(vser) else float("nan")

    # The block above can be simplified; use a simpler robust method:
    # recompute percentiles properly
    out2 = {}
    for label, metric_list in spec.items():
        vals = []
        for idx in ztab.index:
            vals.append(_score_from_spec_z(ztab, ztab.loc[idx], metric_list))
        vser = pd.Series(vals)
        if player_row.name in ztab.index:
            player_val = _score_from_spec_z(ztab, player_row, metric_list)
            out2[label] = float(vser.rank(pct=True)[vser.index[vser.index == vser.index][0]]) if len(vser) else float("nan")
            # replace with clean percentile rank of player_val within vser
            out2[label] = float((vser.rank(pct=True) * 100.0).iloc[int(np.where(ztab.index == player_row.name)[0][0])]) if len(vser) else float("nan")
        else:
            out2[label] = float("nan")

    return out2

def _metric_goodness_pct(
    cohort_df: pd.DataFrame,
    player_row: pd.Series,
    metric_name: str,
    higher_is_better: bool,
    use_tier_z: bool = False,
) -> tuple[float, float, str]:

    """
    Returns (cdf_score_0_to_100, raw_player_value, resolved_column)

    cdf_score computed from robust z score (median, MAD) mapped through normal CDF.
    Minutes shrinkage is applied using player's minutes.
    """
    resolved = _resolve_metric_col(cohort_df, metric_name)
    if not resolved:
        return float("nan"), float("nan"), ""

    pv_raw = _to_num(player_row.get(resolved, float("nan")))
    if pv_raw != pv_raw:
        return float("nan"), float("nan"), resolved

    mins = _to_num(player_row.get("Minutes played", player_row.get("Minutes", float("nan"))))
    mins = float(mins) if mins == mins else 0.0

    ser = pd.to_numeric(cohort_df[resolved], errors="coerce")
    ser = ser.replace([np.inf, -np.inf], np.nan).dropna()
    if ser.empty:
        return float("nan"), pv_raw, resolved

    med = float(ser.median())
    mad = float((ser - med).abs().median())

    m0 = 900.0
    w = mins / (mins + m0) if (mins + m0) > 0 else 0.0
    x_shrunk = (w * pv_raw) + ((1.0 - w) * med)

    scale = 1.4826 * mad
    if not (scale > 0):
        sd = float(ser.std(ddof=0))
        scale = sd if sd > 0 else 1.0

    z = (x_shrunk - med) / scale

    if not higher_is_better:
        z = -z

    # Apply league tier coefficient AFTER z scoring (shrink towards 0)
    if use_tier_z:
        coef = _to_num(player_row.get("__tier_factor", float("nan")))

        if coef != coef:  # NaN fallback to league key mapping
            lk = player_row.get("__league", player_row.get("__league_key", None))
            kk = _norm_league_key_for_tier(lk)
            tier_label = LEAGUE_TIER_LABEL.get(kk)
            if tier_label:
                try:
                    coef = float(tier_strength_coef(tier_label))
                except Exception:
                    coef = 0.50
            else:
                coef = 0.50

        # Safety clamp. Tier factors should shrink z, not amplify it.
        coef = float(max(0.10, min(1.00, coef)))
        z = float(z) * coef

    # Now clip and map to CDF
    z = max(-3.0, min(3.0, float(z)))


    phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    score = 100.0 * phi

    return float(score), float(pv_raw), resolved


def _score_bundle(rules, min_kpis=3, cohort_df=None, target_row=None, use_tier_z: bool = False):

    met = []
    total_w = 0.0
    met_w = 0.0
    evaluated = 0

    if cohort_df is None or target_row is None or cohort_df.empty or target_row.empty:
        return float("nan"), met

    for metric_name, thr, hib, w in rules:
        g, pv, resolved = _metric_goodness_pct(
            cohort_df, target_row, metric_name, hib, use_tier_z=use_tier_z
        )

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

#-------- RTR reranking helpers --------
# Cosine similarity for 1D numpy arrays

def _cosine_1d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    da = float(np.linalg.norm(a))
    db = float(np.linalg.norm(b))
    if da <= 0.0 or db <= 0.0:
        return 0.0
    return float(np.dot(a, b) / (da * db))


def _trait_defs_for_role_group(role_group: str) -> dict:
    trait_defs = None
    try:
        trait_defs = GLOBAL_TRAITS
    except Exception:
        trait_defs = None

    if not trait_defs:
        try:
            trait_defs = TRAITS
        except Exception:
            trait_defs = {}

    if not trait_defs:
        return {}

    first_val = next(iter(trait_defs.values()))
    if isinstance(first_val, dict):
        return trait_defs.get(role_group, {}) or {}
    return trait_defs


def _compute_rtr_vectors(
    *,
    profile_key: str,
    cohort_df: pd.DataFrame,
    row: pd.Series,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str], list[str]]:
    """
    Returns
    role_vec, trait_vec, resp_vec plus the aligned label lists for debugging and reuse.
    All vectors are on 0 to 100 scale, consistent with your existing blocks.
    """

    role_group = role_group_from_profile(profile_key)

    role_defs = POSITION_ROLES.get(role_group, {}) or {}
    trait_defs_use = _trait_defs_for_role_group(role_group)
    resp_defs = RESPONSIBILITIES.get(profile_key, {}) or {}

    role_names = list(role_defs.keys())
    trait_names = list(trait_defs_use.keys())
    resp_names = list(resp_defs.keys()) if isinstance(resp_defs, dict) else list(resp_defs)

    role_vec = []
    for role_name in role_names:
        rules = role_defs.get(role_name, {})
        score, _detail = _score_bundle(rules, min_kpis=3, cohort_df=cohort_df, target_row=row)
        role_vec.append(0.0 if pd.isna(score) else float(score))

    trait_vec = []
    for trait_name in trait_names:
        rules = trait_defs_use.get(trait_name, {})
        score, _detail = _score_bundle(rules, min_kpis=3, cohort_df=cohort_df, target_row=row)
        trait_vec.append(0.0 if pd.isna(score) else float(score))

    resp_pct, _resp_breakdown = _compute_responsibility_scores(cohort_df, row, profile_key)
    resp_vec = []
    for resp_name in resp_names:
        v = resp_pct.get(resp_name, np.nan)
        resp_vec.append(0.0 if pd.isna(v) else float(v))

    return (
        np.asarray(role_vec, dtype=float),
        np.asarray(trait_vec, dtype=float),
        np.asarray(resp_vec, dtype=float),
        role_names,
        trait_names,
        resp_names,
    )


def rerank_candidates_by_rtr(
    *,
    profile_key: str,
    cohort_df: pd.DataFrame,
    target_row: pd.Series,
    candidates_df: pd.DataFrame,
    shortlist_n: int = 50,
    w_role: float = 0.34,
    w_trait: float = 0.33,
    w_resp: float = 0.33,
) -> pd.DataFrame:
    """
    candidates_df is expected to already be sorted by Stage 1 similarity.
    Adds RoleSim, TraitSim, RespSim, RTR_Sim and returns reranked df.
    """

    shortlist = candidates_df.head(int(shortlist_n)).copy()

    t_role, t_trait, t_resp, role_names, trait_names, resp_names = _compute_rtr_vectors(
        profile_key=profile_key, cohort_df=cohort_df, row=target_row
    )

    role_sims = []
    trait_sims = []
    resp_sims = []
    rtr_sims = []

    for _idx, r in shortlist.iterrows():
        c_role, c_trait, c_resp, _rn, _tn, _rsn = _compute_rtr_vectors(
            profile_key=profile_key, cohort_df=cohort_df, row=r
        )

        s_role = _cosine_1d(t_role, c_role)
        s_trait = _cosine_1d(t_trait, c_trait)
        s_resp = _cosine_1d(t_resp, c_resp)

        s_all = (w_role * s_role) + (w_trait * s_trait) + (w_resp * s_resp)

        role_sims.append(float(s_role))
        trait_sims.append(float(s_trait))
        resp_sims.append(float(s_resp))
        rtr_sims.append(float(s_all))

    shortlist["RoleSim"] = role_sims
    shortlist["TraitSim"] = trait_sims
    shortlist["RespSim"] = resp_sims
    shortlist["RTR_Sim"] = rtr_sims

    shortlist = shortlist.sort_values("RTR_Sim", ascending=False)
    return shortlist


def _percentile_of_value(series: pd.Series, v: float) -> float:
    s = series.dropna()
    if s.empty or pd.isna(v):
        return float("nan")
    return float((s <= float(v)).mean() * 100.0)

def _mb_parse_value_eur(x):
    if x is None:
        return np.nan
    try:
        if isinstance(x, float) and np.isnan(x):
            return np.nan
    except Exception:
        pass

    if isinstance(x, (int, float, np.integer, np.floating)):
        val = float(x)
        return val if np.isfinite(val) and val > 0 else np.nan

    s = str(x).strip().lower()
    if not s or s in {"nan", "none", "na", "n/a", "-"}:
        return np.nan

    s = (
        s.replace("€", "")
         .replace("eur", "")
         .replace("£", "")
         .replace("$", "")
         .replace("value", "")
         .replace("market", "")
         .strip()
    )
    s = s.replace("\u00a0", "").replace(" ", "")
    s = s.replace(",", ".") if _re.search(r"\d,\d{1,2}\s*[mk]", s) else s.replace(",", "")

    mult = 1.0
    if any(tok in s for tok in ["million", "mill", "mio", "mn"]) or s.endswith("m"):
        mult = 1_000_000.0
    elif any(tok in s for tok in ["thousand", "ths", "k"]) or s.endswith("k"):
        mult = 1_000.0

    m = _re.findall(r"\d+(?:\.\d+)?", s)
    if not m:
        return np.nan

    val = float(m[0]) * mult
    return val if np.isfinite(val) and val > 0 else np.nan


def _mb_parse_contract_dt(x):
    if x is None:
        return pd.NaT
    try:
        if isinstance(x, float) and np.isnan(x):
            return pd.NaT
    except Exception:
        pass
    s = str(x).strip()
    if not s or s.casefold() in {"nan", "none", "free", "unknown"}:
        return pd.NaT
    return pd.to_datetime(s, errors="coerce", dayfirst=True)


def _mb_winsorise_series(s, p=0.02):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() < 5:
        return s
    lo = s.quantile(p)
    hi = s.quantile(1.0 - p)
    return s.clip(lower=lo, upper=hi)


def _mb_zscore_series(s):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    mu = s.mean(skipna=True)
    sd = s.std(ddof=0, skipna=True)
    if sd is None or (isinstance(sd, float) and np.isnan(sd)) or sd == 0:
        return pd.Series(np.zeros(len(s)), index=s.index, dtype="float64")
    return pd.Series(np.divide(np.subtract(s.values, mu), sd), index=s.index)


def _mb_robust_zscore_series(s):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    med = s.median(skipna=True)
    mad = (s - med).abs().median(skipna=True)
    if pd.notna(mad) and float(mad) > 0:
        return ((s - med) / (1.4826 * float(mad))).clip(-3.5, 3.5)
    return _mb_zscore_series(s).clip(-3.5, 3.5)


def _mb_pick_col(df, candidates):
    if df is None or not hasattr(df, "columns"):
        return None
    exact = {str(c): c for c in df.columns}
    lower = {str(c).strip().casefold(): c for c in df.columns}
    for c in candidates:
        if c in exact:
            return exact[c]
        key = str(c).strip().casefold()
        if key in lower:
            return lower[key]
    return None


def _mb_position_group(pos_text: str) -> str:
    t = str(pos_text or "").strip().casefold()
    if "gk" in t:
        return "GK"
    if any(x in t for x in ["cb", "lcb", "rcb", "centre back", "center back"]):
        return "CB"
    if any(x in t for x in ["lb", "rb", "lwb", "rwb", "full back", "fullback", "wing back", "wingback"]):
        return "FB"
    if any(x in t for x in ["dmf", "ldmf", "rdmf", "dm", "dmc"]):
        return "DM"
    if any(x in t for x in ["cmf", "lcmf", "rcmf", "cm", "mc"]):
        return "CM"
    if any(x in t for x in ["amf", "lamf", "ramf", "am", "cam", "ss"]):
        return "AM"
    if any(x in t for x in ["lwf", "rwf", "wf"]):
        return "WF"
    if any(x in t for x in ["lw", "rw", "lm", "rm", "winger"]):
        return "WM"
    if any(x in t for x in ["cf", "st", "striker", "forward"]):
        return "CF"
    return "Other"


def _mb_series_or_default(df, candidates, default=np.nan):
    col = _mb_pick_col(df, candidates)
    if col is None:
        return pd.Series(default, index=df.index, dtype="float64"), None
    return pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan), col


def _mb_value_league_factor(df: pd.DataFrame) -> pd.Series:
    for c in ["_strength_factor", "__strength_factor", "_elo_factor", "__elo_factor", "__tier_factor", "_tier_factor"]:
        if c in df.columns:
            vals = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
            if vals.notna().any():
                return vals.fillna(vals.median(skipna=True)).clip(0.55, 1.65)

    if "Elo" in df.columns:
        elo = pd.to_numeric(df["Elo"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if elo.notna().any():
            med = elo.median(skipna=True)
            return (1.0 + ((elo.fillna(med) - med) / 1000.0)).clip(0.65, 1.55)

    tier_col = _mb_pick_col(df, ["__tier", "Tier", "tier"])
    if tier_col is not None:
        tier = pd.to_numeric(df[tier_col], errors="coerce")
        mapped = tier.map({1.0: 1.08, 2.0: 0.92, 3.0: 0.78, 4.0: 0.66, 5.0: 0.58})
        return mapped.fillna(0.90).clip(0.55, 1.25)

    return pd.Series(1.0, index=df.index, dtype="float64")


def _mb_build_perf_score(df, kpi_cols, metric_direction=None):
    """
    Builds a single performance score from KPI columns with robust scaling and minutes shrinkage.
    """
    use_cols = [c for c in kpi_cols if c in df.columns]
    if not use_cols:
        return pd.Series(np.nan, index=df.index), []

    work = df.copy()
    z_cols = []

    md_callable = callable(metric_direction)
    md_dict = metric_direction if isinstance(metric_direction, dict) else {}

    for c in use_cols:
        s = _mb_winsorise_series(work[c], p=0.02)

        invert = False
        if md_callable:
            invert = not bool(metric_direction(c))
        else:
            v = md_dict.get(c, "high")
            if isinstance(v, bool):
                invert = not v
            else:
                direction = str(v).lower()
                invert = direction in {"low", "lower", "negative", "neg"}

        if invert:
            s = pd.Series(np.negative(s.values), index=s.index)

        z = _mb_robust_zscore_series(s)
        work[c] = z
        z_cols.append(c)

    perf = work[z_cols].mean(axis=1)

    mins, _mins_col = _mb_series_or_default(work, ["Minutes played", "Minutes", "Min", "Mins"], default=np.nan)
    if mins.notna().any():
        mins_clean = mins.fillna(0.0).clip(lower=0.0)
        reliability = (mins_clean / (mins_clean + 900.0)).clip(0.0, 1.0)
        perf = (perf * reliability) + (perf.median(skipna=True) * (1.0 - reliability))

    return perf, z_cols


def _mb_standardise_matrix(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.asarray(X, dtype="float64")
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
    Xs = (X - mu) / sd
    Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)
    return Xs, mu, sd


def _mb_weighted_ridge_huber(X: np.ndarray, y: np.ndarray, base_weight: np.ndarray, ridge: float = 1.25) -> tuple[np.ndarray, np.ndarray, float]:
    X = np.asarray(X, dtype="float64")
    y = np.asarray(y, dtype="float64")
    w = np.asarray(base_weight, dtype="float64")
    w = np.where(np.isfinite(w) & (w > 0), w, 1.0)

    beta = np.zeros(X.shape[1], dtype="float64")
    eye = np.eye(X.shape[1], dtype="float64")
    eye[0, 0] = 0.0

    for _ in range(5):
        sw = np.sqrt(w)
        Xw = X * sw[:, None]
        yw = y * sw
        try:
            beta = np.linalg.solve(Xw.T @ Xw + ridge * eye, Xw.T @ yw)
        except np.linalg.LinAlgError:
            beta = np.linalg.lstsq(Xw.T @ Xw + ridge * eye, Xw.T @ yw, rcond=None)[0]

        resid = y - (X @ beta)
        med = np.nanmedian(resid)
        mad = np.nanmedian(np.abs(resid - med))
        scale = 1.4826 * mad if np.isfinite(mad) and mad > 0 else np.nanstd(resid)
        if not np.isfinite(scale) or scale <= 0:
            scale = 0.35

        huber = np.minimum(1.0, (1.65 * scale) / np.maximum(np.abs(resid), 1e-9))
        w = np.asarray(base_weight, dtype="float64") * huber

    pred = X @ beta
    resid = y - pred
    scale = np.nanmedian(np.abs(resid - np.nanmedian(resid))) * 1.4826
    if not np.isfinite(scale) or scale <= 0:
        scale = np.nanstd(resid)
    if not np.isfinite(scale) or scale <= 0:
        scale = 0.45

    return beta, pred, float(scale)


def _mb_apply_professional_value_model(df: pd.DataFrame, perf_col: str = "_perf_z") -> tuple[pd.DataFrame, dict]:
    """
    Builds a more stable fair value estimate from internal market values.

    It uses log market value as the target and blends a robust fitted model with
    positional cohort medians. The output is an estimate, not a transfer fee.
    """
    out = df.copy()
    info = {
        "status": "not_run",
        "rows_used": 0,
        "features_used": [],
        "model_weight": 0.0,
        "residual_scale": np.nan,
    }

    if out.empty:
        return out, info

    if "_mv_eur" not in out.columns:
        mv_col = _mb_pick_col(out, ["Market value", "Market Value", "MV", "Transfermarkt value", "Transfermarkt Value"])
        out["_mv_eur"] = out[mv_col].apply(_mb_parse_value_eur) if mv_col else np.nan
    else:
        out["_mv_eur"] = pd.to_numeric(out["_mv_eur"], errors="coerce")

    age, age_col = _mb_series_or_default(out, ["Age", "Player age"], default=np.nan)
    mins, mins_col = _mb_series_or_default(out, ["Minutes played", "Minutes", "Min", "Mins"], default=np.nan)
    perf = pd.to_numeric(out.get(perf_col, pd.Series(np.nan, index=out.index)), errors="coerce").replace([np.inf, -np.inf], np.nan)

    if perf.notna().sum() < 5:
        perf = pd.Series(0.0, index=out.index, dtype="float64")
    else:
        perf = perf.fillna(perf.median(skipna=True))

    pos_col = _mb_pick_col(out, ["Position", "Primary position", "Primary Position", "Pos"])
    if pos_col is not None:
        out["_mb_position_group"] = out[pos_col].astype(str).map(_mb_position_group)
    else:
        out["_mb_position_group"] = "Other"

    if "_contract_dt" not in out.columns:
        contract_col = _mb_pick_col(out, ["Contract expires", "Contract expiry", "Contract Expiry", "Contract until", "Contract Until"])
        out["_contract_dt"] = out[contract_col].apply(_mb_parse_contract_dt) if contract_col else pd.NaT

    today = pd.Timestamp.today().normalize()
    contract_days = pd.to_datetime(out["_contract_dt"], errors="coerce").sub(today).dt.days
    contract_months = pd.Series(np.divide(contract_days.values.astype(float), 30.0), index=out.index)
    contract_years = (contract_months / 12.0).clip(-0.5, 5.0)

    league_factor = _mb_value_league_factor(out)
    mins_clean = mins.fillna(0.0).clip(lower=0.0)
    log_mins = np.log1p(mins_clean).replace([np.inf, -np.inf], np.nan)

    age_clean = age.copy()
    if age_clean.notna().any():
        age_clean = age_clean.fillna(age_clean.median(skipna=True)).clip(15.0, 40.0)
    else:
        age_clean = pd.Series(25.0, index=out.index, dtype="float64")

    age_peak_distance = (age_clean - 24.0).abs()
    age_squared = (age_clean - 24.0) ** 2
    perf_age = perf * (1.0 / (1.0 + age_peak_distance))
    perf_mins = perf * (mins_clean / (mins_clean + 900.0)).fillna(0.0)

    numeric_features = pd.DataFrame(
        {
            "performance": perf,
            "age": age_clean,
            "age_squared": age_squared,
            "distance_from_peak_age": age_peak_distance,
            "log_minutes": log_mins,
            "contract_years": contract_years.fillna(contract_years.median(skipna=True) if contract_years.notna().any() else 1.5),
            "league_strength": league_factor,
            "performance_age_interaction": perf_age,
            "performance_minutes_interaction": perf_mins,
        },
        index=out.index,
    )

    numeric_features = numeric_features.replace([np.inf, -np.inf], np.nan)
    for c in numeric_features.columns:
        med = numeric_features[c].median(skipna=True)
        numeric_features[c] = numeric_features[c].fillna(med if np.isfinite(med) else 0.0)

    pos_dummies = pd.get_dummies(out["_mb_position_group"], prefix="pos", dtype=float)
    feature_frame = pd.concat([numeric_features, pos_dummies], axis=1)
    feature_names = feature_frame.columns.tolist()

    y = pd.to_numeric(out["_mv_eur"], errors="coerce")
    y = y.where((y > 0) & np.isfinite(y))
    log_y = np.log(y)

    valid = log_y.notna() & feature_frame.notna().all(axis=1)
    valid = valid & y.between(20_000, 250_000_000, inclusive="both")

    if int(valid.sum()) < 18:
        global_log = float(np.nanmedian(log_y[log_y.notna()])) if log_y.notna().any() else np.log(250_000.0)
        pos_log = out.groupby("_mb_position_group")["_mv_eur"].transform(lambda s: np.log(pd.to_numeric(s, errors="coerce").dropna()).median())
        baseline_log = pos_log.fillna(global_log)
        out["_fair_log_mv"] = baseline_log
        out["_fair_mv_eur"] = np.exp(out["_fair_log_mv"])
        out["_fair_low_eur"] = out["_fair_mv_eur"] * 0.70
        out["_fair_high_eur"] = out["_fair_mv_eur"] * 1.30
        out["_valuation_confidence"] = "Low"
        out["_valuation_method"] = "positional median fallback"
        info.update({"status": "fallback", "rows_used": int(valid.sum()), "model_weight": 0.0})
        return out, info

    X_raw = feature_frame.to_numpy(dtype="float64")
    Xs, _mu, _sd = _mb_standardise_matrix(X_raw)
    X = np.column_stack([np.ones(len(out)), Xs])

    train_mask = valid.values
    train_y = log_y.values[train_mask]

    train_mins = mins_clean.values[train_mask]
    minutes_weight = 0.35 + (0.65 * (train_mins / (train_mins + 900.0)))
    minutes_weight = np.where(np.isfinite(minutes_weight), minutes_weight, 0.50)

    beta, train_pred, scale = _mb_weighted_ridge_huber(X[train_mask], train_y, minutes_weight, ridge=1.25)
    pred_log_model = pd.Series(X @ beta, index=out.index)

    global_log = float(np.nanmedian(log_y[valid]))
    pos_log_map = out.loc[valid].groupby("_mb_position_group")["_mv_eur"].median().map(np.log)
    baseline_log = out["_mb_position_group"].map(pos_log_map).fillna(global_log).astype(float)

    n_train = int(valid.sum())
    model_weight = float(np.clip((n_train - 15.0) / 75.0, 0.35, 0.88))
    reliability = (mins_clean / (mins_clean + 900.0)).clip(0.0, 1.0).fillna(0.0)
    row_weight = (model_weight * (0.45 + 0.55 * reliability)).clip(0.20, 0.90)

    fair_log = (row_weight * pred_log_model) + ((1.0 - row_weight) * baseline_log)
    low_cap = float(np.nanpercentile(y[valid], 2.0))
    high_cap = float(np.nanpercentile(y[valid], 98.0))
    if not np.isfinite(low_cap) or low_cap <= 0:
        low_cap = 20_000.0
    if not np.isfinite(high_cap) or high_cap <= low_cap:
        high_cap = max(low_cap * 3.0, float(np.nanmax(y[valid])))

    fair_mv = np.exp(fair_log).clip(low_cap * 0.60, high_cap * 1.40)

    uncertainty = (0.42 + (1.0 - reliability) * 0.30 + max(0.0, 0.55 - model_weight) * 0.40).clip(0.30, 0.85)
    out["_fair_log_mv"] = np.log(fair_mv)
    out["_fair_mv_eur"] = fair_mv
    out["_fair_low_eur"] = np.exp(out["_fair_log_mv"] - uncertainty).clip(lower=10_000.0)
    out["_fair_high_eur"] = np.exp(out["_fair_log_mv"] + uncertainty).clip(upper=high_cap * 1.80)
    out["_valuation_confidence_score"] = (100.0 * row_weight).clip(0.0, 100.0)
    out["_valuation_confidence"] = pd.cut(
        out["_valuation_confidence_score"],
        bins=[-0.1, 40.0, 60.0, 78.0, 100.1],
        labels=["Low", "Medium", "High", "Very high"],
    ).astype(str)
    out["_valuation_method"] = "robust log value model"

    info.update(
        {
            "status": "modelled",
            "rows_used": n_train,
            "features_used": feature_names,
            "model_weight": model_weight,
            "residual_scale": scale,
        }
    )
    return out, info


def _mb_fit_expected_value(log_mv, perf, age=None):
    y = pd.to_numeric(log_mv, errors="coerce")
    x1 = pd.to_numeric(perf, errors="coerce").fillna(0.0)

    temp = pd.DataFrame({"_mv_eur": np.exp(y), "_perf_z": x1}, index=y.index)
    if age is not None:
        temp["Age"] = pd.to_numeric(age, errors="coerce")

    modelled, _info = _mb_apply_professional_value_model(temp, perf_col="_perf_z")
    if "_fair_log_mv" in modelled.columns:
        return pd.Series(modelled["_fair_log_mv"].values, index=y.index)

    return pd.Series(np.nan, index=y.index)


def _as_float(x):
    try:
        return float(_to_num(x))
    except Exception:
        try:
            return float(x)
        except Exception:
            return float("nan")

def _pick_minutes(row: "pd.Series") -> float:
    for c in ["Minutes", "Minutes played", "Min", "mins", "Mins"]:
        if c in row:
            v = _as_float(row.get(c))
            if pd.notna(v):
                return v
    return float("nan")

def _confidence_from_minutes(mins: float) -> str:
    if pd.isna(mins):
        return "Unknown sample"
    if mins < 450:
        return "Low sample"
    if mins < 900:
        return "Medium sample"
    if mins < 1800:
        return "High sample"
    return "Very high sample"

def _infer_profile_key_from_position_text(txt: str) -> str:
    raw = (txt or "").strip().upper()
    try:
        known_profiles = set(RESPONSIBILITIES.keys())
    except Exception:
        known_profiles = set()

    if raw in known_profiles:
        return raw

    try:
        return _infer_profile_key(txt)
    except Exception:
        # last fallback for weird strings
        return (txt or "").strip()


def _detail_to_gap_rows(detail_list, *, area: str, label: str):
    """
    detail_list is what _score_bundle returns per role/trait.
    Expected keys per row in detail:
        metric / metric_col, goodness_pct, threshold, hit, player_value
    """
    rows = []
    if not detail_list:
        return rows

    for d in detail_list:
        metric = d.get("metric") or d.get("metric_col") or d.get("kpi") or d.get("name") or ""
        goodness = _as_float(d.get("goodness_pct", d.get("pct")))
        thr = _as_float(d.get("threshold", d.get("min_pct")))
        hit = bool(d.get("hit", False))

        if pd.isna(goodness) or pd.isna(thr):
            continue

        gap = max(0.0, thr - goodness)
        if hit:
            gap = 0.0

        if gap >= 20:
            sev = "High"
        elif gap >= 10:
            sev = "Medium"
        elif gap > 0:
            sev = "Low"
        else:
            sev = "Hit"

        rows.append(
            {
                "Area": area,
                "Profile": label,
                "Metric": str(metric),
                "Player pct": round(goodness, 1),
                "Threshold": round(thr, 1),
                "Gap": round(gap, 1),
                "Severity": sev,
                "Hit": hit,
            }
        )
    return rows

def _coverage_and_avg_gap(rows):
    if not rows:
        return 0.0, float("nan"), 0, 0
    total = len(rows)
    hits = sum(1 for r in rows if r.get("Hit"))
    misses = total - hits
    miss_gaps = [r["Gap"] for r in rows if (not r.get("Hit")) and pd.notna(r.get("Gap"))]
    avg_gap = float(pd.Series(miss_gaps).mean()) if miss_gaps else 0.0
    coverage = hits / total if total else 0.0
    return coverage, avg_gap, hits, misses


def _score_roles_traits_responsibilities_global(profile_key, cohort_df, target_row):
    """Global version that requires explicit df arguments."""
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
        try:
            trait_defs = TRAITS
        except:
            trait_defs = {}

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
    # Keep this import local so the Search tab cannot crash if this helper is
    # loaded before the private profile helper is present in module globals.
    from helpers.profile_defs import _compute_responsibility_scores as _compute_resp_scores

    resp_pct, resp_breakdown = _compute_resp_scores(
        cohort_df=cohort_df,
        player_row=target_row,
        profile_key=profile_key,
    )

    return role_scores, role_detail, trait_scores, trait_detail, resp_pct, resp_breakdown

def calculate_search_tab_gaps(
    cohort_df,
    target_row,
    position_text,
    top_n: int = 8,
    resp_floor: float = 50.0,
):
    """
    Pure compute for the Search tab 'Gaps and risk flags' block.
    Returns a dict payload (or None if we cannot compute).
    Relies on existing helpers already in this module:
      _infer_profile_key_from_position_text
      RESPONSIBILITIES
      _score_roles_traits_responsibilities
      _pick_minutes
      _confidence_from_minutes
      _detail_to_gap_rows
      _coverage_and_avg_gap
      _as_float
    """

    if cohort_df is None or getattr(cohort_df, "empty", True):
        return None
    if target_row is None or len(target_row) == 0:
        return None

    profile_key = _infer_profile_key_from_position_text(position_text)
    if not profile_key:
        return None

    try:
        if profile_key not in RESPONSIBILITIES:
            return None
    except Exception:
        pass

    # Use the global scorer and pass the dataframes explicitly
    role_scores, role_detail, trait_scores, trait_detail, resp_pct, resp_breakdown = _score_roles_traits_responsibilities_global(profile_key, cohort_df, target_row)

    mins = _pick_minutes(target_row)
    conf = _confidence_from_minutes(mins)

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

    combined_misses = [r for r in (role_rows + trait_rows) if not r.get("Hit")]
    combined_misses = sorted(
        combined_misses,
        key=lambda r: (r.get("Gap") if pd.notna(r.get("Gap")) else -1),
        reverse=True,
    )[:top_n]
    df_gaps = pd.DataFrame(combined_misses)

    low_resps = []
    if isinstance(resp_pct, dict) and resp_pct:
        for name, pct in sorted(resp_pct.items(), key=lambda x: x[1]):
            p = _as_float(pct)
            if pd.isna(p):
                continue
            if p < resp_floor:
                low_resps.append({
                    "Responsibility": name,
                    "Pct": round(p, 1),
                    "Gap vs floor": round(resp_floor - p, 1),
                })
        low_resps = low_resps[:3]
    df_resp = pd.DataFrame(low_resps)

    major_gaps = 0
    for r in combined_misses:
        try:
            if float(r.get("Gap", 0.0)) >= 15.0:
                major_gaps += 1
        except Exception:
            continue

    # ... inside calculate_search_tab_gaps ...

    # --- 1. Construct the Narrative Summary (Better Words) ---
    lines = []
    
    # Context & Reliability
    rel_label = "High" if mins > 900 else ("Medium" if mins > 450 else "Low")
    lines.append(f"**Statistical Reliability:** {rel_label} ({int(mins)} mins analyzed).")

    # Profile Alignment (The "Fit")
    if best_role:
        role_cov_pct = int((role_hits / (role_hits + role_misses)) * 100) if (role_hits + role_misses) > 0 else 0
        lines.append(f"**Profile Alignment:** Best statistical fit is **{best_role}** (Score: {best_role_score:.0f}), meeting {role_cov_pct}% of key metric thresholds.")
    
    # The Risks (Gaps & Responsibilities)
    risk_flags = []
    
    if not df_gaps.empty:
        top_gaps = df_gaps.head(3)
        gap_strs = [f"{row.get('Metric','')} (-{row.get('Gap','0'):.0f}%)" for _, row in top_gaps.iterrows()]
        risk_flags.append(f"**Major Deficits:** Significant underperformance in {', '.join(gap_strs)} compared to the target threshold.")

    if not df_resp.empty:
        low_resps = [f"{row.get('Responsibility','')}" for _, row in df_resp.iterrows()]
        risk_flags.append(f"**Baseline Concerns:** Fails to meet the minimum standard (50th percentile) for {', '.join(low_resps)}.")

    if risk_flags:
        lines.extend(risk_flags)
    else:
        lines.append("No critical statistical red flags detected within the current profile parameters.")

    weakness_summary = "\n\n".join([l for l in lines if l])
    
    # ... return dictionary including 'weakness_summary', 'major_gaps', etc ...

    return {
        "profile_key": profile_key,
        "mins": mins,
        "confidence": conf,
        "best_role": best_role,
        "best_role_score": best_role_score,
        "best_trait": best_trait,
        "best_trait_score": best_trait_score,
        "role_cov": role_cov,
        "role_avg_gap": role_avg_gap,
        "role_hits": role_hits,
        "role_misses": role_misses,
        "trait_cov": trait_cov,
        "trait_avg_gap": trait_avg_gap,
        "trait_hits": trait_hits,
        "trait_misses": trait_misses,
        "major_gaps": major_gaps,
        "df_gaps": df_gaps,
        "df_resp": df_resp,
        "resp_pct": resp_pct,
        "resp_breakdown": resp_breakdown,
        "weakness_summary": weakness_summary,
        "resp_floor": resp_floor,
        "top_n": top_n,
    }

#--------------------------------------------------------------------------------
# --- PREVIOUS SEASON HELPERS ---
#--------------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_prev_season_master(prev_root: Path) -> pd.DataFrame:
    """Loads 24/25 data for Belgium, France, Netherlands."""
    frames = []
    # Adjust folder names if your actual folders are named differently (e.g., "Belgium 24 25")
    # We look for any folder inside the previous season root
    if prev_root.exists():
        for nation_folder in prev_root.iterdir():
            if nation_folder.is_dir():
                frames += _collect_country_frames(str(nation_folder), nation_folder.name, [1, 2])
    
    if not frames:
        return pd.DataFrame()
    
    df = pd.concat(frames, ignore_index=True, sort=False)
    # Standard cleaning
    if "Minutes played" in df.columns:
        df["_mins"] = pd.to_numeric(df["Minutes played"].map(parse_minutes), errors="coerce")
    return df

def _load_reference_players_default() -> pd.DataFrame:
    """
    Default Reference players loader for the search tab.
    Uses the resilient CSV reader so weird encodings do not crash.
    """
    if not os.path.exists(REFERENCE_PLAYERS_PATH):
        return pd.DataFrame()

    try:
        # use the robust loader you already defined above
        df = read_csv_resilient(REFERENCE_PLAYERS_PATH)
        df = df.astype(str).fillna("")
        return df
    except Exception as e:
        st.warning(f"Failed to read reference players CSV: {e}")
        return pd.DataFrame()

def _metric_phase(name: str, is_gk: bool) -> str:
    n = str(name or "").casefold()

    if any(k in n for k in ["corner", "free kick", "freekick", "set piece", "set-piece", "throw in", "throw-in", "penalty"]):
        return "Set pieces"

    if is_gk and any(k in n for k in ["save", "clean sheet", "conceded", "xg against", "shots against", "prevented"]):
        return "Goalkeeping"

    if any(k in n for k in ["tackle", "interception", "defensive duel", "aerial duel", "clearance", "block", "challenge", "recoveries"]):
        return "Defending"

    if any(k in n for k in ["pass", "possession", "progressive", "build-up", "build up", "carry", "touches", "deep completion"]):
        return "Possession"

    if any(k in n for k in ["shot", "xg", "xa", "goal", "assist", "key pass", "dribble", "cross", "touches in box", "accelerations"]):
        return "Attacking"

    return "Other"


def _get_metric_value(row: pd.Series, metric_names: list[str]) -> float:
    """
    Try a list of possible metric column names on the row, return first valid float or NaN.
    This keeps things robust if Wyscout headings vary slightly between leagues.
    """
    for name in metric_names:
        if name in row.index:
            try:
                v = float(row[name])
                if not math.isnan(v):
                    return v
            except Exception:
                continue
    return float("nan")


def _infer_archetypes_for_row(
    pos_text: str,
    row: pd.Series,
    league_pcts: dict[str, float],
) -> list[tuple[str, str]]:
    """
    Return a list of (archetype_name, explanation) based on basic stat rules.
    You can tune thresholds and metric name lists to your taste.
    """

    pos_u = (pos_text or "").upper()
    arcs: list[tuple[str, str]] = []

    # Convenience shortcuts
    val = lambda names: _get_metric_value(row, names)

    # Winger archetypes
    if any(tag in pos_u for tag in ["RW", "LW", "WINGER", "INVERTED WINGER"]):
        dribbles_p90 = val(["Dribbles per 90", "Dribbles (per 90)"])
        xg_p90 = val(["xG per 90", "xG (per 90)", "xG/90"])
        xa_p90 = val(["xA per 90", "xA (per 90)", "xA/90"])
        prog_runs_p90 = val(["Progressive runs per 90", "Progressive runs (per 90)"])
        shots_p90 = val(["Shots per 90", "Shots (per 90)"])
        touches_box_p90 = val(["Touches in box per 90", "Touches in box (per 90)"])

        # End product winger example you gave
        if (
            not math.isnan(dribbles_p90)
            and not math.isnan(xg_p90)
            and not math.isnan(xa_p90)
            and dribbles_p90 >= 7
            and xg_p90 >= 0.25
            and xa_p90 >= 0.25
        ):
            arcs.append(
                (
                    "End product winger",
                    "High volume one v one profile who also generates both shot and assist threat in the box.",
                )
            )
        # Ball carrying winger
        elif (
            not math.isnan(dribbles_p90)
            and dribbles_p90 >= 7
            and (math.isnan(xg_p90) or xg_p90 < 0.20)
            and (math.isnan(xa_p90) or xa_p90 < 0.20)
        ):
            arcs.append(
                (
                    "Ball carrying winger",
                    "Carries the ball a lot to advance play, with end product still catching up.",
                )
            )
        # Box arriving winger
        elif (
            not math.isnan(shots_p90)
            and not math.isnan(touches_box_p90)
            and shots_p90 >= 2.5
            and touches_box_p90 >= 4.0
        ):
            arcs.append(
                (
                    "Box arriving winger",
                    "Arrives into the area frequently and gets shots off from dangerous positions.",
                )
            )

    # Centre back archetypes
    if any(tag in pos_u for tag in ["CB", "CENTRE BACK", "CENTER BACK", "RCB", "LCB"]):
        prog_passes_p90 = val(["Progressive passes per 90", "Progressive passes (per 90)"])
        def_duels_p90 = val(["Defensive duels per 90", "Defensive duels (per 90)"])
        def_duels_win = val(["Defensive duels won, %", "Defensive duels won %"])
        aerial_duels_p90 = val(["Aerial duels per 90", "Aerial duels (per 90)"])
        aerial_win = val(["Aerial duels won, %", "Aerial duels won %"])

        if (
            not math.isnan(prog_passes_p90)
            and not math.isnan(def_duels_win)
            and prog_passes_p90 >= 4.0
            and def_duels_win >= 50.0
        ):
            arcs.append(
                (
                    "Ball playing centre back",
                    "Comfortable breaking lines with forward passing while still defending duels at a solid level.",
                )
            )
        elif (
            not math.isnan(def_duels_p90)
            and not math.isnan(def_duels_win)
            and def_duels_p90 >= 8.0
            and def_duels_win >= 55.0
        ):
            arcs.append(
                (
                    "Duel dominant stopper",
                    "Aggressive central defender who does a lot of work in direct duels and looks stable in win rate.",
                )
            )
        elif (
            not math.isnan(aerial_duels_p90)
            and not math.isnan(aerial_win)
            and aerial_duels_p90 >= 5.0
            and aerial_win >= 60.0
        ):
            arcs.append(
                (
                    "Aerial specialist centre back",
                    "Profiles as a strong presence in the air in both boxes and in direct long ball situations.",
                )
            )

    # Defensive midfielder archetypes
    if any(tag in pos_u for tag in ["DEFENSIVE MIDFIELDER", "DM", "HOLDING MIDFIELDER", "NUMBER 6", "NO 6"]):
        def_duels_p90 = val(["Defensive duels per 90", "Defensive duels (per 90)"])
        def_duels_win = val(["Defensive duels won, %", "Defensive duels won %"])
        prog_passes_p90 = val(["Progressive passes per 90", "Progressive passes (per 90)"])
        passes_final_third_p90 = val(["Passes to final third per 90", "Passes to final third (per 90)"])

        if (
            not math.isnan(def_duels_p90)
            and not math.isnan(def_duels_win)
            and def_duels_p90 >= 8.0
            and def_duels_win >= 50.0
        ):
            arcs.append(
                (
                    "Ball winning six",
                    "Screening type midfielder who gets through a lot of defensive work and wins a good share of duels.",
                )
            )
        elif (
            not math.isnan(prog_passes_p90)
            and not math.isnan(passes_final_third_p90)
            and prog_passes_p90 >= 5.0
            and passes_final_third_p90 >= 6.0
        ):
            arcs.append(
                (
                    "Playmaking six",
                    "First pass playmaker who regularly progresses the ball and finds the final third.",
                )
            )

    # Central midfielder archetypes
    if any(tag in pos_u for tag in ["CENTRAL MIDFIELDER", "CM", "BOX TO BOX", "NUMBER 8", "NO 8"]):
        def_duels_p90 = val(["Defensive duels per 90", "Defensive duels (per 90)"])
        def_duels_win = val(["Defensive duels won, %", "Defensive duels won %"])
        prog_runs_p90 = val(["Progressive runs per 90", "Progressive runs (per 90)"])
        passes_final_third_p90 = val(["Passes to final third per 90", "Passes to final third (per 90)"])
        xg_p90 = val(["xG per 90", "xG (per 90)", "xG/90"])
        xa_p90 = val(["xA per 90", "xA (per 90)", "xA/90"])
        touches_box_p90 = val(["Touches in box per 90", "Touches in box (per 90)"])

        if (
            not math.isnan(def_duels_p90)
            and not math.isnan(def_duels_win)
            and not math.isnan(prog_runs_p90)
            and def_duels_p90 >= 7.0
            and def_duels_win >= 50.0
            and prog_runs_p90 >= 1.0
        ):
            arcs.append(
                (
                    "Box to box runner",
                    "Midfielder who covers big spaces both pressing and carrying the ball up the pitch.",
                )
            )
        elif (
            not math.isnan(passes_final_third_p90)
            and (not math.isnan(xa_p90) and xa_p90 >= 0.15)
        ):
            arcs.append(
                (
                    "Link play eight",
                    "Connector who links thirds with regular forward passing and some creative output.",
                )
            )
        elif (
            not math.isnan(xg_p90)
            and not math.isnan(touches_box_p90)
            and xg_p90 >= 0.25
            and touches_box_p90 >= 2.0
        ):
            arcs.append(
                (
                    "Box arriving eight",
                    "Central midfielder who attacks the area and offers goal threat from deeper starting positions.",
                )
            )

    # Attacking midfielder archetypes
    if any(tag in pos_u for tag in ["ATTACKING MIDFIELDER", "NUMBER 10", "NO 10", "BOX ENTRY"]):
        xg_p90 = val(["xG per 90", "xG (per 90)", "xG/90"])
        xa_p90 = val(["xA per 90", "xA (per 90)", "xA/90"])
        key_passes_p90 = val(["Key passes per 90", "Key passes (per 90)"])
        touches_box_p90 = val(["Touches in box per 90", "Touches in box (per 90)"])

        if (
            not math.isnan(xa_p90)
            and not math.isnan(key_passes_p90)
            and xa_p90 >= 0.25
            and key_passes_p90 >= 1.5
        ):
            arcs.append(
                (
                    "Chance creating ten",
                    "Attacking midfielder who consistently creates shots for others from central pockets.",
                )
            )
        elif (
            not math.isnan(xg_p90)
            and not math.isnan(touches_box_p90)
            and xg_p90 >= 0.30
            and touches_box_p90 >= 3.0
        ):
            arcs.append(
                (
                    "Box arriving ten",
                    "More goal focused ten who arrives into the area and finishes moves.",
                )
            )

    # Centre forward archetypes
    if any(tag in pos_u for tag in ["STRIKER", "CENTRE FORWARD", "CF", "TARGET MAN", "NUMBER 9", "NO 9"]):
        shots_p90 = val(["Shots per 90", "Shots (per 90)"])
        xg_p90 = val(["xG per 90", "xG (per 90)", "xG/90"])
        xa_p90 = val(["xA per 90", "xA (per 90)", "xA/90"])
        touches_box_p90 = val(["Touches in box per 90", "Touches in box (per 90)"])
        aerial_duels_p90 = val(["Aerial duels per 90", "Aerial duels (per 90)"])
        aerial_win = val(["Aerial duels won, %", "Aerial duels won %"])

        if (
            not math.isnan(shots_p90)
            and not math.isnan(xg_p90)
            and not math.isnan(touches_box_p90)
            and shots_p90 >= 3.0
            and xg_p90 >= 0.4
            and touches_box_p90 >= 5.0
        ):
            arcs.append(
                (
                    "Penalty box nine",
                    "High volume finisher who lives in the box and generates strong expected goal output.",
                )
            )
        elif (
            not math.isnan(aerial_duels_p90)
            and not math.isnan(aerial_win)
            and aerial_duels_p90 >= 5.0
            and aerial_win >= 55.0
        ):
            arcs.append(
                (
                    "Target forward",
                    "More reference style forward with regular involvement in aerial contests and back to goal play.",
                )
            )
        elif (
            not math.isnan(xa_p90)
            and xa_p90 >= 0.20
        ):
            arcs.append(
                (
                    "Link play forward",
                    "Forward who connects play and sets others up rather than only finishing.",
                )
            )

    return arcs

def _sniff_delimiter(sample: bytes) -> str:
    try:
        sample_txt = sample.decode("utf-8", errors="ignore")
        dialect = csv.Sniffer().sniff(sample_txt, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        text = sample.decode("utf-8", errors="ignore")
        counts = {sep: text.count(sep) for sep in [",", ";", "\t", "|"]}
        return max(counts, key=counts.get) if counts else ","


def read_csv_resilient(path: str) -> pd.DataFrame:
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
    except Exception as e:
        raise RuntimeError(f"Cannot open {path}: {e}")

    delim = _sniff_delimiter(head)

    last_err = None
    for enc in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(
                path,
                sep=delim,
                encoding=enc,
                engine="python",
                dtype=str,
                keep_default_na=False,
            )
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("Unknown CSV error")


def read_xlsx_resilient(path: str) -> list[pd.DataFrame]:
    out: list[pd.DataFrame] = []
    try:
        xls = pd.ExcelFile(path)
        for sheet in xls.sheet_names:
            try:
                df_ = xls.parse(sheet_name=sheet, dtype=str)
                out.append(df_)
            except Exception as e:
                st.warning(f"Failed to read sheet '{sheet}' from {os.path.basename(path)}: {e}")
    except Exception as e:
        st.warning(f"Failed to open {os.path.basename(path)}: {e}")
    return out

def _build_global_wyscout_master(nation_dirs: list[str]) -> pd.DataFrame:
    """
    Concatenate all tiers from all nation folders.
    Uses the same _collect_country_frames logic so it auto-picks up new files.
    """
    frames: list[pd.DataFrame] = []
    for folder in nation_dirs:
        prefix = os.path.basename(folder)
        # pull tiers 1–3 for each country; if a tier doesn't exist it is just skipped
        frames += _collect_country_frames(folder, prefix, [1, 2, 3])

    if not frames:
        return pd.DataFrame()

    df_all = pd.concat(frames, ignore_index=True, sort=False)

    # Canonical key columns
    COL_PLAYER = next((c for c in df_all.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM   = next((c for c in df_all.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")
    COL_POS    = next((c for c in df_all.columns if c.lower() in {"position", "pos"}), "Position")

    # Drop obvious dupes (same player/team/pos/tier/source)
    subset_cols = [c for c in [COL_PLAYER, COL_TEAM, COL_POS, "__tier", "__source_file"] if c in df_all.columns]
    if subset_cols:
        df_all = df_all.drop_duplicates(subset=subset_cols).reset_index(drop=True)

    # Ensure league key
    if "__league_key" not in df_all.columns:
        def _mk_key(r):
            nation = str(r.get("__nation", "")).strip()
            league = str(r.get("League", "") or r.get("Competition", "") or "").strip()
            tier   = str(r.get("__tier", "")).strip()
            parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
            return " · ".join(parts) if parts else "Unknown"
        df_all["__league_key"] = df_all.apply(_mk_key, axis=1)

    return df_all


def _percentile_rank(series: pd.Series, value: float) -> float:
    """
    Simple percentile rank: % of cohort <= value.
    Returns NaN if we cannot compute.
    """
    try:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if not len(s):
            return float("nan")
        v = float(value)
        return float((s <= v).mean() * 100.0)
    except Exception:
        return float("nan")


def _pct_bar_html(pct: float) -> str:
    """
    Gradient-style bar (0–100) similar to the full profile tables.
    """
    try:
        val = max(0.0, min(100.0, float(pct)))
    except Exception:
        val = 0.0
    hue = int(120 * (val / 100.0))  # red→green
    return f"""
    <div style="display:flex;align-items:center;gap:8px;min-width:140px;">
      <div style="flex:1;height:8px;border-radius:999px;
                  background:linear-gradient(90deg,hsl({hue},70%,45%) {val:.1f}%, 
                                             rgba(255,255,255,0.10) {val:.1f}%);">
      </div>
      <div style="min-width:46px;text-align:right;font-size:11px;opacity:.9;color:#f5f5f5;">
        {val:.1f}%
      </div>
    </div>
    """



def parse_market_value(text: str) -> float:
    if not text:
        return math.nan
    s = str(text).lower().replace("€", "").replace("eur", "").strip()
    mult = 1.0
    if "m" in s:
        mult = 1_000_000.0
        s = s.replace("m", "")
    elif "k" in s:
        mult = 1_000.0
        s = s.replace("k", "")
    s = s.replace(",", "").strip()
    try:
        return float(s) * mult
    except Exception:
        parts = s.split()
        if len(parts) >= 2 and parts[1].startswith("million"):
            try:
                return float(parts[0]) * 1_000_000.0
            except Exception:
                return math.nan
        return math.nan


def parse_minutes(text: str) -> float:
    try:
        return float(str(text).replace(",", "").strip())
    except Exception:
        return math.nan

def _parse_height_m(x):
    if pd.isna(x):
        return math.nan
    s = str(x).lower().replace(",", ".")
    m = _re.search(r"(\d+(\.\d+)?)\s*m", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return math.nan
    m = _re.search(r"(\d+)\s*cm", s)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except Exception:
            return math.nan
    try:
        v = float(s)
        if 0.5 <= v <= 2.7:
            return v
        if 130 <= v <= 230:
            return v / 100.0
        return math.nan
    except Exception:
        return math.nan

def _restrict_to_three_nations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only rows from Belgium, Netherlands and France
    based on the '__nation' stamp created in _collect_country_frames.
    """
    if "__nation" not in df.columns:
        return df

    nation_key = df["__nation"].astype(str).str.strip().str.casefold()
    mask = nation_key.isin(THREE_NATION_FILTER).fillna(False).astype(bool)
    return df.loc[mask].copy()

def _find_metric_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """
    Try to find a column in df matching any of the candidate names.
    First use exact case-insensitive match, then substring match.
    """
    cols = list(df.columns)
    lower_map = {c.lower(): c for c in cols}

    # exact match
    for name in candidates:
        key = name.lower()
        if key in lower_map:
            return lower_map[key]

    # fallback substring
    for name in candidates:
        key = name.lower()
        for c in cols:
            if key in c.lower():
                return c

    return None

def _collect_country_frames(folder: str, country_label: str, tiers: list[int]) -> list[pd.DataFrame]:
    """
    Load Tier CSV/XLSX files for one nation folder and stamp: __nation, __tier, __league_key.
    country_label is the nation folder's basename (for name matching in filenames).
    """
    import re
    from pathlib import Path

    nation = country_label.strip()
    frames: list[pd.DataFrame] = []
    seen: set[str] = set()   # make sure we never add the same file twice

    def _read_and_stamp(path, tier_guess: int | None):
        try:
            path = Path(path).resolve()
            if str(path) in seen:
                return
            seen.add(str(path))

            if path.suffix.lower() == ".csv":
                df_ = read_csv_resilient(str(path))
            else:
                dfs = read_xlsx_resilient(str(path))
                if dfs:
                    df_ = pd.concat(dfs, ignore_index=True, sort=False)
                else:
                    df_ = pd.read_excel(str(path), dtype=str).fillna("")

            m = re.search(r"(\d+)", path.stem)
            tier = int(m.group(1)) if m else (tier_guess or 0)

            df_["__source_file"] = path.name
            df_["__nation"] = nation
            df_["__tier"] = tier
            df_["__league_key"] = f"{nation} · T{tier if tier else '?'}"
            frames.append(df_)
        except Exception as e:
            st.warning(f"Failed to read {path.name}: {e}")

    # explicit tier files such as "<Nation>1.csv"
    for t in tiers:
        for ext in (".csv", ".xlsx"):
            p = Path(folder) / f"{country_label}{t}{ext}"
            if p.exists():
                _read_and_stamp(p, t)

    # any other file in folder that mentions the nation and tier
    for ext in ("*.csv", "*.xlsx"):
        for f in glob.glob(os.path.join(folder, ext)):
            name = os.path.basename(f)
            if country_label.lower().replace(" ", "") in name.lower().replace(" ", ""):
                for t in tiers:
                    if str(t) in name:
                        _read_and_stamp(f, t)
                        break

    return frames

def _attach_league_strength(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Tier coefficient needs a tier label column or mapping
    # If you already have a column, swap "__league_tier_label" for your real column name
    if "__league_tier_label" in out.columns:
        out["_tier_strength"] = out["__league_tier_label"].map(lambda x: tier_strength_coef(str(x)))
    else:
        out["_tier_strength"] = 0.50

    # Optional ClubElo influence if available
    out = _attach_elo_factor(out)
    elo_weight = 0.10
    f = pd.to_numeric(out.get("_elo_factor", 1.0), errors="coerce").fillna(1.0)
    out["_strength_factor"] = out["_tier_strength"] * (1.0 + elo_weight * (f - 1.0))

    return out

__all__ = ['ENCODING_CANDIDATES', '_strip_accents', 'WYSROOTDIR', 'REFERENCE_PLAYERS_PATH', 'CLUBELO_DIR', '_clubelo_latest_path', '_clubelo_dated_path', 'fetch_today', 'update_clubelo_cache_if_needed', '_club_key', '_load_clubelo_cache', '_attach_elo_factor', '_attach_tier_factor', '_apply_league_normalisation', '_norm_league_key_for_tier', '_tier_one_benchmark_cohort', '_apply_league_factor_to_kpis', '_POSITION_ALIAS_MAP', '_normalise_pos_text', 'WS_POS_TO_ROLE_PROFILE', 'WS_POS_ORDER', 'WS_POS_COMPAT', '_WS_POS_CODE_RE', '_ws_pos_tokens', '_ROLE_PRESET_LABEL_TO_PROFILE_KEY', '_preset_label_to_profile_key', '_text_to_profile_key', '_infer_profile_key', 'TOP5_NATIONS', 'NEXT7_NATIONS', '_leaguekey_parts', '_tier1_divs_for_nations', '_dedupe_keep_order', '_unpack_rule', '_zscore_series', '_ensure_z_and_pct', '_score_from_spec_z', '_compute_label_scores', '_metric_goodness_pct', '_score_bundle', '_cosine_1d', '_trait_defs_for_role_group', '_compute_rtr_vectors', 'rerank_candidates_by_rtr', '_percentile_of_value', '_mb_parse_value_eur', '_mb_parse_contract_dt', '_mb_winsorise_series', '_mb_zscore_series', '_mb_pick_col', '_mb_build_perf_score', '_mb_apply_professional_value_model', '_mb_fit_expected_value', '_as_float', '_pick_minutes', '_confidence_from_minutes', '_infer_profile_key_from_position_text', '_detail_to_gap_rows', '_coverage_and_avg_gap', '_score_roles_traits_responsibilities_global', 'calculate_search_tab_gaps', '_load_prev_season_master', '_load_reference_players_default', '_metric_phase', '_get_metric_value', '_infer_archetypes_for_row', '_sniff_delimiter', 'read_csv_resilient', 'read_xlsx_resilient', '_build_global_wyscout_master', '_percentile_rank', '_pct_bar_html', 'parse_market_value', 'parse_minutes', '_parse_height_m', '_restrict_to_three_nations', '_find_metric_col', '_collect_country_frames', '_attach_league_strength']