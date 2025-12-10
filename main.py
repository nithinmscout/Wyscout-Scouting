# app.py — Part 1/6
from __future__ import annotations

# =========================
# 1) STANDARD LIB IMPORTS
# =========================
import os, io, re, datetime as dt, base64, csv, math, unicodedata, glob
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

# =========================
# 2) THIRD-PARTY IMPORTS
# =========================
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Optional deps for PDF-image preview
try:
    import fitz  # PyMuPDF
    from PIL import Image
except Exception:
    fitz = None
    Image = None

# Optional deps for scraping
try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None
    BeautifulSoup = None

try:
    from fake_useragent import UserAgent
except Exception:
    UserAgent = None


# =========================
# 3) BASIC APP CONFIG
# =========================
st.set_page_config(page_title="FC Midtjylland Scouting Dashboard", layout="wide")

DEFAULT_DB_CSV    = "Scout DB (1).csv"
DEFAULT_DEPTH_CSV = "depth_fcm.csv"

# Pitch positions as columns in the depth CSV (keep as-is to match your CSV)
FCM_POSITIONS = [
    "11a - LWF","9 - AF","9a - TM","7a - RWF","11 - LM","10 - CAM","10a","7 - RM",
    "6","8","3 - LB/LWB","5L","4 - CCB","5R","2 - RB/RWB","GK"
]
DEPTH_SLOTS = 4

# Role order for buckets / position pickers
ROLE_ORDER = [
    "11a - LWF","9 - AF","9a - TM","7a - RWF","11 - LM","10 - CAM","10a","7 - RM",
    "6","8","3 - LB/LWB","5L","4 - CCB","5R","2 - RB/RWB","GK"
]

# Required columns in the master DB
REQUIRED_COLUMNS = [
    "Name","Position","Age","Age Group","Player Current Team","Potential Rating (1-4)","Watched","Verdict",
    "Shadow Team Colour Code","Player Height","TM Value","Highest TM Value","Contract Until","Agency",
    "Player Nationality","Current Salary","Player weight","Dominant Foot","Source","DOB","Strengths",
    "Weaknesses","Fixture Date","Scout Report By","Created time","Last edited time","Untitled Database",
    "Current Rating (1-4)","Division","Playing Nation","Loan Club","On loan","Full Report Path","Photo URL","Photo Path",
    # Wyscout linkage
    "Wyscout Player ID",
    # CA/PA sliders (manual overrides)
    "Current Ability (manual)","Potential Ability (manual)"
]

# Fixtures config (folders will hold multiple league CSVs per nation)
FIXTURES_ROOT = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Fixtures"
NATION_FIX_DIRS = {
    "Belgium":     os.path.join(FIXTURES_ROOT, "Belgium"),
    "Netherlands": os.path.join(FIXTURES_ROOT, "Netherlands"),
    "France":      os.path.join(FIXTURES_ROOT, "France"),
    "Other":       os.path.join(FIXTURES_ROOT, "Other"),
}
for _p in NATION_FIX_DIRS.values():
    os.makedirs(_p, exist_ok=True)

# Season window (25/26)
SEASON_START_2526 = date(2025, 7, 1)
SEASON_END_2526   = date(2026, 6, 30)
UPCOMING_WINDOW_DAYS = 14

# Logo discovery
POSSIBLE_LOGOS = [
    os.path.join("FCM Scouting", "FCM logo.png"),
    os.path.join("FCM Scouting", "FCM_logo.png"),
    "FCM logo.png", "FCM_logo.png",
]
def find_logo() -> Optional[str]:
    for p in POSSIBLE_LOGOS:
        if os.path.exists(p): return p
    return None


# =========================
# 4) GLOBAL CSS
# =========================
st.markdown("""
<style>
.header-logo { display:flex; justify-content:flex-end; align-items:flex-start; padding-top:8px; }
.header-logo img { width:72px; height:auto; border-radius:8px; }

/* chips on pitch */
.chips { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.chip { padding:2px 8px; border-radius:12px;
  background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.20);
  font-size:12px; line-height:16px; white-space:nowrap; }
.chip-first { font-weight:800; font-size:15px; padding:4px 10px; }
.chip-second { font-size:13px; }

/* pitch cards */
.depth-card { padding:8px 10px; border:1px solid rgba(255,255,255,0.12); border-radius:12px;
  background:rgba(255,255,255,0.05); }
.depth-label { font-weight:800; font-size:13px; margin-bottom:4px; letter-spacing:.4px; }
.pitch { border-radius:18px; padding:10px 8px;
  background:radial-gradient(ellipse at center, rgba(0,80,0,0.28), rgba(0,0,0,0.12)); }
.block-container { padding-top: 1rem; }
hr { margin: .5rem 0; }
div[data-baseweb="input"] input { height:34px; font-size:13px; }

/* small badge */
.badge { display:inline-block; padding:2px 8px; border-radius:999px;
  border:1px solid rgba(255,255,255,0.2); background:rgba(255,255,255,0.08);
  font-size:12px; margin-left:8px; }

/* tiny player cards (Reporting page) */
.player-card { border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:10px; }
.player-card h4 { margin:0 0 4px 0; font-size:14px; }
.player-card .meta { font-size:12px; opacity:.8; }

.small-expander > details > summary { font-size:12px !important; opacity:.85; }

/* tables */
.dataframe th, .dataframe td { font-size:12px; }
</style>
""", unsafe_allow_html=True)


# =========================
# 5) SHARED HELPERS
# =========================

IMAGES_DIR = os.path.join("FCM Scouting", "player photos")
os.makedirs(IMAGES_DIR, exist_ok=True)

def download_image_to_disk(url: str, player_name: str) -> Optional[str]:
    if not url or not requests:
        return None
    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0"
        r = requests.get(url, headers={"User-Agent": ua}, timeout=15)
        r.raise_for_status()
        ext = ".jpg"
        ct = r.headers.get("Content-Type","").lower()
        if "png" in ct: ext = ".png"
        safe = re.sub(r"[^\w\-. ]", "_", player_name).strip("_") or "player"
        out = os.path.join(IMAGES_DIR, f"{safe}{ext}")
        with open(out, "wb") as f:
            f.write(r.content)
        return out
    except Exception:
        return None

def _clean_name(name_raw: str) -> str:
    name = re.sub(r"^\s*#?\d+\s+", "", (name_raw or "").strip())
    name = re.sub(r"\s*\(#?\d+\)\s*$", "", name)
    return name.strip()

def _tidy_person_name(s: str) -> str:
    parts = str(s or "").strip().split()
    lowers = {"van","de","der","den","da","dos","das","del","di","la","le","du","von"}
    out = []
    for i,p in enumerate(parts):
        pp = p.strip()
        if pp.lower() in lowers and i>0:
            out.append(pp.lower())
        else:
            out.append(pp[:1].upper() + pp[1:].lower())
    return " ".join(out)

def split_roles(cell: str) -> List[str]:
    if not cell: return []
    return [x.strip() for x in cell.split(",") if x.strip()]

def get_primary_role(row: pd.Series) -> str:
    roles = split_roles(str(row.get("Position","")))
    return roles[0] if roles else ""

def ensure_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns: df[c] = ""
    return df

def _norm_str(s: Any) -> str:
    """Case/diacritic/punctuation-insensitive key for duplicate checks & matching."""
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\W_]+", "", s)
    return s

# ---- Date / height parsing
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
def _parse_date_any(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except: pass
    m = re.match(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", s)
    if m:
        mon = MONTHS.get(m.group(1).lower(), 0)
        if mon: return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"([A-Za-z]{3,9})\s+(\d{4})", s)
    if m:
        mon = MONTHS.get(m.group(1).lower(), 6)
        return f"{int(m.group(2)):04d}-{mon:02d}-30"
    return ""

def _norm_height_meters(s: str) -> str:
    s = (s or "").lower().replace("meters","m").replace("metres","m").replace("\xa0"," ").strip()
    m = re.search(r"([\d\.,]+)\s*m", s) or re.search(r"([\d\.,]+)$", s)
    if not m: return s.strip()
    try:
        f = float(m.group(1).replace(",", "."))
        if 0.5 < f < 2.7: return f"{f:.2f} m"
    except: ...
    return s.strip()

def calc_age_from_row(r: pd.Series) -> Optional[int]:
    a = str(r.get("Age","")).strip()
    if a.isdigit():
        try: return int(a)
        except: pass
    dob = str(r.get("DOB","")).strip()
    try:
        y,m,d = map(int, dob.split("-"))
        born = date(y,m,d)
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except:
        return None

def compute_age_series(df_in: pd.DataFrame) -> pd.Series:
    ages = []
    today = date.today()
    for _, r in df_in.iterrows():
        a = str(r.get("Age","")).strip()
        if a.isdigit():
            ages.append(int(a)); continue
        dob = str(r.get("DOB","")).strip()
        try:
            y,m,d = map(int, dob.split("-"))
            born = date(y,m,d)
            ages.append(today.year - born.year - ((today.month, today.day) < (born.month, born.day)))
        except:
            ages.append(None)
    return pd.Series(ages, index=df_in.index, dtype="float")

# ---- TM value normalization
def parse_eur_value(s: str) -> Optional[float]:
    if not s: return None
    txt = str(s).lower().replace("€","").replace("eur","").strip()
    txt = txt.replace(",", "")
    if "million" in txt:
        try:
            return float(txt.split()[0]) * 1_000_000
        except:
            pass
    mult = 1.0
    if txt.endswith("m"):
        mult = 1_000_000.0; txt = txt[:-1]
    elif txt.endswith("k"):
        mult = 1_000.0; txt = txt[:-1]
    try:
        return float(txt) * mult
    except:
        return None

def fmt_eur_compact(v: Optional[float]) -> str:
    if v is None: return ""
    try:
        v = float(v)
    except:
        return ""
    if v >= 1_000_000:
        val = round(v/1_000_000, 2)
        val = int(val) if float(val).is_integer() else val
        return f"€{val}m"
    elif v >= 1_000:
        val = round(v/1_000, 0)
        val = int(val)
        return f"€{val}k"
    elif v > 0:
        val = round(v/1_000, 1)
        return f"€{val}k"
    return "€0"


# =========================
# 6) ROBUST CSV READER (fixes encoding / delimiter / quote issues)
# =========================
def read_csv_flexible(path: str) -> pd.DataFrame:
    """
    Robust reader that prefers strings (dtype=str) and sniffs the delimiter.
    Tries multiple encodings to avoid 'utf-8' codec and quote errors.
    """
    attempts = [
        dict(encoding="utf-8-sig", sep=None, engine="python", dtype=str, keep_default_na=True),
        dict(encoding="cp1252",    sep=None, engine="python", dtype=str, keep_default_na=True),
        dict(encoding="latin1",    sep=None, engine="python", dtype=str, keep_default_na=True),
    ]
    for kw in attempts:
        try:
            df = pd.read_csv(path, **kw)
            df.columns = [str(c).strip().replace("\ufeff","") for c in df.columns]
            return df
        except Exception:
            continue
    # last resort
    df = pd.read_csv(path, sep=None, engine="python", dtype=str, keep_default_na=True, encoding_errors="replace")
    df.columns = [str(c).strip().replace("\ufeff","") for c in df.columns]
    return df


# =========================
# 7) TRANSFERMARKT SCRAPERS (player + fixtures helper)
# =========================
def get_transfermarkt_player_info(player_url: str) -> Optional[dict]:
    if not (requests and BeautifulSoup):
        return None
    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0"
        resp = requests.get(player_url, headers={"User-Agent": ua}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        out = {}

        headline_container = soup.find("div", class_="data-header__headline-container")
        if headline_container:
            shirt = headline_container.find("span", class_="data-header__shirt-number")
            if shirt:
                out["shirt_number"] = shirt.get_text(strip=True).replace("#","").strip()
            h1 = headline_container.find("h1", class_="data-header__headline-wrapper")
            if h1:
                sspan = h1.find("span", class_="data-header__shirt-number")
                if sspan: sspan.extract()
                out["player_name"] = _clean_name(h1.get_text(strip=True))

        mvw = soup.find("a", class_="data-header__market-value-wrapper")
        if mvw:
            mv_text = re.sub(r"Last update:.*", "", mvw.get_text(strip=True)).strip()
            out["market_value"] = mv_text

        # image
        img_url = None
        og = soup.find("meta", attrs={"property":"og:image"})
        if og and og.get("content"):
            img_url = og["content"]
        if not img_url:
            cand = soup.select_one("img[data-testid='player-header-image'], img.data-header__profile-image, img[data-picture]")
            if cand and cand.get("src"):
                img_url = cand["src"]
            elif cand and cand.get("srcset"):
                try:
                    parts = [p.strip().split(" ")[0] for p in cand["srcset"].split(",") if p.strip()]
                    if parts: img_url = parts[-1]
                except: pass
        out["image_url"] = img_url or ""

        info = soup.find("div", class_="info-table info-table--right-space")
        if info:
            spans = info.find_all("span", class_="info-table__content")
            for i in range(0, len(spans), 2):
                if i+1 >= len(spans): break
                label = spans[i].get_text(strip=True).replace(":","")
                value_span = spans[i+1]
                value = value_span.get_text(strip=True)
                if "Date of birth" in label:
                    if "(" in value and ")" in value:
                        d = value.split("(")[0].strip()
                        a = value.split("(")[1].split(")")[0].strip()
                        out["date_of_birth"] = d; out["age"] = a
                    else:
                        out["date_of_birth"] = value
                elif "Height" in label:
                    out["height"] = value
                elif "Citizenship" in label:
                    out["citizenship"] = value
                elif "Position" in label:
                    out["position"] = value
                elif "Foot" in label:
                    out["foot"] = value
                elif "Player agent" in label:
                    link = value_span.find("a")
                    out["player_agent"] = link.get_text(strip=True) if link else value
                elif "Current club" in label:
                    link = value_span.find("a")
                    out["current_club"] = link.get_text(strip=True) if link else value
                elif "Contract expires" in label:
                    out["contract_expiry"] = value
                elif "Contract option" in label:
                    out["contract_option"] = value
        return out
    except Exception:
        return None

def scrape_transfermarkt(url: str) -> (dict, str):
    if not requests or not BeautifulSoup:
        return {}, "Please install 'requests' and 'beautifulsoup4'."
    data = get_transfermarkt_player_info(url.strip())
    if not data:
        return {}, "Fetch failed or layout changed."
    name = _tidy_person_name(data.get("player_name",""))
    mv_eur = parse_eur_value(data.get("market_value",""))
    mapped = {
        "Name": name,
        "Player Height": _norm_height_meters(data.get("height","")),
        "Player Nationality": data.get("citizenship",""),
        "Dominant Foot": data.get("foot",""),
        "Agency": data.get("player_agent",""),
        "Player Current Team": data.get("current_club",""),
        "Contract Until": _parse_date_any(data.get("contract_expiry","")) or data.get("contract_expiry",""),
        "DOB": _parse_date_any(data.get("date_of_birth","")) or data.get("date_of_birth",""),
        "Age": data.get("age",""),
        "TM Value": fmt_eur_compact(mv_eur) if mv_eur is not None else data.get("market_value",""),
        "Photo URL": data.get("image_url",""),
    }
    return mapped, "Fetched successfully."


# =========================
# 8) Wyscout MASTER LOADER + ENRICHMENT + COHORT BUILDERS
# =========================

@st.cache_data(show_spinner=False)
def wyscout_folders() -> Dict[str, str]:
    # match your analysis folders
    return {
        "Belgium":     r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Belgium",
        "Netherlands": r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Dutch",
        "France":      r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\France",
    }

@st.cache_data(show_spinner=False)
def load_wyscout_master() -> pd.DataFrame:
    folders = wyscout_folders()
    frames: List[pd.DataFrame] = []
    for nation, folder in folders.items():
        if not folder or not os.path.isdir(folder): 
            continue
        for path in glob.glob(str(Path(folder) / "*.csv")):
            try:
                df = read_csv_flexible(path)
                df["__source_file"] = Path(path).name
                df["__nation"] = nation
                frames.append(df)
            except Exception as e:
                st.warning(f"Failed to read {path}: {e}")
        for xlsx_path in glob.glob(str(Path(folder) / "*.xlsx")):
            try:
                xls = pd.ExcelFile(xlsx_path)
                for sheet in xls.sheet_names:
                    try:
                        df_ = xls.parse(sheet_name=sheet, dtype=str)
                        df_.columns = [str(c).strip().replace("\ufeff","") for c in df_.columns]
                        df_["__source_file"] = Path(xlsx_path).name
                        df_["__nation"] = nation
                        frames.append(df_)
                    except Exception as e:
                        st.warning(f"Failed to read {xlsx_path} [{sheet}]: {e}")
            except Exception as e:
                st.warning(f"Failed to open {xlsx_path}: {e}")
    if not frames:
        return pd.DataFrame()
    master = pd.concat(frames, ignore_index=True, sort=False)
    # Normalise some known columns to strings
    for c in ["Player","Team","Position","Minutes played","Market value","Contract expires","DOB","Wyscout Player ID"]:
        if c in master.columns:
            master[c] = master[c].astype(str)
    return master

# Global Wyscout master (build once)
try:
    master_ws = load_wyscout_master()
    if not master_ws.empty:
        for col in ["Player","Team","Position","Minutes played"]:
            if col in master_ws.columns:
                master_ws[col] = master_ws[col].astype(str)
        for col in ["__nation","__source_file"]:
            if col not in master_ws.columns:
                master_ws[col] = ""
except Exception as _e:
    master_ws = pd.DataFrame()
    st.warning(f"Wyscout data failed to load: {_e}")

# ---- Wyscout position → broad group
WS_POS_TO_GROUP = {
    "GK": "Goalkeepers",
    "RB": "Fullbacks", "RWB": "Fullbacks", "LB": "Fullbacks", "LWB": "Fullbacks",
    "RCB": "Centre-backs", "CB": "Centre-backs", "LCB": "Centre-backs",
    "DMF": "Defensive mids", "RDMF":"Defensive mids", "LDMF":"Defensive mids",
    "CMF": "Central mids", "RCMF":"Central mids", "LCMF":"Central mids",
    "AMF": "Attacking mids", "RAMF":"Attacking mids", "LAMF":"Attacking mids",
    "RW": "Wingers", "RWF":"Wingers", "RM":"Wingers",
    "LW": "Wingers", "LWF":"Wingers", "LM":"Wingers",
    "CF": "Strikers", "ST":"Strikers", "SS":"Strikers",
}

# ---- Our FCM roles → acceptable Wyscout tokens
FCM_TO_WS = {
    "2 - RB/RWB": {"RB","RWB"},
    "3 - LB/LWB": {"LB","LWB"},
    "4 - CCB": {"RCB","CB","LCB"},
    "5L": {"LCB","CB"},
    "5R": {"RCB","CB"},
    "6": {"DMF","RDMF","LDMF"},
    "8": {"CMF","RCMF","LCMF"},
    "10 - CAM": {"AMF","RAMF","LAMF"},
    "10a": {"AMF","RAMF","LAMF"},
    "11a - LWF": {"LW","LWF","LM"},
    "7a - RWF":  {"RW","RWF","RM"},
    "11 - LM": {"LM","LWF","LW"},
    "7 - RM": {"RM","RWF","RW"},
    "9 - AF": {"CF","ST","SS"},
    "9a - TM": {"CF","ST","SS"},
    "GK": {"GK"},
}

def _ws_pos_tokens(s: str) -> list[str]:
    return [t.strip().upper() for t in re.split(r"[,/;]\s*", str(s or "")) if t.strip()]

def enrich_with_groups(master: pd.DataFrame) -> pd.DataFrame:
    df = master.copy()
    if "Position" not in df.columns:
        df["Position"] = ""
    pos_tokens = df["Position"].astype(str).apply(_ws_pos_tokens)
    groups_col, fcm_roles_col = [], []
    for ts in pos_tokens:
        gset = {WS_POS_TO_GROUP[t] for t in ts if t in WS_POS_TO_GROUP}
        rset = set()
        for fcm_role, wsset in FCM_TO_WS.items():
            if any(t in wsset for t in ts):
                rset.add(fcm_role)
        groups_col.append(sorted(gset) if gset else [])
        fcm_roles_col.append(sorted(rset) if rset else [])
    df["__groups"] = groups_col
    df["__fcm_roles"] = fcm_roles_col
    return df

def filter_season_and_minutes(df: pd.DataFrame, min_minutes: int = 600) -> pd.DataFrame:
    mins = pd.to_numeric(df.get("Minutes played", pd.Series(index=df.index, dtype=str)), errors="coerce")
    if pd.notna(mins).any():
        df = df[mins >= min_minutes].copy()
    return df

def build_cohort(master: pd.DataFrame,
                 cohort_type: str,
                 fcm_role: str | None = None,
                 general_group: str | None = None,
                 nations: list[str] | None = None,
                 min_minutes: int = 600,
                 league_hint: str | None = None) -> pd.DataFrame:
    df = enrich_with_groups(master)

    if "__groups" not in df.columns:
        df["__groups"] = [[] for _ in range(len(df))]
    if "__fcm_roles" not in df.columns:
        df["__fcm_roles"] = [[] for _ in range(len(df))]

    if nations:
        df = df[df["__nation"].isin(nations)].copy()
    if league_hint and "__source_file" in df.columns:
        df = df[df["__source_file"].astype(str).str.contains(str(league_hint), case=False, na=False)].copy()

    df = filter_season_and_minutes(df, min_minutes=min_minutes)

    if cohort_type == "FCM" and fcm_role:
        df = df[df["__fcm_roles"].apply(lambda L: fcm_role in (L or []))].copy()
    elif cohort_type == "GROUP" and general_group:
        df = df[df["__groups"].apply(lambda L: general_group in (L or []))].copy()

    return df

# Packs & weights (include CM & AM)
PACKS = {
    "Wingers": {
        "Chance creation": ["xA per 90","Shot assists per 90","Crosses per 90","Accurate crosses, %","Key passes per 90"],
        "Ball carrying":   ["Dribbles per 90","Successful dribbles, %","Progressive runs per 90","Accelerations per 90"],
        "Final third":     ["Passes to penalty area per 90","Accurate passes to penalty area, %","Touches in box per 90"]
    },
    "Fullbacks": {
        "Defending":       ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","Interceptions per 90","PAdj Interceptions"],
        "Progression":     ["Progressive runs per 90","Progressive passes per 90","Passes to final third per 90","Accurate passes to final third, %"],
        "Crossing":        ["Crosses per 90","Accurate crosses, %","Deep completed crosses per 90"]
    },
    "Centre-backs": {
        "Duels & aerials": ["Defensive duels per 90","Defensive duels won, %","Aerial duels per 90","Aerial duels won, %","Shots blocked per 90"],
        "Build-up":        ["Passes per 90","Accurate passes, %","Forward passes per 90","Accurate forward passes, %","Progressive passes per 90"]
    },
    "Central mids": {
        "Progression":     ["Progressive runs per 90","Progressive passes per 90","Passes to final third per 90","Accurate passes to final third, %"],
        "Link & security": ["Passes per 90","Accurate passes, %","Short / medium passes per 90","Accurate short / medium passes, %","Fouls suffered per 90"],
        "Creation":        ["xA per 90","Shot assists per 90","Key passes per 90","Smart passes per 90","Accurate smart passes, %"]
    },
    "Attacking mids": {
        "Creation":        ["xA per 90","Shot assists per 90","Key passes per 90","Smart passes per 90","Accurate smart passes, %"],
        "Carrying":        ["Dribbles per 90","Successful dribbles, %","Progressive runs per 90"],
        "Final third":     ["Passes to penalty area per 90","Accurate passes to penalty area, %","Touches in box per 90"]
    },
    "Defensive mids": {
        "Defending":       ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","Interceptions per 90","PAdj Interceptions"],
        "Build-up":        ["Passes per 90","Accurate passes, %","Forward passes per 90","Accurate forward passes, %","Progressive passes per 90"]
    },
    "Strikers": {
        "Finishing":       ["Goals per 90","Non-penalty goals per 90","xG per 90","Shots per 90","Shots on target, %","Goal conversion, %"],
        "Presence":        ["Touches in box per 90","Offensive duels per 90","Offensive duels won, %"]
    },
    "Goalkeepers": {
        "Shot stopping":   ["Conceded goals per 90","Shots against per 90","Save rate, %","xG against per 90","Prevented goals per 90"],
        "Sweeper":         ["Back passes received as GK per 90","Exits per 90","Aerial duels per 90"]
    }
}

DEFAULT_WEIGHTS = {
    "Wingers": {"Chance creation":0.40,"Ball carrying":0.35,"Final third":0.25},
    "Fullbacks": {"Defending":0.45,"Progression":0.35,"Crossing":0.20},
    "Centre-backs": {"Duels & aerials":0.55,"Build-up":0.45},
    "Central mids": {"Progression":0.40,"Link & security":0.35,"Creation":0.25},
    "Attacking mids": {"Creation":0.45,"Carrying":0.30,"Final third":0.25},
    "Defensive mids": {"Defending":0.55,"Build-up":0.45},
    "Strikers": {"Finishing":0.60,"Presence":0.40},
    "Goalkeepers": {"Shot stopping":0.65,"Sweeper":0.35},
}

def zscores_table(df: pd.DataFrame, metrics: List[str]) -> pd.DataFrame:
    z = pd.DataFrame(index=df.index)
    for m in metrics:
        col = pd.to_numeric(df.get(m), errors="coerce")
        if col.notna().sum() >= 3:
            z[m] = (col - col.mean()) / (col.std(ddof=0) + 1e-9)
        else:
            z[m] = np.nan
    return z

def overall_score_from_clusters(row: pd.Series, packs: Dict[str, List[str]], weights: Dict[str, float]) -> float:
    score = 0.0; wsum = 0.0
    for cluster, mlist in packs.items():
        w = float(weights.get(cluster, 0.0))
        if w <= 0: 
            continue
        vals = [float(row.get(m, np.nan)) for m in mlist if m in row and pd.notna(row.get(m))]
        if vals:
            score += w * float(np.nanmean(vals))
            wsum += w
    return score / (wsum + 1e-9)

def rank_and_percentiles(df: pd.DataFrame, metrics: List[str]) -> pd.DataFrame:
    out = df.copy()
    for m in metrics:
        series = pd.to_numeric(out[m], errors="coerce")
        out[f"{m}__rank"] = series.rank(ascending=False, method="min")
        out[f"{m}__pct"]  = series.rank(pct=True, ascending=True) * 100.0
    return out

def prepare_cohort_analysis(master: pd.DataFrame,
                            target_player_name: str | None,
                            target_wyscout_id: str | None,
                            cohort_type: str,
                            fcm_role: str | None,
                            general_group: str | None,
                            nations: list[str],
                            min_minutes: int = 600,
                            league_hint: str | None = None
                            ) -> Tuple[pd.DataFrame, Dict[str, List[str]], Dict[str, float], pd.Series]:
    cohort = build_cohort(master,
                          cohort_type=cohort_type,
                          fcm_role=fcm_role,
                          general_group=general_group,
                          nations=nations,
                          min_minutes=min_minutes,
                          league_hint=league_hint)
    # pick pack by cohort type
    if cohort_type == "FCM":
        # map our FCM role to the closest broad pack
        role_to_group = {
            "11a - LWF":"Wingers","7a - RWF":"Wingers","11 - LM":"Wingers","7 - RM":"Wingers",
            "2 - RB/RWB":"Fullbacks","3 - LB/LWB":"Fullbacks",
            "4 - CCB":"Centre-backs","5L":"Centre-backs","5R":"Centre-backs",
            "6":"Defensive mids","8":"Central mids","10 - CAM":"Attacking mids","10a":"Attacking mids",
            "9 - AF":"Strikers","9a - TM":"Strikers","GK":"Goalkeepers"
        }
        group = role_to_group.get(fcm_role or "", "Wingers")
    else:
        group = general_group or "Wingers"

    packs = PACKS.get(group, {})
    weights = DEFAULT_WEIGHTS.get(group, {})

    metrics = sorted({m for ms in packs.values() for m in ms})
    if not metrics or cohort.empty:
        return pd.DataFrame(), {}, {}, pd.Series(dtype=float)

    # numeric subset for zscores
    df_num = cohort.copy()
    for m in metrics:
        df_num[m] = pd.to_numeric(df_num.get(m), errors="coerce")
    ztab = zscores_table(df_num, metrics)

    # overall score first
    scores = []
    for idx, r in ztab.iterrows():
        scores.append(overall_score_from_clusters(r, packs, weights))
    ztab["__overall_score"] = scores
    ztab["__overall_rank"]  = ztab["__overall_score"].rank(ascending=False, method="min")
    ztab["__overall_pct"]   = ztab["__overall_score"].rank(pct=True, ascending=True) * 100.0

    # add metric ranks/percentiles
    ztab = rank_and_percentiles(ztab, metrics)

    # choose target row (ID preferred)
    target_mask = pd.Series([False]*len(ztab), index=ztab.index)
    if target_wyscout_id and "Wyscout Player ID" in cohort.columns:
        ids = cohort["Wyscout Player ID"].astype(str)
        target_mask = ids == str(target_wyscout_id)
    elif target_player_name and "Player" in cohort.columns:
        target_mask = cohort["Player"].astype(str).str.casefold() == str(target_player_name).casefold()

    target_row = ztab[target_mask].iloc[0] if target_mask.any() else pd.Series(dtype=float)
    return ztab, packs, weights, target_row

# app.py — Part 2/6
# =========================
# 9) DB & DEPTH HELPERS
# =========================
@st.cache_data(show_spinner=False)
def load_db(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        df.to_csv(path, index=False)
        return df
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    # ensure all required columns exist
    for c in REQUIRED_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    # normalise types as strings
    for c in df.columns:
        df[c] = df[c].astype(str)
    return df[[*df.columns]]

def write_db(path: str, df: pd.DataFrame):
    tmp = f"{path}.tmp"
    df.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, path)

def blank_depth_df() -> pd.DataFrame:
    df = pd.DataFrame({pos: [""]*DEPTH_SLOTS for pos in FCM_POSITIONS})
    df.index = [f"{i+1}" for i in range(DEPTH_SLOTS)]
    return df

@st.cache_data(show_spinner=False)
def load_depth(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        df = blank_depth_df()
        df.to_csv(path, index=True)
        return df
    df = pd.read_csv(path, index_col=0, dtype=str, keep_default_na=False)
    for pos in FCM_POSITIONS:
        if pos not in df.columns:
            df[pos] = ""
    if len(df) < DEPTH_SLOTS:
        extra = DEPTH_SLOTS - len(df)
        df = pd.concat([df, pd.DataFrame({c:[""]*extra for c in df.columns})], ignore_index=True)
    if len(df) > DEPTH_SLOTS:
        df = df.iloc[:DEPTH_SLOTS].copy()
    df.index = [f"{i+1}" for i in range(DEPTH_SLOTS)]
    df = df[[c for c in FCM_POSITIONS]]
    return df

def save_depth(path: str, df: pd.DataFrame):
    tmp = f"{path}.tmp"
    df.to_csv(tmp, index=True, encoding="utf-8")
    os.replace(tmp, path)

def add_or_update_row(df: pd.DataFrame, row: Dict[str, Any]) -> pd.DataFrame:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.setdefault("Created time", now)
    row["Last edited time"] = now
    for c in REQUIRED_COLUMNS:
        row.setdefault(c, "")
    # robust match on Name + Team
    name_norm_series = df["Name"].astype(str).map(_norm_str)
    team_norm_series = df["Player Current Team"].astype(str).map(_norm_str)
    new_name_norm = _norm_str(row.get("Name",""))
    new_team_norm = _norm_str(row.get("Player Current Team",""))
    mask = (name_norm_series == new_name_norm) & (team_norm_series == new_team_norm)
    if mask.any():
        idx = df[mask].index[0]
        for k,v in row.items():
            if k in df.columns and str(v) != "":
                df.at[idx, k] = v
    else:
        df = pd.concat(
            [df, pd.DataFrame([row], columns=[*df.columns, *[c for c in row.keys() if c not in df.columns]])],
            ignore_index=True
        )
    return df

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

def _safe_unlink(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def _sort_newest_first(df_in: pd.DataFrame) -> pd.DataFrame:
    t1 = pd.to_datetime(df_in.get("Created time", ""), errors="coerce")
    t2 = pd.to_datetime(df_in.get("Last edited time", ""), errors="coerce")
    order = t1.fillna(t2)
    return df_in.assign(__sort=order).sort_values("__sort", ascending=False, na_position="last").drop(columns="__sort", errors="ignore")


# =========================
# 10) CARD RENDERER (image left, info right)
# =========================
def render_player_card(r: pd.Series, key_prefix: str = "", show_more: bool = True):
    with st.container(border=True):
        img_src = str(r.get("Photo Path","")).strip() or str(r.get("Photo URL","")).strip()

        col_img, col_info = st.columns([1, 3])
        with col_img:
            if img_src:
                st.image(img_src, width=110)
        with col_info:
            has_report = bool(str(r.get("Full Report Path","")).strip())
            badge = ' <span class="badge">📄 Full report</span>' if has_report else ""
            name_html = f"**{r.get('Name','')}**{badge}"
            st.markdown(name_html, unsafe_allow_html=True)

            # Show loan context in compact line
            team = r.get("Player Current Team",""); pos = r.get("Position",""); age = r.get("Age","")
            loan_flag = str(r.get("On loan","")).strip().lower() == "yes"
            loan_club = r.get("Loan Club","")
            top_line = f"{loan_club} → {team}" if loan_flag and loan_club else team
            st.caption(f"{top_line} • {pos} • Age: {age}")

            tmv = r.get("TM Value",""); cr = r.get("Current Rating (1-4)",""); pr = r.get("Potential Rating (1-4)",""); watched = r.get("Watched","")
            st.write(f"**Value:** {tmv}  |  **CR/PR:** {cr}/{pr}")
            # manual CA/PA if present
            ca = r.get("Current Ability (manual)",""); pa = r.get("Potential Ability (manual)","")
            if ca or pa:
                st.caption(f"CA/PA: {ca or '—'} / {pa or '—'}")
            if watched:
                st.caption(f"Watched: {watched}")

            if show_more:
                with st.expander("More", expanded=False):
                    strengths = r.get("Strengths",""); weaknesses = r.get("Weaknesses","")
                    if strengths:
                        st.write("**Strengths**"); st.write(strengths)
                    if weaknesses:
                        st.write("**Weaknesses**"); st.write(weaknesses)
                    if r.get("Source",""):
                        st.link_button("Transfermarkt", r["Source"], type="secondary")
                    if has_report:
                        st.markdown(f"[📄 Open full report]({r['Full Report Path']})")


# =========================
# 11) NAV STATE
# =========================
if "db_csv" not in st.session_state: st.session_state.db_csv   = DEFAULT_DB_CSV
if "depth_csv" not in st.session_state: st.session_state.depth_csv = DEFAULT_DEPTH_CSV
if "nav" not in st.session_state: st.session_state.nav = "🏠 Home"
if "profile_focus" not in st.session_state: st.session_state.profile_focus = None  # index for reporting page

with st.sidebar:
    st.markdown("### Menu")
    def menu_btn(label: str, key: str):
        active = (st.session_state.nav == label)
        btn = st.button(label, use_container_width=True, type=("primary" if active else "secondary"), key=key)
        if btn: st.session_state.nav = label
    menu_btn("🏠 Home", "nav_home")
    menu_btn("📚 All Players", "nav_players")
    menu_btn("📝 Player reports", "nav_reports")
    menu_btn("📊 Data analysis", "nav_analysis")
    menu_btn("📅 Fixtures", "nav_fixtures")
    menu_btn("⚙️ Files", "nav_files")
nav = st.session_state.nav


# =========================
# 12) ALL PLAYERS PAGE
# =========================
if nav == "📚 All Players":
    st.title("All Players")
    df = load_db(st.session_state.db_csv).copy()

    # newest-first view
    df = _sort_newest_first(df)

    left, right = st.columns([1,3])

    # ---- Import / Export (left)
    with left:
        st.subheader("Import CSV (append)")
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up is not None:
            try:
                newdf = pd.read_csv(up, dtype=str, keep_default_na=False)
                for c in REQUIRED_COLUMNS:
                    if c not in newdf.columns: newdf[c] = ""
                merged = pd.concat([df, newdf[[*newdf.columns]]], ignore_index=True)
                write_db(st.session_state.db_csv, merged); st.success(f"Imported {len(newdf)} rows.")
                st.cache_data.clear(); df = load_db(st.session_state.db_csv).copy()
                df = _sort_newest_first(df)
            except Exception as e:
                st.error(f"Import failed: {e}")
        st.subheader("Export current view"); st.caption("Exports the filtered table on the right.")

    # ---- Add new player (left expander) with ON-LOAN flow + DOB bounds + contract presets + CA/PA
    with st.expander("➕ Add a new player (template / TM scrape)", expanded=False):
        scrape_url = st.text_input("Transfermarkt URL (optional)", key="add_scrape_url",
                                   placeholder="https://www.transfermarkt.com/.../profil/spieler/12345")
        if st.button("Fetch from Transfermarkt", type="secondary", key="add_fetch_tm"):
            data, msg = scrape_transfermarkt(scrape_url.strip())
            if msg: st.info(msg)
            if data:
                for k, v in data.items():
                    if v is not None:
                        st.session_state[f"new_{k}"] = v
                st.session_state["add_source"] = scrape_url.strip()
                st.success("Fetched from Transfermarkt.")
                st.rerun()  # refresh to fill fields

        def add_new_dropdown(label, options, state_key_choice, state_key_new, default_text=""):
            choice = st.selectbox(label, ["— select —"] + options + ["Add new…"], key=state_key_choice)
            new_val = st.text_input(f"Add new ({label.lower()})",
                                    value=st.session_state.get(state_key_new, default_text),
                                    key=f"{state_key_new}__input") if choice=="Add new…" else ""
            return new_val if new_val else (choice if choice not in ["— select —","Add new…"] else "")

        df_all = df.copy()
        existing_teams = sorted([t for t in df_all["Player Current Team"].unique().tolist() if t])
        existing_agencies = sorted([t for t in df_all["Agency"].unique().tolist() if t])
        existing_nat = sorted([t for t in df_all["Player Nationality"].unique().tolist() if t])
        existing_play_nat = sorted([t for t in df_all["Playing Nation"].unique().tolist() if t])
        existing_age_groups = sorted([t for t in df_all.get("Age Group", pd.Series(dtype=str)).astype(str).unique().tolist() if t and t != "nan"])
        existing_divisions = sorted([t for t in df_all.get("Division", pd.Series(dtype=str)).astype(str).unique().tolist() if t and t != "nan"])

        c1, c2 = st.columns([2,2])
        name = c1.text_input("Name", value=st.session_state.get("new_Name",""), key="add_name")
        # ON LOAN TOGGLE
        on_loan = c2.checkbox("On loan?", value=False, key="add_onloan")

        # Team fields depend on loan state
        if on_loan:
            loan_club = add_new_dropdown("Loan club (current team)", existing_teams, "add_loan_team_choice","new_Loan Club", st.session_state.get("new_Loan Club",""))
            parent_club = add_new_dropdown("Parent club", existing_teams, "add_parent_team_choice","new_Player Current Team", st.session_state.get("new_Player Current Team",""))
            team_final = parent_club  # stored in DB as current team
        else:
            team_final = add_new_dropdown("Player Current Team", existing_teams, "add_team_choice","new_Player Current Team", st.session_state.get("new_Player Current Team",""))
            loan_club = ""

        pos_sel = st.multiselect("Positions (multi-select, first = primary)", ROLE_ORDER,
                                 default=[st.session_state.get("new_Position","")] if st.session_state.get("new_Position") else [],
                                 key="add_positions")
        pos_str = ", ".join([p for p in pos_sel if p])

        d1, d2, d3 = st.columns(3)
        playing_nation = add_new_dropdown("Playing Nation (league country)", existing_play_nat,"add_playing_nation_choice","new_Playing Nation", st.session_state.get("new_Playing Nation",""))
        nationality = add_new_dropdown("Player Nationality (citizenship)", existing_nat,"add_citizenship_choice","new_Player Nationality", st.session_state.get("new_Player Nationality",""))
        division = add_new_dropdown("Division", existing_divisions, "add_division_choice", "new_Division", st.session_state.get("new_Division",""))

        # DOB bounded picker
        e1, e2, e3 = st.columns(3)
        dob_saved = st.session_state.get("new_DOB","")
        dob_default = None
        try:
            if dob_saved:
                y,m,d = map(int, str(dob_saved).split("-")); dob_default = date(y,m,d)
        except: ...
        dob_in = e1.date_input("DOB", value=dob_default, min_value=date(1900,1,1), max_value=date(2100,12,31), format="YYYY-MM-DD", key="add_dob")
        age = e2.text_input("Age", value=str(st.session_state.get("new_Age","")), key="add_age")
        age_group = add_new_dropdown("Age Group", existing_age_groups, "add_age_group_choice", "new_Age Group")

        # Height/weight/foot
        f1, f2, f3 = st.columns(3)
        default_h = st.session_state.get("new_Player Height","")
        try: default_h_num = float((default_h or "").lower().replace("m","").strip()) if default_h else 0.0
        except: default_h_num = 0.0
        height_num = f1.number_input("Player Height (m)", min_value=0.0, max_value=2.5, step=0.01, value=default_h_num, key="add_height")
        height_str = f"{height_num:.2f} m" if height_num > 0 else ""
        weight = f2.number_input("Player Weight (kg)", min_value=0, max_value=150, step=1, value=0, key="add_weight")
        weight_str = str(weight) if weight>0 else ""
        foot = f3.selectbox("Dominant Foot", ["", "Right", "Left", "Both"],
                            index=(["","Right","Left","Both"].index(st.session_state.get("new_Dominant Foot","")) if st.session_state.get("new_Dominant Foot","") in ["","Right","Left","Both"] else 0),
                            key="add_foot")

        # Agency / Contract presets (June 30 2026..2031)
        g1, g2, g3 = st.columns(3)
        agency_final = add_new_dropdown("Agency", existing_agencies,"add_agency_choice","new_Agency", st.session_state.get("new_Agency",""))
        preset_years = [2026, 2027, 2028, 2029, 2030, 2031]
        preset_labels = [f"06/{str(y)[-2:]}" for y in preset_years]
        preset_values = [date(y,6,30) for y in preset_years]
        preset_choice = g2.selectbox("Contract preset", ["— none —"] + preset_labels, key="add_contract_preset")
        custom_contract = g2.date_input("…or pick a date", format="YYYY-MM-DD", key="add_contract_date")
        if preset_choice != "— none —":
            pick_idx = preset_labels.index(preset_choice)
            contract_until_date = preset_values[pick_idx]
        else:
            contract_until_date = custom_contract if isinstance(custom_contract, date) else None
        contract_until = contract_until_date.strftime("%Y-%m-%d") if contract_until_date else str(st.session_state.get("new_Contract Until",""))
        source = g3.text_input("Transfermarkt URL", value=st.session_state.get("add_scrape_url",""), key="add_source")

        # Ratings and verdicts
        h1, h2, h3 = st.columns(3)
        rating_opts = ["","1","1.5","2","2.5","3","3.5","4"]
        current_rating = h1.selectbox("Current Rating (1–4, halves)", rating_opts, key="add_cr")
        potential_rating = h2.selectbox("Potential Rating (1–4, halves)", rating_opts, key="add_pr")
        verdict = h3.selectbox("Verdict", ["", "Shortlist", "Monitor", "Not a fit", "Sign", "Loan", "Trial"], key="add_verdict")

        # Watched field
        i1, i2 = st.columns(2)
        watched_choice = i1.selectbox("Watched", ["", "needs deep dive", "watched once", "watched 2–3x", "full report done", "Custom…"], key="add_watched_choice")
        watched_custom = i2.text_input("Custom watched note", key="add_watched_custom") if watched_choice == "Custom…" else ""
        watched_final = watched_custom if watched_choice == "Custom…" else watched_choice

        strengths = st.text_area("Strengths", key="add_strengths")
        weaknesses = st.text_area("Weaknesses", key="add_weaknesses")

        # TM values and CA/PA manual sliders
        j1, j2 = st.columns(2)
        tm_val = j1.text_input("TM Value", value=st.session_state.get("new_TM Value",""), key="add_tm")
        tm_val_hi = j2.text_input("Highest TM Value", value=st.session_state.get("new_Highest TM Value",""), key="add_tm_hi")

        k1, k2 = st.columns(2)
        ca_manual = k1.slider("Current Ability (manual)", min_value=0, max_value=100, value=0, key="add_ca_manual")
        pa_manual = k2.slider("Potential Ability (manual)", min_value=0, max_value=100, value=0, key="add_pa_manual")

        save_photo_local = st.checkbox("Also download and store player photo", value=True, key="add_save_photo")

        if st.button("Add to database", key="add_report_btn"):
            if not name.strip():
                st.error("Name is required.")
            else:
                tm_compact = fmt_eur_compact(parse_eur_value(tm_val)) if tm_val else ""
                tm_hi_compact = fmt_eur_compact(parse_eur_value(tm_val_hi)) if tm_val_hi else tm_val_hi

                # compute age from DOB if age empty
                if dob_in and not age.strip():
                    try:
                        today = date.today()
                        age_calc = today.year - dob_in.year - ((today.month, today.day) < (dob_in.month, dob_in.day))
                        age = str(age_calc)
                    except:
                        pass

                # prepare row
                row = {
                    "Name": _tidy_person_name(name.strip()),
                    "Position": pos_str.strip(),
                    "Age": age.strip(),
                    "DOB": dob_in.strftime("%Y-%m-%d") if dob_in else "",
                    "Age Group": age_group.strip(),
                    "Player Current Team": (team_final or "").strip(),
                    "Loan Club": loan_club.strip() if on_loan else "",
                    "On loan": "Yes" if on_loan else "No",
                    "Playing Nation": (playing_nation or "").strip(),
                    "Player Nationality": (nationality or "").strip(),
                    "Division": division.strip(),
                    "Dominant Foot": foot.strip(),
                    "Player Height": height_str.strip(),
                    "Player weight": weight_str.strip(),
                    "Agency": (agency_final or "").strip(),
                    "Contract Until": contract_until.strip(),
                    "Current Rating (1-4)": current_rating or "",
                    "Potential Rating (1-4)": potential_rating or "",
                    "Verdict": verdict.strip(),
                    "Watched": watched_final.strip(),
                    "Strengths": strengths.strip(),
                    "Weaknesses": weaknesses.strip(),
                    "Source": source.strip(),
                    "TM Value": tm_compact,
                    "Highest TM Value": tm_hi_compact,
                    "Current Ability (manual)": str(ca_manual) if ca_manual else "",
                    "Potential Ability (manual)": str(pa_manual) if pa_manual else "",
                }

                # Add photo fields BEFORE inserting
                photo_url = str(st.session_state.get("new_Photo URL","")).strip()
                photo_path = ""
                if save_photo_local and photo_url:
                    photo_path = download_image_to_disk(photo_url, row["Name"]) or ""
                row["Photo URL"] = photo_url
                row["Photo Path"] = photo_path

                df2 = add_or_update_row(df.copy(), row)
                write_db(st.session_state.db_csv, df2)

                st.success(f"✅ New player added: {row['Name']}")
                st.cache_data.clear()
                # clear temp states
                for k in list(st.session_state.keys()):
                    if k.startswith(("add_", "new_")):
                        del st.session_state[k]
                st.rerun()

    # ---- Table view & filters (right)
    with right:
        colf = st.columns(6)
        f_team   = colf[0].selectbox("Team", [""] + sorted(df["Player Current Team"].unique().tolist()))
        f_pos    = colf[1].selectbox("Position", [""] + sorted(df["Position"].unique().tolist()))
        f_verdict= colf[2].selectbox("Verdict", [""] + sorted(df["Verdict"].unique().tolist()))
        f_nation = colf[3].selectbox("Playing Nation", [""] + sorted(df["Playing Nation"].unique().tolist()))
        search   = colf[4].text_input("Search name")

        age_series_all = compute_age_series(df)
        amin = int(pd.to_numeric(age_series_all, errors="coerce").dropna().min()) if age_series_all.notna().any() else 15
        amax = int(pd.to_numeric(age_series_all, errors="coerce").dropna().max()) if age_series_all.notna().any() else 40
        age_min, age_max = colf[5].slider("Age", min_value=amin, max_value=amax, value=(amin, amax))

        view = df.copy()
        if f_team:   view = view[view["Player Current Team"] == f_team]
        if f_pos:    view = view[view["Position"] == f_pos]
        if f_verdict:view = view[view["Verdict"] == f_verdict]
        if f_nation: view = view[view["Playing Nation"] == f_nation]
        if search:   view = view[view["Name"].str.contains(search, case=False, na=False)]
        age_series_view = compute_age_series(view)
        view = view[(age_series_view >= age_min) & (age_series_view <= age_max)]

        # newest-first
        view = _sort_newest_first(view)

        st.caption(f"Showing {len(view)} of {len(df)}")
        view_show = view.assign(**{"Full report?": view["Full Report Path"].apply(lambda x: "Yes" if str(x).strip() else "")})

        edited = st.data_editor(view_show, use_container_width=True, num_rows="dynamic", key="all_editor")
        c1, c2, c3 = st.columns(3)
        if c1.button("Save changes"):
            to_save = edited.drop(columns=["Full report?"], errors="ignore")
            df.loc[to_save.index, :] = to_save
            write_db(st.session_state.db_csv, df); st.success("Saved."); st.cache_data.clear()
        export_buttons(edited, key_suf="_players")

# app.py — Part 3/6

# =========================
# 13) HOME PAGE (Depth, Position, Nation, Deep Dive)
# =========================
def normalize_roles_to_options(text: str) -> list[str]:
    """Normalize to ROLE_ORDER labels from stored strings like '7a', '7a - RWF', '7a/RWF'."""
    ROLE_PREFIX_TO_LABEL = {role.split(" - ")[0].strip(): role for role in ROLE_ORDER}
    raw = [p.strip() for p in (text or "").split(",") if p.strip()]
    cleaned: list[str] = []
    for p in raw:
        if p in ROLE_ORDER and p not in cleaned:
            cleaned.append(p); continue
        prefix = re.split(r"\s*[-/•|]\s*", p, 1)[0].strip()
        if prefix in ROLE_PREFIX_TO_LABEL:
            label = ROLE_PREFIX_TO_LABEL[prefix]
            if label not in cleaned:
                cleaned.append(label)
    return cleaned

if nav == "🏠 Home":
    left, right = st.columns([5,1])
    with left: st.title("FC Midtjylland Scouting Assistant")
    with right:
        lp = find_logo()
        if lp:
            st.markdown('<div class="header-logo">', unsafe_allow_html=True); st.image(lp); st.markdown('</div>', unsafe_allow_html=True)

    depth_df = load_depth(st.session_state.depth_csv).copy()
    df = load_db(st.session_state.db_csv).copy()
    df = _sort_newest_first(df)

    tab_pitch, tab_pos, tab_nat, tab_deep = st.tabs(["⚽ Team depth","🧭 By position","🌍 By nation","🧪 Deep dive required"])

    # ----- Team depth -----
    with tab_pitch:
        view_mode = st.toggle("Edit mode", value=False, help="Switch to edit the grid")

        def card_view(code: str):
            st.markdown('<div class="depth-card">', unsafe_allow_html=True)
            st.markdown(f'<div class="depth-label">{code}</div>', unsafe_allow_html=True)
            a = depth_df.at["1", code] if code in depth_df.columns else ""
            b = depth_df.at["2", code] if code in depth_df.columns else ""
            html = '<div class="chips">'
            if a: html += f'<span class="chip chip-first">{a}</span>'
            if b: html += f'<span class="chip chip-second">{b}</span>'
            html += '</div>'; st.markdown(html, unsafe_allow_html=True)
            with st.expander("3rd & 4th", expanded=False):
                c = depth_df.at["3", code] if code in depth_df.columns else ""
                d = depth_df.at["4", code] if code in depth_df.columns else ""
                html2 = '<div class="chips">'
                if c: html2 += f'<span class="chip">{c}</span>'
                if d: html2 += f'<span class="chip">{d}</span>'
                html2 += '</div>'; st.markdown(html2, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        def card_edit(code: str):
            st.markdown('<div class="depth-card">', unsafe_allow_html=True)
            st.markdown(f'<div class="depth-label">{code}</div>', unsafe_allow_html=True)
            for i in range(1, DEPTH_SLOTS+1):
                key = f"{code}_{i}"
                cur = depth_df.at[str(i), code] if code in depth_df.columns else ""
                depth_df.at[str(i), code] = st.text_input(f"{code} #{i}", value=cur, key=key, label_visibility="collapsed", placeholder=f"{code} #{i}")
            st.markdown('</div>', unsafe_allow_html=True)

        rows = [
            ["", "11a", "", "9", "9a", "", "7a", ""],
            ["", "", "10a", "10", "", ""],
            ["", "11", "", "6", "", "8", "", "7", ""],
            ["3", "", "5L", "4", "5R", "", "2"],
            ["", "", "", "GK", "", "", ""],
        ]

        st.subheader("On-pitch depth")
        st.markdown('<div class="pitch">', unsafe_allow_html=True)
        for row in rows:
            cols = st.columns(len(row))
            for col, code in zip(cols, row):
                with col:
                    if code: (card_edit if view_mode else card_view)(code)
        st.markdown('</div>', unsafe_allow_html=True)

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("Save depth chart"):
            save_depth(st.session_state.depth_csv, depth_df)
            st.success("Depth chart saved.")
            st.cache_data.clear()
        c2.download_button("Download depth chart (CSV)", data=depth_df.to_csv(index=True).encode("utf-8"), file_name="depth_fcm.csv", mime="text/csv")

    # ----- By position -----
    with tab_pos:
        st.subheader("Players by FCM role")
        view = df.copy()
        age_series_pos = compute_age_series(view)
        amin = int(pd.to_numeric(age_series_pos, errors="coerce").dropna().min()) if age_series_pos.notna().any() else 15
        amax = int(pd.to_numeric(age_series_pos, errors="coerce").dropna().max()) if age_series_pos.notna().any() else 40
        age_min_pos, age_max_pos = st.slider("Age range", min_value=amin, max_value=amax, value=(amin, amax), key="pos_age")
        view = view[(age_series_pos >= age_min_pos) & (age_series_pos <= age_max_pos)]

        # metrics table
        summary_rows = []
        for role in ROLE_ORDER:
            mask_role = view["Position"].apply(lambda x: role.lower() in [r.lower() for r in split_roles(x)])
            sub = view[mask_role]; total = len(sub)
            watched_cnt = int(sub["Watched"].astype(str).str.strip().ne("").sum())
            u21_cnt = 0
            for _, rr in sub.iterrows():
                age_num = calc_age_from_row(rr)
                if age_num is not None and age_num <= 21: u21_cnt += 1
            summary_rows.append({"Role": role, "Total": total, "Watched": watched_cnt, "Unwatched": total - watched_cnt, "U21": u21_cnt})
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True, height=280)

        cf1, cf2 = st.columns([2,2])
        roles_selected = cf1.multiselect("Choose roles", ROLE_ORDER, default=ROLE_ORDER)
        name_q = cf2.text_input("Search name")

        if name_q: view = view[view["Name"].str.contains(name_q, case=False, na=False)]
        chosen_roles = roles_selected or ROLE_ORDER

        st.markdown("#### Role metrics")
        for role in chosen_roles:
            mask_role = view["Position"].apply(lambda x: role.lower() in [r.lower() for r in split_roles(x)])
            sub = view[mask_role]; total = len(sub)
            watched_cnt = int(sub["Watched"].astype(str).str.strip().ne("").sum())
            unwatched = total - watched_cnt
            u21_cnt = 0
            for _, rr in sub.iterrows():
                age_num = calc_age_from_row(rr)
                if age_num is not None and age_num <= 21: u21_cnt += 1
            c1, c2, c3 = st.columns(3)
            with c1: st.metric(label=f"{role} — Total", value=total)
            with c2: st.metric(label="Watched / Unwatched", value=f"{watched_cnt} / {unwatched}")
            with c3: st.metric(label="U21", value=u21_cnt)
        st.markdown("---")

        buckets: Dict[str, List[pd.Series]] = {r: [] for r in chosen_roles}
        for _, row in view.iterrows():
            roles = [rr.lower() for rr in split_roles(row.get("Position",""))]
            for r in chosen_roles:
                if r.lower() in roles: buckets[r].append(row)

        for role in chosen_roles:
            players = buckets.get(role, [])
            st.markdown(f"**{role} — {len(players)}**")
            cols = st.columns(3)
            for i, r in enumerate(players):
                with cols[i % 3]: render_player_card(r, key_prefix=f"{role}_{i}")
            st.markdown("<hr/>", unsafe_allow_html=True)

    # ----- By nation -----
    with tab_nat:
        st.subheader("Players by nation")
        nat = st.selectbox("Choose playing nation", [""] + sorted(df["Playing Nation"].unique().tolist()))
        v = df if not nat else df[df["Playing Nation"] == nat]

        age_series_nat = compute_age_series(v)
        amin = int(pd.to_numeric(age_series_nat, errors="coerce").dropna().min()) if age_series_nat.notna().any() else 15
        amax = int(pd.to_numeric(age_series_nat, errors="coerce").dropna().max()) if age_series_nat.notna().any() else 40
        age_min_nat, age_max_nat = st.slider("Age range", min_value=amin, max_value=amax, value=(amin, amax), key="nat_age")
        v = v[(age_series_nat >= age_min_nat) & (age_series_nat <= age_max_nat)]

        st.caption(f"{len(v)} players")
        cols = st.columns(3)
        for i, (_, r) in enumerate(v.iterrows()):
            with cols[i % 3]: render_player_card(r, key_prefix=f"nat_{i}")

    # ----- Deep dive -----
    with tab_deep:
        st.subheader("Players requiring deep dive")
        rule = st.selectbox("Rule", ["Watched contains 'deep'", "Watched is empty", "Custom keyword…"], index=0)
        if rule == "Watched contains 'deep'":
            mask = df["Watched"].str.contains("deep", case=False, na=False)
        elif rule == "Watched is empty":
            mask = df["Watched"].str.strip().eq("") | df["Watched"].isna()
        else:
            kw = st.text_input("Keyword", value="deep"); mask = df["Watched"].str.contains(kw, case=False, na=False)
        dd = df[mask].copy(); st.caption(f"{len(dd)} players")
        base_dir = os.path.join("FCM Scouting", "full reports done"); os.makedirs(base_dir, exist_ok=True)
        df_all = df.copy(); changed = False
        for idx, r in dd.iterrows():
            with st.container(border=True):
                has_report = bool(r.get("Full Report Path","").strip())
                badge = ' <span class="badge">📄 Full report</span>' if has_report else ""
                st.markdown(f"**{r['Name']}** — {r['Position']} • {r['Player Current Team']}{badge}", unsafe_allow_html=True)
                st.caption(f"Watched: {r['Watched']}")
                done = st.checkbox("Full report done", value=has_report, key=f"rep_{idx}")
                up = None
                if done and not has_report:
                    up = st.file_uploader("Upload full report (PDF)", type=["pdf"], key=f"pdf_{idx}")
                if done and up is not None:
                    date_str = dt.datetime.now().strftime("%Y-%m-%d")
                    safe_name = re.sub(r"[^\w\-. ]", "_", r["Name"])
                    fp = os.path.join(base_dir, f"{safe_name} - {date_str}.pdf")
                    with open(fp, "wb") as f: f.write(up.read())
                    new_watch = (r["Watched"] + f" | full report done {date_str}").strip()
                    df_all.at[idx, "Watched"] = new_watch
                    df_all.at[idx, "Full Report Path"] = fp
                    changed = True; st.success(f"Saved report for {r['Name']}")
        if changed:
            write_db(st.session_state.db_csv, df_all); st.success("Database updated with full reports."); st.cache_data.clear()


# =========================
# 14) PLAYER REPORTS PAGE
# =========================
def get_profile_template(primary_role: str) -> Dict[str, List[str]]:
    sections = [
        "Attacking - Off-ball & On-ball",
        "Defensive - Off-ball & On-ball",
        "Physical Capacity & Anthropometric",
        "Psychosocial & Game Knowledge/IQ",
        "Tactical Fit",
        "Set-Pieces",
        "Extra Notes",
        "Conclusion"
    ]
    r = (primary_role or "").lower()
    if r in ["2","3"]:
        kpis = ["1v1 Defending","Positioning & Recovery Runs","Build-up under Pressure",
                "Over/Underlap Timing","Effective Crossing","Aerial at Back Post","Set-pieces"]
    elif r in ["11","7","11a","7a"]:
        kpis = ["1v1 Attacking/Dribbling","Final Pass / Chance Creation","Crossing Quality",
                "Speed, Agility, Power","Pressing & Track-back","End Product (G+A threat)","Set-pieces"]
    elif r in ["9","9a"]:
        kpis = ["Finishing / Box Presence","Movement (Near/Far/Across)","Back-to-Goal / Link-Up",
                "Aerial Duels","Speed & Power","Defensive Pressing","Set-pieces (Pens)"]
    elif r in ["10","10a"]:
        kpis = ["Vision & Through Balls","Decision-making in Final Third","Ball Carrying Between Lines",
                "Press Resistance","Finds Pockets / Off-ball","Counterpress & Workrate","Set-pieces"]
    elif r == "8":
        kpis = ["Engine / Repeat High Intensity","Progressive Passing","Ball Carrying",
                "Press Resistance","Defensive Duels / Transition Cover","Counterpress & Pressing","Set-pieces"]
    elif r == "6":
        kpis = ["Screening / Positioning","Build-up Passing Range","Press Resistance",
                "Aerial & Ground Duels","Tempo Control","Pressing Triggers & Protection","Set-pieces (Deep)"]
    elif r in ["4","5l","5r"]:
        kpis = ["Aerial Duels","1v1 Defending","Line Control & Positioning","Ball Progression (Passing)",
                "Speed/Recovery for Depth","Leadership & Communication","Set-pieces (Both Boxes)"]
    elif r == "gk":
        kpis = ["Shot-stopping","1v1 Goalkeeping","Aerial Claims/Crosses","Distribution (Short & Long)",
                "Sweeper Actions","Communication/Organization","Set-pieces"]
    else:
        kpis = ["1v1 Defending","Effective Crossing","Workrate & Pressing","Speed, Agility, Power","Offensive Threat","Set-pieces"]
    return {"sections": sections, "kpis": kpis}

def profile_editor(df: pd.DataFrame, row_index: int) -> pd.DataFrame:
    row = df.loc[row_index].copy()
    primary_role = get_primary_role(row)
    tmpl = get_profile_template(primary_role)
    st.caption(f"Primary role: **{primary_role or 'N/A'}**")

    kpi_cols = [f"KPI: {k}" for k in tmpl["kpis"]] + ["KPI: Average"]
    section_cols = [f"Profile: {s}" for s in tmpl["sections"]]
    df = ensure_columns(df, kpi_cols + section_cols)

    st.markdown("##### Positional KPI (1–4, halves ok)")
    kpi_vals = []
    for k in tmpl["kpis"]:
        col = f"KPI: {k}"
        try:
            cur = float(df.at[row_index, col]) if str(df.at[row_index, col]).strip() not in ["","nan"] else 0.0
        except:
            cur = 0.0
        v = st.number_input(k, min_value=0.0, max_value=4.0, step=0.5, value=cur, key=f"kpi_{row_index}_{k}")
        kpi_vals.append(v)
    avg = round(sum(kpi_vals)/len(kpi_vals),2) if kpi_vals else 0.0
    st.metric("Average KPI", avg)
    st.markdown("---")

    note_vals: Dict[str,str] = {}
    for sname in tmpl["sections"]:
        col = f"Profile: {sname}"
        cur = str(df.at[row_index, col]) if col in df.columns else ""
        note_vals[sname] = st.text_area(sname, value=cur, key=f"note_{row_index}_{sname}", height=120 if sname!="Conclusion" else 100)

    if st.button("💾 Save profile", type="primary", key=f"save_profile_{row_index}"):
        for k, v in zip(tmpl["kpis"], kpi_vals):
            df.at[row_index, f"KPI: {k}"] = "" if v==0 else str(v)
        df.at[row_index, "KPI: Average"] = "" if avg==0 else str(avg)
        for sname, txt in note_vals.items():
            df.at[row_index, f"Profile: {sname}"] = txt.strip()
        df.at[row_index, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_db(st.session_state.db_csv, df)
        st.success("Profile saved.")
        st.cache_data.clear()
    return df

# Stable focus keys for detail page
def _focus_key_from_row(r: pd.Series) -> str:
    return f"{_norm_str(r.get('Name',''))}|{_norm_str(r.get('Player Current Team',''))}"

def _resolve_focus_index(df: pd.DataFrame, stored_key: Optional[str]) -> Optional[int]:
    if stored_key:
        name_key, team_key = stored_key.split("|")
        mask = (df["Name"].map(_norm_str) == name_key) & (df["Player Current Team"].map(_norm_str) == team_key)
        if mask.any():
            return df[mask].index[0]
    return None

if nav == "📝 Player reports":
    st.title("Player reporting")
    df = load_db(st.session_state.db_csv).copy()
    df = _sort_newest_first(df)

    if "profile_focus_key" not in st.session_state:
        st.session_state.profile_focus_key = None

    # ---- Filters
    fcols = st.columns([2,2,2,2,2,2])
    name_q   = fcols[0].text_input("Search name", key="rep_search")
    f_team   = fcols[1].selectbox("Team", [""] + sorted(df["Player Current Team"].unique().tolist()), key="rep_team")
    f_role   = fcols[2].selectbox("Role (contains)", [""] + ROLE_ORDER, key="rep_role")
    f_nation = fcols[3].selectbox("Playing Nation", [""] + sorted(df["Playing Nation"].unique().tolist()), key="rep_nat")
    f_verdict= fcols[4].selectbox("Verdict", [""] + sorted(df["Verdict"].unique().tolist()), key="rep_verdict")

    age_series_rep_all = compute_age_series(df)
    amin = int(pd.to_numeric(age_series_rep_all, errors="coerce").dropna().min()) if age_series_rep_all.notna().any() else 15
    amax = int(pd.to_numeric(age_series_rep_all, errors="coerce").dropna().max()) if age_series_rep_all.notna().any() else 40
    age_min_rep, age_max_rep = fcols[5].slider("Age", min_value=amin, max_value=amax, value=(amin, amax), key="rep_age")

    # restore focus index if we have a stable key
    if st.session_state.profile_focus is None and st.session_state.profile_focus_key:
        idx_res = _resolve_focus_index(df, st.session_state.profile_focus_key)
        if idx_res is not None:
            st.session_state.profile_focus = idx_res

    focus_idx = st.session_state.profile_focus

    # ===== DETAIL PAGE =====
    if focus_idx is not None and focus_idx in df.index:
        r = df.loc[focus_idx]

        back_col, _sp = st.columns([1,9])
        with back_col:
            if st.button("← Back to list", use_container_width=True, key=f"rep_back_{focus_idx}"):
                st.session_state.profile_focus = None
                st.session_state.profile_focus_key = None
                st.rerun()

        st.markdown("---")

        # --- Header area: image left, details right (+ TM link) with loan-aware header
        img_col, info_col = st.columns([1,3])
        with img_col:
            img_src = r.get("Photo Path","").strip() or r.get("Photo URL","").strip()
            if img_src:
                st.image(img_src, width=220)
        with info_col:
            st.subheader(r.get("Name",""))
            loan_flag = str(r.get("On loan","")).strip().lower() == "yes"
            loan_club = r.get("Loan Club","").strip()
            parent = r.get("Player Current Team","").strip()
            current_label = f"{loan_club} → {parent}" if loan_flag and loan_club else parent
            st.caption(
                f"{current_label} • {r.get('Position','')} "
                f"• Age: {r.get('Age','')} | Height: {r.get('Player Height','')} | Foot: {r.get('Dominant Foot','')}"
            )
            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("TM Value", r.get("TM Value",""))
            with m2: st.metric("Agency", r.get("Agency",""))
            with m3: st.metric("Citizenship", r.get("Player Nationality",""))
            with m4: st.metric("Contract until", r.get("Contract Until",""))
            # Transfermarkt URL action row
            tm_url = st.text_input("Transfermarkt URL", value=r.get("Source",""), key=f"tm_url_{focus_idx}")
            cols_fetch = st.columns([1,2,2])
            if cols_fetch[0].button("Fetch from Transfermarkt (fill empty)", key=f"tm_fetch_{focus_idx}"):
                if tm_url.strip():
                    data, msg = scrape_transfermarkt(tm_url.strip())
                    if msg: st.info(msg)
                    if data:
                        # only fill empty fields; normalise TM value on the way in
                        filled = 0
                        for k, v in data.items():
                            if k == "TM Value":
                                if not str(df.at[focus_idx, "TM Value"]).strip() and v:
                                    df.at[focus_idx, "TM Value"] = v; filled += 1
                            elif k == "Contract Until":
                                if not str(df.at[focus_idx, "Contract Until"]).strip() and v:
                                    df.at[focus_idx, "Contract Until"] = v; filled += 1
                            elif k in df.columns and not str(df.at[focus_idx, k]).strip() and v:
                                df.at[focus_idx, k] = v; filled += 1

                        # set Source to TM URL if empty
                        if not str(df.at[focus_idx, "Source"]).strip():
                            df.at[focus_idx, "Source"] = tm_url.strip()

                        # try download photo if we still don't have a local path
                        if str(df.at[focus_idx, "Photo Path"]).strip() == "":
                            pu = str(df.at[focus_idx, "Photo URL"]).strip()
                            if pu:
                                saved = download_image_to_disk(pu, df.at[focus_idx, "Name"])
                                if saved:
                                    df.at[focus_idx, "Photo Path"] = saved

                        df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        # persist and keep focus stable via key
                        st.session_state.profile_focus_key = _focus_key_from_row(df.loc[focus_idx])
                        write_db(st.session_state.db_csv, df)
                        st.success(f"Details updated from Transfermarkt. Fields filled: {filled}")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.warning("Please paste a Transfermarkt URL.")

        st.markdown("---")

        # -------- General details (editable) with DOB bounds, contract presets, CA/PA sliders
        with st.form(key=f"gen_{focus_idx}", clear_on_submit=False):
            g1, g2, g3 = st.columns(3)
            name_val   = g1.text_input("Name", value=r.get("Name",""))
            # loan aware team editing
            loan_edit = g2.checkbox("On loan?", value=(str(r.get("On loan","")).strip().lower()=="yes"), key=f"loan_edit_{focus_idx}")
            team_val   = g3.text_input("Parent club (Player Current Team)", value=r.get("Player Current Team",""))

            loan_club_val = ""
            if loan_edit:
                loan_club_val = st.text_input("Loan club (current team)", value=r.get("Loan Club",""), key=f"loanclub_{focus_idx}")

            # Division dropdown with add
            existing_divisions = sorted([t for t in df["Division"].astype(str).unique().tolist() if t and t != "nan"])
            _div_choice = [""] + existing_divisions + ["Add new…"]
            cur_div = r.get("Division","")
            div_idx = _div_choice.index(cur_div) if cur_div in _div_choice else 0
            _sel = st.selectbox("Division", _div_choice, index=div_idx, key=f"div_sel_{focus_idx}")
            division_val = _sel if _sel != "Add new…" else st.text_input("New division", key=f"div_new_{focus_idx}")

            # Positions (multiselect over ROLE_ORDER)
            cur_roles = normalize_roles_to_options(r.get("Position",""))
            pos_sel   = st.multiselect("Positions (first = primary)", ROLE_ORDER, default=cur_roles, key=f"pos_sel_{focus_idx}")
            pos_val   = ", ".join(pos_sel)

            # Agency / foot / height
            row_agencies      = df["Agency"].astype(str).tolist()
            h1, h2, h3 = st.columns(3)
            agencies = [""] + sorted(set([x for x in row_agencies if x])) + ["Add new…"]
            cur_ag = r.get("Agency","")
            ag = h1.selectbox("Agency", agencies, index=(agencies.index(cur_ag) if cur_ag in agencies else 0), key=f"agency_{focus_idx}")
            agency_val = ag if ag != "Add new…" else st.text_input("New agency", key=f"agency_new_{focus_idx}")

            foot_val   = h2.selectbox("Dominant Foot", ["", "Right", "Left", "Both"],
                                      index=(["","Right","Left","Both"].index(r.get("Dominant Foot",""))
                                             if r.get("Dominant Foot","") in ["","Right","Left","Both"] else 0))
            height_txt = (r.get("Player Height","") or "").lower().replace("m","").strip()
            try: height_default = float(height_txt) if height_txt else 0.0
            except: height_default = 0.0
            height_val_num = h3.number_input("Player Height (m)", min_value=0.0, max_value=2.5, step=0.01, value=height_default)

            # Nationality / Playing nation
            n1, n2, n3 = st.columns(3)
            row_citizenships  = df["Player Nationality"].astype(str).tolist()
            row_play_nations  = df["Playing Nation"].astype(str).tolist()
            cits = [""] + sorted(set([x for x in row_citizenships if x])) + ["Add new…"]
            cur_nat = r.get("Player Nationality","")
            nat_sel = n1.selectbox("Player Nationality (citizenship)", cits, index=(cits.index(cur_nat) if cur_nat in cits else 0), key=f"cit_{focus_idx}")
            nat_val      = nat_sel if nat_sel != "Add new…" else st.text_input("New nationality", key=f"cit_new_{focus_idx}")
            plats = [""] + sorted(set([x for x in row_play_nations if x])) + ["Add new…"]
            cur_pl = r.get("Playing Nation","")
            pl_sel = n2.selectbox("Playing Nation (league country)", plats, index=(plats.index(cur_pl) if cur_pl in plats else 0), key=f"plnat_{focus_idx}")
            play_nat_val = pl_sel if pl_sel != "Add new…" else st.text_input("New playing nation", key=f"plnat_new_{focus_idx}")
            tm_val = n3.text_input("TM Value", value=r.get("TM Value",""))

            # DOB / Age / Contract with presets
            d1, d2, d3 = st.columns(3)
            dob_raw = r.get("DOB",""); dob_default = None
            try:
                if dob_raw:
                    y,m,d = map(int, str(dob_raw).split("-")); dob_default = date(y,m,d)
            except: ...
            dob_in = d1.date_input("DOB", value=dob_default, min_value=date(1900,1,1), max_value=date(2100,12,31), format="YYYY-MM-DD", key=f"dob_{focus_idx}")
            age_val = d2.text_input("Age", value=r.get("Age",""))

            # contract presets
            preset_years = [2026,2027,2028,2029,2030,2031]
            preset_labels = [f"06/{str(y)[-2:]}" for y in preset_years]
            preset_values = [date(y,6,30) for y in preset_years]
            preset_choice2 = d3.selectbox("Contract preset", ["— none —"] + preset_labels, key=f"contract_preset_{focus_idx}")
            contract_raw = r.get("Contract Until",""); contract_default = None
            try:
                if contract_raw:
                    y,m,d = map(int, str(contract_raw).split("-")); contract_default = date(y,m,d)
            except: ...
            contract_in = d3.date_input("…or pick a date", value=contract_default, format="YYYY-MM-DD", key=f"contract_date_{focus_idx}")
            # compute contract value
            if preset_choice2 != "— none —":
                cidx = preset_labels.index(preset_choice2); contract_until_val = preset_values[cidx]
            else:
                contract_until_val = contract_in

            # Highest TM, Source, CA/PA manual sliders
            t1, t2 = st.columns(2)
            tm_hi_val = t1.text_input("Highest TM Value", value=r.get("Highest TM Value",""))
            source_val= t2.text_input("Transfermarkt URL", value=r.get("Source",""))

            u1, u2 = st.columns(2)
            try:
                ca_default = int(str(r.get("Current Ability (manual)","") or "0"))
            except: ca_default = 0
            try:
                pa_default = int(str(r.get("Potential Ability (manual)","") or "0"))
            except: pa_default = 0
            ca_manual = u1.slider("Current Ability (manual)", min_value=0, max_value=100, value=ca_default, key=f"ca_{focus_idx}")
            pa_manual = u2.slider("Potential Ability (manual)", min_value=0, max_value=100, value=pa_default, key=f"pa_{focus_idx}")

            saved_general = st.form_submit_button("💾 Save general details")
            if saved_general:
                # normalize TM values on save
                tm_compact = fmt_eur_compact(parse_eur_value(tm_val)) if tm_val else ""
                tm_hi_compact = fmt_eur_compact(parse_eur_value(tm_hi_val)) if tm_hi_val else tm_hi_val

                df.at[focus_idx, "Name"] = _tidy_person_name(name_val.strip())
                df.at[focus_idx, "Player Current Team"] = team_val.strip()
                df.at[focus_idx, "Division"] = division_val.strip()
                df.at[focus_idx, "Position"] = pos_val.strip()
                df.at[focus_idx, "Agency"] = agency_val.strip()
                df.at[focus_idx, "Dominant Foot"] = foot_val.strip()
                df.at[focus_idx, "Player Height"] = (f"{height_val_num:.2f} m" if height_val_num > 0 else "")
                df.at[focus_idx, "Player Nationality"] = nat_val.strip()
                df.at[focus_idx, "Playing Nation"] = play_nat_val.strip()
                df.at[focus_idx, "TM Value"] = tm_compact
                df.at[focus_idx, "Highest TM Value"] = tm_hi_compact
                df.at[focus_idx, "Source"] = source_val.strip()

                # loan fields
                df.at[focus_idx, "On loan"] = "Yes" if loan_edit else "No"
                df.at[focus_idx, "Loan Club"] = loan_club_val.strip() if loan_edit else ""

                if dob_in:
                    df.at[focus_idx, "DOB"] = dob_in.strftime("%Y-%m-%d")
                    try:
                        today = date.today()
                        age_calc = today.year - dob_in.year - ((today.month, today.day) < (dob_in.month, dob_in.day))
                        df.at[focus_idx, "Age"] = str(age_calc) if not str(age_val).strip() else str(age_val).strip()
                    except: ...
                else:
                    df.at[focus_idx, "Age"] = str(age_val).strip()

                if contract_until_val:
                    df.at[focus_idx, "Contract Until"] = contract_until_val.strftime("%Y-%m-%d")

                df.at[focus_idx, "Current Ability (manual)"] = str(ca_manual) if ca_manual else ""
                df.at[focus_idx, "Potential Ability (manual)"] = str(pa_manual) if pa_manual else ""

                df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # keep focus stable
                st.session_state.profile_focus_key = _focus_key_from_row(df.loc[focus_idx])
                write_db(st.session_state.db_csv, df)
                st.success("General details saved.")
                st.cache_data.clear()
                st.rerun()

        # --- Scouting notes & KPIs
        st.markdown("---")
        st.subheader("📝 Scouting notes & KPIs")
        df = profile_editor(df, focus_idx)

        # --- Full report files
        st.markdown("---")
        st.subheader("📄 Full report")
        REPORTS_DIR = os.path.join("FCM Scouting", "full reports done")
        os.makedirs(REPORTS_DIR, exist_ok=True)

        # reload r in case we saved above
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
                    # keep focus key
                    st.session_state.profile_focus_key = _focus_key_from_row(df.loc[focus_idx])
                    write_db(st.session_state.db_csv, df)
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
       
        # After saving general details and before the PDF/full report section:
        render_wyscout_linker_and_cohort(df, focus_idx)

        # ---- PDF preview
        if cur_pdf_path and os.path.exists(cur_pdf_path):
            mode = st.radio(
                "Preview mode",
                ["Image pages (compatible)", "Embedded (may be blocked by ad blockers)"],
                index=0,
                horizontal=True,
                key=f"pdf_mode_{focus_idx}"
            )

            def _embed_pdf_data_uri(pdf_path: str, height: int = 900) -> bool:
                try:
                    with open(pdf_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    src = f"data:application/pdf;base64,{b64}#toolbar=1&navpanes=0&scrollbar=1"
                    components.html(
                        f'<object data="{src}" type="application/pdf" width="100%" height="{height}">'
                        f'<iframe src="{src}" width="100%" height="{height}" style="border:none;"></iframe>'
                        f'</object>',
                        height=height,
                    )
                    return True
                except Exception as e:
                    st.warning(f"Could not embed PDF: {e}")
                    return False

            def _render_pdf_as_images(pdf_path: str, max_pages: int = 30, dpi: int = 160):
                if fitz is None or Image is None:
                    st.info("For image previews, install PyMuPDF and Pillow:\n\n`pip install pymupdf pillow`")
                    return
                try:
                    doc = fitz.open(pdf_path)
                    total = min(len(doc), max_pages)
                    for i in range(total):
                        page = doc.load_page(i)
                        mat = fitz.Matrix(dpi/72, dpi/72)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        img_bytes = pix.tobytes("png")
                        st.image(Image.open(io.BytesIO(img_bytes)), caption=f"Page {i+1}", use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render PDF pages: {e}")

            if mode.startswith("Image"):
                max_pages = st.slider("Pages to render", 1, 40, 20, key=f"pdf_pages_{focus_idx}")
                dpi = st.slider("Render DPI", 110, 200, 160, key=f"pdf_dpi_{focus_idx}")
                _render_pdf_as_images(cur_pdf_path, max_pages=max_pages, dpi=dpi)
            else:
                ok = _embed_pdf_data_uri(cur_pdf_path, height=900)
                if not ok:
                    st.info("If the embed is blocked by your browser, switch preview mode to **Image pages** above.")

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
                df_latest = load_db(st.session_state.db_csv).copy()
                row_current = df.loc[focus_idx]

                for col in ["Full Report Path", "Photo Path"]:
                    _safe_unlink(str(row_current.get(col, "")).strip())

                if focus_idx in df_latest.index:
                    df_latest = df_latest.drop(index=focus_idx, errors="ignore")
                else:
                    name_key = _norm_str(row_current.get("Name", ""))
                    team_key = _norm_str(row_current.get("Player Current Team", ""))
                    mask = (
                        df_latest["Name"].apply(_norm_str) == name_key
                    ) & (
                        df_latest["Player Current Team"].apply(_norm_str) == team_key
                    )
                    df_latest = df_latest[~mask].copy()

                write_db(st.session_state.db_csv, df_latest)
                st.cache_data.clear()

                st.success("Player deleted.")
                st.session_state.profile_focus = None
                st.session_state.profile_focus_key = None
                st.rerun()

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

        cards_per_row = 3
        idxs = view.index.tolist()
        for start in range(0, len(idxs), cards_per_row):
            cols = st.columns(cards_per_row)
            for col, idx in zip(cols, idxs[start:start+cards_per_row]):
               with col:
                   row = view.loc[idx]
                   render_player_card(row, key_prefix=f"rep_{idx}", show_more=False)
                   if st.button("Open report", key=f"open_{idx}", use_container_width=True):
                        st.session_state.profile_focus = idx
                        st.session_state.profile_focus_key = _focus_key_from_row(row)
                        st.rerun()

# app.py — Part 4/6
# =========================
# 16) 📅 FIXTURES (Multi-nation) — Season 25/26
# =========================

# ---- Season window (25/26) ----
SEASON_START_2526 = date(2025, 7, 1)
SEASON_END_2526   = date(2026, 6, 30)
UPCOMING_WINDOW_DAYS = 14

# ---- Where fixtures live on disk ----
# Put each nation’s fixture CSVs inside these folders. You can change these.
FIXTURES_ROOT = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Fixtures"
NATION_FOLDERS = {
    "Belgium":     os.path.join(FIXTURES_ROOT, "Belgium"),
    "Netherlands": os.path.join(FIXTURES_ROOT, "Netherlands"),
    "France":      os.path.join(FIXTURES_ROOT, "France"),
    "Other":       os.path.join(FIXTURES_ROOT, "Other"),
}
# Make sure the folders exist
for _nf in NATION_FOLDERS.values():
    os.makedirs(_nf, exist_ok=True)

# ---- Simple, stable tiny hash for Streamlit widget keys ----
def _tiny_key(s: str) -> str:
    try:
        import hashlib
        return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:10]
    except Exception:
        return str(abs(hash(s)))  # fallback

# ---- Team name normalisation and synonyms ----
TEAM_SYNONYMS = {
    # Examples; extend as needed
    "psv": {"psv", "psv eindhoven", "p.s.v."},
    "ajax": {"ajax", "afc ajax"},
    "antwerp": {"royal antwerp", "r antwerp", "antwerp"},
    "olympique lyon": {"olympique lyon", "ol lyon", "lyon"},
    "olympique marseille": {"olympique de marseille", "olympique marseille", "marseille", "om"},
}
def _canonical_team(name: str) -> str:
    key = _norm_str(name)
    for canon, variants in TEAM_SYNONYMS.items():
        if key in {_norm_str(v) for v in variants}:
            return canon
    return name.strip()

# ---- Load a fixture CSV (Transfermarkt-like dump you already have) ----
# Expected columns: Title, Given planned earliest start, Given planned earliest end
@st.cache_data(show_spinner=False)
def load_fixtures_csv(path: str, season_start: date, season_end: date) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=["Fixture ID","Title","KO_date","Home","Away","Watched"])
    # Handle tricky encodings and separators
    attempts = [
        dict(sep=None, engine="python", encoding="utf-8-sig"),
        dict(sep=None, engine="python", encoding="cp1252"),
        dict(sep=None, engine="python", encoding="latin1"),
    ]
    for opt in attempts:
        try:
            raw = pd.read_csv(path, **opt)
            break
        except Exception:
            raw = None
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["Fixture ID","Title","KO_date","Home","Away","Watched"])

    # Standardise columns that might have stray spaces
    cols = {c.strip(): c for c in raw.columns}
    def _pick(name: str) -> str:
        for c in cols:
            if _norm_str(c) == _norm_str(name):
                return cols[c]
        return name

    col_title = _pick("Title")
    col_start = _pick("Given planned earliest start")
    col_end   = _pick("Given planned earliest end")

    df = raw.copy()
    if col_title not in df.columns: df[col_title] = ""
    if col_start not in df.columns: df[col_start] = ""

    # Parse KO date from dd/mm/yyyy (as you noted)
    def _parse_dmy(x):
        s = str(x).strip()
        # try dd/mm/yyyy HH:MM, dd/mm/yyyy, etc
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return pd.to_datetime(s, format=fmt, errors="raise").date()
            except Exception:
                pass
        try:
            return pd.to_datetime(s, errors="coerce").date()
        except Exception:
            return pd.NaT

    df["KO_date"] = df[col_start].apply(_parse_dmy)
    # Extract Home/Away from Title: “Home - Away” or “Home vs Away”
    def _split_title(t):
        s = str(t)
        if " - " in s:
            a, b = s.split(" - ", 1)
            return a.strip(), b.strip()
        if " vs " in s.lower():
            parts = re.split(r"\s+vs\s+", s, flags=re.IGNORECASE)
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
        return "", ""

    HA = df[col_title].apply(_split_title)
    df["Home"] = [ _canonical_team(a) for a, _ in HA ]
    df["Away"] = [ _canonical_team(b) for _, b in HA ]

    # Add watched column if missing
    if "Watched" not in df.columns:
        df["Watched"] = ""

    # Fixture ID stable per row content + file
    fkey = _tiny_key(path)
    df["Fixture ID"] = df.apply(lambda r: _tiny_key(f"{fkey}|{r.get(col_title,'')}|{r.get('KO_date','')}"), axis=1)

    # Season filter
    df = df[(pd.to_datetime(df["KO_date"], errors="coerce").dt.date >= season_start) &
            (pd.to_datetime(df["KO_date"], errors="coerce").dt.date <= season_end)].copy()

    # Cast KO_date to date
    df["KO_date"] = pd.to_datetime(df["KO_date"], errors="coerce").dt.date
    return df[["Fixture ID","Title","KO_date","Home","Away","Watched"]]

# ---- Persist watched flag back into its CSV (by Title+KO_date best-effort) ----
def toggle_fixture_watched(path: str, fixture_id: str, watched_state: bool) -> bool:
    try:
        attempts = [
            dict(sep=None, engine="python", encoding="utf-8-sig"),
            dict(sep=None, engine="python", encoding="cp1252"),
            dict(sep=None, engine="python", encoding="latin1"),
        ]
        for opt in attempts:
            try:
                df = pd.read_csv(path, **opt); break
            except Exception:
                df = None
        if df is None:
            return False

        # Rebuild the same ID logic to find row(s)
        col_title = [c for c in df.columns if _norm_str(c) == _norm_str("Title")]
        col_start = [c for c in df.columns if _norm_str(c) == _norm_str("Given planned earliest start")]
        if not col_title or not col_start:
            return False
        col_title = col_title[0]; col_start = col_start[0]
        tmp = df.copy()
        tmp["__KO_date"] = pd.to_datetime(tmp[col_start], errors="coerce")
        tmp["__KO_date"] = tmp["__KO_date"].dt.date
        fkey = _tiny_key(path)
        tmp["__fid"] = tmp.apply(lambda r: _tiny_key(f"{fkey}|{r.get(col_title,'')}|{r.get('__KO_date','')}"), axis=1)

        mask = (tmp["__fid"] == fixture_id)
        if not mask.any():
            # If we cannot find exact, do nothing gracefully
            return True

        # Ensure column Watched exists
        if "Watched" not in df.columns:
            df["Watched"] = ""
        df.loc[mask.index[mask], "Watched"] = "Yes" if watched_state else "No"

        # Write back, preserving encoding
        tmpfile = f"{path}.tmp"
        df.to_csv(tmpfile, index=False, encoding="utf-8-sig")
        os.replace(tmpfile, path)
        st.cache_data.clear()
        return True
    except Exception:
        return False

# ---- Read all CSVs per nation folder ----
def _list_league_files(nation: str) -> list[str]:
    folder = NATION_FOLDERS.get(nation)
    if not folder or not os.path.exists(folder):
        return []
    files = [f for f in os.listdir(folder) if f.lower().endswith(".csv")]
    files.sort()
    return files

@st.cache_data(show_spinner=False)
def load_all_selected_fixtures(season_start: date, season_end: date) -> list[tuple[str, str, pd.DataFrame]]:
    bundles = []
    for nation, folder in NATION_FOLDERS.items():
        if not os.path.exists(folder): continue
        for fn in _list_league_files(nation):
            path = os.path.join(folder, fn)
            fx = load_fixtures_csv(path, season_start, season_end)
            if not fx.empty:
                bundles.append((nation, path, fx))
    return bundles

# ---- Quick grouping helpers for General / Calendar ----
def week_bounds(anchor: date) -> tuple[date, date]:
    # week Monday..Sunday
    start = anchor - dt.timedelta(days=anchor.weekday())
    end = start + dt.timedelta(days=6)
    return start, end

def group_fixtures_by_day(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    d = {}
    for _dday, sub in df.groupby(df["KO_date"]):
        d[_dday] = sub.sort_values(["KO_date","Title"])
    return d

# ---- Link players to fixtures (basic: by club name, including Loan Club) ----
def _players_for_fixture(players_df: pd.DataFrame, home: str, away: str, nation: str) -> tuple[list[pd.Series], list[pd.Series]]:
    h = _canonical_team(home); a = _canonical_team(away)
    def _belongs(row: pd.Series, team_name: str) -> bool:
        team = _canonical_team(str(row.get("Player Current Team","")))
        loan = _canonical_team(str(row.get("Loan Club","")))
        return (team and _norm_str(team) == _norm_str(team_name)) or (loan and _norm_str(loan) == _norm_str(team_name))
    pool = players_df.copy()
    if nation:
        pool = pool[pool["Playing Nation"].astype(str).str.lower() == nation.lower()]
    home_players = [r for _, r in pool.iterrows() if _belongs(r, h)]
    away_players = [r for _, r in pool.iterrows() if _belongs(r, a)]
    return home_players, away_players

def interest_score(home_players: list[pd.Series], away_players: list[pd.Series]) -> int:
    # simple: number of tracked players in fixture
    return len(home_players) + len(away_players)

def _player_chip(r: pd.Series) -> str:
    nm = str(r.get("Name","")).strip() or "Unknown"
    pos = str(r.get("Position","")).strip()
    return f'<span class="chip" title="{pos}">{nm}</span>'

# ---- Card renderer with safe, unique keys per checkbox ----
def _render_fixture_cards_multination(view: pd.DataFrame, fixtures_path: str, nation: str):
    if view.empty:
        return
    players = load_db(st.session_state.db_csv).copy()
    for _, r in view.sort_values(["KO_date","Title"]).iterrows():
        fid = str(r["Fixture ID"])
        watched = str(r.get("Watched","")).strip().lower() == "yes"
        koday = r["KO_date"]
        dt_txt = ""
        if isinstance(koday, (pd.Timestamp,)):
            dt_txt = koday.strftime("%a %d %b")
        elif isinstance(koday, date):
            dt_txt = koday.strftime("%a %d %b")
        # Unique key uses file path + fixture id
        key_suffix = f"{_tiny_key(fixtures_path)}_{fid}"

        ph, pa = _players_for_fixture(players, r["Home"], r["Away"], nation)
        with st.container(border=True):
            c1, c2 = st.columns([5,1])
            with c1:
                st.markdown(f"**{r['Home']} vs {r['Away']}**")
                st.caption(f"{dt_txt} • {r['Title']} • {nation}")
            with c2:
                new_state = st.checkbox(
                    "Watched",
                    value=watched,
                    key=f"fx_w_{key_suffix}",
                    help="Toggle to mark this game as watched."
                )
                if new_state != watched:
                    ok = toggle_fixture_watched(fixtures_path, fid, new_state)
                    if ok:
                        st.success("Saved")
                    else:
                        # revert UI if failed
                        st.session_state[f"fx_w_{key_suffix}"] = watched
            st.markdown("Players to scout")
            cols = st.columns(2)
            with cols[0]:
                st.caption(r["Home"])
                chips = " ".join([_player_chip(x) for x in ph[:20]]) if ph else "—"
                st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
            with cols[1]:
                st.caption(r["Away"])
                chips = " ".join([_player_chip(x) for x in pa[:20]]) if pa else "—"
                st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)

# ---- Transfermarkt scraping for imports (league and single) ----
def _requests_session():
    sess = requests.Session()
    ua = UserAgent().random if UserAgent else "Mozilla/5.0"
    sess.headers.update({"User-Agent": ua})
    return sess

def fetch_transfermarkt_league(league_url: str) -> pd.DataFrame:
    """
    Fetch a league's full fixture list from Transfermarkt 'gesamtspielplan' pages.
    Returns DataFrame with Title, Given planned earliest start, Given planned earliest end.
    """
    if not (requests and BeautifulSoup):
        raise RuntimeError("Install requests and beautifulsoup4")
    s = _requests_session()
    r = s.get(league_url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # TM tables often with data-attributes; fallback to text scrapes
    # We look for rows that include two team names and a date.
    rows = []
    # Each fixture row generally under table class 'items' or similar
    for tr in soup.select("table tr"):
        txt = " ".join(tr.stripped_strings)
        # crude pattern: TeamA - TeamB and a date in dd/mm/yyyy
        m = re.search(r"(.+?)\s[-–]\s(.+?)\s+(\d{2}\.\d{2}\.\d{4}|\d{2}/\d{2}/\d{4})", txt)
        if not m:
            # Some pages show date first then teams
            m2 = re.search(r"(\d{2}\.\d{2}\.\d{4}|\d{2}/\d{2}/\d{4}).+?(.+?)\s[-–]\s(.+?)", txt)
            if m2:
                date_s = m2.group(1)
                home = m2.group(2); away = m2.group(3)
            else:
                continue
        else:
            home = m.group(1); away = m.group(2); date_s = m.group(3)

        # normalise date to dd/mm/yyyy
        date_s = date_s.replace(".", "/")
        try:
            _ = datetime.strptime(date_s, "%d/%m/%Y")
            title = f"{home.strip()} - {away.strip()}"
            rows.append({"Title": title, "Given planned earliest start": date_s, "Given planned earliest end": ""})
        except Exception:
            continue

    if not rows:
        # Try TM's modern card grid
        for card in soup.select("[data-matchid]"):
            home = card.get("data-home") or ""
            away = card.get("data-away") or ""
            date_ms = card.get("data-date") or ""
            try:
                dt_ = datetime.fromtimestamp(int(date_ms)/1000.0)
                date_s = dt_.strftime("%d/%m/%Y")
                title = f"{home.strip()} - {away.strip()}"
                rows.append({"Title": title, "Given planned earliest start": date_s, "Given planned earliest end": ""})
            except Exception:
                continue

    return pd.DataFrame(rows, columns=["Title","Given planned earliest start","Given planned earliest end"])

def fetch_transfermarkt_single(match_url: str) -> dict:
    """
    Fetch a single match from a TM match report page.
    Returns dict with Title and Given planned earliest start/end.
    """
    if not (requests and BeautifulSoup):
        raise RuntimeError("Install requests and beautifulsoup4")
    s = _requests_session()
    r = s.get(match_url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # Try to grab team names from header
    h = soup.find("h1")
    title = ""
    if h:
        t = " ".join(h.stripped_strings)
        if " - " in t or " – " in t or " vs " in t.lower():
            title = t.replace(" – ", " - ").replace(" VS ", " vs ").strip()
    if not title:
        # fallback: og:title
        og = soup.find("meta", attrs={"property":"og:title"})
        if og and og.get("content"):
            title = og["content"].strip()
    # Date: look for 'kickoff', 'date' labels
    date_txt = ""
    for lab in soup.select("span, div"):
        sss = lab.get_text(" ", strip=True)
        m = re.search(r"(\d{2}\.\d{2}\.\d{4}|\d{2}/\d{2}/\d{4})", sss)
        if m:
            date_txt = m.group(1).replace(".", "/")
            break
    if not title or not date_txt:
        raise RuntimeError("Could not parse teams/date from this page.")
    # normalise variant "Home vs Away" into "Home - Away"
    if " vs " in title.lower():
        parts = re.split(r"\s+vs\s+", title, flags=re.IGNORECASE)
        if len(parts) >= 2:
            title = f"{parts[0].strip()} - {parts[1].strip()}"
    return {"Title": title, "Given planned earliest start": date_txt, "Given planned earliest end": ""}

# ---- UI for Fixtures page ----
if nav == "📅 Fixtures":
    st.title("📅 Fixtures — Season 25/26")

    # Top-level tabs: three nations + Other + General + Calendar + Import
    tab_be, tab_nl, tab_fr, tab_other, tab_general, tab_calendar, tab_import = st.tabs(
        ["🇧🇪 Belgium", "🇳🇱 Netherlands", "🇫🇷 France", "🌍 Other", "⭐ General", "📆 Calendar", "⬇ Import"]
    )

    # ---- A reusable per-nation tab body ----
    def _nation_tab(label: str, nation: str, holder):
        nation_path = NATION_FOLDERS.get(nation)
        with holder:
            st.caption(f"Folder: {nation_path if nation_path else '—'}")
            if not nation_path or not os.path.exists(nation_path):
                st.info("No fixture folder found for this nation.")
                return

            files = _list_league_files(nation)
            pick = st.selectbox("League file", ["All leagues"] + files, key=f"{nation}_filepick")
            # Build a combined DataFrame
            frames = []
            if pick == "All leagues":
                for fn in files:
                    path = os.path.join(nation_path, fn)
                    fx = load_fixtures_csv(path, SEASON_START_2526, SEASON_END_2526)
                    if not fx.empty:
                        fx["__path"] = path
                        frames.append(fx)
            elif pick:
                path = os.path.join(nation_path, pick)
                fx = load_fixtures_csv(path, SEASON_START_2526, SEASON_END_2526)
                if not fx.empty:
                    fx["__path"] = path
                    frames.append(fx)

            if not frames:
                st.info("No data found for this selection.")
                return

            all_fx = pd.concat(frames, ignore_index=True)

            sub_upcoming, sub_all = st.tabs(["Upcoming (next 14 days)", "All season"])

            # -------- Upcoming --------
            with sub_upcoming:
                all_teams = sorted(set([t for t in pd.concat([all_fx["Home"], all_fx["Away"]]).astype(str).tolist() if t]))
                fcols = st.columns([2,2,2,2])
                team_filter = fcols[0].selectbox("Filter by team", [""] + all_teams, index=0, key=f"{nation}_up_team")
                include_past_3 = fcols[1].toggle("Include past 3 days", value=False, key=f"{nation}_up_past3",
                                                 help="Show recent games too")

                today = date.today()
                start_window = today - dt.timedelta(days=3) if include_past_3 else today
                end_window = today + dt.timedelta(days=UPCOMING_WINDOW_DAYS)

                view = all_fx[(all_fx["KO_date"] >= start_window) & (all_fx["KO_date"] <= end_window)].copy()
                if team_filter:
                    view = view[(view["Home"] == team_filter) | (view["Away"] == team_filter)].copy()

                st.caption(f"{len(view)} fixtures from {start_window.strftime('%d/%m/%Y')} to {end_window.strftime('%d/%m/%Y')}")
                if view.empty:
                    st.info("No fixtures in the selected window.")
                else:
                    # Path choice: if All leagues, use each row’s __path; render in groups to keep keys unique
                    for pth, sub in view.groupby(view["__path"]):
                        _render_fixture_cards_multination(sub, fixtures_path=pth, nation=nation)

            # -------- All season --------
            with sub_all:
                all_teams = sorted(set([t for t in pd.concat([all_fx["Home"], all_fx["Away"]]).astype(str).tolist() if t]))
                g1, g2, g3 = st.columns([2,3,2])
                team_filter2 = g1.multiselect("Teams", all_teams, default=[], key=f"{nation}_all_teams")
                rng = g2.date_input("Date range", value=(SEASON_START_2526, SEASON_END_2526),
                                    format="YYYY-MM-DD", key=f"{nation}_all_rng")
                text_q = g3.text_input("Search title (free text)", key=f"{nation}_all_q")

                view2 = all_fx.copy()
                if team_filter2:
                    mask = False
                    for t in team_filter2:
                        mask = mask | (view2["Home"] == t) | (view2["Away"] == t)
                    view2 = view2[mask]
                if isinstance(rng, (list, tuple)) and len(rng) == 2:
                    try:
                        d1, d2 = rng
                        view2 = view2[(view2["KO_date"] >= d1) & (view2["KO_date"] <= d2)]
                    except Exception:
                        pass
                if text_q:
                    view2 = view2[view2["Title"].astype(str).str.contains(text_q, case=False, na=False)]

                st.caption(f"{len(view2)} fixtures")
                if view2.empty:
                    st.info("No fixtures for the selected filters.")
                else:
                    for pth, sub in view2.groupby(view2["__path"]):
                        _render_fixture_cards_multination(sub, fixtures_path=pth, nation=nation)

    # Render each nation
    _nation_tab("Belgium", "Belgium", tab_be)
    _nation_tab("Netherlands", "Netherlands", tab_nl)
    _nation_tab("France", "France", tab_fr)
    _nation_tab("Other", "Other", tab_other)

    # -------- ⭐ General: combined next 7 days across all nations --------
    with tab_general:
        st.subheader("Combined fixtures — next 7 days")
        bundles = load_all_selected_fixtures(SEASON_START_2526, SEASON_END_2526)
        if not bundles:
            st.info("No fixture files found.")
        else:
            players = load_db(st.session_state.db_csv).copy()
            today = date.today()
            end7 = today + dt.timedelta(days=7)

            rows = []
            for nation, path, df in bundles:
                view = df[(df["KO_date"] >= today) & (df["KO_date"] <= end7)].copy()
                for _, r in view.iterrows():
                    home, away = r["Home"], r["Away"]
                    ph, pa = _players_for_fixture(players, home, away, nation)
                    sc = interest_score(ph, pa)
                    rows.append({
                        "Nation": nation,
                        "Path": path,
                        "Fixture ID": r["Fixture ID"],
                        "KO_date": r["KO_date"],
                        "Title": r["Title"],
                        "Home": home,
                        "Away": away,
                        "Watched": r.get("Watched","No"),
                        "Score": sc,
                        "_ph": ph, "_pa": pa
                    })
            if not rows:
                st.info("No fixtures in the next 7 days.")
            else:
                df_rows = pd.DataFrame(rows).sort_values(["Score","KO_date"], ascending=[False, True])
                for _, rr in df_rows.iterrows():
                    fid = rr["Fixture ID"]; nation = rr["Nation"]; path = rr["Path"]
                    watched = str(rr["Watched"]).strip().lower() == "yes"
                    koday = rr["KO_date"]
                    dt_txt = koday.strftime("%a %d %b") if isinstance(koday, date) else ""
                    key_suffix = f"{_tiny_key(path)}_{fid}"
                    with st.container(border=True):
                        c1, c2 = st.columns([5,1])
                        with c1:
                            st.markdown(f"**{rr['Home']} vs {rr['Away']}**")
                            st.caption(f"{dt_txt} • {rr['Title']} • {nation}")
                        with c2:
                            new_state = st.checkbox("Watched", value=watched, key=f"fx_w_general_{key_suffix}")
                            if new_state != watched:
                                ok = toggle_fixture_watched(path, fid, new_state)
                                if ok: st.success("Saved")
                                else: st.session_state[f"fx_w_general_{key_suffix}"] = watched
                        st.markdown("Players to scout")
                        cols = st.columns(2)
                        with cols[0]:
                            st.caption(rr["Home"])
                            chips = " ".join([_player_chip(r) for r in rr["_ph"][:20]]) if rr["_ph"] else "—"
                            st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                        with cols[1]:
                            st.caption(rr["Away"])
                            chips = " ".join([_player_chip(r) for r in rr["_pa"][:20]]) if rr["_pa"] else "—"
                            st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)

    # -------- 📆 Calendar view (week grid) --------
    with tab_calendar:
        st.subheader("Week view")
        bundles = load_all_selected_fixtures(SEASON_START_2526, SEASON_END_2526)
        if not bundles:
            st.info("No fixture files found.")
        else:
            anchor = st.date_input("Week of", value=date.today(), format="YYYY-MM-DD")
            wk_start, wk_end = week_bounds(anchor)
            st.caption(f"{wk_start.strftime('%d %b %Y')} — {wk_end.strftime('%d %b %Y')}")

            frames = []
            for nation, path, df in bundles:
                sub = df[(df["KO_date"] >= wk_start) & (df["KO_date"] <= wk_end)].copy()
                if not sub.empty:
                    sub["Nation"] = nation
                    sub["Path"] = path
                    frames.append(sub)
            if not frames:
                st.info("No fixtures this week.")
            else:
                allw = pd.concat(frames, ignore_index=True, sort=False)
                by_day = group_fixtures_by_day(allw)

                days = [wk_start + dt.timedelta(days=i) for i in range(7)]
                cols = st.columns(7)
                for col, dday in zip(cols, days):
                    with col:
                        st.markdown(f"**{dday.strftime('%a')}**")
                        st.caption(dday.strftime("%d %b"))
                        day_df = by_day.get(dday, pd.DataFrame())
                        if day_df.empty:
                            st.write("—")
                        else:
                            for _, r in day_df.iterrows():
                                fid = r["Fixture ID"]; nation = r["Nation"]; path = r["Path"]
                                watched = str(r.get("Watched","No")).strip().lower() == "yes"
                                key_suffix = f"{_tiny_key(path)}_{fid}"
                                with st.container(border=True):
                                    st.markdown(f"{r['Home']} vs {r['Away']}")
                                    st.caption(f"{r['Title']} • {nation}")
                                    new_state = st.checkbox("Watched", value=watched, key=f"fx_w_cal_{key_suffix}")
                                    if new_state != watched:
                                        ok = toggle_fixture_watched(path, fid, new_state)
                                        if ok: st.success("Saved")
                                        else: st.session_state[f"fx_w_cal_{key_suffix}"] = watched

    # -------- ⬇ Import (Transfermarkt) --------
    with tab_import:
        st.subheader("Import fixtures from Transfermarkt")
        st.caption("Choose **League fixtures** to dump a full schedule into a nation folder as a CSV. Use **Single match** to append one game into any CSV (including Other).")

        mode = st.radio("Import type", ["League fixtures", "Single match"], horizontal=True)

        if mode == "League fixtures":
            lg_url = st.text_input("Transfermarkt league URL (gesamtspielplan)", placeholder="https://www.transfermarkt.com/ligue-1/gesamtspielplan/wettbewerb/FR1/saison_id/2025")
            nation_pick = st.selectbox("Save under nation", list(NATION_FOLDERS.keys()), index=list(NATION_FOLDERS.keys()).index("France") if "France" in NATION_FOLDERS else 0)
            file_name = st.text_input("File name (without .csv)", value="ligue1_2025_26")
            run = st.button("Fetch & save (overwrite if exists)", type="primary")
            if run:
                try:
                    df_league = fetch_transfermarkt_league(lg_url)
                    if df_league.empty:
                        st.warning("No rows fetched from Transfermarkt. Check the URL.")
                    else:
                        # Save as CSV in chosen nation folder
                        folder = NATION_FOLDERS[nation_pick]
                        os.makedirs(folder, exist_ok=True)
                        out_path = os.path.join(folder, f"{file_name}.csv")
                        df_league.to_csv(out_path, index=False, encoding="utf-8-sig")
                        st.success(f"Saved {len(df_league)} fixtures to {out_path}")
                        st.cache_data.clear()
                except Exception as e:
                    st.error(f"League import failed: {e}")

        else:
            mt_url = st.text_input("Transfermarkt single match URL (spielbericht)", placeholder="https://www.transfermarkt.com/spielbericht/index/spielbericht/4745212")
            # Let the user choose an existing CSV file in any nation, or create a new one in Other
            nat_sel = st.selectbox("Target nation folder", list(NATION_FOLDERS.keys()), index=list(NATION_FOLDERS.keys()).index("Other") if "Other" in NATION_FOLDERS else 0)
            folder = NATION_FOLDERS[nat_sel]
            files = _list_league_files(nat_sel)
            target_choice = st.selectbox("Append into file", ["Create new…"] + files)
            new_name = ""
            if target_choice == "Create new…":
                new_name = st.text_input("New file name (without .csv)", value="other_matches")
            run2 = st.button("Fetch & append", type="primary")
            if run2:
                try:
                    row = fetch_transfermarkt_single(mt_url)
                    if not row:
                        st.warning("Could not parse this match page.")
                    else:
                        if target_choice == "Create new…":
                            out_path = os.path.join(folder, f"{new_name}.csv")
                            exists = os.path.exists(out_path)
                            df_old = pd.read_csv(out_path, sep=None, engine="python", encoding="utf-8-sig") if exists else pd.DataFrame(columns=["Title","Given planned earliest start","Given planned earliest end","Watched"])
                        else:
                            out_path = os.path.join(folder, target_choice)
                            # ensure existing can be read
                            attempts = [
                                dict(sep=None, engine="python", encoding="utf-8-sig"),
                                dict(sep=None, engine="python", encoding="cp1252"),
                                dict(sep=None, engine="python", encoding="latin1"),
                            ]
                            df_old = None
                            for opt in attempts:
                                try:
                                    df_old = pd.read_csv(out_path, **opt); break
                                except Exception:
                                    pass
                            if df_old is None:
                                df_old = pd.DataFrame(columns=["Title","Given planned earliest start","Given planned earliest end","Watched"])

                        # Append new row
                        row["Watched"] = "No"
                        df_new = pd.concat([df_old, pd.DataFrame([row])], ignore_index=True)
                        df_new.to_csv(out_path, index=False, encoding="utf-8-sig")
                        st.success(f"Appended match to {out_path}")
                        st.cache_data.clear()
                except Exception as e:
                    st.error(f"Single match import failed: {e}")

# app.py — Part 5/6
# =========================
# 17) 📊 Wyscout linker + Cohort analytics
# =========================

# Ensure DB has a Wyscout ID column
if "Wyscout ID" not in REQUIRED_COLUMNS:
    REQUIRED_COLUMNS.append("Wyscout ID")

# ---- Wyscout folders: reuse your league folders (same as Data analysis) ----
WS_DIRS = {
    "Belgium":     r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Belgium",
    "Netherlands": r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Dutch",
    "France":      r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\France",
}
WS_FILE_PATTERNS = ["*.csv"]  # we read all CSVs in those folders

# ---- Safe CSV reader for Wyscout dumps ----
def _read_ws_csv_any(path: str) -> pd.DataFrame:
    attempts = [
        dict(sep=None, engine="python", encoding="utf-8-sig"),
        dict(sep=None, engine="python", encoding="cp1252"),
        dict(sep=None, engine="python", encoding="latin1"),
    ]
    for opt in attempts:
        try:
            return pd.read_csv(path, **opt)
        except Exception:
            pass
    return pd.DataFrame()

# ---- Normalise strings (robust to floats/None) ----
def _norm_s(obj) -> str:
    s = "" if obj is None or (isinstance(obj, float) and pd.isna(obj)) else str(obj)
    try:
        s = unicodedata.normalize("NFKD", s)
    except Exception:
        pass
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\W_]+", "", s)
    return s

# ---- Map Wyscout positions to FCM role buckets (multi-role) ----
_FCM_ROLE_BY_WS = {
    # wide
    "lw": ["11a - LWF","11 - LM"],
    "lamf": ["11a - LWF","11 - LM"],
    "rw": ["7a - RWF","7 - RM"],
    "ramf": ["7a - RWF","7 - RM"],
    "lwf": ["11a - LWF"], "rwf": ["7a - RWF"],
    # striker / forwards
    "cf": ["9 - AF","9a - TM"],
    "st": ["9 - AF","9a - TM"],
    "ss": ["10 - CAM","10a"],
    # mids
    "amf": ["10 - CAM","10a"],
    "cmf": ["8"],
    "rcmf": ["8"], "lcmf": ["8"],
    "dmf": ["6"], "rdmf": ["6"], "ldmf": ["6"],
    # fullbacks / wingbacks
    "rb": ["2 - RB/RWB"], "rwb": ["2 - RB/RWB"],
    "lb": ["3 - LB/LWB"], "lwb": ["3 - LB/LWB"],
    # centre-backs
    "cb": ["4 - CCB","5L","5R"], "lcb": ["5L"], "rcb": ["5R"],
    # gk
    "gk": ["GK"],
}

def map_ws_to_fcm_roles(ws_pos: str) -> list[str]:
    if not ws_pos:
        return []
    # ws strings could be "CF, LW" etc
    roles = set()
    for token in re.split(r"[\/,\|;]+|\s+", str(ws_pos)):
        key = _norm_s(token)
        if key in _FCM_ROLE_BY_WS:
            for r in _FCM_ROLE_BY_WS[key]:
                roles.add(r)
    return sorted(roles)

# ---- Guarantee Wyscout ID, synthesised from name | team | dob ----
def ensure_wyscout_id_column(df: pd.DataFrame) -> pd.DataFrame:
    if "Wyscout ID" not in df.columns:
        df["Wyscout ID"] = ""
    # synthesise if missing
    def _synth(row):
        if str(row.get("Wyscout ID","")).strip():
            return str(row.get("Wyscout ID","")).strip()
        name = str(row.get("Player","") or "")
        team = str(row.get("Team","") or "")
        dob  = str(row.get("DOB","") or row.get("Date of birth","") or "")
        raw = f"{_norm_s(name)}|{_norm_s(team)}|{dob}"
        return _tiny_key(raw)
    df["Wyscout ID"] = df.apply(_synth, axis=1)
    return df

# ---- Load Wyscout master across all nations/tiers ----
@st.cache_data(show_spinner=False)
def load_wyscout_master() -> pd.DataFrame:
    frames = []
    for nation, folder in WS_DIRS.items():
        if not os.path.exists(folder):
            continue
        for pat in WS_FILE_PATTERNS:
            for path in glob.glob(os.path.join(folder, pat)):
                df_ = _read_ws_csv_any(path)
                if df_.empty: 
                    continue
                # Standardise some known columns if present
                df_.columns = [str(c).strip().replace("\ufeff", "") for c in df_.columns]
                df_["__nation"] = nation
                df_["__source_file"] = os.path.basename(path)
                # Defensive guards for columns used later
                for col in ["Player","Team","Position","Minutes played","Age","Foot","Contract expires","Market value"]:
                    if col not in df_.columns:
                        df_[col] = ""
                frames.append(df_)
    if not frames:
        return pd.DataFrame(columns=["Player","Team","Position","Minutes played","Wyscout ID","__nation","__source_file","__fcm_roles"])
    master = pd.concat(frames, ignore_index=True, sort=False)
    # Minutes numeric
    master["Minutes played"] = pd.to_numeric(master["Minutes played"], errors="coerce")
    # Attach FCM roles list
    master["__fcm_roles"] = master["Position"].apply(map_ws_to_fcm_roles)
    # Ensure Wyscout ID
    master = ensure_wyscout_id_column(master)
    return master

# ---- Fuzzy search helpers (no extra deps) ----
def _ratio(a: str, b: str) -> int:
    return int(100 * difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio())

def wyscout_candidates(master: pd.DataFrame, name: str, team_hint: str = "", nation_hint: str = "") -> pd.DataFrame:
    if master.empty:
        return pd.DataFrame()
    nm = str(name or "").strip()
    th = str(team_hint or "").strip()
    cand = master.copy()
    if nation_hint:
        cand = cand[cand["__nation"].astype(str).str.lower() == nation_hint.lower()]
    if th:
        # loose team filter
        nt = _norm_s(th)
        cand = cand[cand["Team"].apply(lambda x: _norm_s(x)==nt or nt in _norm_s(x))]
    if nm:
        cand["__score"] = cand["Player"].apply(lambda x: _ratio(str(x), nm))
        cand = cand.sort_values("__score", ascending=False)
    return cand.head(200)

# ---- Metric packs (you can tune later) ----
PACKS = {
    "WINGER": [
        "Goals per 90","Assists per 90","xG per 90","xA per 90",
        "Dribbles per 90","Successful dribbles, %","Offensive duels per 90","Offensive duels won, %",
        "Crosses per 90","Accurate crosses, %","Progressive runs per 90","Touches in box per 90",
        "Key passes per 90","Shots per 90","Shots on target, %",
    ],
    "FULLBACK": [
        "Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %",
        "Aerial duels per 90","Aerial duels won, %","Interceptions per 90","PAdj Interceptions",
        "Crosses per 90","Accurate crosses, %","Progressive runs per 90","Passes to final third per 90",
        "Accurate passes, %","Progressive passes per 90",
    ],
    "STRIKER": [
        "Goals per 90","xG per 90","Shots per 90","Shots on target, %","Goal conversion, %",
        "Touches in box per 90","Head goals per 90",
        "Offensive duels per 90","Offensive duels won, %",
    ],
    "AM": [
        "Assists per 90","xA per 90","Key passes per 90","Shot assists per 90",
        "Smart passes per 90","Accurate smart passes, %","Through passes per 90","Accurate through passes, %",
        "Progressive passes per 90","Accurate progressive passes, %","Passes to penalty area per 90","Accurate passes to penalty area, %",
        "Dribbles per 90","Successful dribbles, %",
    ],
    "CM": [
        "Passes per 90","Accurate passes, %","Progressive passes per 90","Accurate progressive passes, %",
        "Passes to final third per 90","Accurate passes to final third, %",
        "Interceptions per 90","PAdj Interceptions",
        "Duels per 90","Duels won, %",
    ],
    "DM": [
        "Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %",
        "Interceptions per 90","PAdj Interceptions","Sliding tackles per 90","PAdj Sliding tackles",
        "Aerial duels per 90","Aerial duels won, %",
        "Progressive passes per 90","Accurate progressive passes, %",
    ],
    "CB": [
        "Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %",
        "Aerial duels per 90","Aerial duels won, %","Shots blocked per 90","Interceptions per 90","PAdj Interceptions",
        "Passes per 90","Accurate passes, %","Progressive passes per 90",
    ],
    "GK": [
        "Conceded goals per 90","Save rate, %","Shots against per 90",
        "Prevented goals per 90","Exits per 90","Aerial duels per 90","Back passes received as GK per 90",
    ],
}

# ---- Role → pack mapping ----
def pack_for_role(fcm_role: str) -> str:
    r = (fcm_role or "").lower()
    if r in ["11a - lwf","11 - lm","7a - rwf","7 - rm"]:
        return "WINGER"
    if r in ["2 - rb/rwb","3 - lb/lwb"]:
        return "FULLBACK"
    if r in ["9 - af","9a - tm"]:
        return "STRIKER"
    if r in ["10 - cam","10a"]:
        return "AM"
    if r == "8":
        return "CM"
    if r == "6":
        return "DM"
    if r in ["4 - ccb","5l","5r"]:
        return "CB"
    if r == "gk":
        return "GK"
    return "CM"

# ---- Build cohort ----
def build_cohort(master: pd.DataFrame,
                 cohort_type: str,
                 fcm_role: str | None = None,
                 min_minutes: int = 300,
                 league_hint: str | None = None) -> pd.DataFrame:
    df = master.copy()
    if df.empty:
        return df
    # Minutes filter
    if "Minutes played" in df.columns:
        df = df[pd.to_numeric(df["Minutes played"], errors="coerce").fillna(0) >= min_minutes]
    # Cohort logic
    if cohort_type == "FCM" and fcm_role:
        # keep players that have this FCM role among their mapped roles
        if "__fcm_roles" not in df.columns:
            df["__fcm_roles"] = df["Position"].apply(map_ws_to_fcm_roles)
        df = df[df["__fcm_roles"].apply(lambda L: fcm_role in (L or []))]
    # League hint further narrows by nation
    if league_hint:
        df = df[df["__nation"].astype(str).str.lower() == league_hint.lower()]
    return df

# ---- Z-score table ----
def zscore_table(cohort: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    if cohort.empty:
        return cohort
    use = cohort.copy()
    for m in metrics:
        if m not in use.columns:
            use[m] = np.nan
        use[m] = pd.to_numeric(use[m], errors="coerce")
    # compute z per column
    zcols = {}
    for m in metrics:
        col = use[m]
        mu = col.mean(skipna=True)
        sd = col.std(skipna=True)
        if sd and sd > 0:
            z = (col - mu) / sd
        else:
            z = pd.Series([0]*len(col), index=col.index, dtype="float")
        zcols[m] = z
    ztab = use[["Player","Team","Position","Minutes played","Wyscout ID","__nation","__source_file"]].copy()
    for m in metrics:
        ztab[f"z::{m}"] = zcols[m]
    # overall score = mean of positive “good” metrics' z
    z_only = ztab[[c for c in ztab.columns if c.startswith("z::")]]
    ztab["__overall_score"] = z_only.mean(axis=1, skipna=True)
    ztab["__overall_rank"] = ztab["__overall_score"].rank(ascending=False, method="min")
    return ztab

# ---- UI renderer inside Player reports detail page ----
def render_wyscout_linker_and_cohort(df_players: pd.DataFrame, focus_idx: int):
    st.markdown("---")
    st.subheader("📊 Data comparison (Wyscout)")

    master_ws = load_wyscout_master()
    if master_ws.empty:
        st.info("No Wyscout data found. Make sure your Belgium/Dutch/France CSVs exist in their folders.")
        return

    r = df_players.loc[focus_idx]

    # ——— Linker row
    with st.expander("Link Wyscout record", expanded=False):
        c1, c2, c3 = st.columns(3)
        current_ws_id = str(r.get("Wyscout ID","")).strip()
        c1.write(f"Current Wyscout ID: `{current_ws_id or '—'}`")
        nation_hint = c2.selectbox("Nation hint", ["","Belgium","Netherlands","France"], key=f"ws_nat_{focus_idx}")
        team_hint = c3.text_input("Team hint", value=str(r.get("Player Current Team","")), key=f"ws_team_{focus_idx}")

        qname = st.text_input("Find by player name", value=str(r.get("Name","")), key=f"ws_name_{focus_idx}")
        if st.button("Search", key=f"ws_search_{focus_idx}"):
            st.session_state[f"ws_cands_{focus_idx}"] = wyscout_candidates(master_ws, qname, team_hint, nation_hint).to_dict("records")

        cands = st.session_state.get(f"ws_cands_{focus_idx}", [])
        if cands:
            options = [f"{i+1}. {row['Player']} — {row['Team']} ({row['__nation']}) [{row.get('Wyscout ID','')}]" for i, row in enumerate(cands)]
            pick = st.selectbox("Candidates", ["—"] + options, key=f"ws_pick_{focus_idx}")
            if pick != "—":
                sel = cands[options.index(pick)-1]
                if st.button("Attach to this player", type="primary", key=f"ws_attach_{focus_idx}"):
                    df_players.at[focus_idx, "Wyscout ID"] = str(sel.get("Wyscout ID",""))
                    write_db(st.session_state.db_csv, df_players)
                    st.success("Linked Wyscout ID to player.")
                    st.cache_data.clear()

        # Manual attach
        man = st.text_input("Manual Wyscout ID", value=current_ws_id, key=f"ws_manual_{focus_idx}")
        if st.button("Save manual ID", key=f"ws_save_manual_{focus_idx}"):
            df_players.at[focus_idx, "Wyscout ID"] = man.strip()
            write_db(st.session_state.db_csv, df_players)
            st.success("Saved Wyscout ID.")
            st.cache_data.clear()

    # ——— Cohort controls
    st.markdown("#### Cohort settings")
    mode1, mode2, mode3, mode4 = st.columns([1.2,1.2,1.2,1.2])
    cohort_mode = mode1.selectbox("Comparison mode", ["FCM","GROUP"], key=f"cohort_mode_{focus_idx}")
    # FCM role dropdown from this player’s roles
    player_roles = normalize_roles_to_options(r.get("Position",""))
    default_role = player_roles[0] if player_roles else "8"
    role_pick = mode2.selectbox("FCM role", ROLE_ORDER, index=(ROLE_ORDER.index(default_role) if default_role in ROLE_ORDER else 0), key=f"cohort_role_{focus_idx}")
    league_hint = mode3.selectbox("League filter (nation)", ["","Belgium","Netherlands","France"], key=f"cohort_nat_{focus_idx}")
    min_minutes = int(mode4.number_input("Min minutes", min_value=0, max_value=5000, step=50, value=300, key=f"cohort_mins_{focus_idx}"))

    # Pack choice overrides by role group
    default_pack = pack_for_role(role_pick)
    pack_choice = st.selectbox("Metric pack", list(PACKS.keys()), index=list(PACKS.keys()).index(default_pack), key=f"cohort_pack_{focus_idx}")
    metrics = PACKS[pack_choice]

    # Build cohort
    try:
        cohort = build_cohort(master_ws, cohort_type=cohort_mode, fcm_role=role_pick, min_minutes=min_minutes, league_hint=(league_hint or None))
        if cohort.empty:
            st.info("No players in cohort with current filters.")
            return

        ztab = zscore_table(cohort, metrics)
        # Try to find this player’s row in cohort
        target_row = None
        wsid = str(df_players.at[focus_idx, "Wyscout ID"]).strip()
        if wsid:
            match = ztab[ztab["Wyscout ID"].astype(str) == wsid]
            if not match.empty:
                target_row = match.iloc[0]
        if target_row is None:
            # fallback by name
            nm = str(r.get("Name","")).strip()
            match = ztab[ztab["Player"].astype(str).str.fullmatch(nm, case=False, na=False)]
            if not match.empty:
                target_row = match.iloc[0]

        # Header KPIs
        if target_row is not None:
            c1, c2 = st.columns(2)
            c1.metric("Overall score (z-mean)", f"{float(target_row['__overall_score']):.2f}")
            c2.metric("Overall rank in cohort", int(target_row["__overall_rank"]))
        else:
            st.caption("This player was not matched in the cohort by Wyscout ID or exact name. You can still browse the cohort below.")

        # Top 5 strengths
        st.markdown("##### 🏅 Top 5 strengths in this cohort")
        if target_row is None:
            st.write("—")
        else:
            # gather z cols
            zs = []
            for m in metrics:
                zval = float(target_row.get(f"z::{m}", 0.0))
                zs.append((m, zval, float(cohort[m].loc[target_row.name]) if m in cohort.columns else np.nan))
            zs.sort(key=lambda x: x[1], reverse=True)
            top5 = zs[:5]
            for m, zval, raw in top5:
                bar = "█"*max(1, min(20, int(round(10+zval*3))))
                st.write(f"{m}: **{raw if not np.isnan(raw) else 'NA'}**  | z={zval:+.2f}  {bar}")

        # Detailed metrics table
        st.markdown("##### Metrics table")
        # Build readable table
        table = ztab.copy()
        # bring selected columns
        show_cols = ["Player","Team","Position","Minutes played","__overall_score","__overall_rank"] + metrics
        for c in show_cols:
            if c not in table.columns:
                table[c] = np.nan
        table = table[show_cols].sort_values(["__overall_rank","__overall_score"], ascending=[True, False])

        # highlight target
        def _row_style(row):
            if wsid and str(row.get("Wyscout ID","")) == wsid:
                return ["font-weight:700; background-color: rgba(255,255,255,0.08)"]*len(row)
            return [""]*len(row)
        # Show
        st.dataframe(table, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Cohort build failed: {e}")

# app.py — Part 6/6
# =========================
# 18) Final glue: imports, CSS tweaks, safe-date helpers, and call sites
# =========================

# Extra imports used by Parts 4–5 (keep idempotent)
import glob
import difflib
import numpy as np

# ---------- CSS polish for metrics tables ----------
st.markdown("""
<style>
.dataframe td, .dataframe th {
  font-size: 12.5px;
  line-height: 18px;
}
.dataframe th {
  white-space: nowrap;
}
</style>
""", unsafe_allow_html=True)

# ---------- Safe date bounds for all date_inputs ----------
SAFE_MIN_DATE = date(1900, 1, 1)
SAFE_MAX_DATE = date(2100, 12, 31)

def safe_date_input(label: str, value: Optional[date], key: str):
    v = value if isinstance(value, date) and (SAFE_MIN_DATE <= value <= SAFE_MAX_DATE) else None
    return st.date_input(label, value=v, min_value=SAFE_MIN_DATE, max_value=SAFE_MAX_DATE, format="YYYY-MM-DD", key=key)

# ---------- Contract quick presets (06/2026 .. 06/2031) ----------
def contract_presets_years(start_y: int = 2026, end_y: int = 2031) -> list[str]:
    return [f"{y}-06-30" for y in range(start_y, end_y + 1)]

# ---------- Tiny helper to place Wyscout section inside Player detail ----------
def render_player_wyscout_block(df_players: pd.DataFrame, focus_idx: int):
    try:
        render_wyscout_linker_and_cohort(df_players, focus_idx)
    except NameError:
        # If Part 5/6 not loaded yet
        st.info("Wyscout module not loaded (Part 5/6).")
    except Exception as e:
        st.error(f"Wyscout block failed: {e}")

# ---------- HOW TO CALL (reference, non-executing comment) ----------
# In your Player reports detail view, after the general details form save and
# before the Full report PDF section, ensure you have:
#
#     render_player_wyscout_block(df, focus_idx)
#
# This wraps the full linking + cohort UI safely.

# ---------- End of Part 6/6 ----------


# =========================
# 10) STREAMLIT STATE & NAV
# =========================
if "db_csv" not in st.session_state: st.session_state.db_csv   = DEFAULT_DB_CSV
if "depth_csv" not in st.session_state: st.session_state.depth_csv = DEFAULT_DEPTH_CSV
if "nav" not in st.session_state: st.session_state.nav = "🏠 Home"
if "profile_focus_id" not in st.session_state: st.session_state.profile_focus_id = None  # stable Row ID for report detail

with st.sidebar:
    st.markdown("### Menu")
    def menu_btn(label: str, key: str):
        active = (st.session_state.nav == label)
        btn = st.button(label, use_container_width=True, type=("primary" if active else "secondary"), key=key)
        if btn: st.session_state.nav = label
    menu_btn("🏠 Home", "nav_home")
    menu_btn("📚 All Players", "nav_players")
    menu_btn("📝 Player reports", "nav_reports")
    menu_btn("📊 Data analysis", "nav_analysis")
    menu_btn("📅 Fixtures", "nav_fixtures")
    menu_btn("⚙️ Files", "nav_files")
nav = st.session_state.nav


# =========================
# 11) FILE SETTINGS PAGE
# =========================
if nav == "⚙️ Files":
    st.header("File settings")
    st.subheader("Database CSV")
    dbp = st.text_input("Player DB CSV path", value=st.session_state.db_csv)
    if st.button("Use this DB CSV"):
        st.session_state.db_csv = dbp; st.cache_data.clear()
    st.success(f"Active DB: {st.session_state.db_csv}")

    st.subheader("Depth Chart CSV")
    dpp = st.text_input("Depth CSV path", value=st.session_state.depth_csv)
    if st.button("Use this Depth CSV"):
        st.session_state.depth_csv = dpp; st.cache_data.clear()
    st.success(f"Active Depth: {st.session_state.depth_csv}")
    st.stop()


# =========================
# 12) HOME PAGE (Depth, Position, Nation, Deep Dive)
# =========================
def _sort_newest_first(df_in: pd.DataFrame) -> pd.DataFrame:
    t1 = pd.to_datetime(df_in.get("Created time", ""), errors="coerce")
    t2 = pd.to_datetime(df_in.get("Last edited time", ""), errors="coerce")
    order = t1.fillna(t2)
    return df_in.assign(__sort=order).sort_values("__sort", ascending=False, na_position="last").drop(columns="__sort", errors="ignore")

if nav == "🏠 Home":
    left, right = st.columns([5,1])
    with left: st.title("FC Midtjylland Scouting Assistant")
    with right:
        lp = find_logo()
        if lp:
            st.markdown('<div class="header-logo">', unsafe_allow_html=True); st.image(lp); st.markdown('</div>', unsafe_allow_html=True)

    depth_df = load_depth(st.session_state.depth_csv).copy()
    df = load_db(st.session_state.db_csv).copy()

    df = _sort_newest_first(df)

    tab_pitch, tab_pos, tab_nat, tab_deep = st.tabs(["⚽ Team depth","🧭 By position","🌍 By nation","🧪 Deep dive required"])

    # ----- Team depth -----
    with tab_pitch:
        view_mode = st.toggle("Edit mode", value=False, help="Switch to edit the grid")

        def card_view(code: str):
            st.markdown('<div class="depth-card">', unsafe_allow_html=True)
            st.markdown(f'<div class="depth-label">{code}</div>', unsafe_allow_html=True)
            a = depth_df.at["1", code] if code in depth_df.columns else ""
            b = depth_df.at["2", code] if code in depth_df.columns else ""
            html = '<div class="chips">'
            if a: html += f'<span class="chip chip-first">{a}</span>'
            if b: html += f'<span class="chip chip-second">{b}</span>'
            html += '</div>'; st.markdown(html, unsafe_allow_html=True)
            with st.expander("3rd & 4th", expanded=False):
                c = depth_df.at["3", code] if code in depth_df.columns else ""
                d = depth_df.at["4", code] if code in depth_df.columns else ""
                html2 = '<div class="chips">'
                if c: html2 += f'<span class="chip">{c}</span>'
                if d: html2 += f'<span class="chip">{d}</span>'
                html2 += '</div>'; st.markdown(html2, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        def card_edit(code: str):
            st.markdown('<div class="depth-card">', unsafe_allow_html=True)
            st.markdown(f'<div class="depth-label">{code}</div>', unsafe_allow_html=True)
            for i in range(1, DEPTH_SLOTS+1):
                key = f"{code}_{i}"
                cur = depth_df.at[str(i), code] if code in depth_df.columns else ""
                depth_df.at[str(i), code] = st.text_input(f"{code} #{i}", value=cur, key=key, label_visibility="collapsed", placeholder=f"{code} #{i}")
            st.markdown('</div>', unsafe_allow_html=True)

        rows = [
            ["", "11a", "", "9", "9a", "", "7a", ""],
            ["", "", "10a", "10", "", ""],
            ["", "11", "", "6", "", "8", "", "7", ""],
            ["3", "", "5L", "4", "5R", "", "2"],
            ["", "", "", "GK", "", "", ""],
        ]

        st.subheader("On-pitch depth")
        st.markdown('<div class="pitch">', unsafe_allow_html=True)
        for row in rows:
            cols = st.columns(len(row))
            for col, code in zip(cols, row):
                with col:
                    if code: (card_edit if view_mode else card_view)(code)
        st.markdown('</div>', unsafe_allow_html=True)

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("Save depth chart"):
            save_depth(st.session_state.depth_csv, depth_df)
            st.success("Depth chart saved.")
            st.cache_data.clear()
        c2.download_button("Download depth chart (CSV)", data=depth_df.to_csv(index=True).encode("utf-8"), file_name="depth_fcm.csv", mime="text/csv")

    # ----- By position ----- 
    with tab_pos:
        st.subheader("Players by FCM role")
        view = df.copy()
        age_series_pos = compute_age_series(view)
        amin = int(age_series_pos.dropna().min()) if age_series_pos.notna().any() else 15
        amax = int(age_series_pos.dropna().max()) if age_series_pos.notna().any() else 40
        age_min_pos, age_max_pos = st.slider("Age range", min_value=amin, max_value=amax, value=(amin, amax), key="pos_age")
        view = view[(age_series_pos >= age_min_pos) & (age_series_pos <= age_max_pos)]

        summary_rows = []
        for role in ROLE_ORDER:
            mask_role = view["Position"].apply(lambda x: role.lower() in [r.lower() for r in split_roles(x)])
            sub = view[mask_role]; total = len(sub)
            watched_cnt = int(sub["Watched"].astype(str).str.strip().ne("").sum())
            u21_cnt = 0
            for _, rr in sub.iterrows():
                age_num = calc_age_from_row(rr)
                if age_num is not None and age_num <= 21: u21_cnt += 1
            summary_rows.append({"Role": role, "Total": total, "Watched": watched_cnt, "Unwatched": total - watched_cnt, "U21": u21_cnt})
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True, height=280)

        cf1, cf2 = st.columns([2,2])
        roles_selected = cf1.multiselect("Choose roles", ROLE_ORDER, default=ROLE_ORDER)
        name_q = cf2.text_input("Search name")

        if name_q: view = view[view["Name"].str.contains(name_q, case=False, na=False)]
        chosen_roles = roles_selected or ROLE_ORDER

        st.markdown("#### Role metrics")
        for role in chosen_roles:
            mask_role = view["Position"].apply(lambda x: role.lower() in [r.lower() for r in split_roles(x)])
            sub = view[mask_role]; total = len(sub)
            watched_cnt = int(sub["Watched"].astype(str).str.strip().ne("").sum())
            unwatched = total - watched_cnt
            u21_cnt = 0
            for _, rr in sub.iterrows():
                age_num = calc_age_from_row(rr)
                if age_num is not None and age_num <= 21: u21_cnt += 1
            c1, c2, c3 = st.columns(3)
            with c1: st.metric(label=f"{role} — Total", value=total)
            with c2: st.metric(label="Watched / Unwatched", value=f"{watched_cnt} / {unwatched}")
            with c3: st.metric(label="U21", value=u21_cnt)
        st.markdown("---")

        buckets: Dict[str, List[pd.Series]] = {r: [] for r in chosen_roles}
        for _, row in view.iterrows():
            roles = [rr.lower() for rr in split_roles(row.get("Position",""))]
            for r in chosen_roles:
                if r.lower() in roles: buckets[r].append(row)

        for role in chosen_roles:
            players = buckets.get(role, [])
            st.markdown(f"**{role} — {len(players)}**")
            cols = st.columns(3)
            for i, r in enumerate(players):
                with cols[i % 3]: render_player_card(r, key_prefix=f"{role}_{i}")
            st.markdown("<hr/>", unsafe_allow_html=True)

    # ----- By nation -----
    with tab_nat:
        st.subheader("Players by nation")
        nat = st.selectbox("Choose playing nation", [""] + sorted(df["Playing Nation"].unique().tolist()))
        v = df if not nat else df[df["Playing Nation"] == nat]

        age_series_nat = compute_age_series(v)
        amin = int(age_series_nat.dropna().min()) if age_series_nat.notna().any() else 15
        amax = int(age_series_nat.dropna().max()) if age_series_nat.notna().any() else 40
        age_min_nat, age_max_nat = st.slider("Age range", min_value=amin, max_value=amax, value=(amin, amax), key="nat_age")
        v = v[(age_series_nat >= age_min_nat) & (age_series_nat <= age_max_nat)]

        flg = flag_for_country(nat) if nat else ""
        st.caption(f"{flg} {len(v)} players" if nat else f"{len(v)} players")
        cols = st.columns(3)
        for i, (_, r) in enumerate(v.iterrows()):
            with cols[i % 3]: render_player_card(r, key_prefix=f"nat_{i}")

    # ----- Deep dive -----
    with tab_deep:
        st.subheader("Players requiring deep dive")
        rule = st.selectbox("Rule", ["Watched contains 'deep'", "Watched is empty", "Custom keyword…"], index=0)
        if rule == "Watched contains 'deep'":
            mask = df["Watched"].str.contains("deep", case=False, na=False)
        elif rule == "Watched is empty":
            mask = df["Watched"].str.strip().eq("") | df["Watched"].isna()
        else:
            kw = st.text_input("Keyword", value="deep"); mask = df["Watched"].str.contains(kw, case=False, na=False)
        dd = df[mask].copy(); st.caption(f"{len(dd)} players")
        base_dir = os.path.join("FCM Scouting", "full reports done"); os.makedirs(base_dir, exist_ok=True)
        df_all = df.copy(); changed = False
        for idx, r in dd.iterrows():
            with st.container(border=True):
                has_report = bool(r.get("Full Report Path","").strip())
                badge = ' <span class="badge">📄 Full report</span>' if has_report else ""
                st.markdown(f"**{r['Name']}** — {r['Position']} • {r['Player Current Team']}{badge}", unsafe_allow_html=True)
                st.caption(f"Watched: {r['Watched']}")
                done = st.checkbox("Full report done", value=has_report, key=f"rep_{idx}")
                up = None
                if done and not has_report:
                    up = st.file_uploader("Upload full report (PDF)", type=["pdf"], key=f"pdf_{idx}")
                if done and up is not None:
                    date_str = dt.datetime.now().strftime("%Y-%m-%d")
                    safe_name = re.sub(r"[^\w\-. ]", "_", r["Name"])
                    fp = os.path.join(base_dir, f"{safe_name} - {date_str}.pdf")
                    with open(fp, "wb") as f: f.write(up.read())
                    new_watch = (r["Watched"] + f" | full report done {date_str}").strip()
                    df_all.at[idx, "Watched"] = new_watch
                    df_all.at[idx, "Full Report Path"] = fp
                    changed = True; st.success(f"Saved report for {r['Name']}")
        if changed:
            write_db(st.session_state.db_csv, df_all); st.success("Database updated with full reports."); st.cache_data.clear()


# =========================
# 13) ALL PLAYERS PAGE
# =========================
if nav == "📚 All Players":
    st.title("All Players")
    df = load_db(st.session_state.db_csv).copy()
    df = _sort_newest_first(df)

    left, right = st.columns([1,3])

    # ---- Import / Export (left)
    with left:
        st.subheader("Import CSV (append)")
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up is not None:
            try:
                newdf = pd.read_csv(up, dtype=str, keep_default_na=False)
                for c in REQUIRED_COLUMNS:
                    if c not in newdf.columns: newdf[c] = ""
                newdf = _ensure_row_ids(newdf)  # ensure Row IDs for imported rows
                merged = pd.concat([df, newdf[[*newdf.columns]]], ignore_index=True)
                write_db(st.session_state.db_csv, merged); st.success(f"Imported {len(newdf)} rows.")
                st.cache_data.clear(); df = load_db(st.session_state.db_csv).copy()
                df = _sort_newest_first(df)
            except Exception as e:
                st.error(f"Import failed: {e}")
        st.subheader("Export current view"); st.caption("Exports the filtered table on the right.")

    # ---- Add new player (left expander)
    with st.expander("➕ Add a new player (role template or scrape Transfermarkt)", expanded=False):
        scrape_url = st.text_input("Transfermarkt URL (optional)", key="add_scrape_url",
                                   placeholder="https://www.transfermarkt.com/.../profil/spieler/12345")
        if st.button("Fetch from Transfermarkt", type="secondary", key="add_fetch_tm"):
            data, msg = scrape_transfermarkt(scrape_url.strip())
            if msg: st.info(msg)
            if data:
                for k, v in data.items():
                    if v is not None:
                        st.session_state[f"new_{k}"] = v
                st.session_state["add_source"] = scrape_url.strip()
                st.success("Fetched from Transfermarkt.")
                st.rerun()  # refresh so fields fill in

        def add_new_dropdown(label, options, state_key_choice, state_key_new, default_text=""):
            choice = st.selectbox(label, ["— select —"] + options + ["Add new…"], key=state_key_choice)
            new_val = st.text_input(f"Add new ({label.lower()})",
                                    value=st.session_state.get(state_key_new, default_text),
                                    key=f"{state_key_new}__input") if choice=="Add new…" else ""
            return new_val if new_val else (choice if choice not in ["— select —","Add new…"] else "")

        df_all = df.copy()
        existing_teams = sorted([t for t in df_all["Player Current Team"].unique().tolist() if t])
        existing_agencies = sorted([t for t in df_all["Agency"].unique().tolist() if t])
        existing_nat = sorted([t for t in df_all["Player Nationality"].unique().tolist() if t])
        existing_play_nat = sorted([t for t in df_all["Playing Nation"].unique().tolist() if t])
        existing_age_groups = sorted([t for t in df_all.get("Age Group", pd.Series(dtype=str)).astype(str).unique().tolist() if t and t != "nan"])
        existing_divisions = sorted([t for t in df_all.get("Division", pd.Series(dtype=str)).astype(str).unique().tolist() if t and t != "nan"])

        # Basic identity
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", value=st.session_state.get("new_Name",""), key="add_name")
        pos_sel = c2.multiselect("Positions (multi-select, first = primary)", ROLE_ORDER,
                                 default=[st.session_state.get("new_Position","")] if st.session_state.get("new_Position") else [],
                                 key="add_positions")
        pos_str = ", ".join([p for p in pos_sel if p])

        # On-loan UX
        on_loan_flag = st.checkbox("On loan?", value=False, key="add_onloan")
        if on_loan_flag:
            # When on loan, Player Current Team becomes the Loan Club picker
            loan_club_final = add_new_dropdown("Loan club (current visible club)", existing_teams,
                                               "add_loan_club_choice","new_Loan Club",
                                               st.session_state.get("new_Player Current Team",""))
            parent_club_final = add_new_dropdown("Parent club (contracted to)", existing_teams,
                                                 "add_parent_club_choice","new_Parent Club","")
            # Player Current Team field is hidden in this mode
            team_final = parent_club_final
        else:
            # Standard mode: only current team shown
            team_final = add_new_dropdown("Player Current Team", existing_teams, "add_team_choice","new_Player Current Team", st.session_state.get("new_Player Current Team",""))
            loan_club_final = ""
            parent_club_final = ""

        # Nations and Division
        d1, d2, d3 = st.columns(3)
        playing_nation = add_new_dropdown("Playing Nation (league country)", existing_play_nat,"add_playing_nation_choice","new_Playing Nation", st.session_state.get("new_Playing Nation",""))
        nationality = add_new_dropdown("Player Nationality (citizenship)", existing_nat,"add_citizenship_choice","new_Player Nationality", st.session_state.get("new_Player Nationality",""))
        division = add_new_dropdown("Division", existing_divisions, "add_division_choice", "new_Division", st.session_state.get("new_Division",""))

        # Age, DOB with bounds, Age group
        e1, e2, e3 = st.columns(3)
        dob_prefill = st.session_state.get("new_DOB","")
        try:
            y,m,d = map(int, dob_prefill.split("-")) if dob_prefill else (None,None,None)
            dob_default = date(y,m,d) if y else None
        except:
            dob_default = None
        dob = e1.date_input("DOB", value=dob_default, format="YYYY-MM-DD",
                            min_value=date(1900,1,1), max_value=date(2100,12,31), key="add_dob")
        age = e2.text_input("Age", value=st.session_state.get("new_Age",""), key="add_age")
        age_group = add_new_dropdown("Age Group", existing_age_groups, "add_age_group_choice", "new_Age Group")

        # Anthropometrics and foot
        f1, f2, f3 = st.columns(3)
        default_h = st.session_state.get("new_Player Height","")
        try: default_h_num = float((default_h or "").lower().replace("m","").strip()) if default_h else 0.0
        except: default_h_num = 0.0
        height_num = f1.number_input("Player Height (m)", min_value=0.0, max_value=2.5, step=0.01, value=default_h_num, key="add_height")
        height_str = f"{height_num:.2f} m" if height_num > 0 else ""
        weight = f2.number_input("Player Weight (kg)", min_value=0, max_value=150, step=1, value=0, key="add_weight")
        weight_str = str(weight) if weight>0 else ""
        foot = f3.selectbox("Dominant Foot", ["", "Right", "Left", "Both"],
                            index=(["","Right","Left","Both"].index(st.session_state.get("new_Dominant Foot","")) if st.session_state.get("new_Dominant Foot","") in ["","Right","Left","Both"] else 0),
                            key="add_foot")

        # Agency, Contract, TM source
        g1, g2, g3 = st.columns(3)
        agency_final = add_new_dropdown("Agency", existing_agencies,"add_agency_choice","new_Agency", st.session_state.get("new_Agency",""))

        # Contract presets 06/26 … 06/31
        year_presets = [2026, 2027, 2028, 2029, 2030, 2031]
        preset_labels = [f"06/{str(y)[-2:]}" for y in year_presets]
        preset_dates = [f"{y}-06-30" for y in year_presets]
        preset_choice = g2.selectbox("Contract Until (quick presets)", ["— none —"] + preset_labels, key="add_contract_preset")
        chosen_preset_date = ""
        if preset_choice != "— none —":
            chosen_preset_date = preset_dates[preset_labels.index(preset_choice)]
        # Also allow a custom pick
        contract_default = None
        contract_prefill = st.session_state.get("new_Contract Until","")
        try:
            if contract_prefill:
                cy,cm,cd = map(int, contract_prefill.split("-")); contract_default = date(cy,cm,cd)
        except: ...
        custom_contract = g2.date_input("…or pick a date", value=contract_default, format="YYYY-MM-DD",
                                        min_value=date(1900,1,1), max_value=date(2100,12,31), key="add_contract_date")
        contract_until = chosen_preset_date or (custom_contract.strftime("%Y-%m-%d") if custom_contract else "")

        source = g3.text_input("Transfermarkt URL", value=st.session_state.get("add_scrape_url",""), key="add_source")

        # Ratings: Current & Potential sliders (1–4, step 0.5)
        h1, h2 = st.columns(2)
        current_rating = h1.slider("Current Ability (1–4)", min_value=0.0, max_value=4.0, step=0.5, value=0.0, key="add_cr_slider")
        potential_rating = h2.slider("Potential Ability (1–4)", min_value=0.0, max_value=4.0, step=0.5, value=0.0, key="add_pr_slider")
        
        # Verdict and Watched
        v1, v2 = st.columns(2)
        verdict = v1.selectbox(
            "Verdict",
            ["", "1 - Avg/Lower PLAYER in Bottom Tier League", "1.5 - Good Pl in Bottom Tier League / Avg Pl in Low Tier Leagues", "2 - Good Pl in Low Tier League / Avg Pl in Mid Tier Leagues", "2.5 - Good Pl in Mid Tier League / Avg Pl in High Tier Leagues", "3 - Good Pl in High Tier League / Avg Pl in Top Tier Leagues", "3.5 - Good Pl in Top Tiera","4 - World-Class Talent"],
            key="add_verdict"
        )

        watched_choice = v2.selectbox(
            "Watched",
            ["", "needs deep dive", "Namechecked", "Monitor", "full report done","Longlisted","Unlikely", "Custom…"],
            key="add_watched_choice"
        )
        watched_custom = st.text_input("Custom watched note", key="add_watched_custom") if watched_choice == "Custom…" else ""
        watched_final = watched_custom if watched_choice == "Custom…" else watched_choice


        # Qualitative notes
        strengths = st.text_area("Strengths", key="add_strengths")
        weaknesses = st.text_area("Weaknesses", key="add_weaknesses")

        # TM values, photo
        j1, j2 = st.columns(2)
        tm_val = j1.text_input("TM Value", value=st.session_state.get("new_TM Value",""), key="add_tm")
        tm_val_hi = j2.text_input("Highest TM Value", value=st.session_state.get("new_Highest TM Value",""), key="add_tm_hi")
        save_photo_local = st.checkbox("Also download and store player photo", value=True, key="add_save_photo")

        if st.button("Add to database", key="add_report_btn"):
            if not name.strip():
                st.error("Name is required.")
            else:
                tm_compact = fmt_eur_compact(parse_eur_value(tm_val)) if tm_val else ""
                tm_hi_compact = fmt_eur_compact(parse_eur_value(tm_val_hi)) if tm_val_hi else tm_val_hi

                row = {
                    "Name": _tidy_person_name(name.strip()),
                    "Position": pos_str.strip(),
                    "Age": age.strip(),
                    "DOB": dob.strftime("%Y-%m-%d") if dob else "",
                    "Age Group": age_group.strip(),
                    "Player Current Team": (team_final or "").strip(),
                    "Playing Nation": (playing_nation or "").strip(),
                    "Player Nationality": (nationality or "").strip(),
                    "Division": division.strip(),
                    "Dominant Foot": foot.strip(),
                    "Player Height": height_str.strip(),
                    "Player weight": weight_str.strip(),
                    "Agency": (agency_final or "").strip(),
                    "Contract Until": contract_until.strip(),
                    "Current Rating (1-4)": (str(current_rating) if current_rating > 0 else ""),
                    "Potential Rating (1-4)": (str(potential_rating) if potential_rating > 0 else ""),
                    "Verdict": verdict.strip(),
                    "Watched": watched_final.strip(),
                    "Strengths": strengths.strip(),
                    "Weaknesses": weaknesses.strip(),
                    "Source": source.strip(),
                    "TM Value": tm_compact,
                    "Highest TM Value": tm_hi_compact,
                    # On-loan wiring
                    "On loan": "Yes" if on_loan_flag else "No",
                    "Loan Club": loan_club_final.strip() if on_loan_flag else "",
                    "Parent Club": parent_club_final.strip() if on_loan_flag else "",
                }
                # Photo before insert/update
                photo_url = str(st.session_state.get("new_Photo URL","")).strip()
                photo_path = ""
                if save_photo_local and photo_url:
                    photo_path = download_image_to_disk(photo_url, row["Name"]) or ""
                row["Photo URL"] = photo_url
                row["Photo Path"] = photo_path

                df2 = add_or_update_row(df.copy(), row)
                write_db(st.session_state.db_csv, df2)

                st.success(f"✅ New player added: {row['Name']}")
                # Try auto-link to Wyscout (best-effort; does not block the add flow)
                try:
                    master = load_wyscout_master()
                    if not master.empty:
                        # find the just-added row by name+team
                        new_mask = (df2["Name"].astype(str) == row["Name"]) & (df2["Player Current Team"].astype(str) == row["Player Current Team"])
                        new_idx = df2[new_mask].index
                        if len(new_idx):
                            idx = new_idx[0]
                            wsid, _ = try_auto_attach_wyscout_id(master, df2.loc[idx], score_threshold=0.86)
                            if wsid:
                                df2.at[idx, "Wyscout Player ID"] = wsid
                                df2.at[idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                write_db(st.session_state.db_csv, df2)
                                st.toast(f"Wyscout auto-link: {wsid}", icon="✅")
                except Exception:
                    pass

                st.cache_data.clear()
                # clear all inputs/state
                for k in list(st.session_state.keys()):
                    if k.startswith(("add_", "new_")):
                        del st.session_state[k]
                st.rerun()

    # ---- Table view & filters (right)
    with right:
        colf = st.columns(8)
        f_team    = colf[0].selectbox("Team", [""] + sorted(df["Player Current Team"].unique().tolist()))
        f_pos     = colf[1].selectbox("Position", [""] + sorted(df["Position"].unique().tolist()))
        f_verdict = colf[2].selectbox("Verdict", [""] + sorted(df["Verdict"].unique().tolist()))
        f_watched = colf[3].selectbox("Watched", [""] + sorted(df["Watched"].unique().tolist()))
        f_nation  = colf[4].selectbox("Playing Nation", [""] + sorted(df["Playing Nation"].unique().tolist()))
        f_onloan  = colf[5].selectbox("On loan", ["", "Yes", "No"]) if "On loan" in df.columns else ""
        search    = colf[6].text_input("Search name")
        # keep age slider as colf[7] below

        age_series_all = compute_age_series(df)
        amin = int(age_series_all.dropna().min()) if age_series_all.notna().any() else 15
        amax = int(age_series_all.dropna().max()) if age_series_all.notna().any() else 40
        age_min, age_max = colf[7].slider("Age", min_value=amin, max_value=amax, value=(amin, amax))


        view = df.copy()
        if f_team:    view = view[view["Player Current Team"] == f_team]
        if f_pos:     view = view[view["Position"] == f_pos]
        if f_verdict: view = view[view["Verdict"] == f_verdict]
        if f_nation:  view = view[view["Playing Nation"] == f_nation]
        if f_onloan:  view = view[view.get("On loan","").astype(str).str.lower() == f_onloan.lower()]
        if f_watched: view = view[view["Watched"] == f_watched]
        if search:    view = view[view["Name"].str.contains(search, case=False, na=False)]
        age_series_view = compute_age_series(view)
        view = view[(age_series_view >= age_min) & (age_series_view <= age_max)]

        view = _sort_newest_first(view)

        st.caption(f"Showing {len(view)} of {len(df)}")
        view_show = view.assign(**{"Full report?": view["Full Report Path"].apply(lambda x: "Yes" if str(x).strip() else "")})

        edited = st.data_editor(view_show, use_container_width=True, num_rows="dynamic", key="all_editor")
        c1, c2, c3 = st.columns(3)
        if c1.button("Save changes"):
            to_save = edited.drop(columns=["Full report?"], errors="ignore")
            df.loc[to_save.index, :] = to_save
            write_db(st.session_state.db_csv, df); st.success("Saved."); st.cache_data.clear()
        export_buttons(edited, key_suf="_players")


# =========================
# 14) PLAYER REPORTS PAGE
# =========================
if nav == "📝 Player reports":
    st.title("Player reporting")
    df = load_db(st.session_state.db_csv).copy()

    # newest-first for lists on this page
    df = _sort_newest_first(df)

    # Resolve focused row via stable Row ID
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

    # ---- Filters
    fcols = st.columns([2,2,2,2,2,2])
    name_q   = fcols[0].text_input("Search name", key="rep_search")
    f_team   = fcols[1].selectbox("Team", [""] + sorted(df["Player Current Team"].unique().tolist()), key="rep_team")
    f_role   = fcols[2].selectbox("Role (contains)", [""] + ROLE_ORDER, key="rep_role")
    f_nation = fcols[3].selectbox("Playing Nation", [""] + sorted(df["Playing Nation"].unique().tolist()), key="rep_nat")
    f_verdict= fcols[4].selectbox("Verdict", [""] + sorted(df["Verdict"].unique().tolist()), key="rep_verdict")

    age_series_rep_all = compute_age_series(df)
    amin = int(age_series_rep_all.dropna().min()) if age_series_rep_all.notna().any() else 15
    amax = int(age_series_rep_all.dropna().max()) if age_series_rep_all.notna().any() else 40
    age_min_rep, age_max_rep = fcols[5].slider("Age", min_value=amin, max_value=amax, value=(amin, amax), key="rep_age")

    # ===== DETAIL PAGE =====
    if focus_idx is not None and focus_idx in df.index:
        r = df.loc[focus_idx]

        back_col, _sp = st.columns([1,9])
        with back_col:
            if st.button("← Back to list", use_container_width=True, key="rep_back"):
                st.session_state.profile_focus_id = None
                st.rerun()

        st.markdown("---")

        # --- Header area: image + details, loan-aware club label
        img_col, info_col = st.columns([1,3])
        with img_col:
            img_src = r.get("Photo Path","").strip() or r.get("Photo URL","").strip()
            if img_src:
                st.image(img_src, width=220)
        with info_col:
            # Loan-aware current club display
            on_loan = str(r.get("On loan","")).strip().lower() in {"yes","true","1"}
            loan_club = str(r.get("Loan Club","")).strip()
            parent_club = str(r.get("Parent Club","")).strip()
            team = str(r.get("Player Current Team","")).strip()
            visible_team = f"{loan_club} → {parent_club}" if on_loan and loan_club and parent_club else (loan_club or team)

            st.subheader(r.get("Name",""))
            st.caption(
                f"{visible_team} • {r.get('Position','')} "
                f"• Age: {r.get('Age','')} | Height: {r.get('Player Height','')} | Foot: {r.get('Dominant Foot','')}"
            )
            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("TM Value", r.get("TM Value",""))
            with m2: st.metric("Agency", r.get("Agency",""))
            with m3: st.metric("Citizenship", r.get("Player Nationality",""))
            with m4: st.metric("Contract until", r.get("Contract Until",""))

            # Transfermarkt URL + fetch
            tm_url = st.text_input("Transfermarkt URL", value=r.get("Source",""), key=f"tm_url_{focus_idx}")
            cols_fetch = st.columns([1,2,2])
            if cols_fetch[0].button("Fetch from Transfermarkt (fill empty)", key=f"tm_fetch_{focus_idx}"):
                if tm_url.strip():
                    data, msg = scrape_transfermarkt(tm_url.strip())
                    if msg: st.info(msg)
                    if data:
                        # only fill empty fields; normalize TM value on the way in
                        for k, v in data.items():
                            if k in ["Name"] and not str(df.at[focus_idx, k]).strip():
                                df.at[focus_idx, k] = _tidy_person_name(v)
                            elif k == "TM Value":
                                existing = str(df.at[focus_idx, "TM Value"]).strip()
                                if not existing:
                                    df.at[focus_idx, "TM Value"] = v
                            elif k == "Contract Until":
                                if not str(df.at[focus_idx, "Contract Until"]).strip():
                                    df.at[focus_idx, "Contract Until"] = v
                            elif k in df.columns and not str(df.at[focus_idx, k]).strip():
                                df.at[focus_idx, k] = v

                        if not str(df.at[focus_idx, "Source"]).strip():
                            df.at[focus_idx, "Source"] = tm_url.strip()

                        if str(df.at[focus_idx, "Photo Path"]).strip() == "":
                            pu = str(df.at[focus_idx, "Photo URL"]).strip()
                            if pu:
                                saved = download_image_to_disk(pu, df.at[focus_idx, "Name"])
                                if saved:
                                    df.at[focus_idx, "Photo Path"] = saved

                        df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        write_db(st.session_state.db_csv, df)
                        st.success("Details updated from Transfermarkt.")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.warning("Please paste a Transfermarkt URL.")

        st.markdown("---")

        # -------- General details (editable)
        with st.form(key=f"gen_{focus_idx}", clear_on_submit=False):
            g1, g2, g3 = st.columns(3)
            name_val   = g1.text_input("Name", value=r.get("Name",""))
            team_val   = g2.text_input("Player Current Team", value=r.get("Player Current Team",""))

            existing_divisions = sorted([t for t in df["Division"].astype(str).unique().tolist() if t and t != "nan"])
            _div_choice = [""] + existing_divisions + ["Add new…"]
            cur_div = r.get("Division","")
            div_idx = _div_choice.index(cur_div) if cur_div in _div_choice else 0
            _sel = st.selectbox("Division", _div_choice, index=div_idx, key=f"div_sel_{focus_idx}")
            division_val = _sel if _sel != "Add new…" else st.text_input("New division", key=f"div_new_{focus_idx}")

            # Positions (multiselect)
            cur_roles = normalize_roles_to_options(r.get("Position",""))
            pos_sel   = st.multiselect("Positions (first = primary)", ROLE_ORDER, default=cur_roles, key=f"pos_sel_{focus_idx}")
            pos_val   = ", ".join(pos_sel)

            # Agency, foot, height
            row_agencies      = df["Agency"].astype(str).tolist()
            row_citizenships  = df["Player Nationality"].astype(str).tolist()
            row_play_nations  = df["Playing Nation"].astype(str).tolist()

            h1, h2, h3 = st.columns(3)
            agencies = [""] + sorted(set([x for x in row_agencies if x])) + ["Add new…"]
            cur_ag = r.get("Agency","")
            ag = st.selectbox("Agency", agencies, index=(agencies.index(cur_ag) if cur_ag in agencies else 0), key=f"agency_{focus_idx}")
            agency_val = ag if ag != "Add new…" else st.text_input("New agency", key=f"agency_new_{focus_idx}")

            foot_val   = h2.selectbox("Dominant Foot", ["", "Right", "Left", "Both"],
                                      index=(["","Right","Left","Both"].index(r.get("Dominant Foot",""))
                                             if r.get("Dominant Foot","") in ["","Right","Left","Both"] else 0))
            height_txt = (r.get("Player Height","") or "").lower().replace("m","").strip()
            try: height_default = float(height_txt) if height_txt else 0.0
            except: height_default = 0.0
            height_val_num = h3.number_input("Player Height (m)", min_value=0.0, max_value=2.5, step=0.01, value=height_default)

            # Nationalities / playing nation
            n1, n2, n3 = st.columns(3)
            cits = [""] + sorted(set([x for x in row_citizenships if x])) + ["Add new…"]
            cur_nat = r.get("Player Nationality","")
            nat_sel = st.selectbox("Player Nationality (citizenship)", cits, index=(cits.index(cur_nat) if cur_nat in cits else 0), key=f"cit_{focus_idx}")
            nat_val      = nat_sel if nat_sel != "Add new…" else st.text_input("New nationality", key=f"cit_new_{focus_idx}")

            plats = [""] + sorted(set([x for x in row_play_nations if x])) + ["Add new…"]
            cur_pl = r.get("Playing Nation","")
            pl_sel = st.selectbox("Playing Nation (league country)", plats, index=(plats.index(cur_pl) if cur_pl in plats else 0), key=f"plnat_{focus_idx}")
            play_nat_val = pl_sel if pl_sel != "Add new…" else st.text_input("New playing nation", key=f"plnat_new_{focus_idx}")

            tm_val = n3.text_input("TM Value", value=r.get("TM Value",""))

            # DOB and age
            d1, d2, d3 = st.columns(3)
            dob_raw = r.get("DOB",""); dob_default = None
            try:
                if dob_raw:
                    y,m,d = map(int, dob_raw.split("-")); dob_default = date(y,m,d)
            except: ...
            dob_in = d1.date_input("DOB", value=dob_default, format="YYYY-MM-DD",
                                   min_value=date(1900,1,1), max_value=date(2100,12,31))
            age_val = d2.text_input("Age", value=r.get("Age",""))

            # Contract, TM highest, source
            contract_raw = r.get("Contract Until",""); contract_default = None
            try:
                if contract_raw:
                    y,m,d = map(int, contract_raw.split("-")); contract_default = date(y,m,d)
            except: ...
            contract_in = d3.date_input("Contract Until", value=contract_default, format="YYYY-MM-DD",
                                        min_value=date(1900,1,1), max_value=date(2100,12,31))

            t1, t2 = st.columns(2)
            tm_hi_val = t1.text_input("Highest TM Value", value=r.get("Highest TM Value",""))
            source_val= t2.text_input("Transfermarkt URL", value=r.get("Source",""))
            
            # Verdict + Watched on profile
            wcol1, wcol2 = st.columns(2)

            # Verdict
            verdict_options = ["", "1 - Avg/Lower PLAYER in Bottom Tier League", "1.5 - Good Pl in Bottom Tier League / Avg Pl in Low Tier Leagues", "2 - Good Pl in Low Tier League / Avg Pl in Mid Tier Leagues", "2.5 - Good Pl in Mid Tier League / Avg Pl in High Tier Leagues", "3 - Good Pl in High Tier League / Avg Pl in Top Tier Leagues", "3.5 - Good Pl in Top Tiera","4 - World-Class Talent"]
            cur_verdict = r.get("Verdict", "")
            verdict_idx = verdict_options.index(cur_verdict) if cur_verdict in verdict_options else 0
            verdict_val = wcol1.selectbox("Verdict", verdict_options, index=verdict_idx, key=f"verdict_{focus_idx}")

            # Watched
            watched_presets = ["", "needs deep dive", "Namechecked", "Monitor", "full report done","Longlisted","Unlikely", "Custom…"]
            cur_watched = r.get("Watched", "")
            watched_idx = watched_presets.index(cur_watched) if cur_watched in watched_presets else (
                watched_presets.index("Custom…") if cur_watched else 0
            )
            watched_sel = wcol2.selectbox("Watched", watched_presets, index=watched_idx, key=f"watched_{focus_idx}")
            watched_custom2 = st.text_input("Custom watched note", value=(cur_watched if cur_watched not in watched_presets else ""), key=f"watched_custom_{focus_idx}") if watched_sel == "Custom…" else ""
            watched_val = watched_custom2 if watched_sel == "Custom…" else watched_sel

            # Ratings sliders in profile
            r1, r2 = st.columns(2)
            cr_default = 0.0
            try:
                cr_default = float(r.get("Current Rating (1-4)","") or 0.0)
            except: ...
            pr_default = 0.0
            try:
                pr_default = float(r.get("Potential Rating (1-4)","") or 0.0)
            except: ...
            cr_slider = r1.slider("Current Ability (1–4)", min_value=0.0, max_value=4.0, step=0.5, value=cr_default, key=f"cr_slider_{focus_idx}")
            pr_slider = r2.slider("Potential Ability (1–4)", min_value=0.0, max_value=4.0, step=0.5, value=pr_default, key=f"pr_slider_{focus_idx}")

            saved_general = st.form_submit_button("💾 Save general details")
            if saved_general:
                tm_compact = fmt_eur_compact(parse_eur_value(tm_val)) if tm_val else ""
                tm_hi_compact = fmt_eur_compact(parse_eur_value(tm_hi_val)) if tm_hi_val else tm_hi_val

                df.at[focus_idx, "Name"] = _tidy_person_name(name_val.strip())
                df.at[focus_idx, "Player Current Team"] = team_val.strip()
                df.at[focus_idx, "Division"] = division_val.strip()
                df.at[focus_idx, "Position"] = pos_val.strip()
                df.at[focus_idx, "Agency"] = agency_val.strip()
                df.at[focus_idx, "Dominant Foot"] = foot_val.strip()
                df.at[focus_idx, "Player Height"] = (f"{height_val_num:.2f} m" if height_val_num > 0 else "")
                df.at[focus_idx, "Player Nationality"] = nat_val.strip()
                df.at[focus_idx, "Playing Nation"] = play_nat_val.strip()
                df.at[focus_idx, "TM Value"] = tm_compact
                df.at[focus_idx, "Highest TM Value"] = tm_hi_compact
                df.at[focus_idx, "Source"] = source_val.strip()
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
                    except: ...
                if contract_in:
                    df.at[focus_idx, "Contract Until"] = contract_in.strftime("%Y-%m-%d")

                df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                write_db(st.session_state.db_csv, df)
                st.success("General details saved.")
                st.cache_data.clear()
        
        # =========================
        # 📈 Wyscout link + Data panel (put this inside the DETAIL PAGE for the selected player)
        # Place after your "General details" form, before notes/KPIs
        # =========================
        # =========================
        # 🔗 Wyscout linkage (auto + manual)
        # =========================
        st.markdown("---")
        st.subheader("🔗 Wyscout linkage")
        # =========================
        # 📊 Cohort scope controls
        # =========================
        st.markdown("---")
        st.subheader("📊 Cohort comparison")
        st.caption(
            f"Wyscout rows loaded: {0 if master_ws is None else len(master_ws)}"
            + (f" | nations={sorted(master_ws['__nation'].dropna().unique().tolist())}" if not master_ws.empty else "")
        )
        
        # ---- Comparison mode & pack selector
        mode1, mode2 = st.columns([1, 1])
        cohort_mode = mode1.selectbox(
            "Comparison mode",
            ["FCM", "GROUP"],
            key=f"{_keybase}_mode",
        )


        if cohort_mode == "FCM":
            # If FCM mode
            fcm_role_choice = mode2.selectbox("FCM role", ROLE_ORDER, key=f"{_keybase}_fcmrole")
            group_choice = None
        else:
            # Broad groups
            broad_groups = ["Wingers","Fullbacks","Centre-backs","Central mids","Attacking mids","Defensive mids","Strikers","Goalkeepers"]
            # If GROUP mode
            group_choice = mode2.selectbox("General group", broad_groups, key=f"{_keybase}_group")
            fcm_role_choice = None


        scope1, scope2, scope3 = st.columns([1.3, 1, 1.2])
        nations_pick = scope1.multiselect(
            "Nations in cohort",
            ["Belgium","Netherlands","France"],
            default=["Belgium","Netherlands","France"],
            key=f"{_keybase}_nations",
        )
        league_hint = scope2.text_input(
            "League filter (e.g., 'France1', 'Dutch2')",
            value="",
            help="Filters Wyscout rows by file name containing this token (e.g., France1.csv).",
            key=f"{_keybase}_leag",
        )
        mins_thresh = scope3.number_input(
            "Minimum minutes",
            min_value=0, max_value=5000, value=600, step=30,
            key=f"{_keybase}_mins",
        )


        # Active Wyscout ID used for THIS analysis run
        linked_id = str(df.at[focus_idx, "Wyscout Player ID"]).strip() if "Wyscout Player ID" in df.columns else ""
        manual_pick_id = st.session_state.get(f"{_keybase}_wsid_pick", "").strip()
        current_ws_id_or_manual_pick = manual_pick_id or linked_id

        # Optional: show which ID we are using right now
        if current_ws_id_or_manual_pick:
            st.caption(f"Using Wyscout ID for analysis: `{current_ws_id_or_manual_pick}`")
        else:
            st.warning("No Wyscout ID selected yet. Use Auto-attach or Manual pick above to set one for analysis.")

        # ---- Build the cohort tables (make sure prepare_cohort_analysis is updated to accept league_hint)
        try:
            ztab, packs, weights, target_row = prepare_cohort_analysis(
                master_ws,                                  # your Wyscout master df
                target_player_name=r.get("Name", ""),       # fall back to name when ID missing
                target_wyscout_id=current_ws_id_or_manual_pick,
                cohort_type=cohort_mode,                    # "FCM" or "GROUP" from your UI
                fcm_role=fcm_role_choice,                   # your FCM role picker
                general_group=group_choice,                 # your general group picker (Wingers, Fullbacks, etc.)
                nations=nations_pick,
                min_minutes=int(mins_thresh),
                league_hint=(league_hint or None),
            )
        except Exception as e:
            st.error(f"Cohort build failed: {e}")
            ztab = pd.DataFrame(); packs = {}; weights = {}; target_row = pd.Series(dtype=object)

        # Reload current row (in case details were just saved)
        r = df.loc[focus_idx]
        master = load_wyscout_master()
        m = load_wyscout_master()
        st.caption(f"Wyscout rows loaded: {len(m)} | nations={sorted(m['__nation'].dropna().unique().tolist()) if not m.empty else '—'}")
        with st.expander("Wyscout loader debug", expanded=False):
            st.caption("Folders discovered:")
            for p in wyscout_folders():
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
                st.session_state[f"ws_id_pick_{focus_idx}"] = ws_id_in.strip()
                write_db(st.session_state.db_csv, df)
                st.success("Wyscout Player ID saved.")
                st.cache_data.clear()

        with cols_lk[1]:
            if master.empty:
                st.caption("No Wyscout data loaded.")
            else:
                if st.button("🤖 Auto-attach", key=f"auto_wsid_{focus_idx}"):
                    wsid, cands = try_auto_attach_wyscout_id(master, r, score_threshold=0.82)
                    st.session_state[f"ws_cands_{focus_idx}"] = cands
                    if wsid:
                        df.at[focus_idx, "Wyscout Player ID"] = wsid
                        df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        write_db(st.session_state.db_csv, df)
                        # NEW: also set the analysis pick so the cohort uses it immediately
                        st.session_state[f"{_keybase}_wsid_pick"] = wsid
                        st.success(f"Linked automatically: {wsid}")
                        st.cache_data.clear()
                    else:
                        st.info("No high-confidence match (≥ 0.82). Pick manually below.")


        with cols_lk[2]:
            st.caption("If auto-match fails, use the manual picker below.")

        # Manual picker scoped by nation/tier and fuzzy-sorted
        if not master.empty:
            nat_hint, tier_hint = _parse_division(r.get("Playing Nation",""), r.get("Division",""))
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
                    hit = cand_df.index[cand_df["Wyscout Player ID"].astype(str) == ws_id_cur]
                    pre_idx = int(hit[0]) if len(hit) else 0
                pick = st.selectbox("Manual pick (sorted by similarity)", cand_df["__label"].tolist(), index=pre_idx, key=f"ws_pick_{focus_idx}")
                if st.button("Link selected", key=f"ws_link_sel_{focus_idx}"):
                    row_sel = cand_df.iloc[cand_df["__label"].tolist().index(pick)]
                    wsid = str(row_sel["Wyscout Player ID"])
                    df.at[focus_idx, "Wyscout Player ID"] = wsid
                    df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    write_db(st.session_state.db_csv, df)
                    st.success(f"Linked manually: {wsid}")
                    st.cache_data.clear()
                # Use the selected candidate for THIS analysis run (without writing DB)
                if st.button("Use for analysis (no save)", key=f"ws_use_sel_{focus_idx}"):
                    row_sel = cand_df.iloc[cand_df["__label"].tolist().index(pick)]
                    wsid = str(row_sel["Wyscout Player ID"])
                    st.session_state[f"{_keybase}_wsid_pick"] = wsid
                    st.success(f"Using {wsid} for analysis below (not saved to DB).")


        st.markdown("---")
        st.subheader("📈 Data — cohort comparison")
        # Unique key base for this player's cohort widgets
        _keybase = f"cohort_{focus_idx}_{_norm_str(r.get('Name',''))}_{_norm_str(r.get('Player Current Team',''))}"

        # ---- Comparison mode & pack selector
        mode1, mode2 = st.columns([1, 1])
        cohort_mode = mode1.selectbox(
            "Comparison mode",
            ["FCM", "GROUP"],
            key=f"{_keybase}_mode",
        )

        if cohort_mode == "FCM":
            # If FCM mode
            fcm_role_choice = mode2.selectbox("FCM role", ROLE_ORDER, key=f"{_keybase}_fcmrole")
            group_choice = None
        else:
            broad_groups = ["Wingers","Fullbacks","Centre-backs","Central mids","Attacking mids","Defensive mids","Strikers","Goalkeepers"]
            # If GROUP mode
            group_choice = mode2.selectbox("General group", broad_groups, key=f"{_keybase}_group")
            fcm_role_choice = None

        # 2) Cohort controls
        master = load_wyscout_master()
        if master.empty:
            st.info("No Wyscout data loaded yet. Add your Belgium/Dutch/France CSVs to the folders used by your Data analysis section.")
        else:
            nations_avail = sorted([x for x in master["__nation"].dropna().astype(str).unique().tolist() if x])
            default_nations = nations_avail or ["Belgium","Netherlands","France"]
            n1, n2 = st.columns([2,1])
            sel_nations = n1.multiselect("Leagues", default_nations, default=default_nations, key=f"co_nations_{focus_idx}")
            min_minutes = n2.slider("Minutes threshold", min_value=0, max_value=1800, value=600, step=30, key=f"co_min_{focus_idx}")

            ct_left, ct_right = st.columns([1,2])
            cohort_choice = ct_left.radio("Cohort", ["FCM role peers", "General group peers"], horizontal=False, key=f"co_type_{focus_idx}")

            # FCM role default from this player's first stored role (if any)
            player_roles = normalize_roles_to_options(r.get("Position",""))
            default_role = player_roles[0] if player_roles else ""
            # General group default guessed from role label
            grp_opts = ["GK","FB","CB","DM","CMAM","W","CF"]
            # crude guess
            guess_grp = "GK" if str(default_role).startswith("GK") else ("CB" if any(x in (default_role or "") for x in ["4","5L","5R"]) else ("FB" if any(x in (default_role or "") for x in ["2","3"]) else ("W" if any(x in (default_role or "") for x in ["11","7","11a","7a"]) else ("DM" if default_role == "6" else ("CMAM" if default_role in ["8","10 - CAM","10a"] else "W")))))

            if cohort_choice == "FCM role peers":
                fcm_role = ct_right.selectbox("FCM role", ROLE_ORDER, index=(ROLE_ORDER.index(default_role) if default_role in ROLE_ORDER else 0), key=f"co_fcm_{focus_idx}")
                general_group = None
                cohort_type_key = "FCM"
            else:
                general_group = ct_right.selectbox("Group", grp_opts, index=(grp_opts.index(guess_grp) if guess_grp in grp_opts else grp_opts.index("W")), key=f"co_grp_{focus_idx}")
                fcm_role = None
                cohort_type_key = "GROUP"

            # 3) Build cohort + compute z-scores
            target_ws_id = str(r.get("Wyscout Player ID","")).strip() or None
            target_name  = str(r.get("Name","")).strip() or None

            ztab, packs, weights, target_row = prepare_cohort_analysis(
                master_ws,
                target_player_name=r.get("Name",""),
                target_wyscout_id=current_ws_id_or_manual_pick,
                cohort_type=cohort_mode,
                fcm_role=fcm_role_choice,
                general_group=group_choice,
                nations=nations_pick,
                min_minutes=int(mins_thresh),
                league_hint=(league_hint or None),
            )

            
            if not ztab.empty:
            # Overall rank/score are added by prepare_cohort_analysis
                # Safely show overall score and rank (only if target matched)
                if not target_row.empty and "__overall_rank" in target_row and "__overall_score" in target_row:
                    st.metric("Overall score", f"{float(target_row['__overall_score']):.2f}")
                    st.metric("Overall rank in cohort", int(target_row["__overall_rank"]))
                else:
                    st.caption("This player isn’t matched in the current cohort yet.")

                    st.caption(f"Percentile: {float(target_row['__overall_pct']):.1f}")

            render_metric_table_for_target(ztab, target_row, packs)

            # 4) Render quick summary and stash the table for Part 3 rendering
            if ztab.empty or not packs:
                st.info("No cohort data found with the current filters. Try reducing the minutes threshold or changing leagues.")
            else:
                csum1, csum2, csum3 = st.columns([1,1,2])
                csum1.metric("Cohort size", len(ztab))
                if target_row.empty:
                    csum2.metric("Overall score", "—")
                    csum3.caption("This player was not matched in the cohort by Wyscout ID or exact name. You can still browse the cohort below.")
                else:
                    try:
                        rk = int(target_row.get("__overall_rank", 0))
                        sc = float(target_row.get("__overall_score", float("nan")))
                        pc = float(target_row.get("__overall_pct", float("nan")))
                        csum2.metric("Overall score", f"{sc:.2f}")
                        csum3.caption(f"Overall rank: **{rk} / {len(ztab)}** • Percentile: **{pc:.1f}%**")
                    except Exception:
                        csum2.metric("Overall score", "—")
                        csum3.caption("—")

                # Stash into session for Part 3 rich rendering (colour bars etc.)
                st.session_state[f"cohort_ztab_{focus_idx}"] = ztab
                st.session_state[f"cohort_packs_{focus_idx}"] = packs
                st.session_state[f"cohort_weights_{focus_idx}"] = weights

                # Lightweight preview table for now (Part 3 will add coloured metric table + Top 5 strengths)
                preview_cols = [c for c in ["Player","Team","Position","Minutes played","__overall_score","__overall_rank","__overall_pct"] if c in ztab.columns]
                st.dataframe(ztab.sort_values("__overall_score", ascending=False)[preview_cols].head(25),
                            use_container_width=True, hide_index=True)

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
                mask = ztab.get("Wyscout Player ID", pd.Series([""]*len(ztab))).astype(str) == target_ws_id
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

            if player_row is None:
                st.caption("This player is not in the cohort (no Wyscout ID or exact name match).")
            else:
                # Build list of (metric, z_adjusted, raw, pct, rank)
                top_items = []
                for clust, metrics in packs.items():
                    for m in metrics:
                        if not _metric_exists(m):
                            continue
                        zval = player_row.get(f"{m}__z", float("nan"))
                        if not np.isfinite(zval):
                            continue
                        # invert if lower is better
                        if not metric_direction(m):
                            zval = -zval
                        raw = player_row.get(m, np.nan)
                        pct = player_row.get(f"{m}__pct", np.nan)
                        rk  = player_row.get(f"{m}__rank", np.nan)
                        top_items.append((clust, m, float(zval), raw, pct, rk))

                if not top_items:
                    st.caption("No valid metrics for this player in the current cohort.")
                else:
                    # sort by z descending and take top 5
                    top_items.sort(key=lambda x: x[2], reverse=True)
                    top5 = top_items[:5]
                    ccols = st.columns(5)
                    for (col, item) in zip(ccols, top5):
                        clust, m, zsc, raw, pct, rk = item
                        with col:
                            st.markdown(f"**{m}**")
                            st.caption(clust)
                            st.markdown(_pct_bar(pct), unsafe_allow_html=True)
                            st.caption(f"Raw: {_fmt_raw(raw)}  |  Rank: {int(rk) if pd.notna(rk) else 'NA'}")

            st.markdown("---")
            st.subheader("📊 Metric tables")

            # ------- Per-cluster metric tables with coloured percentiles -------
            for clust_name, metrics in packs.items():
                show_cols = []
                rows_html = []
                # Build rows as HTML to get nice colour bars for percentile
                for m in metrics:
                    if not _metric_exists(m):
                        continue
                    # cohort aggregates
                    cohort_raw = pd.to_numeric(ztab[m], errors="coerce")
                    mu = cohort_raw.mean(skipna=True)
                    sd = cohort_raw.std(skipna=True, ddof=0)
                    # player values (if present)
                    if player_row is not None:
                        raw_v = player_row.get(m, np.nan)
                        pct_v = player_row.get(f"{m}__pct", np.nan)
                        rk_v  = player_row.get(f"{m}__rank", np.nan)
                    else:
                        raw_v = np.nan; pct_v = np.nan; rk_v = np.nan

                    row_html = f"""
                    <tr>
                    <td style="padding:6px 8px;white-space:nowrap;">{m}</td>
                    <td style="padding:6px 8px;text-align:right;">{_fmt_raw(raw_v)}</td>
                    <td style="padding:6px 8px;text-align:right;">{int(rk_v) if pd.notna(rk_v) else 'NA'}</td>
                    <td style="padding:6px 8px;">{_pct_bar(pct_v)}</td>
                    <td style="padding:6px 8px;text-align:right;opacity:.85;">{_fmt_raw(mu)}</td>
                    <td style="padding:6px 8px;text-align:right;opacity:.85;">{_fmt_raw(sd)}</td>
                    </tr>
                    """
                    rows_html.append(row_html)

                if not rows_html:
                    continue

                st.markdown(f"**{clust_name}**")
                st.markdown("""
                <table style="width:100%;border-collapse:separate;border-spacing:0 6px;">
                <thead>
                    <tr>
                    <th style="text-align:left;padding:6px 8px;">Metric</th>
                    <th style="text-align:right;padding:6px 8px;">Raw</th>
                    <th style="text-align:right;padding:6px 8px;">Rank</th>
                    <th style="text-align:left;padding:6px 8px;">Percentile</th>
                    <th style="text-align:right;padding:6px 8px;opacity:.85;">Cohort mean</th>
                    <th style="text-align:right;padding:6px 8px;opacity:.85;">Cohort stdev</th>
                    </tr>
                </thead>
                <tbody>
                """, unsafe_allow_html=True)

                st.markdown("\n".join(rows_html), unsafe_allow_html=True)
                st.markdown("</tbody></table>", unsafe_allow_html=True)
                st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

            st.markdown("---")
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


        # --- Scouting notes & KPIs
        st.markdown("---")
        st.subheader("📝 Scouting notes & KPIs")
        df = profile_editor(df, focus_idx)

        # --- Full report files
        st.markdown("---")
        st.subheader("📄 Full report")
        REPORTS_DIR = os.path.join("FCM Scouting", "full reports done")
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
                    write_db(st.session_state.db_csv, df)
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
                _render_pdf_as_images(cur_pdf_path, max_pages=max_pages, dpi=dpi)
            else:
                ok = _embed_pdf_data_uri(cur_pdf_path, height=900)
                if not ok:
                    st.info("If the embed is blocked by your browser, switch preview mode to **Image pages** above.")

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
                    write_db(st.session_state.db_csv, df_latest)
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

# =========================
# 15) DATA ANALYSIS PAGE
# =========================
if nav == "📊 Data analysis":
    st.title("Data analysis")

    from pathlib import Path
    import glob, math, re as _re

    # -------------------- robust CSV/XLSX readers --------------------
    ENCODING_CANDIDATES = [
        "utf-8-sig",
        "cp1252",
        "latin1",
        "utf-16",
        "utf-16le",
        "utf-16be",
    ]

    def _sniff_delimiter(sample: bytes) -> str:
        # Try csv.Sniffer first, fall back to common separators
        try:
            sample_txt = sample.decode("utf-8", errors="ignore")
            dialect = csv.Sniffer().sniff(sample_txt, delimiters=",;\t|")
            return dialect.delimiter
        except Exception:
            # Heuristic counts
            text = sample.decode("utf-8", errors="ignore")
            counts = {sep: text.count(sep) for sep in [",",";","\t","|"]}
            return max(counts, key=counts.get) if counts else ","

    def read_csv_resilient(path: str) -> pd.DataFrame:
        # Read small head to guess delimiter
        try:
            with open(path, "rb") as fh:
                head = fh.read(65536)
        except Exception as e:
            raise RuntimeError(f"Cannot open {path}: {e}")

        delim = _sniff_delimiter(head)

        last_err = None
        for enc in ENCODING_CANDIDATES:
            try:
                return pd.read_csv(path, sep=delim, encoding=enc, engine="python", dtype=str, keep_default_na=False)
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("Unknown CSV error")

    def read_xlsx_resilient(path: str) -> list[pd.DataFrame]:
        out = []
        try:
            xls = pd.ExcelFile(path)
            for sheet in xls.sheet_names:
                try:
                    df_ = xls.parse(sheet_name=sheet, dtype=str)
                    out.append(df_)
                except Exception as e:
                    st.warning(f"Failed to read sheet '{sheet}' from {Path(path).name}: {e}")
        except Exception as e:
            st.warning(f"Failed to open {Path(path).name}: {e}")
        return out

    # -------------------- unified parsing helpers --------------------
    def parse_market_value(text: str) -> float:
        if not text: return math.nan
        s = str(text).lower().replace("€","").replace("eur","").strip()
        mult = 1.0
        if "m" in s:
            mult = 1_000_000.0; s = s.replace("m","")
        elif "k" in s:
            mult = 1_000.0; s = s.replace("k","")
        s = s.replace(",", "").strip()
        try:
            return float(s) * mult
        except Exception:
            if "million" in s.split():
                try: return float(s.split()[0]) * 1_000_000.0
                except: return math.nan
            return math.nan

    def parse_minutes(text: str) -> float:
        try: return float(str(text).replace(",", "").strip())
        except: return math.nan

    def parse_date_any(s: str) -> pd.Timestamp | pd.NaT:
        if not s: return pd.NaT
        s = str(s).strip()
        fmts = ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%d-%m-%Y","%d.%m.%Y","%b %d, %Y","%d %b %Y")
        for fmt in fmts:
            try: return pd.to_datetime(s, format=fmt)
            except Exception: pass
        try: return pd.to_datetime(s, errors="coerce")
        except: return pd.NaT

    def _parse_height_m(x):
        if pd.isna(x): return math.nan
        s = str(x).lower().replace(",", ".")
        m = _re.search(r"(\d+(\.\d+)?)\s*m", s)
        if m:
            try: return float(m.group(1))
            except: return math.nan
        m = _re.search(r"(\d+)\s*cm", s)
        if m:
            try: return float(m.group(1))/100.0
            except: return math.nan
        try:
            v = float(s)
            return v if 0.5 <= v <= 2.7 else (v/100.0 if 130 <= v <= 230 else math.nan)
        except: return math.nan

    POS_CHOICES = [
        "GK",
        "RB","RWB","RCB","CB","LCB","LB","LWB",
        "DMF","RDMF","LDMF","CMF","RCMF","LCMF",
        "AMF","RAMF","LAMF",
        "RW","RWF","RM",
        "LW","LWF","LM",
        "CF","ST","SS"
    ]

    # -------------------- folders --------------------
    # Update these if your drive letters change
    belgium_dir = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Belgium"
    dutch_dir   = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Dutch"
    france_dir  = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\France"

    tabs = st.tabs(["🇧🇪 Belgium (tiers)", "🇳🇱 Dutch (tiers)", "🇫🇷 France (tiers)"])

    def _collect_country_frames(folder: str, country_label: str, tiers: list[int]) -> list[pd.DataFrame]:
        frames: list[pd.DataFrame] = []

        # Explicit tier files like France1.csv, France2.csv, France3.csv
        for t in tiers:
            csv_path = Path(folder) / f"{country_label}{t}.csv"
            if csv_path.exists():
                try:
                    df_ = read_csv_resilient(str(csv_path))
                    df_["__source_file"] = csv_path.name
                    df_["__tier"] = t
                    frames.append(df_)
                except Exception as e:
                    st.warning(f"Failed to read {csv_path}: {e}")
            # Also load any xlsx with similar naming
            xlsx_path = Path(folder) / f"{country_label}{t}.xlsx"
            if xlsx_path.exists():
                for df_ in read_xlsx_resilient(str(xlsx_path)):
                    df_["__source_file"] = xlsx_path.name
                    df_["__tier"] = t
                    frames.append(df_)

        # Also include any other loose CSV/XLSX in the folder whose name contains the tier number
        for any_csv in glob.glob(str(Path(folder) / "*.csv")):
            name = Path(any_csv).name
            for t in tiers:
                if str(t) in name and (country_label.lower() in name.lower()):
                    try:
                        df_ = read_csv_resilient(any_csv)
                        df_["__source_file"] = name
                        df_["__tier"] = t
                        frames.append(df_)
                    except Exception as e:
                        st.warning(f"Failed to read {name}: {e}")

        for any_xlsx in glob.glob(str(Path(folder) / "*.xlsx")):
            name = Path(any_xlsx).name
            for t in tiers:
                if str(t) in name and (country_label.lower() in name.lower()):
                    for df_ in read_xlsx_resilient(any_xlsx):
                        df_["__source_file"] = name
                        df_["__tier"] = t
                        frames.append(df_)

        return frames

    def render_country_tab(label: str, folder: str, file_prefix: str, key_prefix: str):
        st.subheader(f"{label} league analysis")

        # Pick tiers to include
        ti1, ti2, ti3 = st.columns(3)
        t1 = ti1.checkbox("Tier 1", value=True, key=f"{key_prefix}_t1")
        t2 = ti2.checkbox("Tier 2", value=True, key=f"{key_prefix}_t2")
        t3 = ti3.checkbox("Tier 3", value=True, key=f"{key_prefix}_t3")
        tiers = [i for i, flag in zip([1,2,3], [t1,t2,t3]) if flag]

        # Gather frames
        frames = _collect_country_frames(folder, file_prefix, tiers)

        if not frames:
            st.error(f"No data found for {label} ({'–'.join(map(str, tiers))}).")
            return

        df_all = pd.concat(frames, ignore_index=True, sort=False)
        # Normalize columns if present
        # Try to map common headers
        COL_PLAYER   = next((c for c in df_all.columns if c.lower() in {"player","name","player name"}), "Player")
        COL_TEAM     = next((c for c in df_all.columns if c.lower() in {"team","club","current team","squad"}), "Team")
        COL_POS      = next((c for c in df_all.columns if c.lower() in {"position","pos"}), "Position")
        COL_AGE      = next((c for c in df_all.columns if c.lower() == "age"), "Age")
        COL_MIN      = next((c for c in df_all.columns if "minute" in c.lower()), "Minutes played")
        COL_MV       = next((c for c in df_all.columns if "market value" in c.lower() or c.lower()=="mv"), "Market value")
        COL_CONTRACT = next((c for c in df_all.columns if "contract" in c.lower()), "Contract expires")

        # Helper columns
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

        # -------------------- filters --------------------
        BASE_COLS = [COL_PLAYER, COL_TEAM, "Foot", COL_POS, COL_AGE, COL_MV, COL_CONTRACT, "__tier", "__source_file"]

        f1, f2, f3 = st.columns(3)
        q_name  = f1.text_input("Search name", placeholder="Type part of a name…", key=f"{key_prefix}_qname")
        teams   = sorted(df_all[COL_TEAM].dropna().astype(str).unique().tolist()) if COL_TEAM in df_all.columns else []
        sel_team = f2.multiselect("Teams", teams, key=f"{key_prefix}_teams")
        sel_pos = f3.multiselect("Positions (Wyscout style)", POS_CHOICES, key=f"{key_prefix}_pos")

        g1, g2 = st.columns(2)
        if COL_AGE in df_all.columns:
            age_series = pd.to_numeric(df_all[COL_AGE], errors="coerce")
            if age_series.notna().any():
                amin, amax = int(age_series.min()), int(age_series.max())
                age_rng = g1.slider("Age range", value=(amin, amax), min_value=amin, max_value=amax, key=f"{key_prefix}_age")
            else:
                age_rng = None
        else:
            age_rng = None

        if pd.to_numeric(df_all["_mins"], errors="coerce").notna().any():
            mmin = int(pd.to_numeric(df_all["_mins"], errors="coerce").min())
            mmax = int(pd.to_numeric(df_all["_mins"], errors="coerce").max())
            mins_rng = g2.slider("Minutes played", value=(mmin, mmax), min_value=mmin, max_value=mmax, step=10, key=f"{key_prefix}_mins")
        else:
            mins_rng = None

        h1, h2 = st.columns(2)
        if pd.to_numeric(df_all["_height_m"], errors="coerce").notna().any():
            hmin = float(pd.to_numeric(df_all["_height_m"], errors="coerce").min())
            hmax = float(pd.to_numeric(df_all["_height_m"], errors="coerce").max())
            height_rng = h1.slider("Height (m)", value=(round(hmin,2), round(hmax,2)),
                                   min_value=0.50, max_value=2.50, step=0.01, key=f"{key_prefix}_height")
        else:
            height_rng = None

        j1, j2 = st.columns(2)
        if pd.to_numeric(df_all["_mv_eur"], errors="coerce").notna().any():
            mv_min = int(pd.to_numeric(df_all["_mv_eur"], errors="coerce").min())
            mv_max = int(pd.to_numeric(df_all["_mv_eur"], errors="coerce").max())
            mv_rng = j1.slider("Market value (€)", value=(mv_min, mv_max),
                               min_value=mv_min, max_value=mv_max, step=50_000, key=f"{key_prefix}_mv")
        else:
            mv_rng = None

        if pd.to_datetime(df_all["_contract_dt"], errors="coerce").notna().any():
            cmin = pd.to_datetime(df_all["_contract_dt"]).min().date()
            cmax = pd.to_datetime(df_all["_contract_dt"]).max().date()
            contract_rng = j2.date_input("Contract expires (range)", value=(cmin, cmax), format="YYYY-MM-DD", key=f"{key_prefix}_contract")
        else:
            contract_rng = None

        helper_cols = {"_mv_eur","_mins","_contract_dt","_height_m"}
        present_base = [c for c in BASE_COLS if c in df_all.columns]
        kpi_candidates = [c for c in df_all.columns if c not in present_base and c not in helper_cols]

        show_kpis = st.multiselect("Pick KPI columns", options=kpi_candidates, default=kpi_candidates, key=f"{key_prefix}_kpis")

        # -------------------- filter data --------------------
        view = df_all.copy()

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
            start_dt = pd.to_datetime(contract_rng[0]); end_dt = pd.to_datetime(contract_rng[1])
            view = view[(pd.to_datetime(view["_contract_dt"], errors="coerce") >= start_dt) &
                        (pd.to_datetime(view["_contract_dt"], errors="coerce") <= end_dt)]

        if height_rng:
            hseries = pd.to_numeric(view["_height_m"], errors="coerce")
            view = view[(hseries >= height_rng[0]) & (hseries <= height_rng[1])]

        st.caption(f"Rows: {len(view)} / {len(df_all)}")

        display_cols = present_base + [c for c in show_kpis if c not in present_base and c in view.columns]
        display_cols = [c for c in display_cols if c in view.columns]
        to_show = view[display_cols] if display_cols else view

        st.dataframe(
            to_show,
            use_container_width=True,
            hide_index=True,
            column_order=display_cols if display_cols else None,
        )

        c1, c2 = st.columns(2)
        c1.download_button(
            "Download filtered (CSV)",
            data=to_show.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{label.lower().split()[0]}_filtered.csv",
            mime="text/csv",
            key=f"{key_prefix}_dl_csv"
        )
        try:
            with pd.ExcelWriter(io.BytesIO(), engine="xlsxwriter") as w:
                to_show.to_excel(w, index=False, sheet_name=label)
                xldata = w.book.filename.getvalue()  # type: ignore
            c2.download_button(
                "Download filtered (Excel)",
                data=xldata,
                file_name=f"{label.lower().split()[0]}_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key_prefix}_dl_xlsx"
            )
        except Exception:
            st.caption("Install xlsxwriter for Excel export. CSV export always works.")

    with tabs[0]:
        render_country_tab("Belgium", belgium_dir, file_prefix="Belgium", key_prefix="be")
    with tabs[1]:
        render_country_tab("Dutch", dutch_dir, file_prefix="Dutch", key_prefix="nl")
    with tabs[2]:
        render_country_tab("France", france_dir, file_prefix="France", key_prefix="fr")

# =========================
# 16) 📅 FIXTURES (Multi-nation) — Season 25/26
# =========================
if nav == "📅 Fixtures":
    st.title("📅 Fixtures — Season 25/26")

    # ---- Nations (folders under Fixtures/)
    NATIONS = ["Belgium", "Netherlands", "France", "Other"]

    # helper: list CSVs under a nation folder
    def _nation_files(nation: str) -> list[str]:
        folder = nation_dir(nation)
        files = []
        try:
            for n in os.listdir(folder):
                if n.lower().endswith(".csv"):
                    files.append(os.path.join(folder, n))
        except Exception:
            pass
        return sorted(files, key=lambda p: os.path.basename(p).lower())

    # UI tabs along the very top: one per nation + general/calendar/import
    top_labels = [f"🇧🇪 Belgium", f"🇳🇱 Netherlands", f"🇫🇷 France", "⭐ Other", "🟨 General (7d)", "📆 Calendar", "🔎 Import"]
    tab_be, tab_nl, tab_fr, tab_other, tab_general, tab_calendar, tab_import = st.tabs(top_labels)

    # Reusable renderer for one nation tab
    def _nation_tab_ui(nation: str, tab, keyroot: str):
        with tab:
            # pick which league (tier) file to show
            files = _nation_files(nation)
            if not files:
                st.info(f"No CSVs found under `{nation_dir(nation)}` yet.")
                return
            options = ["All leagues"] + [os.path.basename(p) for p in files]
            pick = st.selectbox("League file", options, key=f"{keyroot}_pick")
            show_path = os.path.join(nation_dir(nation), pick) if pick != "All leagues" else files[0]
            st.caption(f"Folder: {nation_dir(nation)}")
            st.caption(f"Source: {show_path}")

            # Load
            try:
                fx_all = [load_fixtures_csv(p, SEASON_START_2526, SEASON_END_2526) for p in (files if pick=="All leagues" else [show_path])]
                fx = pd.concat(fx_all, ignore_index=True, sort=False) if len(fx_all) > 1 else fx_all[0]
            except Exception as e:
                st.error(f"Failed to load fixtures: {e}")
                return

            # All teams in this nation bundle
            all_teams = sorted(set(pd.concat([fx["Home"], fx["Away"]]).astype(str).tolist()))

            sub_upcoming, sub_all = st.tabs([f"Upcoming (next {UPCOMING_WINDOW_DAYS} days)", "All season"])
            with sub_upcoming:
                fcols = st.columns([3,2,2])
                team_filter = fcols[0].selectbox("Filter by team", [""] + all_teams, key=f"{keyroot}_up_team")
                include_past_3 = fcols[1].toggle("Include past 3 days", value=False, key=f"{keyroot}_up_past3")

                today = date.today()
                start_window = today - dt.timedelta(days=3) if include_past_3 else today
                end_window = today + dt.timedelta(days=UPCOMING_WINDOW_DAYS)

                view = fx[(fx["KO_date"] >= start_window) & (fx["KO_date"] <= end_window)].copy()
                if team_filter:
                    view = view[(view["Home"] == team_filter) | (view["Away"] == team_filter)]
                st.caption(f"{len(view)} fixtures from {start_window.strftime('%d/%m/%Y')} to {end_window.strftime('%d/%m/%Y')}")
                if view.empty:
                    st.info("No fixtures in the selected window.")
                else:
                    _render_fixture_cards_multination(view, fixtures_path=show_path, nation=nation, key_prefix=f"up_{keyroot}")

            with sub_all:
                g1, g2, g3 = st.columns([2,3,2])
                team_filter2 = g1.multiselect("Teams", all_teams, default=[], key=f"{keyroot}_all_teams")
                rng = g2.date_input("Date range", value=(SEASON_START_2526, SEASON_END_2526), format="YYYY-MM-DD", key=f"{keyroot}_all_rng")
                text_q = g3.text_input("Search title", key=f"{keyroot}_all_q")

                view2 = fx.copy()
                if team_filter2:
                    mask = False
                    for t in team_filter2:
                        mask = mask | (view2["Home"] == t) | (view2["Away"] == t)
                    view2 = view2[mask]
                if isinstance(rng, (list, tuple)) and len(rng) == 2:
                    try:
                        d1, d2_ = rng
                        view2 = view2[(view2["KO_date"] >= d1) & (view2["KO_date"] <= d2_)]
                    except Exception:
                        pass
                if text_q:
                    view2 = view2[view2["Title"].astype(str).str.contains(text_q, case=False, na=False)]

                st.caption(f"{len(view2)} fixtures")
                if view2.empty:
                    st.info("No fixtures for the selected filters.")
                else:
                    _render_fixture_cards_multination(view2, fixtures_path=show_path, nation=nation, key_prefix=f"all_{keyroot}")

    # Render each nation tab
    _nation_tab_ui("Belgium", tab_be, "be")
    _nation_tab_ui("Netherlands", tab_nl, "nl")
    _nation_tab_ui("France", tab_fr, "fr")
    _nation_tab_ui("Other", tab_other, "oth")

    # -------- 🟨 General (combined next 7 days across all nations/folders) --------
    with tab_general:
        st.subheader("Combined fixtures — next 7 days (all nations)")
        bundles = []
        for nation in NATIONS:
            for p in _nation_files(nation):
                try:
                    df = load_fixtures_csv(p, SEASON_START_2526, SEASON_END_2526).copy()
                    bundles.append((nation, p, df))
                except Exception as e:
                    st.warning(f"Failed to load {nation}: {os.path.basename(p)} ({e})")

        if not bundles:
            st.info("No fixture files found.")
        else:
            players = load_db(st.session_state.db_csv).copy()
            today = date.today()
            end7 = today + dt.timedelta(days=7)
            rows = []
            for nation, path, df in bundles:
                view = df[(df["KO_date"] >= today) & (df["KO_date"] <= end7)].copy()
                for _, r in view.iterrows():
                    home, away = r["Home"], r["Away"]
                    ph, pa = _players_for_fixture(players, home, away, nation)
                    sc = interest_score(ph, pa)
                    rows.append({
                        "Nation": nation, "Path": path, "Fixture ID": r["Fixture ID"],
                        "KO_date": r["KO_date"], "Title": r["Title"], "Home": home, "Away": away,
                        "Watched": r.get("Watched","No"), "Score": sc, "_ph": ph, "_pa": pa
                    })
            if not rows:
                st.info("No fixtures in the next 7 days.")
            else:
                df_rows = pd.DataFrame(rows).sort_values(["Score","KO_date"], ascending=[False, True])
                for _, rr in df_rows.iterrows():
                    fid = rr["Fixture ID"]; nation = rr["Nation"]; path = rr["Path"]
                    watched = str(rr["Watched"]).strip().lower() == "yes"
                    koday = rr["KO_date"]; dt_txt = koday.strftime("%a %d %b") if isinstance(koday, date) else ""
                    with st.container(border=True):
                        c1, c2 = st.columns([5,1])
                        with c1:
                            st.markdown(f"**{rr['Home']} vs {rr['Away']}**")
                            st.caption(f"{dt_txt} • {rr['Title']} • {nation}")
                        with c2:
                            ck_key = f"fx_w_gen_{nation}_{os.path.basename(path)}_{fid}"
                            new_state = st.checkbox("Watched", value=watched, key=ck_key)
                            if new_state != watched:
                                ok = toggle_fixture_watched(path, fid, new_state)
                                if ok: st.success("Saved")
                                else: st.session_state[ck_key] = watched
                        st.markdown("Players to scout")
                        cols = st.columns(2)
                        with cols[0]:
                            st.caption(rr["Home"])
                            chips = " ".join([_player_chip(r) for r in rr["_ph"][:20]]) if rr["_ph"] else "—"
                            st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                        with cols[1]:
                            st.caption(rr["Away"])
                            chips = " ".join([_player_chip(r) for r in rr["_pa"][:20]]) if rr["_pa"] else "—"
                            st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)

    # -------- 📆 Calendar (week grid, all nations/folders) --------
    with tab_calendar:
        st.subheader("Week view — all nations")
        anchor = st.date_input("Week of", value=date.today(), format="YYYY-MM-DD", key="cal_week_anchor")
        wk_start, wk_end = week_bounds(anchor)
        st.caption(f"{wk_start.strftime('%d %b %Y')} — {wk_end.strftime('%d %b %Y')}")
        frames = []
        for nation in NATIONS:
            for p in _nation_files(nation):
                try:
                    sub = load_fixtures_csv(p, SEASON_START_2526, SEASON_END_2526)
                    sub = sub[(sub["KO_date"] >= wk_start) & (sub["KO_date"] <= wk_end)].copy()
                    if not sub.empty:
                        sub["Nation"] = nation; sub["Path"] = p
                        frames.append(sub)
                except: ...
        if not frames:
            st.info("No fixtures this week.")
        else:
            allw = pd.concat(frames, ignore_index=True, sort=False)
            by_day = group_fixtures_by_day(allw)
            days = [wk_start + dt.timedelta(days=i) for i in range(7)]
            cols = st.columns(7)
            for col, dday in zip(cols, days):
                with col:
                    st.markdown(f"**{dday.strftime('%a')}**")
                    st.caption(dday.strftime("%d %b"))
                    day_df = by_day.get(dday, pd.DataFrame())
                    if day_df.empty:
                        st.write("—")
                    else:
                        for _, r in day_df.iterrows():
                            fid = r["Fixture ID"]; nation = r["Nation"]; path = r["Path"]
                            watched = str(r.get("Watched","No")).strip().lower() == "yes"
                            with st.container(border=True):
                                st.markdown(f"{r['Home']} vs {r['Away']}")
                                st.caption(f"{r['Title']} • {nation}")
                                ck_key = f"fx_w_cal_{nation}_{os.path.basename(path)}_{fid}"
                                new_state = st.checkbox("Watched", value=watched, key=ck_key)
                                if new_state != watched:
                                    ok = toggle_fixture_watched(path, fid, new_state)
                                    if ok: st.success("Saved")
                                    else: st.session_state[ck_key] = watched

    # -------- 🔎 Import (league or single match) --------
    with tab_import:
        st.subheader("Import fixtures")
        mode = st.radio("Mode", ["Transfermarkt — League season", "Transfermarkt — Single match"], horizontal=True)

        # Choose nation & file handling
        nation_pick = st.selectbox("Nation/folder", NATIONS, index=0, key="imp_nation")
        nation_folder = nation_dir(nation_pick)

        if mode == "Transfermarkt — League season":
            st.caption("Example: https://www.transfermarkt.com/ligue-1/gesamtspielplan/wettbewerb/FR1/saison_id/2025")
            url = st.text_input("League schedule URL", key="imp_tm_league_url")
            fname = st.text_input("Save as (filename only, e.g. ligue1.csv)", value="league.csv", key="imp_tm_league_name")
            if st.button("Fetch & save league fixtures", type="primary", key="imp_tm_league_btn"):
                try:
                    rows = scrape_transfermarkt_league_fixtures(url)
                    if not rows:
                        st.warning("No fixtures parsed from this page.")
                    else:
                        out_path = os.path.join(nation_folder, fname if fname.lower().endswith(".csv") else f"{fname}.csv")
                        merge_tm_fixtures_into_csv(rows, out_path, SEASON_START_2526, SEASON_END_2526)
                        st.success(f"Saved {len(rows)} fixtures → {out_path}")
                        st.cache_data.clear()
                except Exception as e:
                    st.error(f"Import failed: {e}")

        elif mode == "Transfermarkt — Single match":
            st.caption("Example: https://www.transfermarkt.com/spielbericht/index/spielbericht/4745212")
            url = st.text_input("Match report URL", key="imp_tm_single_url")

            # pick a target CSV inside the nation (append); or choose custom
            files = _nation_files(nation_pick)
            base_opts = [os.path.basename(p) for p in files]
            target_choice = st.selectbox("Append into", ["(type a new filename)"] + base_opts, key="imp_tm_single_target")
            custom_name = ""
            if target_choice == "(type a new filename)":
                custom_name = st.text_input("New/Existing CSV name (e.g. other_matches.csv)", key="imp_tm_single_new")
            if st.button("Fetch & append this match", type="primary", key="imp_tm_single_btn"):
                try:
                    row = scrape_transfermarkt_single_match(url)
                    if not row:
                        st.warning("Could not parse this page.")
                    else:
                        if target_choice == "(type a new filename)":
                            out_path = os.path.join(nation_folder, custom_name if custom_name.lower().endswith(".csv") else f"{custom_name}.csv")
                        else:
                            out_path = os.path.join(nation_folder, target_choice)
                        append_single_fixture(row, out_path)
                        st.success(f"Appended {row['Title']} ({row['Given planned earliest start']}) → {out_path}")
                        st.cache_data.clear()
                except Exception as e:
                    st.error(f"Single match import failed: {e}")

