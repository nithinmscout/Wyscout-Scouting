from __future__ import annotations

# =========================
# 1) STANDARD LIB IMPORTS
# =========================
import os, io, re, datetime as dt, base64, uuid, csv
from datetime import datetime, date
from typing import Dict, Any, Optional, List

# =========================
# 2) THIRD-PARTY IMPORTS
# =========================
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import unicodedata
import csv, json
from helpers.transfermarkt_lineups import fetch_match_lineups
from helpers.data_analysis_helpers import render_u21_tab

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
    "Row ID",
    "Name","Position","Age","Age Group","Player Current Team","Potential Rating (1-4)","Watched","Verdict",
    "Shadow Team Colour Code","Player Height","TM Value","Highest TM Value","Contract Until","Agency",
    "Player Nationality","Current Salary","Player weight","Dominant Foot","Source","DOB","Strengths",
    "Weaknesses","Fixture Date","Scout Report By","Created time","Last edited time","Untitled Database",
    "Current Rating (1-4)","Division","Playing Nation","Loan Club","Parent Club","On loan",
    "Full Report Path","Photo URL","Photo Path"
]

# ---- Wyscout league folders (module-level, used by loaders & linkage UI)
WYS_BELGIUM_DIR = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Belgium"
WYS_DUTCH_DIR   = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\Dutch"
WYS_FRANCE_DIR  = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\France"

# Stable focus key based on a persistent UUID per row
ROW_ID_COL = "Row ID"

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
/* Grid so cards don’t stretch tall columns */
.player-grid{
  display:grid;
  grid-template-columns:repeat(4, 1fr);
  gap:14px;
}
@media (max-width: 1300px){ .player-grid{grid-template-columns:repeat(3,1fr)} }
@media (max-width: 900px){  .player-grid{grid-template-columns:repeat(2,1fr)} }
@media (max-width: 600px){  .player-grid{grid-template-columns:1fr} }

/* Card container */
.player-card{
  background:rgba(255,255,255,0.03);
  border-radius:12px;
  padding:10px;
}

/* Force st.image inside the card to a small, consistent height */
.player-card .stImage img{
  width:100% !important;
  height:120px !important;       /* Tweak: 110–160 works well */
  object-fit:cover !important;
  border-radius:8px;
}
.player-card h4{ margin:8px 0 2px; }
.player-card .meta{ font-size:0.85rem; opacity:.8; margin-bottom:6px; }
/* small expander text look */
.small-expander > details > summary { font-size:12px !important; opacity:.85; }
</style>
            
""", unsafe_allow_html=True)


# =========================
# 5) SHARED HELPERS
# =========================

# ---- Files & images
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

@st.cache_data(show_spinner=False)
def cached_fetch_lineups(url: str, pause: float):
    # reuse your existing helpers
    return fetch_match_lineups(
        url=url,
        pause_seconds=pause,
        get_player_info=get_transfermarkt_player_info,
        normalize_player=scrape_transfermarkt
    )


# ---- Text parsing / roles
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

def _norm_str(s) -> str:
    """
    Case/diacritic/punctuation-insensitive key for duplicate checks & matching.
    Accepts any type (incl. NaN/None/floats) and returns a safe string.
    """
    # Handle pandas NA / None first
    try:
        if s is None or (isinstance(s, float) and pd.isna(s)):
            s = ""
        elif hasattr(pd, "isna") and pd.isna(s):  # catches pd.NA etc.
            s = ""
    except Exception:
        pass

    # Coerce to str safely before normalize
    s = "" if s is None else str(s)

    # Now it is always a string
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\W_]+", "", s)
    return s

def log_df_identity(label: str, df_obj: pd.DataFrame):
    # prints a short fingerprint so you can verify you’re saving the full frame
    try:
        print(f"[DBG] {label}: shape={df_obj.shape}, cols={list(df_obj.columns)[:6]}...")
    except Exception:
        pass


# =========================
# FIXTURE / CLUB MATCH HELPERS
# =========================
import hashlib
import unicodedata
import difflib

# Common “filler” tokens you’ll see in club names that don’t change identity.
_CLUB_STOPWORDS = {
    "fc","cf","sc","ssc","ac","as","r","r.","royal","k","k.","kv","k.v.","krc","kaa","ksc",
    "sv","vv","vvv","sv zulte","om","usg","union","club","cercle","standard","sporting",
    "st.","st","saint","st-truiden","saint-trond","sttruiden","u","ud",
    "afc","s.a.d","nv","bv","nv/bv","kvk","rwd","rwdm","oh","ohl",
}

# Normalise to a compact key for matching
def _strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()

def team_key(s: str) -> str:
    """
    Heavily normalised key:
    - lowercase, remove accents
    - collapse punctuation/whitespace
    - remove common stopwords/prefixes/suffixes
    """
    if not s: return ""
    txt = _strip_accents_lower(s)
    # replace punctuation with space
    txt = re.sub(r"[\W_]+", " ", txt)
    # tokenise, drop tiny tokens, drop stopwords
    toks = [t for t in txt.split() if t and len(t) > 1]
    toks = [t for t in toks if t not in _CLUB_STOPWORDS]
    # special mergers: "saint gilloise" -> "saintgilloise", "union saint gilloise" -> "saintgilloise"
    merged = []
    i = 0
    while i < len(toks):
        if i+1 < len(toks) and toks[i] == "saint" and toks[i+1] in {"gilloise","trond","truiden"}:
            merged.append(f"saint{toks[i+1]}")
            i += 2
        else:
            merged.append(toks[i])
            i += 1
    compact = "".join(merged)
    # final compacting: remove spaces just in case
    compact = compact.replace(" ", "")
    return compact

# Static aliases for Belgium – expand any time you notice variants
BELGIUM_CLUB_ALIASES = {
    "RSC Anderlecht": ["RSC Anderlecht","Anderlecht","RSCA"],
    "Club Brugge": ["Club Brugge","Club Brugge KV","Club Bruges","Brugge"],
    "Cercle Brugge": ["Cercle Brugge","Cercle Bruges","Cercle"],
    "KRC Genk": ["KRC Genk","Genk"],
    "KAA Gent": ["KAA Gent","Gent","AA Gent"],
    "Royal Antwerp": ["Royal Antwerp","Antwerp","RAFC","R. Antwerp"],
    "Standard Liège": ["Standard Liège","Standard Liege","Standard","RFC Standard"],
    "Union Saint-Gilloise": ["Union Saint-Gilloise","Union Saint Gilloise","Union SG","Union"],
    "KV Mechelen": ["KV Mechelen","Mechelen","KVM"],
    "OH Leuven": ["OH Leuven","Oud-Heverlee Leuven","OHL","Leuven"],
    "KV Kortrijk": ["KV Kortrijk","Kortrijk","KVK"],
    "RWD Molenbeek": ["RWD Molenbeek","RWDM","Molenbeek"],
    "KVC Westerlo": ["KVC Westerlo","Westerlo"],
    "Eupen": ["KAS Eupen","Eupen","K.AS Eupen"],
    "Charleroi": ["R Charleroi SC","Charleroi","Sporting Charleroi"],
    "Sint-Truiden": ["Sint-Truiden","St-Truiden","Saint-Trond","STVV","Sint Truiden"],
    "Beerschot": ["Beerschot","Beerschot VA","K Beerschot VA"],
    "Lommel SK": ["Lommel SK","Lommel"],
    "Zulte Waregem": ["SV Zulte Waregem","Zulte Waregem","Zulte"],
    "RWDM": ["RWDM","RWD Molenbeek"],  # duplicate friendly
}

# Add Dutch and French aliases to the same index by merging when you build it:
EXTRA_ALIASES = {
    # Netherlands
    "Ajax": ["Ajax","AFC Ajax"],
    "PSV Eindhoven": ["PSV Eindhoven","PSV"],
    "Feyenoord": ["Feyenoord","Feyenoord Rotterdam"],
    "AZ Alkmaar": ["AZ Alkmaar","AZ"],
    "FC Twente": ["FC Twente","Twente"],
    "SC Heerenveen": ["SC Heerenveen","Heerenveen"],
    "FC Utrecht": ["FC Utrecht","Utrecht"],
    "Vitesse": ["Vitesse","SBV Vitesse"],
    "Sparta Rotterdam": ["Sparta Rotterdam","Sparta"],
    "NEC Nijmegen": ["NEC Nijmegen","NEC"],
    # France
    "Paris Saint-Germain": ["Paris Saint-Germain","PSG","Paris SG"],
    "Olympique de Marseille": ["Olympique de Marseille","Marseille","OM"],
    "Olympique Lyon": ["Olympique Lyon","Lyon","OL","Olympique Lyonnais"],
    "AS Monaco": ["AS Monaco","Monaco"],
    "LOSC Lille": ["LOSC Lille","Lille","Lille OSC"],
    "RC Lens": ["RC Lens","Lens"],
    "Stade Rennais": ["Stade Rennais","Rennes","SRFC"],
    "OGC Nice": ["OGC Nice","Nice"],
    "FC Nantes": ["FC Nantes","Nantes"],
    "Stade Brestois 29": ["Stade Brestois 29","Brest","Stade Brestois"],
    "Montpellier HSC": ["Montpellier HSC","Montpellier"],
    "Toulouse FC": ["Toulouse FC","Toulouse"],
    "Le Havre AC": ["Le Havre AC","Le Havre"],
    "AJ Auxerre": ["AJ Auxerre","Auxerre"],
    "Angers SCO": ["Angers SCO","Angers"],
    "FC Lorient": ["FC Lorient","Lorient"],
    "RC Strasbourg": ["RC Strasbourg","Strasbourg","R. Strasbourg"],
    "FC Metz": ["FC Metz","Metz"],
    "Stade de Reims": ["Stade de Reims","Reims"],
    "AS Saint-Étienne": ["AS Saint-Étienne","Saint-Etienne","St Etienne","ASSE"],
}

def _canonical_from_aliases(static_aliases: dict[str, list[str]]) -> dict[str, str]:
    """
    Build a reverse map from many forms -> canonical label, using team_key().
    """
    rev = {}
    for canon, aliases in static_aliases.items():
        forms = [canon, *aliases]
        for f in forms:
            k = team_key(f)
            if k:
                rev[k] = canon
    return rev

def build_club_syn_index(df_players: pd.DataFrame, static_aliases: Optional[dict[str, list[str]]] = None) -> dict[str, str]:
    base = BELGIUM_CLUB_ALIASES.copy()
    if 'EXTRA_ALIASES' in globals():
        for k, v in EXTRA_ALIASES.items():
            base[k] = v
    static_aliases = static_aliases or base
    index = _canonical_from_aliases(static_aliases)

    # Learn from database: Player Current Team, Loan Club, Parent Club
    cols = ["Player Current Team","Loan Club","Parent Club"]
    for col in cols:
        if col in df_players.columns:
            for raw in df_players[col].astype(str).tolist():
                raw = raw.strip()
                if not raw: continue
                k = team_key(raw)
                if not k: continue
                # If not in index, make a reasonable canonical from the most common surface form
                # Here we just use the original raw string (title-cased) as canonical
                if k not in index:
                    index[k] = _tidy_person_name(raw)
    return index

def canonicalise_club(raw: str, syn_index: dict[str,str]) -> str:
    """
    Return the canonical club name for a raw string using the synonym index.
    If not found, try a fuzzy nearest match on keys; otherwise return the tidied raw.
    """
    if not raw: return ""
    k = team_key(raw)
    if k in syn_index:
        return syn_index[k]
    # Fuzzy on keys
    keys = list(syn_index.keys())
    if keys:
        close = difflib.get_close_matches(k, keys, n=1, cutoff=0.85)  # fairly strict
        if close:
            return syn_index[close[0]]
    return _tidy_person_name(raw)

# Parse "Title" into (home, away)
_FIX_SEPS = [r"\s+vs\s+", r"\s+v\s+", r"\s+-\s+", r"\s+—\s+", r"\s+:\s+"]

def parse_fixture_title(title: str) -> tuple[str, str]:
    """
    Try common separators to split a Title into Home/Away.
    Examples:
      "Anderlecht vs Club Brugge"
      "KRC Genk - Standard Liège"
      "Union SG v Antwerp"
    Returns ("","") if it can’t decide.
    """
    t = (title or "").strip()
    if not t: return "",""
    for sep in _FIX_SEPS:
        parts = re.split(sep, t, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            home = parts[0].strip()
            away = parts[1].strip()
            # Strip trailing metadata after team name if present e.g. "Antwerp (Cup)"
            home = re.split(r"\s+\(", home)[0].strip()
            away = re.split(r"\s+\(", away)[0].strip()
            return home, away
    return "",""

def fixture_row_id(dt_iso: str, home: str, away: str) -> str:
    """
    Create a stable 12-char hash id for a fixture row.
    """
    raw = f"{dt_iso}|{home}|{away}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


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
    """Parse strings like '€2.5m', '€250k', '2,000,000', '2.5 million' → float euros."""
    if not s: return None
    txt = str(s).lower().replace("€","").replace("eur","").strip()
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

def fmt_eur_compact(v: Optional[float]) -> str:
    """Format float euros → '€50k', '€100k', '€0.1m', '€1m', '€10m'."""
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

# ---- PDF preview helpers
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

# Emoji flags (cosmetic)
def flag_for_country(name: str) -> str:
    code_map = {
        "Denmark":"DK","Germany":"DE","France":"FR","Spain":"ES","Italy":"IT","England":"GB","Belgium":"BE",
        "Norway":"NO","Sweden":"SE","Netherlands":"NL","Portugal":"PT","Poland":"PL","USA":"US","Brazil":"BR",
    }
    code = code_map.get(name, "")
    if len(code)==2:
        return ''.join(chr(0x1F1E6 + ord(c)-65) for c in code.upper())
    return ""


# =========================
# 6) SCRAPER HELPERS
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

        # name / shirt / mv
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

        # multiple options for headshot
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

        # right info table
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
    # Normalize name & TM value
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

def add_new_dropdown(label, options, state_key_choice, state_key_new, default_text=""):
            choice = st.selectbox(label, ["— select —"] + options + ["Add new…"], key=state_key_choice)
            new_val = st.text_input(f"Add new ({label.lower()})",
                                    value=st.session_state.get(state_key_new, default_text),
                                    key=f"{state_key_new}__input") if choice=="Add new…" else ""
            return new_val if new_val else (choice if choice not in ["— select —","Add new…"] else "")

import os, shutil, time
import pandas as pd

BACKUP_DIR = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Backups\Automatic Player DB"


def safe_write_db(
    path: str,
    df_new: pd.DataFrame,
    min_rows: int = 10,
    min_cols: int = 5,
    backup_dir: str | None = BACKUP_DIR,
) -> bool:
    """
    Defensive CSV writer:
    Refuses to overwrite if row/col count collapses drastically.
    Makes a timestamped backup before final replace.
    Writes atomically to a temp file.
    Returns True if write succeeded.
    """
    # 1) sanity checks on outgoing frame
    if not isinstance(df_new, pd.DataFrame):
        raise ValueError("safe_write_db expected a DataFrame.")
    rows, cols = df_new.shape
    if rows < min_rows or cols < min_cols:
        raise RuntimeError(f"Refusing to write suspiciously small DB ({rows}x{cols}).")

    # 2) read current file (if it exists) to compare size
    old_rows = old_cols = None
    if os.path.exists(path):
        try:
            df_old = pd.read_csv(path)
            old_rows, old_cols = df_old.shape
            # refuse if we are dropping >50 percent rows unintentionally
            if old_rows and rows < max(5, int(0.5 * old_rows)):
                raise RuntimeError(
                    f"Refusing to overwrite: new rows={rows} << old rows={old_rows}."
                )
        except Exception:
            # if unreadable, still proceed with backup path
            pass

        # 3) timestamped backup in BACKUP_DIR (or alongside original if None)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(path))[0]

        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            backup = os.path.join(
                backup_dir, f"{base_name}__backup_{ts}.csv"
            )
        else:
            backup = f"{os.path.splitext(path)[0]}__backup_{ts}.csv"

        shutil.copy2(path, backup)

    # 4) atomic write
    tmp = f"{path}.tmp"
    df_new.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)
    return True


# =========================
# FIXTURES: constants & helpers
# =========================

# Add a sidebar entry for Fixtures (put this next to your other menu_btn calls)
# If you already render the sidebar elsewhere, just ensure this line exists alongside the others:
#   menu_btn("📅 Fixtures", "nav_fixtures")
# If you prefer to add it inline later, you can skip this comment.

FIXTURES_FILE_BE_T1 = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Fixtures\Belgium1.csv"

# Season window for 25/26: 1 July 2025 → 30 June 2026
SEASON_START_2526 = date(2025, 7, 1)
SEASON_END_2526   = date(2026, 6, 30)

# Upcoming window: next 14 days (local)
UPCOMING_WINDOW_DAYS = 14

# Safe write for any CSV (atomic replace)
def safe_write_csv(path: str, df: pd.DataFrame):
    tmp = f"{path}.tmp"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)

# Very robust CSV reader (tries multiple encodings and sniffed delimiter)
import csv
def _sniff_delimiter_bytes(sample: bytes) -> str:
    try:
        sample_txt = sample.decode("utf-8", errors="ignore")
        dialect = csv.Sniffer().sniff(sample_txt, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        # fallback heuristic
        text = sample.decode("utf-8", errors="ignore")
        counts = {sep: text.count(sep) for sep in [",",";","\t","|"]}
        return max(counts, key=counts.get) if counts else ","

def read_csv_resilient_fixtures(path: str) -> pd.DataFrame:
    ENCODING_CANDIDATES = ["utf-8-sig", "cp1252", "latin1", "utf-16", "utf-16le", "utf-16be"]
    with open(path, "rb") as fh:
        head = fh.read(65536)
    delim = _sniff_delimiter_bytes(head)

    last_err = None
    for enc in ENCODING_CANDIDATES:
        try:
            df_ = pd.read_csv(path, sep=delim, encoding=enc, engine="python", dtype=str, keep_default_na=False)
            # strip weird BOMs and whitespace from headers
            df_.columns = [str(c).replace("\ufeff","").strip() for c in df_.columns]
            return df_
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError(f"Failed to read {path}")

def _parse_ddmmyyyy(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        # pandas is forgiving, but we want a strict dd/mm/yyyy for safety
        d = datetime.strptime(s, "%d/%m/%Y").date()
        return d
    except Exception:
        # try common fallbacks if Excel exported differently
        try:
            # sometimes dd/mm/yy
            d = datetime.strptime(s, "%d/%m/%y").date()
            # normalise to 20xx if needed
            if d.year < 100:
                d = d.replace(year=2000 + d.year)
            return d
        except Exception:
            return None

@st.cache_data(show_spinner=False)
def cached_fetch_lineups(url: str, pause: float):
    return fetch_match_lineups(
        url=url,
        pause_seconds=pause,
        get_player_info=get_transfermarkt_player_info,
        normalize_player=scrape_transfermarkt,
        logger=lambda m: st.caption(m)   # optional debug output
    )

@st.cache_data(show_spinner=False)
def load_fixtures_be_t1(fixtures_path: str, season_start: date, season_end: date) -> pd.DataFrame:
    """
    Load, normalise, and season-filter Belgium tier 1 fixtures.
    Expects columns: Title, Given planned earliest start, Given planned earliest end
    Adds/ensures: Fixture ID, Watched (Yes/No), Home, Away, KO_date
    """
    if not os.path.exists(fixtures_path):
        # Create a skeleton to avoid crashes
        df = pd.DataFrame(columns=["Title","Given planned earliest start","Given planned earliest end","Watched"])
        return df

    df = read_csv_resilient_fixtures(fixtures_path).copy()

    # normalise headers in case of spacing
    hdr_map = {c.lower().strip(): c for c in df.columns}
    def col_like(name: str) -> Optional[str]:
        key = name.lower().strip()
        return hdr_map.get(key)

    col_title = col_like("Title") or "Title"
    col_start = col_like("Given planned earliest start") or "Given planned earliest start"
    col_end   = col_like("Given planned earliest end")   or "Given planned earliest end"

    # Ensure columns exist
    for need in [col_title, col_start, col_end]:
        if need not in df.columns:
            df[need] = ""

    # Parse Home/Away from Title
    homes, aways = [], []
    for t in df[col_title].astype(str).tolist():
        h, a = parse_fixture_title(t)
        homes.append(h)
        aways.append(a)
    df["Home_raw"], df["Away_raw"] = homes, aways

    # Parse KO date (dd/mm/yyyy)
    df["KO_date"] = df[col_start].map(_parse_ddmmyyyy)

    # Season filter
    df = df[(df["KO_date"].notna()) &
            (df["KO_date"] >= season_start) &
            (df["KO_date"] <= season_end)].copy()

    # Watched column
    if "Watched" not in df.columns:
        df["Watched"] = "No"
    df["Watched"] = df["Watched"].replace({"yes":"Yes","no":"No"}, regex=True)

    # Build canonical names using player DB
    players = load_db(st.session_state.db_csv).copy()
    syn_index = build_club_syn_index(players)
    df["Home"] = df["Home_raw"].map(lambda s: canonicalise_club(s, syn_index))
    df["Away"] = df["Away_raw"].map(lambda s: canonicalise_club(s, syn_index))

    # Build Fixture ID (stable)
    fid = []
    for dt_, h, a in zip(df["KO_date"], df["Home"], df["Away"]):
        dt_iso = dt_.strftime("%Y-%m-%d") if isinstance(dt_, date) else ""
        fid.append(fixture_row_id(dt_iso, h, a))
    if "Fixture ID" not in df.columns:
        df["Fixture ID"] = fid
    else:
        # fill empties only
        df["Fixture ID"] = df["Fixture ID"].where(df["Fixture ID"].astype(str).str.strip() != "", fid)

    # Useful sort
    df = df.sort_values(["KO_date","Home","Away"], ascending=[True, True, True]).reset_index(drop=True)
    return df

@st.cache_data
def _discover_global_numeric_kpis() -> list[str]:
    """
    Scan all nation folders and tiers to collect the union of numeric KPI columns.
    Used only for the presets manager, independent of the graphs tab.
    """
    nation_dirs = wyscout_folders()
    frames: list[pd.DataFrame] = []
    for folder in nation_dirs:
        nation_label = os.path.basename(folder)
        # take three tiers for each, you already have _collect_country_frames
        frames += _collect_country_frames(folder, nation_label, [1, 2, 3])

    if not frames:
        return []

    df_all = pd.concat(frames, ignore_index=True, sort=False)
    numeric_cols: list[str] = []
    for c in df_all.columns:
        try:
            col_num = pd.to_numeric(df_all[c], errors="coerce")
        except Exception:
            continue
        if col_num.notna().any():
            numeric_cols.append(c)
    # unique sorted
    return sorted(set(numeric_cols))

def toggle_fixture_watched(fixtures_path: str, fixture_id: str, new_value_yes: bool) -> bool:
    """
    Set Watched = Yes/No for the given Fixture ID and persist to CSV.
    Returns True on success, False on failure.
    """
    try:
        df = read_csv_resilient_fixtures(fixtures_path).copy()
        # normalise headers
        df.columns = [str(c).replace("\ufeff","").strip() for c in df.columns]
        if "Watched" not in df.columns:
            df["Watched"] = "No"
        if "Fixture ID" not in df.columns:
            # if the source never had IDs, rebuild them on the fly using current logic
            # Warning: this may produce different IDs if Title changed, but it's the best fallback
            hdr_map = {c.lower().strip(): c for c in df.columns}
            col_title = hdr_map.get("title", "Title")
            col_start = hdr_map.get("given planned earliest start", "Given planned earliest start")
            homes, aways = [], []
            for t in df[col_title].astype(str).tolist():
                h, a = parse_fixture_title(t); homes.append(h); aways.append(a)
            df["_Home_raw"], df["_Away_raw"] = homes, aways
            ko = df[col_start].map(_parse_ddmmyyyy)
            # temporary syn index
            players = load_db(st.session_state.db_csv)
            syn_index = build_club_syn_index(players)
            home_c = df["_Home_raw"].map(lambda s: canonicalise_club(s, syn_index))
            away_c = df["_Away_raw"].map(lambda s: canonicalise_club(s, syn_index))
            fid = []
            for dt_, h, a in zip(ko, home_c, away_c):
                dt_iso = dt_.strftime("%Y-%m-%d") if isinstance(dt_, date) else ""
                fid.append(fixture_row_id(dt_iso, h, a))
            df["Fixture ID"] = fid

        # write the toggle
        df["Watched"] = df["Watched"].astype(str)
        mask = df["Fixture ID"].astype(str) == str(fixture_id)
        df.loc[mask, "Watched"] = "Yes" if new_value_yes else "No"

        safe_write_csv(fixtures_path, df)
        # clear cache for loader
        st.cache_data.clear()
        return True
    except Exception as e:
        st.warning(f"Could not save fixture status: {e}")
        return False

def _find_metric_col(df: pd.DataFrame, patterns: list[str]) -> str | None:
    cols = list(df.columns)
    for c in cols:
        low = c.lower()
        for pat in patterns:
            if pat in low:
                return c
    return None

def render_u21_tab(st, nation_dirs: list[str], nation_names: list[str]):
    st.subheader("U21 development")

    div_df = _discover_divisions(nation_dirs, nation_names)
    if div_df.empty:
        st.info("No divisions found yet.")
        return

    div_options = div_df["__league_key"].sort_values().unique().tolist()
    sel_divs = st.multiselect(
        "Peer leagues or tiers for U21 pool",
        options=div_options,
        default=[],
        key="u21_divs"
    )

    if not sel_divs:
        st.info("Select at least one division to build the U21 pool.")
        return

    frames: list[pd.DataFrame] = []
    chosen_divs = div_df[div_df["__league_key"].isin(sel_divs)]
    for _, row in chosen_divs.iterrows():
        folder = row["__folder"]
        prefix = row["__prefix"]
        tier = int(row["__tier"] or 0)
        tiers = [tier] if tier else [1, 2, 3]
        frames += _collect_country_frames(folder, prefix, tiers)

    if not frames:
        st.info("No data for the chosen divisions.")
        return

    df = pd.concat(frames, ignore_index=True, sort=False)

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
        st.info("No U21 players with at least 300 minutes in the selected divisions.")
        return

    

    # Filters for Wyscout positions and FCM roles
    col_f1, col_f2, col_f3 = st.columns(3)
    sel_pos = col_f1.multiselect(
        "Wyscout positions",
        options=POS_CHOICES,
        default=[],
        key="u21_positions"
    )
    sel_roles = col_f2.multiselect(
        "FCM roles",
        options=FCM_ROLE_CHOICES,
        default=[],
        key="u21_fcm_roles"
    )
    min_mins = col_f3.slider(
        "Minimum minutes",
        min_value=0,
        max_value=int(df_u21["_mins"].max()),
        value=300,
        step=30,
        key="u21_min_mins"
    )

    mask = df_u21["_mins"] >= min_mins

    if sel_pos and "Position" in df_u21.columns:
        s = df_u21["Position"].astype(str).str.upper()
        pos_mask = pd.Series(False, index=s.index)
        for token in sel_pos:
            pos_mask = pos_mask | s.str.contains(rf"\b{_re.escape(token.upper())}\b", regex=True)
        mask = mask & pos_mask

    if sel_roles and "_fcm_role_guess" in df_u21.columns:
        role_mask = df_u21["_fcm_role_guess"].astype(str).isin(sel_roles)
        mask = mask & role_mask

    df_u21 = df_u21[mask]

    if df_u21.empty:
        st.info("No U21 players match the filters.")
        return

    # --- Normalise minutes using max appearances per league (full df, not only U21) ---
    # Try to detect an appearances column on the full df
    apps_candidates = [
        c for c in df.columns
        if c.lower() in {"appearances", "apps", "matches", "games", "matches played"}
    ]
    if apps_candidates:
        apps_col = apps_candidates[0]

        # numeric appearances for the whole dataset
        df["_apps"] = pd.to_numeric(df[apps_col], errors="coerce")

        # ensure league key exists on full df (df_u21 inherits it)
        if "__league_key" not in df.columns:
            def _mk_league_key(row):
                nation = str(row.get("__nation", "")).strip()
                league = str(
                    row.get("League", "")
                    or row.get("Competition", "")
                    or ""
                ).strip()
                tier = str(row.get("__tier", "")).strip()
                parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
                return " · ".join(parts) if parts else "Unknown"
            df["__league_key"] = df.apply(_mk_league_key, axis=1)

        # per-league max appearances = total games for that league
        df["__max_apps_league"] = df.groupby("__league_key")["_apps"].transform("max")
        df["__max_minutes_league"] = df["__max_apps_league"] * 90.0

        # bring the per-league max minutes into the U21 subset
        df_u21 = df_u21.merge(
            df[["__league_key", "__max_minutes_league"]].drop_duplicates(),
            on="__league_key",
            how="left",
        )

        # final normalised share of minutes
        df_u21["u21_norm_minutes_share"] = (
            df_u21["_mins"] / df_u21["__max_minutes_league"]
        )

    else:
        df_u21["u21_norm_minutes_share"] = pd.NA



    # Find metric columns, robust to slight header changes
    col_g90 = _find_metric_col(df_u21, ["goals per 90", "goals p90", "goals/90", "goals_per_90"])
    col_xg90 = _find_metric_col(df_u21, ["xg per 90", "xg p90", "xg/90", "expected goals per 90"])
    col_sh90 = _find_metric_col(df_u21, ["shots per 90", "shots p90", "shots/90"])
    col_sot_pct = _find_metric_col(df_u21, ["shots on target %", "shots on target, %", "sot %"])

    needed = [col_g90, col_xg90, col_sh90, col_sot_pct]
    if any(c is None for c in needed):
        st.warning(
            "Cannot build the Emergence style index because one of "
            "Goals per 90, xG per 90, Shots per 90 or Shots on target % is missing."
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

    # Emergence style index, age weighted within U21 band
    ages_u21 = pd.to_numeric(df_u21["Age"], errors="coerce")
    # 17 to 23 gets a 1 to 0 weight, clipped at zero
    age_factor = (23 - ages_u21).clip(lower=0) / 6.0
    df_u21["EmergenceIndex"] = _z(df_u21["BPS"]) * age_factor

    # --- NEW: choose minutes metric for visuals ---
    metric_mode = st.radio(
        "Minutes metric",
        ["Normalised share", "Raw minutes"],
        index=0,
        horizontal=True,
        key="u21_minutes_metric",
    )

    if metric_mode == "Raw minutes":
        metric_col = "_mins"
        metric_title = "Minutes played"
    else:
        metric_col = "u21_norm_minutes_share"
        metric_title = "Share of possible league minutes"


    # Ranking and horizontal bar chart
    topN = st.slider(
        "Number of players to show",
        min_value=5,
        max_value=50,
        value=15,
        step=1,
        key="u21_topN"
    )

    COL_PLAYER = next((c for c in df_u21.columns if c.lower() in {"player", "name", "player name"}), "Player")
    COL_TEAM = next((c for c in df_u21.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")

    # Collapse duplicates: one row per player–team–league
    group_cols = [COL_PLAYER, COL_TEAM, "Age", "__league_key"]

    df_rank = (
        df_u21
        .groupby(group_cols, as_index=False)
        .agg({
            "_mins": "sum",                      # total minutes across all rows
            "u21_norm_minutes_share": "max",     # share of minutes in league
            "BPS": "mean",                       # average base performance
            "EmergenceIndex": "mean",            # average emergence score
        })
    )

    # Sort and keep top N
    df_rank = df_rank.sort_values("EmergenceIndex", ascending=False).head(topN)
    df_rank.insert(0, "Rank", range(1, len(df_rank) + 1))


    import altair as alt

    chart_data = df_rank[[COL_PLAYER, COL_TEAM, "Age", "__league_key", "BPS", "EmergenceIndex"]].copy()
    chart_data = chart_data.rename(columns={COL_PLAYER: "Player"})

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
                alt.Tooltip("__league_key:N", title="League"),
            ],
        )
        .properties(height=30 * len(chart_data), width="container")
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### U21 ranking table")
    # add both raw and normalised minutes for inspection
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
    export_buttons(df_rank[display_cols], key_suf="_u21_emergence")



# --- Add more files here ---
FIXTURES_DIR = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Fixtures"
FIXTURES_FILES = {
    "Belgium": os.path.join(FIXTURES_DIR, "Belgium1.csv"),
    "Netherlands": os.path.join(FIXTURES_DIR, "dutch1.csv"),
    "France": os.path.join(FIXTURES_DIR, "ligue1.csv"),
}

# Keep your season window constants
# SEASON_START_2526 = date(2025, 7, 1)
# SEASON_END_2526   = date(2026, 6, 30)

@st.cache_data(show_spinner=False)
def load_fixtures_csv(fixtures_path: str, season_start: date, season_end: date) -> pd.DataFrame:
    """
    Generic loader for any league with columns:
      Title, Given planned earliest start, Given planned earliest end
    Adds: Fixture ID, Watched, Home, Away, KO_date
    Filters to the [season_start, season_end] window.
    """
    if not os.path.exists(fixtures_path):
        return pd.DataFrame(columns=["Title","Given planned earliest start","Given planned earliest end","Watched",
                                     "Home_raw","Away_raw","Home","Away","KO_date","Fixture ID"])

    df = read_csv_resilient_fixtures(fixtures_path).copy()
    df.columns = [str(c).replace("\ufeff","").strip() for c in df.columns]
    # normalise header lookups
    hdr_map = {c.lower().strip(): c for c in df.columns}
    def col_like(name: str) -> str:
        return hdr_map.get(name.lower().strip(), name)

    col_title = col_like("Title")
    col_start = col_like("Given planned earliest start")
    col_end   = col_like("Given planned earliest end")

    for need in [col_title, col_start, col_end]:
        if need not in df.columns:
            df[need] = ""

    # parse home/away
    homes, aways = [], []
    for t in df[col_title].astype(str).tolist():
        h, a = parse_fixture_title(t)
        homes.append(h); aways.append(a)
    df["Home_raw"], df["Away_raw"] = homes, aways

    # parse KO (dd/mm/yyyy)
    df["KO_date"] = df[col_start].map(_parse_ddmmyyyy)

    # season filter
    df = df[(df["KO_date"].notna()) &
            (df["KO_date"] >= season_start) &
            (df["KO_date"] <= season_end)].copy()

    # Watched
    if "Watched" not in df.columns:
        df["Watched"] = "No"
    df["Watched"] = df["Watched"].replace({"yes":"Yes","no":"No"}, regex=True)

    # canonicalise clubs from player DB
    players = load_db(st.session_state.db_csv).copy()
    syn_index = build_club_syn_index(players)
    df["Home"] = df["Home_raw"].map(lambda s: canonicalise_club(s, syn_index))
    df["Away"] = df["Away_raw"].map(lambda s: canonicalise_club(s, syn_index))

    # fixture IDs
    fids = []
    for dt_, h, a in zip(df["KO_date"], df["Home"], df["Away"]):
        dt_iso = dt_.strftime("%Y-%m-%d") if isinstance(dt_, date) else ""
        fids.append(fixture_row_id(dt_iso, h, a))
    if "Fixture ID" not in df.columns:
        df["Fixture ID"] = fids
    else:
        df["Fixture ID"] = df["Fixture ID"].where(df["Fixture ID"].astype(str).str.strip() != "", fids)

    return df.sort_values(["KO_date","Home","Away"]).reset_index(drop=True)


# =========================
# Fixtures: player match helper (nation-aware)
# =========================
def _players_for_team(df_players: pd.DataFrame, canon_team: str, playing_nation: Optional[str] = None) -> list[pd.Series]:
    """
    Return players whose visible current club equals the canon_team using loan logic:
    - If On loan == Yes and Loan Club matches, include
    - Else if Player Current Team matches, include
    If playing_nation is provided, pre-filter by 'Playing Nation' to that nation.
    """
    key_target = team_key(canon_team)
    pool = df_players.copy()

    if playing_nation and "Playing Nation" in pool.columns:
        pool = pool[pool["Playing Nation"].astype(str).str.lower() == playing_nation.lower()]

    out = []
    for _, r in pool.iterrows():
        on_loan  = str(r.get("On loan","")).strip().lower() in {"yes","true","1"}
        loan_club = str(r.get("Loan Club","")).strip()
        current   = str(r.get("Player Current Team","")).strip()

        if on_loan and loan_club and team_key(loan_club) == key_target:
            out.append(r); continue
        if current and team_key(current) == key_target:
            out.append(r)
    return out


def _primary_role_short(row: pd.Series) -> str:
    pos = str(row.get("Position",""))
    parts = [p.strip() for p in pos.split(",") if p.strip()]
    return parts[0] if parts else ""

def _player_chip(row: pd.Series) -> str:
    name = row.get("Name","")
    role = _primary_role_short(row)
    cr = str(row.get("Current Rating (1-4)","")).strip()
    pr = str(row.get("Potential Rating (1-4)","")).strip()
    meta = f"{role}" if role else ""
    if cr or pr:
        meta = f"{meta} • {cr}/{pr}" if meta else f"{cr}/{pr}"
    return f"<span class='chip' title='{meta}'>{name if name else 'Unnamed'}{(' — ' + meta) if meta else ''}</span>"

def _render_fixture_cards(df_view: pd.DataFrame, fixtures_path: str):
    """
    Render fixture cards with watched checkbox and 'players who could play' chips.
    Expects df_view to have: Fixture ID, KO_date, Home, Away, Watched, Title
    """
    players = load_db(st.session_state.db_csv).copy()

    for _, row in df_view.iterrows():
        fid   = str(row.get("Fixture ID","")).strip()
        title = str(row.get("Title","")).strip()
        ko    = row.get("KO_date")
        home  = str(row.get("Home","")).strip()
        away  = str(row.get("Away","")).strip()
        watched = str(row.get("Watched","No")).strip().lower() == "yes"

        # Header line e.g. "Sat 12 Oct 15:00"
        dt_txt = ""
        try:
            if isinstance(ko, date):
                dt_txt = ko.strftime("%a %d %b")
        except Exception:
            pass

        with st.container(border=True):
            top = st.columns([5,1])
            with top[0]:
                st.markdown(f"**{home} vs {away}**")
                st.caption(f"{dt_txt} • {title}")
            with top[1]:
                new_state = st.checkbox("Watched", value=watched, key=f"fx_w_{fid}")
                if new_state != watched:
                    ok = toggle_fixture_watched(fixtures_path, fid, new_state)
                    if ok:
                        st.success("Saved")
                    else:
                        # revert UI if failed
                        st.session_state[f"fx_w_{fid}"] = watched

            # Players who could play
            st.markdown("Players to scout")
            h_players = _players_for_team(players, home)
            a_players = _players_for_team(players, away)

            cols = st.columns(2)
            with cols[0]:
                st.caption(home)
                if h_players:
                    chips = " ".join([_player_chip(r) for r in h_players[:20]])
                    st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                else:
                    st.write("—")

            with cols[1]:
                st.caption(away)
                if a_players:
                    chips = " ".join([_player_chip(r) for r in a_players[:20]])
                    st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                else:
                    st.write("—")

def _render_fixture_cards_multination(df_view: pd.DataFrame, fixtures_path: str, nation: str, key_prefix: str):
    """
    Same as _render_fixture_cards, but passes the nation to player matching
    so you only see players from that country's leagues.
    """
    players = load_db(st.session_state.db_csv).copy()

    for _, row in df_view.iterrows():
        fid   = str(row.get("Fixture ID","")).strip()
        title = str(row.get("Title","")).strip()
        ko    = row.get("KO_date")
        home  = str(row.get("Home","")).strip()
        away  = str(row.get("Away","")).strip()
        watched = str(row.get("Watched","No")).strip().lower() == "yes"

        dt_txt = ""
        try:
            if isinstance(ko, date):
                dt_txt = ko.strftime("%a %d %b")
        except Exception:
            pass

        with st.container(border=True):
            top = st.columns([5,1])
            with top[0]:
                st.markdown(f"**{home} vs {away}**")
                st.caption(f"{dt_txt} • {title}")
            with top[1]:
                new_state = st.checkbox("Watched", value=watched, key=f"fx_w_{key_prefix}_{nation}_{fid}")
                if new_state != watched:
                    ok = toggle_fixture_watched(fixtures_path, fid, new_state)
                    if ok:
                        st.success("Saved")
                    else:
                        st.session_state[f"fx_w_{nation}_{fid}"] = watched

            st.markdown("Players to scout")
            h_players = _players_for_team(players, home, playing_nation=nation)
            a_players = _players_for_team(players, away, playing_nation=nation)

            cols = st.columns(2)
            with cols[0]:
                st.caption(home)
                if h_players:
                    chips = " ".join([_player_chip(r) for r in h_players[:20]])
                    st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                else:
                    st.write("—")
            with cols[1]:
                st.caption(away)
                if a_players:
                    chips = " ".join([_player_chip(r) for r in a_players[:20]])
                    st.markdown(f"<div class='chips'>{chips}</div>", unsafe_allow_html=True)
                else:
                    st.write("—")

# =========================
# Fixtures: combined loader, calendar utils
# =========================

# Where to store imported match details
MATCHES_DB_CSV = os.path.join(FIXTURES_DIR, "Matches_DB.csv")

def ensure_matches_db(path: str = MATCHES_DB_CSV) -> pd.DataFrame:
    cols = [
        "Event ID","Source","Competition","Season","Round","Date","Kickoff (local)",
        "Home","Away","Home score","Away score","Status",
        "Venue","Referee",
        "Home lineup","Away lineup","Home bench","Away bench",
        "Events JSON","Stats JSON","Raw JSON","Imported at"
    ]
    if not os.path.exists(path):
        df = pd.DataFrame(columns=cols)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return df
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in cols:
        if c not in df.columns: df[c] = ""
    return df[[*df.columns]]

def write_matches_db(df: pd.DataFrame, path: str = MATCHES_DB_CSV):
    tmp = f"{path}.tmp"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)

def _local_date_from_date(d: date) -> str:
    try: return d.strftime("%Y-%m-%d")
    except: return ""

def load_all_selected_fixtures(season_start: date, season_end: date) -> list[tuple[str, str, pd.DataFrame]]:
    """
    Return list of (nation_label, path, dataframe) for every file in FIXTURES_FILES that exists.
    Each dataframe is already season-filtered and normalised via load_fixtures_csv.
    """
    out = []
    for nation, path in FIXTURES_FILES.items():
        if path and os.path.exists(path):
            try:
                df = load_fixtures_csv(path, season_start, season_end).copy()
                out.append((nation, path, df))
            except Exception as e:
                st.warning(f"Failed to load fixtures for {nation}: {e}")
    return out

def _players_for_fixture(players_df: pd.DataFrame, home: str, away: str, nation: str) -> tuple[list[pd.Series], list[pd.Series]]:
    return (
        _players_for_team(players_df, home, playing_nation=nation),
        _players_for_team(players_df, away, playing_nation=nation)
    )

def interest_score(players_home: list[pd.Series], players_away: list[pd.Series]) -> int:
    """
    Simple heuristic: count players involved + bonus for higher potentials.
    """
    score = 0
    for r in players_home + players_away:
        score += 1
        try:
            pr = float(str(r.get("Potential Rating (1-4)","0")).strip() or 0)
            score += int(pr >= 3.0)  # small bonus for PR 3.0+
        except: ...
    return score

# ---------- Calendar utilities ----------
def week_bounds(anchor: date) -> tuple[date, date]:
    # Monday start week
    start = anchor - dt.timedelta(days=(anchor.weekday()))
    end = start + dt.timedelta(days=6)
    return start, end

def group_fixtures_by_day(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    buckets: dict[date, pd.DataFrame] = {}
    for d, sub in df.groupby("KO_date"):
        if isinstance(d, date):
            buckets[d] = sub.sort_values(["KO_date","Home","Away"])
    return buckets


# =========================
# Transfermarkt league fixtures scraper
# =========================
def _tm_clean(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").strip())

def scrape_transfermarkt_league_fixtures(url: str) -> list[dict]:
    """
    Scrape a Transfermarkt *league season schedule* page (e.g. Ligue 1 25/26).
    Returns a list of dicts with: Title, Given planned earliest start, Given planned earliest end (same day).
    We parse matchday tables: date, time, home, away. If time missing we still record the date.
    """
    if not (requests and BeautifulSoup):
        raise RuntimeError("Install 'requests' and 'beautifulsoup4' to use the TM scraper.")
    ua = UserAgent().random if UserAgent else "Mozilla/5.0"
    r = requests.get(url, headers={"User-Agent": ua}, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")

    out = []
    # Transfermarkt renders matchday sections; rows often under 'tm-table' or 'fixtures' tables
    # We look for rows that contain a home/away split with team links.
    tables = soup.select("table")  # broad, handle different skins
    for tbl in tables:
        rows = tbl.select("tbody tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            # Try common layout: [Date], [Time], [Home], [: / result], [Away], ...
            # Identify home and away cells by having a link to team page or a 'vereinprofil_tooltip' class
            homes = tr.select("td a.vereinprofil_tooltip") or tr.select("td a[href*='/verein/']")
            # Sometimes both teams are in same query; ensure we find two.
            team_links = [a.get_text(strip=True) for a in homes]
            if len(team_links) < 2:
                # Alternative layout: home in 3rd td, away in 5th or last td
                home_txt = _tm_clean(tds[2].get_text(" ", strip=True)) if len(tds) >= 3 else ""
                away_txt = _tm_clean(tds[4].get_text(" ", strip=True)) if len(tds) >= 5 else ""
                if not home_txt or not away_txt:
                    continue
                home, away = home_txt, away_txt
            else:
                # Usually first two distinct links are the teams
                # Sometimes a crest <img> is also a link – filter out empty texts
                teams = [t for t in team_links if t]
                if len(teams) < 2:
                    continue
                home, away = teams[0], teams[1]

            # Date + time
            date_txt = ""
            time_txt = ""
            # Commonly date in first td, time in second td
            if tds:
                date_txt = _tm_clean(tds[0].get_text(" ", strip=True))
                if len(tds) > 1:
                    time_txt = _tm_clean(tds[1].get_text(" ", strip=True))
            # Fallback: sometimes date is repeated as 'Fri 03/10/25'
            date_txt = re.sub(r"^[A-Za-z]{2,3}\s+", "", date_txt)  # drop weekday names
            # Normalise Transfermarkt formats to dd/mm/yyyy
            # Accept 'dd/mm/yy' or 'dd/mm/yyyy'
            m = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", date_txt)
            if not m:
                continue
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y = 2000 + y
            date_norm = f"{d:02d}/{mth:02d}/{y:04d}"

            title = f"{home} vs {away}"
            # We save earliest start as date; you can later add time handling if needed
            out.append({
                "Title": title,
                "Given planned earliest start": date_norm,
                "Given planned earliest end": date_norm,
            })
    # Deduplicate, keeping first occurrence
    seen = set()
    clean_out = []
    for row in out:
        key = (row["Title"], row["Given planned earliest start"])
        if key in seen:
            continue
        seen.add(key)
        clean_out.append(row)
    return clean_out

def merge_tm_fixtures_into_csv(tm_rows: list[dict], csv_path: str, season_start: date, season_end: date):
    """
    Merge scraped TM fixtures into your league CSV:
      - Ensures required columns
      - Recomputes Fixture ID for every row (based on KO_date + canonical clubs)
      - Keeps any existing 'Watched' values
    """
    # Load existing (resilient)
    df_exist = read_csv_resilient_fixtures(csv_path) if os.path.exists(csv_path) else pd.DataFrame(columns=[
        "Title","Given planned earliest start","Given planned earliest end","Watched"
    ])
    df_exist.columns = [str(c).replace("\ufeff","").strip() for c in df_exist.columns]
    for need in ["Title","Given planned earliest start","Given planned earliest end","Watched"]:
        if need not in df_exist.columns:
            df_exist[need] = ""
    if "Watched" not in df_exist.columns:
        df_exist["Watched"] = "No"

    # Append scraped rows
    df_new = pd.DataFrame(tm_rows)
    for need in ["Title","Given planned earliest start","Given planned earliest end"]:
        if need not in df_new.columns:
            df_new[need] = ""

    # Combine and dedupe on Title + Start
    combo = pd.concat([df_exist, df_new], ignore_index=True)
    combo = combo.drop_duplicates(subset=["Title","Given planned earliest start"], keep="first").copy()

    # Normalise through our pipeline to generate KO_date, Home/Away, Fixture ID
    combo.columns = [str(c).replace("\ufeff","").strip() for c in combo.columns]
    hdr_map = {c.lower().strip(): c for c in combo.columns}
    col_title = hdr_map.get("title", "Title")
    col_start = hdr_map.get("given planned earliest start", "Given planned earliest start")
    # Parse Home/Away from Title
    homes, aways, ko_dates = [], [], []
    for t, ds in zip(combo[col_title].astype(str).tolist(), combo[col_start].astype(str).tolist()):
        h, a = parse_fixture_title(t); homes.append(h); aways.append(a)
        ko_dates.append(_parse_ddmmyyyy(ds))
    combo["Home_raw"], combo["Away_raw"], combo["KO_date"] = homes, aways, ko_dates

    # Season filter then rebuild canon + fixture id
    combo = combo[(combo["KO_date"].notna()) & (combo["KO_date"] >= season_start) & (combo["KO_date"] <= season_end)].copy()
    players = load_db(st.session_state.db_csv).copy()
    syn_index = build_club_syn_index(players)
    combo["Home"] = combo["Home_raw"].map(lambda s: canonicalise_club(s, syn_index))
    combo["Away"] = combo["Away_raw"].map(lambda s: canonicalise_club(s, syn_index))

    fids = []
    for dt_, h, a in zip(combo["KO_date"], combo["Home"], combo["Away"]):
        dt_iso = dt_.strftime("%Y-%m-%d") if isinstance(dt_, date) else ""
        fids.append(fixture_row_id(dt_iso, h, a))
    combo["Fixture ID"] = fids

    # Preserve existing Watched values where the same Title+Start existed
    if "Watched" in df_exist.columns:
        watched_map = {(r["Title"], r["Given planned earliest start"]): r.get("Watched","No") for _, r in df_exist.iterrows()}
        combo["Watched"] = [
            watched_map.get((t, s), "No")
            for t, s in zip(combo["Title"].astype(str), combo["Given planned earliest start"].astype(str))
        ]
        combo["Watched"] = combo["Watched"].replace({"yes":"Yes","no":"No"}, regex=True)

    # Save
    safe_write_csv(csv_path, combo[[
        "Title","Given planned earliest start","Given planned earliest end",
        "Home_raw","Away_raw","Home","Away","KO_date","Fixture ID","Watched"
    ]])
    st.cache_data.clear()

# --- fixtures file discovery per nation ---
def nation_dir(nation: str) -> str:
    path = os.path.join(FIXTURES_DIR, nation)
    os.makedirs(path, exist_ok=True)
    return path

def list_fixtures_for_nation(nation: str) -> list[str]:
    """Return absolute CSV paths inside FIXTURES_DIR/<nation> (sorted)."""
    folder = nation_dir(nation)
    csvs = []
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(".csv"):
                csvs.append(os.path.join(folder, name))
    except Exception:
        pass
    return sorted(csvs, key=lambda p: os.path.basename(p).lower())

def scrape_transfermarkt_single_match(url: str) -> dict:
    """
    Parse a Transfermarkt *single match report* page into our 3 core columns.
    Works with multiple layouts (match reports, live pages, archived pages).
    Returns Title (Home vs Away) and dd/mm/yyyy date.
    """
    if not (requests and BeautifulSoup):
        raise RuntimeError("Install 'requests' and 'beautifulsoup4' to use the TM scraper.")
    ua = UserAgent().random if UserAgent else "Mozilla/5.0"
    r = requests.get(url, headers={"User-Agent": ua}, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "html.parser")

    # --- TEAM NAMES ---
    home, away = "", ""

    # 1) Header H1 like "Paris FC - FC Lorient" or "Paris FC vs FC Lorient"
    h1 = soup.find("h1")
    if h1:
        txt = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
        h, a = parse_fixture_title(txt)
        home, away = h or home, a or away

    # 2) Common: two 'vereinprofil_tooltip' links
    if not (home and away):
        teams = [a.get_text(strip=True) for a in soup.select("a.vereinprofil_tooltip") if a.get_text(strip=True)]
        if len(teams) >= 2:
            home, away = teams[0], teams[1]

    # 3) Meta og:title sometimes has "Home - Away - Match report"
    if not (home and away):
        ogt = soup.find("meta", attrs={"property": "og:title"})
        if ogt and ogt.get("content"):
            h, a = parse_fixture_title(ogt["content"])
            home, away = h or home, a or away

    # 4) Table context: try find two adjacent team cells around "Result"
    if not (home and away):
        row = soup.find("table")
        if row:
            t = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
            m = re.search(r"([A-Z][\w .'-]+)\s+[-:]\s+([A-Z][\w .'-]+)", t, flags=re.I)
            if m:
                home, away = m.group(1).strip(), m.group(2).strip()

    # --- DATE ---
    raw_date = ""
    # A) “Date” label in info tables
    cell = soup.find(string=re.compile(r"Date", re.I))
    if cell and cell.parent:
        nxt = cell.parent.find_next("td")
        if nxt:
            raw_date = nxt.get_text(" ", strip=True)

    # B) As text anywhere (dd.mm.yy, dd/mm/yy, dd-mm-yyyy, “03/10/2025”)
    if not raw_date:
        m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", soup.get_text(" ", strip=True))
        if m:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = 2000 + y if y < 100 else y
            raw_date = f"{d:02d}/{mth:02d}/{y:04d}"

    # C) Month-name formats (e.g., “Oct 03, 2025”)
    if raw_date and not re.match(r"\d{2}/\d{2}/\d{4}", raw_date):
        # normalise any “03.10.25” or “03-10-2025”
        m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", raw_date)
        if m:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = 2000 + y if y < 100 else y
            raw_date = f"{d:02d}/{mth:02d}/{y:04d}"
        else:
            # try english month names
            m2 = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(\d{4})", raw_date)
            if m2:
                mon = MONTHS.get(m2.group(1).lower(), 0)
                if mon:
                    raw_date = f"{int(m2.group(2)):02d}/{mon:02d}/{int(m2.group(3)):04d}"

    if not (home and away and raw_date and re.match(r"\d{2}/\d{2}/\d{4}", raw_date)):
        raise RuntimeError("Could not parse teams/date from this page.")

    return {
        "Title": f"{home} vs {away}",
        "Given planned earliest start": raw_date,
        "Given planned earliest end": raw_date,
    }


def append_single_fixture(row: dict, csv_path: str):
    """Create/append a single fixture into a catch-all CSV, keeping Watched & IDs coherent."""
    exists = os.path.exists(csv_path)
    if exists:
        df = read_csv_resilient_fixtures(csv_path)
    else:
        df = pd.DataFrame(columns=["Title","Given planned earliest start","Given planned earliest end","Watched"])
    for need in ["Title","Given planned earliest start","Given planned earliest end","Watched"]:
        if need not in df.columns: df[need] = ""
    row.setdefault("Watched","No")
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    # normalize through our pipeline to build IDs/Home/Away/KO_date
    tmp = os.path.join(os.path.dirname(csv_path), "__tmp_single.csv")
    safe_write_csv(tmp, df)
    merged = load_fixtures_csv(tmp, SEASON_START_2526, SEASON_END_2526)
    safe_write_csv(csv_path, merged[[
        "Title","Given planned earliest start","Given planned earliest end",
        "Home_raw","Away_raw","Home","Away","KO_date","Fixture ID","Watched"
    ]])
    _safe_unlink(tmp)
    st.cache_data.clear()

# =========================
# A) Wyscout linkage + metrics engine (helpers only)
# =========================

# 1) Ensure Players DB has the new ID column
if "Wyscout Player ID" not in REQUIRED_COLUMNS:
    REQUIRED_COLUMNS.append("Wyscout Player ID")

# 2) Robust CSV reader (handles weird encodings and delimiters)
def read_csv_flexible(path: str) -> pd.DataFrame:
    """
    Robust reader that prefers strings (dtype=str) and sniffs the delimiter.
    Tries multiple encodings to avoid the 'utf-8' codec and quote errors you saw.
    """
    attempts = [
        dict(encoding="utf-8-sig", sep=None, engine="python", dtype=str, keep_default_na=True),
        dict(encoding="cp1252",    sep=None, engine="python", dtype=str, keep_default_na=True),
        dict(encoding="latin1",    sep=None, engine="python", dtype=str, keep_default_na=True),
    ]
    for kw in attempts:
        try:
            return pd.read_csv(path, **kw)
        except Exception:
            continue
    # last resort: read with replacement for any odd bytes
    return pd.read_csv(path, sep=None, engine="python", dtype=str, keep_default_na=True, encoding_errors="replace")


# 3) Wyscout root and auto-discovery of nation folders

# Set this once to the parent folder that contains all nation subfolders
# Example structure:
#   <WYS_ROOT_DIR>/
#     Belgium/
#       Belgium1.csv, Belgium2.xlsx, ...
#     Netherlands/
#       Dutch1.csv, Netherlands2.csv, ...
#     France/
#       France1.xlsx, ...
#     Portugal/
#       Portugal1.csv, Portugal2.csv
WYS_ROOT_DIR = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26"

def wyscout_folders() -> list[str]:
    """
    Return all nation folders under WYS_ROOT_DIR that contain at least one CSV or XLSX.
    """
    import os
    candidates: list[str] = []
    if isinstance(WYS_ROOT_DIR, str) and os.path.isdir(WYS_ROOT_DIR):
        try:
            for name in os.listdir(WYS_ROOT_DIR):
                sub = os.path.join(WYS_ROOT_DIR, name)
                if not os.path.isdir(sub):
                    continue
                # must contain at least one per-league file
                has_files = any(
                    fn.lower().endswith((".csv", ".xlsx"))
                    for fn in os.listdir(sub)
                )
                if has_files:
                    candidates.append(sub)
        except Exception:
            pass
    return sorted(candidates, key=lambda p: os.path.basename(p).lower())


@st.cache_data(show_spinner=False)
def load_wyscout_master() -> pd.DataFrame:
    """
    Load every CSV/XLSX in each discovered nation folder, stamp:
      __nation = folder basename
      __source_file = file name
      __tier = int inferred from filename digits (e.g. 'Portugal2.csv' -> 2, else 0)
    """
    import os, re
    frames = []

    for folder in wyscout_folders():
        nation = os.path.basename(folder).strip()
        for fn in os.listdir(folder):
            if not fn.lower().endswith((".csv", ".xlsx")):
                continue
            path = os.path.join(folder, fn)
            try:
                if fn.lower().endswith(".csv"):
                    df_ = read_csv_flexible(path)  # your existing robust reader
                else:
                    # you already have resilient xlsx helpers in the analysis code
                    # fall back to pandas if not present
                    try:
                        dfs = read_xlsx_resilient(path)  # if you have it
                        if not dfs: 
                            continue
                        df_ = pd.concat(dfs, ignore_index=True, sort=False)
                    except Exception:
                        df_ = pd.read_excel(path, dtype=str).fillna("")

                df_.columns = [str(c).strip().replace("\ufeff", "") for c in df_.columns]
                df_["__source_file"] = fn
                df_["__nation"] = nation

                m = re.search(r"(\d+)", os.path.splitext(fn)[0])
                df_["__tier"] = int(m.group(1)) if m else 0

                frames.append(df_)
            except Exception as e:
                st.warning(f"Failed to read {path}: {e}")

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)
    df = ensure_wyscout_id_column(df)  # keep your existing helper
    return df



# 5) Position synonym maps

# Wyscout raw → General group
WS_POS_TO_GROUP = {
    # GK
    "GK":"GK",
    # Full-backs & wing-backs
    "RB":"FB","RWB":"FB","LB":"FB","LWB":"FB",
    # Centre-backs
    "CB":"CB","RCB":"CB","LCB":"CB",
    # DM / CM / AM
    "DMF":"DM","RDMF":"DM","LDMF":"DM",
    "CMF":"CM","RCMF":"CM","LCMF":"CM",
    "AMF":"AM","RAMF":"AM","LAMF":"AM",
    # Wingers / wide
    "RW":"W","RWF":"W","RM":"W","LW":"W","LWF":"W","LM":"W",
    # Forwards
    "CF":"CF","ST":"CF","SS":"CF",
}

# Wyscout raw → FCM role label (primary best-effort)
# Tune these as you like; many-to-one mapping is fine for cohorting
WS_POS_TO_FCM = {
    "GK":"GK",
    "RB":"2 - RB/RWB","RWB":"2 - RB/RWB",
    "LB":"3 - LB/LWB","LWB":"3 - LB/LWB",
    "CB":"4 - CCB","RCB":"5R","LCB":"5L",
    "DMF":"6","RDMF":"6","LDMF":"6",
    "CMF":"8","RCMF":"8","LCMF":"8",
    "AMF":"10 - CAM","RAMF":"7 - RM","LAMF":"11 - LM",
    "RW":"7a - RWF","RWF":"7a - RWF","RM":"7 - RM",
    "LW":"11a - LWF","LWF":"11a - LWF","LM":"11 - LM",
    "CF":"9 - AF","CF":"9 - TM","SS":"10a",
}

def map_ws_position_to_group(pos_text: str) -> str:
    p = str(pos_text or "").upper().strip()
    return WS_POS_TO_GROUP.get(p, "")

def map_ws_position_to_fcm(pos_text: str) -> str:
    p = str(pos_text or "").upper().strip()
    return WS_POS_TO_FCM.get(p, "")

# 6) Metric registry (clusters) — edit/expand anytime

# Columns considered "bio" or admin → ignore for z-scores
WS_IGNORE_COLS = {
    "Player","Team","Team within selected timeframe","Position","Age","Market value","Contract expires",
    "Birth country","Passport country","Foot","Height","Weight","On loan",
    "__source_file","__nation"
}

# GK-only metrics
GK_METRICS = [
    "Conceded goals per 90","Shots against per 90","Clean sheets","Save rate, %",
    "xG against per 90","Prevented goals per 90",
    "Back passes received as GK per 90","Exits per 90","Aerial duels per 90"
]

# Outfielder packs broken into clusters
PACKS = {
    "W": {  # Wingers
        "Dribbling": ["Dribbles per 90","Successful dribbles, %","Offensive duels per 90","Offensive duels won, %","Accelerations per 90","Progressive runs per 90"],
        "Crossing": ["Crosses per 90","Accurate crosses, %","Crosses to goalie box per 90"],
        "Chance creation": ["xA per 90","Shot assists per 90","Smart passes per 90","Accurate smart passes, %","Key passes per 90","Passes to penalty area per 90","Accurate passes to penalty area, %"],
        "End product": ["xG per 90","Goals per 90","Goal conversion, %","Shots per 90","Shots on target, %","Touches in box per 90"],
        "Progression": ["Progressive passes per 90","Passes to final third per 90","Accurate passes to final third, %"]
    },
    "FB": {  # Full-backs
        "Defending": ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","Aerial duels per 90","Aerial duels won, %","Sliding tackles per 90","PAdj Interceptions","Fouls per 90"],
        "Crossing": ["Crosses per 90","Accurate crosses, %","Crosses to goalie box per 90"],
        "Progression": ["Progressive runs per 90","Progressive passes per 90","Forward passes per 90","Accurate forward passes, %"],
        "Build-up": ["Passes per 90","Accurate passes, %","Short / medium passes per 90","Accurate short / medium passes, %","Long passes per 90","Accurate long passes, %"]
    },
    "CF": {  # Centre forwards
        "Box presence": ["Touches in box per 90","Shots per 90","xG per 90","Non-penalty goals per 90"],
        "Finishing": ["Goal conversion, %","Shots on target, %"],
        "Link & creation": ["xA per 90","Shot assists per 90","Smart passes per 90","Accurate smart passes, %"]
    },
    "CM": {  # Central mids
        "Build-up": ["Passes per 90","Accurate passes, %","Short / medium passes per 90","Accurate short / medium passes, %","Long passes per 90","Accurate long passes, %"],
        "Progression": ["Progressive passes per 90","Passes to final third per 90","Accurate passes to final third, %","Smart passes per 90","Accurate smart passes, %"],
        "Defending": ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","PAdj Interceptions","Fouls per 90"],
        "Creation": ["xA per 90","Shot assists per 90","Key passes per 90"]
    },
     "AM": {  # Attacking mids
        "Chance creation": ["xA per 90","Shot assists per 90","Key passes per 90","Smart passes per 90","Accurate smart passes, %","Passes to penalty area per 90","Accurate passes to penalty area, %"],
        "End product": ["xG per 90","Goals per 90","Goal conversion, %","Shots per 90","Shots on target, %","Touches in box per 90"],
        "Dribbling": ["Dribbles per 90","Successful dribbles, %","Offensive duels per 90","Offensive duels won, %"],
        "Progression": ["Progressive runs per 90","Progressive passes per 90","Passes to final third per 90"]
    },
    "DM": {  # Defensive mids
        "Defending": ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","Interceptions per 90","PAdj Interceptions","Fouls per 90"],
        "Progression": ["Progressive passes per 90","Forward passes per 90","Accurate forward passes, %","Passes per 90","Accurate passes, %"]
    },
    "CB": {  # Centre-backs
        "Defending": ["Successful defensive actions per 90","Defensive duels per 90","Defensive duels won, %","Aerial duels per 90","Aerial duels won, %","Shots blocked per 90","Fouls per 90"],
        "Progression": ["Forward passes per 90","Accurate forward passes, %","Progressive passes per 90","Passes per 90","Accurate passes, %","Long passes per 90","Accurate long passes, %"]
    },
}

# Metrics where LOWER is better (everything else is higher-better)
LOWER_IS_BETTER = {
    # possession loss / discipline
    "Turnovers per 90", "Miscontrols per 90", "Dispossessed per 90",
    "Fouls committed per 90", "Yellow cards per 90", "Red cards per 90",
    # GK against / concessions
    "Goals conceded per 90", "xGA per 90", "PSxG per 90",
    # errors
    "Errors leading to shot", "Errors leading to goal",
    # defensive *won %* is higher better, so do NOT add “…won %” here
}


# Default cluster weights per group (sum to ~1.0; adjust later as you like)
DEFAULT_WEIGHTS = {
    "W":    {"Dribbling":0.25,"Crossing":0.20,"Chance creation":0.25,"End product":0.20,"Progression":0.10},
    "FB":   {"Defending":0.35,"Crossing":0.20,"Progression":0.25,"Build-up":0.20},
    "CF":   {"Box presence":0.40,"Finishing":0.35,"Link & creation":0.25},
    "CM":   {"Build-up":0.35,"Progression":0.30,"Defending":0.20,"Creation":0.15},
    "AM":   {"Chance creation":0.35,"End product":0.30,"Dribbling":0.20,"Progression":0.15},
    "DM":   {"Defending":0.55,"Progression":0.45},
    "CB":   {"Defending":0.60,"Progression":0.40},
    "GK":   {"Shot-stopping":0.55,"Box & aerial":0.25,"Sweeping/Distribution":0.20},  # we’ll map GK metrics into these buckets below
}

# GK clusters mapping (uses GK_METRICS list)
GK_PACK = {
    "Shot-stopping": ["Conceded goals per 90","Shots against per 90","Save rate, %","xG against per 90","Prevented goals per 90"],
    "Box & aerial":  ["Exits per 90","Aerial duels per 90","Back passes received as GK per 90"],
    "Sweeping/Distribution": []  # placeholder if you later add distribution metrics for GKs
}

# 7) Utility: winsorise → z-score → rank/percentile

import numpy as np

def _winsorise(series: pd.Series, lower=0.01, upper=0.99) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    ql, qu = s.quantile(lower), s.quantile(upper)
    return s.clip(lower=ql, upper=qu)

def _zscore(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True, ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series([np.nan]*len(s), index=s.index)
    return (s - mu) / sd

# ---------- General-analysis helpers ----------

def prepare_numeric_matrix(df: pd.DataFrame, kpis: list[str]) -> pd.DataFrame:
    mat = df[[c for c in kpis if c in df.columns]].apply(pd.to_numeric, errors="coerce")
    # drop rows with all-NaN in selected KPIs
    mat = mat.dropna(how="all")
    return mat

def zscore_block(df: pd.DataFrame, kpis: list[str]) -> pd.DataFrame:
    mat = prepare_numeric_matrix(df, kpis)
    out = df.loc[mat.index, ["Player","Team","Position"]].copy() if "Player" in df.columns else df.loc[mat.index].copy()
    for c in mat.columns:
        out[f"{c}__z"] = _zscore(_winsorise(mat[c]))
        _, pct = _rank_and_percentile(mat[c], higher_is_better=metric_direction(c))
        out[f"{c}__pct"] = pct
    return out

def pca_block(df: pd.DataFrame, kpis: list[str], n_components: int = 2) -> pd.DataFrame:
    try:
        from sklearn.preprocessing import StandardScaler
        from sklearn.decomposition import PCA
    except Exception:
        st.warning("Install scikit-learn to use PCA:  pip install scikit-learn")
        return pd.DataFrame()
    mat = prepare_numeric_matrix(df, kpis)
    idx = mat.index
    X = mat.fillna(mat.mean(numeric_only=True))
    Xs = StandardScaler(with_mean=True, with_std=True).fit_transform(X.values)
    pca = PCA(n_components=min(n_components, X.shape[1]))
    pcs = pca.fit_transform(Xs)
    out = df.loc[idx, ["Player","Team","Position"]].copy() if "Player" in df.columns else df.loc[idx].copy()
    for i in range(pcs.shape[1]):
        out[f"PC{i+1}"] = pcs[:, i]
    out["PCA_variance_explained"] = pca.explained_variance_ratio_.sum()
    return out

def dea_block(df: pd.DataFrame, outputs: list[str], inputs: list[str] | None = None) -> pd.DataFrame:
    """
    Output-oriented CCR DEA.
    If no inputs provided, uses a single dummy input (=1) so we measure pure 'output efficiency'.
    """
    try:
        import pulp
    except Exception:
        st.warning("Install PuLP to use DEA:  pip install pulp")
        return pd.DataFrame()

    outs = df[[c for c in outputs if c in df.columns]].apply(pd.to_numeric, errors="coerce")
    if inputs:
        ins = df[[c for c in inputs if c in df.columns]].apply(pd.to_numeric, errors="coerce")
    else:
        ins = pd.DataFrame({"__one__": 1.0}, index=df.index)

    # drop rows with NaNs in any chosen columns
    keep = outs.dropna().index.intersection(ins.dropna().index)
    outs, ins = outs.loc[keep], ins.loc[keep]

    scores = []
    for j in keep:
        # Maximise theta s.t. for all i: sum_k lambda_k * y_ik >= theta * y_ij, and sum_k lambda_k * x_ik <= x_ij
        prob = pulp.LpProblem("DEA", pulp.LpMaximize)
        lambdas = {k: pulp.LpVariable(f"lam_{k}", lowBound=0) for k in keep}
        theta = pulp.LpVariable("theta", lowBound=0)

        # objective
        prob += theta

        # output constraints
        for col in outs.columns:
            prob += pulp.lpSum(lambdas[k] * outs.loc[k, col] for k in keep) >= theta * outs.loc[j, col]

        # input constraints
        for col in ins.columns:
            prob += pulp.lpSum(lambdas[k] * ins.loc[k, col] for k in keep) <= ins.loc[j, col]

        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        val = theta.value() if theta.value() is not None else float("nan")
        scores.append((j, float(val)))

    out = df.loc[keep, ["Player","Team","Position"]].copy() if "Player" in df.columns else df.loc[keep].copy()
    out["DEA_efficiency"] = [v for _, v in scores]
    # clamp to 0..∞; typical CCR scores ≥ 1 for output orientation (≥1 means relatively efficient)
    return out


def _rank_and_percentile(series: pd.Series, higher_is_better: bool = True) -> tuple[pd.Series, pd.Series]:
    s = pd.to_numeric(series, errors="coerce")
    # rank: 1 = best
    rank = s.rank(ascending=not higher_is_better, method="min")
    if s.nunique(dropna=True) <= 1:
        pct = pd.Series([50.0] * len(s), index=s.index)  # neutral 50th percentile

    # percentile: 0..100, where higher_is_better -> higher value => higher percentile
    if higher_is_better:
        pct = s.rank(pct=True, ascending=True) * 100.0
    else:
        pct = s.rank(pct=True, ascending=False) * 100.0
    return rank, pct


# Some % metrics are "higher is better"; some "lower is better" rarely appear here.
# Define any inversions here if needed later.
LOWER_IS_BETTER = {
    # Example if you want to invert fouls or conceded; for now we keep higher-is-better default for most creation/progression.
    "Fouls per 90": True,
    "Conceded goals per 90": True,
    "Shots against per 90": True,
}

def metric_direction(metric_name: str) -> bool:
    """Return True if higher is better for this metric."""
    return not LOWER_IS_BETTER.get(metric_name, False)

# 8) Season filter and minutes threshold
def filter_season_and_minutes(df: pd.DataFrame, min_minutes: int = 600) -> pd.DataFrame:
    # Your CSVs already contain 25/26 slices (by folder), but we’ll add a simple minutes filter
    out = df.copy()
    if "Minutes played" in out.columns:
        mins = pd.to_numeric(out["Minutes played"], errors="coerce")
        out = out[mins >= float(min_minutes)].copy()
    return out

# 9) Enrich master with grouping tags
import re

def _split_roles(pos_text: str) -> list[str]:
    if pd.isna(pos_text): return []
    parts = re.split(r"[,/;|]+", str(pos_text))
    return [p.strip().upper() for p in parts if p.strip()]

def enrich_with_groups(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    roles_multi = out["Position"].apply(_split_roles) if "Position" in out.columns else [[]]*len(out)

    out["_groups"] = roles_multi.apply(lambda lst: [WS_POS_TO_GROUP.get(p, "") for p in lst if WS_POS_TO_GROUP.get(p, "")])
    out["_fcm_roles"] = roles_multi.apply(lambda lst: [WS_POS_TO_FCM.get(p, "") for p in lst if WS_POS_TO_FCM.get(p, "")])

    out["_group"] = out["_groups"].apply(lambda L: L[0] if L else "")
    out["_fcm_role_guess"] = out["_fcm_roles"].apply(lambda L: L[0] if L else "")
    out["_is_gk"] = out["_group"].eq("GK")
    return out


# 10) Build a cohort
def build_cohort(master: pd.DataFrame,
                 cohort_type: str,
                 fcm_role: str | None = None,
                 general_group: str | None = None,
                 nations: list[str] | None = None,
                 min_minutes: int = 600) -> pd.DataFrame:
    """
    cohort_type: "FCM" or "GROUP"
    fcm_role: e.g., "11a - LWF"
    general_group: one of {"GK","FB","CB","DM","CMAM","W","CF"}
    nations: filter by ["Belgium","Netherlands","France"] if provided
    """
    df = enrich_with_groups(master)
    if nations:
        df = df[df["__nation"].isin(nations)].copy()
    df = filter_season_and_minutes(df, min_minutes=min_minutes)

    if cohort_type == "FCM":
        if not fcm_role:
            return df.iloc[0:0]
        # match on our guessed fcm label
        df = df[df["_fcm_roles"].apply(lambda L: fcm_role in L)].copy()
    else:  # "GROUP"
        if not general_group:
            return df.iloc[0:0]
        df = df[df["_groups"].apply(lambda L: general_group in L)].copy()
    return df

# 11) Choose metric pack based on the cohort
def metrics_for_cohort(df_cohort: pd.DataFrame, cohort_type: str, fcm_role: str | None, general_group: str | None) -> dict[str, list[str]]:
    if df_cohort.empty:
        return {}
    if df_cohort["_is_gk"].any() and df_cohort["_is_gk"].all():
        return GK_PACK
    # outfield: pick group by general group (more stable)
    grp = general_group
    if cohort_type == "FCM":
        # infer from positions present if not supplied
        vals = df_cohort["_group"].dropna().unique().tolist()
        grp = vals[0] if vals else "W"
    packs = PACKS.get(grp or "W", PACKS["W"])
    return packs

# 12) Compute z-scores table for selected metrics
def zscore_table(df_cohort: pd.DataFrame, player_row: pd.Series, metric_clusters: dict[str, list[str]]) -> pd.DataFrame:
    if df_cohort.empty or not metric_clusters:
        return pd.DataFrame()
    # Flatten metric list and keep only columns that exist
    metrics = [m for cluster in metric_clusters.values() for m in cluster if m in df_cohort.columns and m not in WS_IGNORE_COLS]
    if not metrics:
        return pd.DataFrame()

    # Winsorise then z-score per metric
    zcols = {}
    ranks = {}
    pcts = {}
    for m in metrics:
        ws = _winsorise(df_cohort[m])
        z = _zscore(ws)
        zcols[m] = z
        hi = metric_direction(m)
        r, p = _rank_and_percentile(ws, higher_is_better=hi)
        ranks[m], pcts[m] = r, p

    # Assemble a tidy table for the whole cohort, then we’ll pick the player’s row by name/ID upstream
    # keep key identity/meta columns so later UI can build divisions/scopes
    meta_cols = [
    "Wyscout Player ID","Player","Team","Position","Minutes played",
    "Age","DOB","__nation","Country","League","__division",
    "__file_date","__source_file","__overall_score","__overall_rank",
    "__overall_pct","__league_rank","__league_pct"
    ]

    present = [c for c in meta_cols if c in df_cohort.columns]
    base_cols = ["Player","Team","Position","Minutes played"]
    out = df_cohort[[c for c in base_cols if c in df_cohort.columns]].copy()
    # Ensure Age exists: compute from DOB if needed
    if "Age" not in out.columns or out["Age"].isna().all():
        if "DOB" in out.columns:
            out["Age"] = compute_age_series(out)

    for c in present:
        out[c] = df_cohort[c].values

    for m in metrics:
        out[m] = pd.to_numeric(df_cohort[m], errors="coerce")
        out[f"{m}__z"] = zcols[m]
        out[f"{m}__rank"] = ranks[m]
        out[f"{m}__pct"] = pcts[m]
    return out

# 13) Overall score from cluster-weighted z-scores
def overall_score_from_clusters(row: pd.Series, metric_clusters: dict[str, list[str]], weights: dict[str, float]) -> float:
    # Average z per cluster, then weighted sum
    cluster_scores = []
    cluster_weights = []
    for cname, cols in metric_clusters.items():
        zs = []
        for m in cols:
            zval = row.get(f"{m}__z", np.nan)
            if np.isfinite(zval):
                # invert direction if needed
                if not metric_direction(m):
                    zval = -zval
                zs.append(zval)
        if zs:
            cluster_scores.append(np.nanmean(zs))
            cluster_weights.append(weights.get(cname, 0.0))
    if not cluster_scores or sum(cluster_weights) <= 0:
        return np.nan
    # normalise weights
    w = np.array(cluster_weights, dtype=float)
    w = w / w.sum()
    return float(np.dot(np.array(cluster_scores, dtype=float), w))



# 14) Convenience: prepare everything for one cohort (returns cohort table + weights + pack label)
def prepare_cohort_analysis(
    master: pd.DataFrame,
    target_player_name: str | None,
    target_wyscout_id: str | None,
    cohort_type: str,
    fcm_role: str | None,
    general_group: str | None,
    nations: list[str] | None = None,      # ← made optional
    min_minutes: int = 600,
    age_min: int | None = None,
    age_max: int | None = None
):
    # --- Handle optional nations ---
    if nations is None:
        if "__nation" in master.columns:
            nations = (
                master["__nation"]
                .dropna().astype(str).str.strip()
                .drop_duplicates().tolist()
            )
        else:
            nations = []

    cohort = build_cohort(
        master,
        cohort_type=cohort_type,
        fcm_role=fcm_role,
        general_group=general_group,
        nations=nations,
        min_minutes=min_minutes,
    )

    if not cohort.empty and (age_min is not None or age_max is not None):
        a = pd.to_numeric(cohort.get("Age", pd.Series(dtype=str)), errors="coerce")
        if age_min is not None:
            cohort = cohort[a >= age_min]
        if age_max is not None:
            cohort = cohort[a <= age_max]
    if cohort.empty:
        return cohort, {}, {}, pd.Series(dtype=float)
   
    # Pick pack + weights
    if cohort["_is_gk"].any() and cohort["_is_gk"].all():
        packs = GK_PACK
        weights = DEFAULT_WEIGHTS["GK"]
        pack_key = "GK"
    else:
        grp = general_group
        if cohort_type == "FCM" and not grp:
            vals = cohort["_group"].dropna().unique().tolist()
            grp = vals[0] if vals else "W"
        packs = PACKS.get(grp or "W", PACKS["W"])
        weights = DEFAULT_WEIGHTS.get(grp or "W", DEFAULT_WEIGHTS["W"])
        pack_key = grp or "W"


    ztab = zscore_table(cohort, None, packs)
    if ztab.empty:
        return cohort, packs, weights, pd.Series(dtype=float)

    # Compute overall score per row
    scores = []
    for _, r in ztab.iterrows():
        scores.append(overall_score_from_clusters(r, packs, weights))
    ztab["__overall_score"] = scores

    # Identify the target player row by Wyscout ID if present, else by name match
    target_mask = pd.Series([False]*len(ztab), index=ztab.index)
    if target_wyscout_id and "Wyscout Player ID" in cohort.columns:
        ids = cohort["Wyscout Player ID"].astype(str)
        target_mask = ids == str(target_wyscout_id)
    elif target_player_name and "Player" in cohort.columns:
        import unicodedata, re
        def _norm_name(x: str) -> str:
            x = (x or "").strip()
            x = unicodedata.normalize("NFKD", x)
            x = "".join(ch for ch in x if not unicodedata.combining(ch))
            x = x.casefold()
            return re.sub(r"[\W_]+", "", x)
        norm_target = _norm_name(target_player_name)
        target_mask = cohort["Player"].apply(lambda s: _norm_name(str(s)) == norm_target)


    target_row = ztab[target_mask].iloc[0] if target_mask.any() else pd.Series(dtype=float)

    # Add cohort overall ranks
    ztab["__overall_rank"] = ztab["__overall_score"].rank(ascending=False, method="min")
    ztab["__overall_pct"]  = ztab["__overall_score"].rank(pct=True, ascending=True) * 100.0  # higher score → lower pct rank, invert if you prefer
    
    # ---- Division label (Country · League · Tier) ----
    def _first_present(df, cols):
        for c in cols:
            if c in df.columns:
                return c
        return None

    country_col = _first_present(ztab, ["Country", "__nation", "Nation"])
    league_col  = _first_present(ztab, ["Competition", "League", "Tournament"])
    tier_col    = _first_present(ztab, ["Tier", "Division", "Level"])

    def _mk_division(row):
        parts = []
        if country_col: parts.append(str(row.get(country_col, "")).strip())
        if league_col:  parts.append(str(row.get(league_col, "")).strip())
        if tier_col and pd.notna(row.get(tier_col)):
            parts.append(f"T{row.get(tier_col)}")
        lbl = " · ".join([p for p in parts if p])
        return lbl if lbl else "Unknown"

    ztab["__division"] = ztab.apply(_mk_division, axis=1)

    return ztab, packs, weights, target_row

def compute_metric_derivatives(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for m in cols:
        if m not in out.columns:
            continue
        s = pd.to_numeric(out[m], errors="coerce")
        # sign: invert lower-is-better metrics so that higher = better consistently
        s_use = -s if m in LOWER_IS_BETTER else s

        mu = float(s_use.mean(skipna=True))
        sd = float(s_use.std(skipna=True, ddof=0))
        if not np.isfinite(sd) or sd == 0:
            z = pd.Series(0.0, index=s_use.index)  # flat distribution
        else:
            z = (s_use - mu) / sd

        # rank: higher-better after the sign fix
        rk = s_use.rank(ascending=False, method="min")

        # percentile: 0..100 (if only 1 valid value, put 50)
        n = rk.notna().sum()
        if n > 1:
            pct = 100.0 * (1.0 - (rk - 1.0) / (n - 1.0))
        else:
            pct = pd.Series(np.where(rk.notna(), 50.0, np.nan), index=rk.index)

        out[f"{m}__mu"]   = mu
        out[f"{m}__sd"]   = sd
        out[f"{m}__z"]    = z
        out[f"{m}__rank"] = rk
        out[f"{m}__pct"]  = pct
    return out

# =========================
# Fuzzy match + synonym helpers for Wyscout linking
# =========================
import difflib
import hashlib

# Club synonyms (add/extend as you find cases)
WS_CLUB_SYNONYMS = {
    # normalized -> canonical
    "royalantwerp": "Antwerp",
    "psv": "PSV Eindhoven",
    "psveindhoven": "PSV Eindhoven",
    "ajax": "Ajax",
    "afcajax": "Ajax",
    "olympiquelyonnais": "Lyon",
    "lyon": "Lyon",
    "stadebrestois": "Brest",
    "brest": "Brest",
    "rcsa": "Strasbourg",
    "strasbourg": "Strasbourg",
    "fcmidtjylland": "FC Midtjylland",
    # add lots more as you encounter variants
}

# League/tier synonyms, to map your Division text -> nation + tier key for Wyscout file hints
LEAGUE_SYNONYMS = {
    # France
    "ligue1": ("France", "1"),
    "fr1": ("France", "1"),
    "ligue2": ("France", "2"),
    "fr2": ("France", "2"),
    "national": ("France", "3"),
    "fr3": ("France", "3"),
    # Netherlands
    "eredivisie": ("Netherlands", "1"),
    "nl1": ("Netherlands", "1"),
    "keuken kampioen": ("Netherlands", "2"),
    "keukenkampioen": ("Netherlands", "2"),
    "eerste divisie": ("Netherlands", "2"),
    "nl2": ("Netherlands", "2"),
    # Belgium
    "pro league": ("Belgium", "1"),
    "jupiler": ("Belgium", "1"),
    "be1": ("Belgium", "1"),
    "chalproleague": ("Belgium", "2"),
    "challenger pro league": ("Belgium", "2"),
    "be2": ("Belgium", "2"),
}

def _canonical_team_name(s: str) -> str:
    key = _norm_str(s)
    return WS_CLUB_SYNONYMS.get(key, s)

def _parse_division(nation_text: str, division_text: str) -> tuple[str|None, str|None]:
    """
    Try to infer (nation, tier) from Playing Nation + Division using synonyms.
    Returns (nation, tier) like ('France','1') or (None, None) if not sure.
    """
    nrm = _norm_str((division_text or "")) + _norm_str((nation_text or ""))
    # try division synonyms first
    for k, (nat, tier) in LEAGUE_SYNONYMS.items():
        if k in _norm_str(division_text or ""):
            return nat, tier
    # fallback: just nation
    if "france" in _norm_str(nation_text or ""):
        return "France", None
    if "nether" in _norm_str(nation_text or "") or "dutch" in _norm_str(nation_text or ""):
        return "Netherlands", None
    if "belg" in _norm_str(nation_text or ""):
        return "Belgium", None
    return None, None

def _surname(name: str) -> str:
    parts = str(name or "").strip().split()
    return parts[-1] if parts else ""

def _synthetic_ws_id(name: str, team: str, dob: str) -> str:
    """Stable synthetic ID when no real ID column exists."""
    n = _norm_str(name)
    t = _norm_str(team)
    d = "" if dob is None else str(dob)
    raw = f"{n}|{t}|{d}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def ensure_wyscout_id_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Wyscout Player ID" not in out.columns:
        # Build deterministic IDs from Player|Team|DOB (DOB may not exist in some exports)
        has_dob = "DOB" in out.columns
        ids = []
        for _, r in out.iterrows():
            name = r.get("Player", "")
            team = r.get("Team", "")
            dob  = r.get("DOB", "") if has_dob else ""
            ids.append(_synthetic_ws_id(name, team, dob))
        out["Wyscout Player ID"] = ids
    return out


def _league_file_hint_mask(df: pd.DataFrame, nation: str|None, tier: str|None) -> pd.Series:
    """
    Returns a boolean mask roughly selecting the nation/tier based on __nation and filename heuristics.
    Only works if load_wyscout_master() filled __nation and __source_file.
    """
    mask = pd.Series([True]*len(df), index=df.index)
    if nation:
        mask = mask & (df["__nation"].astype(str) == nation)
    if tier and "__source_file" in df.columns:
        tkey = tier.strip()
        # Expect source files named like France1.csv, Dutch2.xlsx etc.
        mask = mask & df["__source_file"].astype(str).str.contains(tkey, case=False, na=False)
    return mask

def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_str(a), _norm_str(b)).ratio()

def find_wyscout_candidates(master: pd.DataFrame,
                            player_name: str,
                            team_hint: str,
                            nation: str|None,
                            tier: str|None,
                            top_k: int = 25) -> pd.DataFrame:
    """
    Returns a small dataframe of best matches with a composite score, columns:
    [Player, Team, Position, Minutes played, __nation, __source_file, Wyscout Player ID, __score]
    """
    if master.empty:
        return pd.DataFrame()

    df = ensure_wyscout_id_column(master)
    # Scope by nation/tier hint if possible
    try:
        m = _league_file_hint_mask(df, nation, tier)
        scoped = df[m].copy()
        if scoped.empty:
            scoped = df.copy()
    except Exception:
        scoped = df.copy()

    # canonicalise the team hint
    team_canon = _canonical_team_name(team_hint)

    rows = []
    for _, r in scoped.iterrows():
        nm = str(r.get("Player",""))
        tm = _canonical_team_name(str(r.get("Team","")))
        # name similarity: try full and surname emphasis
        s_full = _similar(player_name, nm)
        s_last = _similar(_surname(player_name), _surname(nm))
        s_team = _similar(team_canon, tm) if team_canon else 0.0
        # combine: name is primary, surname helps, team helps
        score = 0.65*s_full + 0.20*s_last + 0.15*s_team
        rows.append((score, nm, tm, r.get("Position",""), r.get("Minutes played",""),
                     r.get("__nation",""), r.get("__source_file",""), r.get("Wyscout Player ID","")))

    rows.sort(key=lambda x: x[0], reverse=True)
    best = rows[:top_k]
    if not best:
        return pd.DataFrame()
    return pd.DataFrame(best, columns=["__score","Player","Team","Position","Minutes played","__nation","__source_file","Wyscout Player ID"])

def try_auto_attach_wyscout_id(master: pd.DataFrame, player_row: pd.Series,
                               score_threshold: float = 0.82) -> tuple[str|None, pd.DataFrame]:
    """
    Attempt to find a single high-confidence match.
    Returns (wyscout_id or None, candidate_df for UI).
    """
    name = str(player_row.get("Name",""))
    team = str(player_row.get("Player Current Team",""))
    nation = str(player_row.get("Playing Nation",""))
    division = str(player_row.get("Division",""))

    nat_hint, tier_hint = _parse_division(nation, division)

    cands = find_wyscout_candidates(master, name, team, nat_hint, tier_hint, top_k=30)
    if cands.empty:
        return None, cands
    best = cands.iloc[0]
    if float(best["__score"]) >= score_threshold:
        return str(best["Wyscout Player ID"]), cands
    return None, cands


# =========================
# 7) DB & DEPTH HELPERS
# =========================
def _ensure_row_ids(df: pd.DataFrame, db_path: Optional[str] = None) -> pd.DataFrame:
    if ROW_ID_COL not in df.columns:
        df[ROW_ID_COL] = ""
    missing = df[ROW_ID_COL].astype(str).str.strip().eq("")
    if missing.any():
        df.loc[missing, ROW_ID_COL] = [str(uuid.uuid4()) for _ in range(int(missing.sum()))]
        if db_path:
            log_df_identity("About to save", df)  # must be the full DB
            safe_write_db(db_path, df)
    return df

def _idx_by_row_id(df: pd.DataFrame, row_id: str) -> Optional[int]:
    if ROW_ID_COL not in df.columns or not row_id:
        return None
    matches = df.index[df[ROW_ID_COL].astype(str) == str(row_id)]
    return int(matches[0]) if len(matches) else None

@st.cache_data(show_spinner=False)
def load_db(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        df.to_csv(path, index=False)
        return df
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in REQUIRED_COLUMNS:
        if c not in df.columns: df[c] = ""
    df = _ensure_row_ids(df, db_path=path)
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
        if pos not in df.columns: df[pos] = ""
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

    # robust, accent/case/punctuation-insensitive matching on (Name, Team)
    name_norm_series = df["Name"].astype(str).map(_norm_str)
    team_norm_series = df["Player Current Team"].astype(str).map(_norm_str)
    new_name_norm = _norm_str(row.get("Name",""))
    new_team_norm = _norm_str(row.get("Player Current Team",""))
    mask = (name_norm_series == new_name_norm) & (team_norm_series == new_team_norm)

    if mask.any():
        idx = df[mask].index[0]
        row.setdefault(ROW_ID_COL, df.at[idx, ROW_ID_COL])
        for k,v in row.items():
            if k in df.columns and str(v) != "": df.at[idx, k] = v
    else:
        if not str(row.get(ROW_ID_COL, "")).strip():
            row[ROW_ID_COL] = str(uuid.uuid4())
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


# =========================
# 8) CARD RENDERER (image left, info right)
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
            age_group = str(r.get("Age Group","")).strip()
            ag_txt = f" ({age_group})" if age_group else ""
            name_html = f"**{r.get('Name','')}{ag_txt}**{badge}"
            st.markdown(name_html, unsafe_allow_html=True)


            # Loan-aware team label
            on_loan = str(r.get("On loan","")).strip().lower() in {"yes","true","1"}
            loan_club = str(r.get("Loan Club","")).strip()
            parent_club = str(r.get("Parent Club","")).strip()
            team = str(r.get("Player Current Team","")).strip()
            visible_team = f"{loan_club} → {parent_club}" if on_loan and loan_club and parent_club else (loan_club or team)

            pos = r.get("Position",""); age = r.get("Age","")
            st.caption(f"{visible_team} • {pos} • Age: {age}")

            tmv = r.get("TM Value",""); cr = r.get("Current Rating (1-4)",""); pr = r.get("Potential Rating (1-4)",""); watched = r.get("Watched","")
            st.write(f"**Value:** {tmv}  |  **CR/PR:** {cr}/{pr}")
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
# 9) REPORT PROFILE EDITOR
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
        df.at[row_index, "Player Current Team"] = team_val.strip()
        df.at[row_index, "Division"]            = division_val.strip()
        df.at[row_index, "Age Group"]           = age_group_val.strip()
        df.at[row_index, "Agency"]              = agency_val.strip()

        # Store contract date (either preset 30 June or custom date) if present,
        # otherwise clear the cell
        if contract_val:
            df.at[focus_idx, "Contract Until"] = contract_val
        else:
            df.at[focus_idx, "Contract Until"] = ""


        for k, v in zip(tmpl["kpis"], kpi_vals):
            df.at[row_index, f"KPI: {k}"] = "" if v==0 else str(v)
        df.at[row_index, "KPI: Average"] = "" if avg==0 else str(avg)
        for sname, txt in note_vals.items():
            df.at[row_index, f"Profile: {sname}"] = txt.strip()
        df.at[row_index, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_df_identity("About to save", df)  # must be the full DB
        safe_write_db(st.session_state.db_csv, df)
        st.success("Profile saved.")
        st.cache_data.clear()
    return df

# Prefix map for normalizing stored roles
ROLE_PREFIX_TO_LABEL = {role.split(" - ")[0].strip(): role for role in ROLE_ORDER}

def normalize_roles_to_options(text: str) -> list[str]:
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

# ---------- KPI Presets (CSV-backed) ----------
from pathlib import Path
PRESET_PATH = Path("FCM Scouting/Player Profiling/FCM_Positions_KPIs.csv")
PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)

def _load_presets() -> pd.DataFrame:
    if PRESET_PATH.exists():
        try:
            return pd.read_csv(PRESET_PATH, dtype=str).fillna("")
        except Exception:
            st.warning("Failed to read KPI presets CSV. Recreating a fresh one.")
    df = pd.DataFrame(columns=["Profile","KPIs","Positions","Notes"])
    df.to_csv(PRESET_PATH, index=False, encoding="utf-8-sig")
    return df

def _save_presets(df: pd.DataFrame):
    cols = ["Profile","KPIs","Positions","Notes"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols].fillna("")
    df.to_csv(PRESET_PATH, index=False, encoding="utf-8-sig")

def _parse_list(cell: str) -> list[str]:
    if not cell:
        return []
    return [c.strip() for c in str(cell).split(",") if c.strip()]

def _sanitize_defaults(defaults: list[str] | None, options: list[str]) -> tuple[list[str], list[str]]:
    defaults = defaults or []
    opts = set(options)
    valid   = [d for d in defaults if d in opts]
    missing = [d for d in defaults if d not in opts]
    return valid, missing


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
    menu_btn("🧩 Shadow team", "nav_shadow")
    menu_btn("🏆 Tournament", "nav_tournament")
    menu_btn("⚙️ Files", "nav_files")
    if st.session_state.nav == "📝 Player reports" and st.session_state.get("profile_focus_id"):
        st.markdown("---")
        if st.button("⬅ Back to list", use_container_width=True, key="back_to_reports_list"):
            st.session_state.profile_focus_id = None
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

    # ----- Deep dive Tab -----
    with tab_deep:
        st.subheader("Players requiring deep dive")

        rule = st.selectbox("Rule", ["Watched contains 'deep'", "Watched is empty", "Custom keyword…"], index=0)
        if rule == "Watched contains 'deep'":
            mask = df["Watched"].str.contains("deep", case=False, na=False)
        elif rule == "Watched is empty":
            mask = df["Watched"].str.strip().eq("") | df["Watched"].isna()
        else:
            kw = st.text_input("Keyword", value="deep")
            mask = df["Watched"].str.contains(kw, case=False, na=False)

        dd = df[mask].copy()
        st.caption(f"{len(dd)} players")

        # mini-cards grid (4 per row)
        cols = st.columns(7)
        base_dir = os.path.join("FCM Scouting", "full reports done")
        os.makedirs(base_dir, exist_ok=True)
        changed = False
        df_all = df.copy()

        # ---------- Deep Dive: clips visual style + ensure column ----------
        # Ensure the column exists (so first run won't crash)
        if "Clips downloaded" not in df_all.columns:
            df_all["Clips downloaded"] = ""

        # Build a normalised boolean flag on the working frame `dd` for quick counts
        approved_flags = {"yes", "true", "1", "y", "✓", "downloaded"}

        # Ensure the column exists on dd as a Series (not a scalar default)
        if "Clips downloaded" not in dd.columns:
            dd["Clips downloaded"] = ""

        # Vectorised normalisation -> boolean mask
        dd["__clips_bool"] = (
            dd["Clips downloaded"]
            .astype(str).str.strip().str.lower()
            .isin(approved_flags)
        )


        # CSS: small coloured dot + pill badge
        st.markdown("""
        <style>
        .clip-dot { 
        display:inline-block; width:10px; height:10px; border-radius:50%; 
        margin-right:8px; vertical-align:middle;
        }
        .clip-badge {
        display:inline-flex; align-items:center; gap:6px;
        padding:2px 8px; border-radius:999px; font-size:12px; 
        background:rgba(0,0,0,0.06);
        }
        .clip-green { background:#22c55e; }   /* green-500 */
        .clip-red   { background:#ef4444; }   /* red-500  */
        </style>
        """, unsafe_allow_html=True)

        # Small legend + quick counts
        clips_yes = int(dd["__clips_bool"].sum())
        clips_no  = int((~dd["__clips_bool"]).sum())
        l1, l2, l3 = st.columns([1,1,6])
        with l1:
            st.markdown(f"<span class='clip-badge'><span class='clip-dot clip-green'></span>Downloaded: <b>{clips_yes}</b></span>", unsafe_allow_html=True)
        with l2:
            st.markdown(f"<span class='clip-badge'><span class='clip-dot clip-red'></span>Not downloaded: <b>{clips_no}</b></span>", unsafe_allow_html=True)

       
        # 7 cards per row
        CARDS_PER_ROW = 7
        if len(dd) == 0:
            st.info("No players to show.")
        else:
            cols = st.columns(CARDS_PER_ROW)

            for i, (_, r) in enumerate(dd.iterrows()):
                # If we're at the start of a new row (but not the very first row),
                # draw a full-width divider and create a fresh set of columns.
                if i > 0 and i % CARDS_PER_ROW == 0:
                    st.divider()  # or: st.markdown("---")
                    cols = st.columns(CARDS_PER_ROW)

                with cols[i % CARDS_PER_ROW]:
                    # MINI CARD (no heavy expander by default)
                    name = r.get("Name","")
                    team = r.get("Player Current Team","")
                    pos  = r.get("Position","")
                    age  = r.get("Age","")
                    img  = r.get("Photo Path","") or r.get("Photo URL","")

                    # Clips downloaded flag (normalised to bool)
                    clips_yes = False
                    cv = str(r.get("Clips downloaded","")).strip().lower()
                    if cv in {"yes","true","1","y","✓","downloaded"}:
                        clips_yes = True

                    # Tiny status dot next to the player name
                    dot = "<span class='clip-dot clip-green'></span>" if clips_yes else "<span class='clip-dot clip-red'></span>"


                    st.markdown("<div class='player-card'>", unsafe_allow_html=True)
                    if img:
                        st.image(img, use_container_width=True)

                    # name + dot
                    st.markdown(f"<h4 style='display:flex;align-items:center;gap:8px;'>{dot}{name}</h4>", unsafe_allow_html=True)
                    st.markdown(f"<div class='meta'>{team} • {pos} • Age: {age}</div>", unsafe_allow_html=True)

                    # optional admin inside a small expander
                    with st.expander("Admin", expanded=False):
                        has_report = bool(str(r.get("Full Report Path","")).strip())
                        done = st.checkbox("Full report done", value=has_report, key=f"dd_rep_{i}")
                        if done and not has_report:
                            up = st.file_uploader("Upload report (PDF)", type=["pdf"], key=f"dd_pdf_{i}")
                            if up is not None:
                                date_str = dt.datetime.now().strftime("%Y-%m-%d")
                                safe_name = re.sub(r"[^\w\-. ]", "_", name)
                                fp = os.path.join(base_dir, f"{safe_name} - {date_str}.pdf")
                                with open(fp, "wb") as f:
                                    f.write(up.read())
                                new_watch = (r["Watched"] + f" | full report done {date_str}").strip()
                                df_all.at[r.name, "Watched"] = new_watch
                                df_all.at[r.name, "Full Report Path"] = fp
                                changed = True
                        
                        # Clips downloaded checkbox + persist
                        cb = st.checkbox("Clips downloaded", value=clips_yes, key=f"dd_clips_{i}")
                        if cb != clips_yes:
                            df_all.at[r.name, "Clips downloaded"] = "Yes" if cb else ""
                            changed = True


                    st.markdown("</div>", unsafe_allow_html=True)


        if changed:
            log_df_identity("About to save", df_all)  # must be the full DB
            safe_write_db(st.session_state.db_csv, df_all)
            st.success("Database updated with full reports.")
            st.cache_data.clear()



# =========================
# 13) ALL PLAYERS PAGE
# =========================
if nav == "📚 All Players":
    st.title("All Players")
    df = load_db(st.session_state.db_csv).copy()
    # --- Shadow team column bootstrap ---
    if "Shadow Team Color" not in df.columns:
        df["Shadow Team Color"] = ""

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
                safe_write_db(st.session_state.db_csv, merged); st.success(f"Imported {len(newdf)} rows.")
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

        #TM values
        j1, j2 = st.columns(2)
        tm_val = j1.text_input("TM Value", value=st.session_state.get("new_TM Value",""), key="add_tm")
        tm_val_hi = j2.text_input("Highest TM Value", value=st.session_state.get("new_Highest TM Value",""), key="add_tm_hi")

        # Agency
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

        # Source URL TM
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
            ["", "needs deep dive", "Namechecked", "Monitor", "full report done","Longlisted","Unlikely","Data","Assigned by Julian","Needs more development to be considered", "Custom…"],
            key="add_watched_choice"
        )
        watched_custom = st.text_input("Custom watched note", key="add_watched_custom") if watched_choice == "Custom…" else ""
        watched_final = watched_custom if watched_choice == "Custom…" else watched_choice

        # place this with the other inputs in your Add Player form
        shadow_colors = ["", "Green", "Purple", "Red","Blue", "Grey"]
        shadow_color_sel = st.selectbox("Shadow Team Color", shadow_colors, index=0, key="add_shadow_color")


        # Qualitative notes
        strengths = st.text_area("Strengths", key="add_strengths")
        weaknesses = st.text_area("Weaknesses", key="add_weaknesses")

        # TM values, photo
       
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
                    "Shadow Team Colour": shadow_color_sel.strip(),
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
                safe_write_db(st.session_state.db_csv, df2)

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
                                safe_write_db(st.session_state.db_csv, df2)
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
            log_df_identity("About to save", df)  # must be the full DB
            safe_write_db(st.session_state.db_csv, df); st.success("Saved."); st.cache_data.clear()
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
                        log_df_identity("About to save", df)  # must be the full DB
                        safe_write_db(st.session_state.db_csv, df)
                        st.success("Details updated from Transfermarkt.")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.warning("Please paste a Transfermarkt URL.")

        st.markdown("---")
        
        # Build option pools from DB for add_new_dropdowns
        existing_teams      = sorted([t for t in df.get("Player Current Team", pd.Series(dtype=str)).astype(str).unique() if t and t != "nan"])
        existing_agencies   = sorted([t for t in df.get("Agency", pd.Series(dtype=str)).astype(str).unique() if t and t != "nan"])
        existing_divisions  = sorted([t for t in df.get("Division", pd.Series(dtype=str)).astype(str).unique() if t and t != "nan"])
        existing_age_groups = sorted([t for t in df.get("Age Group", pd.Series(dtype=str)).astype(str).unique() if t and t != "nan"])

        def add_new_dropdown_static(label: str,
                            options: list[str],
                            current_value: str,
                            key_prefix: str) -> str:
            """
            Select existing value or 'Add new…'. Always render the text input;
            we only adopt it if user picked 'Add new…'.
            """
            opts = ["— select —"] + options + ["Add new…"]
            # pre-select current value if present
            try:
                idx = opts.index(current_value) if current_value in opts else 0
            except Exception:
                idx = 0

            choice = st.selectbox(label, opts, index=idx, key=f"{key_prefix}__sel")

            # Always show the input (forms don’t re-render on select changes)
            new_txt = st.text_input(f"Add new ({label.lower()})",
                                    value="",
                                    key=f"{key_prefix}__new")

            # Decide the returned value
            if choice == "Add new…" and new_txt.strip():
                return new_txt.strip()
            elif choice not in {"— select —", "Add new…"}:
                return choice
            else:
                # keep the existing DB value if nothing selected
                return current_value.strip() if current_value else ""


        # -------- General details (editable)
        with st.form(key=f"gen_{focus_idx}", clear_on_submit=False):
            st.markdown("<script>window.scrollTo(0, 0);</script>", unsafe_allow_html=True)
            g1, g2, g3 = st.columns(3)
            name_val = g1.text_input("Name", value=r.get("Name",""))

            team_val = add_new_dropdown_static(
                label="Player Current Team",
                options=existing_teams,
                current_value=str(r.get("Player Current Team","")),
                key_prefix=f"detail_team_{focus_idx}"
            )


            #DIVISION WIDGET BLOCK
            division_val = add_new_dropdown_static(
                "Division",
                existing_divisions,
                str(r.get("Division","")),
                f"detail_div_{focus_idx}"
            )

            
            #AGE GROUP WIDGET BLOCK
            age_group_val = add_new_dropdown_static(
                "Age Group",
                existing_age_groups,
                str(r.get("Age Group","")),
                f"detail_agegrp_{focus_idx}"
            )
          

            # Positions (multiselect)
            cur_roles = normalize_roles_to_options(r.get("Position",""))
            pos_sel   = st.multiselect("Positions (first = primary)", ROLE_ORDER, default=[], key=f"pos_sel_{focus_idx}")
            pos_val   = ", ".join(pos_sel)

            # Agency, foot, height
            row_agencies      = df["Agency"].astype(str).tolist()
            row_citizenships  = df["Player Nationality"].astype(str).tolist()
            row_play_nations  = df["Playing Nation"].astype(str).tolist()

            h1, h2, h3 = st.columns(3)
            agency_val = add_new_dropdown_static(
                "Agency",
                existing_agencies,
                str(r.get("Agency","")),
                f"detail_ag_{focus_idx}"
            )


            
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

            # Contract details
            # Contract presets + date
            c1, c2 = st.columns(2)

            year_presets  = [2026, 2027, 2028, 2029, 2030, 2031]
            preset_labels = [f"06/{str(y)[-2:]}" for y in year_presets]
            preset_dates  = [f"{y}-06-30" for y in year_presets]

            cur_contract = str(r.get("Contract Until","")).strip()
            preset_index = 0
            if cur_contract in preset_dates:
                preset_index = preset_dates.index(cur_contract) + 1  # shift by 1 for "— none —"

            preset_choice = c1.selectbox(
                "Contract Until (preset)",
                ["— none —"] + preset_labels,
                index=preset_index,
                key=f"detail_contract_preset_{focus_idx}"
            )
            preset_date = preset_dates[preset_labels.index(preset_choice)] if preset_choice != "— none —" else ""

            # default for the date input: current contract date if any
            contract_default = None
            try:
                if cur_contract:
                    y,m,d = map(int, cur_contract.split("-"))
                    contract_default = date(y,m,d)
            except:
                ...

            custom_contract = c2.date_input(
                "…or pick a date",
                value=contract_default,
                format="YYYY-MM-DD",
                min_value=date(1900,1,1),
                max_value=date(2100,12,31),
                key=f"detail_contract_date_{focus_idx}"
            )

            contract_val = preset_date or (custom_contract.strftime("%Y-%m-%d") if custom_contract else "")


            #TM Value + source url insertion
            t1, t2 = st.columns(2)
            tm_hi_val = t1.text_input("Highest TM Value", value=r.get("Highest TM Value",""))
            source_val= t2.text_input("Transfermarkt URL", value=r.get("Source",""))
            
            # Verdict + Watched + Shadow Team color
            wcol1, wcol2, wcol3 = st.columns(3)

            # Verdict
            verdict_options = ["", "1 - Avg/Lower PLAYER in Bottom Tier League", "1.5 - Good Pl in Bottom Tier League / Avg Pl in Low Tier Leagues", "2 - Good Pl in Low Tier League / Avg Pl in Mid Tier Leagues", "2.5 - Good Pl in Mid Tier League / Avg Pl in High Tier Leagues", "3 - Good Pl in High Tier League / Avg Pl in Top Tier Leagues", "3.5 - Good Pl in Top Tiera","4 - World-Class Talent"]
            cur_verdict = r.get("Verdict", "")
            verdict_idx = verdict_options.index(cur_verdict) if cur_verdict in verdict_options else 0
            verdict_val = wcol1.selectbox("Verdict", verdict_options, index=verdict_idx, key=f"verdict_{focus_idx}")

            # Watched
            watched_presets = ["", "needs deep dive", "Namechecked", "Monitor", "full report done","Longlisted","Unlikely","Data","Assigned by Julian","Needs more development to be considered", "Custom…"]
            cur_watched = r.get("Watched", "")
            watched_idx = watched_presets.index(cur_watched) if cur_watched in watched_presets else (watched_presets.index("Custom…") if cur_watched else 0)
            watched_sel = wcol2.selectbox("Watched", watched_presets, index=watched_idx, key=f"watched_{focus_idx}")
            watched_custom2 = st.text_input("Custom watched note", value=(cur_watched if cur_watched not in watched_presets else ""), key=f"watched_custom_{focus_idx}") if watched_sel == "Custom…" else ""
            watched_val = watched_custom2 if watched_sel == "Custom…" else watched_sel

            # Shadow Team Color (single select)
            shadow_colors = ["", "Green", "Purple", "Red", "Blue", "Grey"]
            cur_color = str(r.get("Shadow Team Color","")).strip()
            color_idx = shadow_colors.index(cur_color) if cur_color in shadow_colors else 0
            shadow_color_val = wcol3.selectbox("Shadow Team Color", shadow_colors, index=color_idx, key=f"shadow_color_{focus_idx}")


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
                df.at[focus_idx, "Position"] = pos_val.strip()
                df.at[focus_idx, "Division"]      = division_val.strip()
                df.at[focus_idx, "Age Group"]     = age_group_val.strip()
                df.at[focus_idx, "Agency"]        = agency_val.strip()
                df.at[focus_idx, "Contract Until"] = contract_val.strip()
                df.at[focus_idx, "Dominant Foot"] = foot_val.strip()
                df.at[focus_idx, "Player Height"] = (f"{height_val_num:.2f} m" if height_val_num > 0 else "")
                df.at[focus_idx, "Player Nationality"] = nat_val.strip()
                df.at[focus_idx, "Playing Nation"] = play_nat_val.strip()
                df.at[focus_idx, "TM Value"] = tm_compact
                df.at[focus_idx, "Highest TM Value"] = tm_hi_compact
                df.at[focus_idx, "Source"] = source_val.strip()
                df.at[focus_idx, "Shadow Team Color"] = shadow_color_val.strip()
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
                

                df.at[focus_idx, "Last edited time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_df_identity("About to save", df)  # must be the full DB
                safe_write_db(st.session_state.db_csv, df)
                st.success("General details saved.")
                st.cache_data.clear()
                st.rerun() 
        
        # =========================
        # 📈 Wyscout link + Data panel (put this inside the DETAIL PAGE for the selected player)
        # Place after your "General details" form, before notes/KPIs
        # =========================
        # =========================
        # 🔗 Wyscout linkage (auto + manual)
        # =========================
        st.markdown("---")
        st.subheader("🔗 Wyscout linkage")

        # Reload current row (in case details were just saved)
        r = df.loc[focus_idx]
        st.markdown("<script>window.scrollTo(0, 0);</script>", unsafe_allow_html=True)
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
                log_df_identity("About to save", df)  # must be the full DB
                safe_write_db(st.session_state.db_csv, df)
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
                        log_df_identity("About to save", df)  # must be the full DB
                        safe_write_db(st.session_state.db_csv, df)
                        st.success(f"Linked automatically: {wsid}")
                        st.cache_data.clear()
                        st.rerun()
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
                    log_df_identity("About to save", df)  # must be the full DB
                    safe_write_db(st.session_state.db_csv, df)
                    st.success(f"Linked manually: {wsid}")
                    st.cache_data.clear()
                    st.rerun()


        st.markdown("---")
        st.subheader("📈 Data — cohort comparison")

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
            # default to all
            sel_divisions = st.multiselect("Peer Leagues / Tiers for Comparison", options=div_options, default=[], key=f"co_divs_{focus_idx}")


            min_minutes = st.slider(
                "Minutes threshold", min_value=0, max_value=1800, value=600, step=30, key=f"co_min_{focus_idx}"
            )

            # Age range (cohort filter)
            age_series_master = pd.to_numeric(master.get("Age", pd.Series(dtype=str)), errors="coerce")
            amin = int(age_series_master.dropna().min()) if age_series_master.notna().any() else 15
            amax = int(age_series_master.dropna().max()) if age_series_master.notna().any() else 40
            age_min, age_max = st.slider(
                "Age range for cohort", min_value=amin, max_value=amax, value=(amin, amax), key=f"co_age_{focus_idx}"
            )

            # Filter the master table by chosen divisions + minutes + age **before** you build the cohort (ztab)
            mask_div = master["__division"].isin(sel_divisions) if "__division" in master.columns else \
                    pd.Series([True]*len(master), index=master.index)

            mask_mins = pd.to_numeric(master.get("Minutes played", 0), errors="coerce").fillna(0) >= min_minutes
            mask_age  = (pd.to_numeric(master.get("Age", 0), errors="coerce").fillna(0) >= age_min) & \
                        (pd.to_numeric(master.get("Age", 0), errors="coerce").fillna(0) <= age_max)

            master_filtered = master[mask_div & mask_mins & mask_age].copy()

            # make sure __division exists on the cohort table later (useful for leader annotations)


            ct_left, ct_right = st.columns([1,2])
            cohort_choice = ct_left.radio("Cohort", ["FCM role peers", "General group peers"], horizontal=False, key=f"co_type_{focus_idx}")

            # FCM role default from this player's first stored role (if any)
            player_roles = normalize_roles_to_options(r.get("Position",""))
            default_role = player_roles[0] if player_roles else ""
            # General group default guessed from role label
            grp_opts = ["GK","FB","CB","DM","CM","AM","W","CF"]
            # crude guess
            guess_grp = (
            "GK" if str(default_role).startswith("GK") else
            ("CB" if any(x in (default_role or "") for x in ["4","5L","5R"]) else
            ("FB" if any(x in (default_role or "") for x in ["2","3"]) else
            ("W" if any(x in (default_role or "") for x in ["11","7","11a","7a"]) else
            ("DM" if default_role == "6" else
            ("CM" if default_role in ["8"] else
            ("AM" if default_role in ["10 - CAM","10a"] else "W"))))))
)

            if cohort_choice == "FCM role peers":
                fcm_role = ct_right.selectbox("FCM role", ROLE_ORDER, index=(ROLE_ORDER.index(default_role) if default_role in ROLE_ORDER else 0), key=f"co_fcm_{focus_idx}")
                general_group = None
                cohort_type_key = "FCM"
            else:
                general_group = ct_right.selectbox("Group", grp_opts, index=(grp_opts.index(guess_grp) if guess_grp in grp_opts else grp_opts.index("W")), key=f"co_grp_{focus_idx}")
                fcm_role = None
                cohort_type_key = "GROUP"

                     
            # --- Force-include target player into the filtered cohort (so we can compare vs any role) ---

            target_ws_id = str(r.get("Wyscout Player ID","")).strip() or None
            target_name  = str(r.get("Name","")).strip() or None

            import unicodedata, re

            def _norm(s: str) -> str:
                s = unicodedata.normalize("NFKD", str(s or ""))
                s = "".join(ch for ch in s if not unicodedata.combining(ch))
                s = s.casefold().strip()
                return re.sub(r"[\W_]+", "", s.casefold().strip())

            # 1) Find the player in the full master (not the filtered one)
            player_row_df = pd.DataFrame()
            if target_ws_id and "Wyscout Player ID" in master.columns:
                mask = master["Wyscout Player ID"].astype(str) == target_ws_id
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
                #    - For FCM role cohorts, we’ll set "_group" to the appropriate macro group.
                #    - For general groups, we’ll set "_group" directly to the radio choice.

                def _role_to_group(role_code: str) -> str:
                    # crude mapping; tweak to your project’s logic
                    if role_code.startswith("GK"): return "GK"
                    if role_code in {"2", "3", "2 - RB/RWB", "3 - LB/LWB"}: return "FB"
                    if role_code in {"4", "5L", "5R", "4 - CCB"}: return "CB"
                    if role_code in {"6"}: return "DM"
                    if role_code in {"8"}: return "CM"
                    if role_code in {"10 - CAM","10a"}: return "AM"
                    if role_code in {"11","7","11a","7a","11 - LM","7 - RM","11a - LWF","7a - RWF"}: return "W"
                    if role_code in {"9","9a","9 - AF","9a - TM"}: return "CF"
                    return "W"  # fallback

                try:
                    idx = master_filtered.index[-1]  # the appended row
                    if cohort_choice == "FCM role peers":
                        master_filtered.at[idx, "_group"] = _role_to_group(fcm_role)
                    else:
                        master_filtered.at[idx, "_group"] = general_group
                except Exception:
                    pass

            


            # --- Step 2: run analysis as usual ---
            ztab, packs, weights, target_row = prepare_cohort_analysis(
                master=master_filtered,
                target_player_name=target_name,
                target_wyscout_id=target_ws_id,
                cohort_type=cohort_type_key,
                fcm_role=fcm_role,
                general_group=general_group,
                min_minutes=int(min_minutes),
                age_min=int(age_min),
                age_max=int(age_max)
            )


            # Ensure ztab has __division by merging from master_filtered (prefer Wyscout ID)
            if "__division" not in ztab.columns:
                if "Wyscout Player ID" in ztab.columns and "Wyscout Player ID" in master_filtered.columns:
                    key_col = "Wyscout Player ID"
                else:
                    key_col = "Player"
                ztab = ztab.merge(
                    master_filtered[[key_col, "__division"]].drop_duplicates(subset=[key_col]),
                    on=key_col, how="left"
                )

            
           

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


            st.subheader("📊 Metric tables")

            # ------- Per-cluster metric tables with coloured percentiles -------
            # Build a dynamic Set-pieces cluster from available columns
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
                        zcol  = f"{m}__z"; pcol = f"{m}__pct"; mucol = f"{m}__mu"; sdcol = f"{m}__sd"
                        raw   = target_row.get(m, np.nan) if not target_row.empty else np.nan
                        pct   = target_row.get(pcol, np.nan) if not target_row.empty else np.nan
                        zsc   = target_row.get(zcol, np.nan) if not target_row.empty else np.nan
                        mu    = ztab[mucol].iloc[0] if mucol in ztab.columns and len(ztab) else np.nan
                        sd    = ztab[sdcol].iloc[0] if sdcol in ztab.columns and len(ztab) else np.nan
                        bar   = _pct_bar(pct) if pd.notna(pct) else _pct_bar(0)
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
                    log_df_identity("About to save", df)  # must be the full DB
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

    def _safe_focus_suf() -> str:
        fid = st.session_state.get("profile_focus_id")
        return str(fid) if fid is not None else "analysis"
    SUF = _safe_focus_suf()

    
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

    FCM_ROLE_CHOICES = [
        "1",
        "2",
        "3",
        "4L","4R",
        "5L","5R",
        "6",
        "8","8A","8B",
        "10","10A",
        "7","7A",
        "11","11A",
        "9","9A",
    ]

    def _discover_divisions(nation_dirs: list[str], nation_names: list[str]) -> pd.DataFrame:
        rows = []
        for folder, nation_label in zip(nation_dirs, nation_names):
            frames = _collect_country_frames(folder, nation_label, [1, 2, 3])
            for df in frames:
                league = None
                for col in ["League", "Competition", "Division"]:
                    if col in df.columns:
                        col_series = df[col].dropna().astype(str)
                        if not col_series.empty:
                            league = str(col_series.iloc[0])
                        break
                tier = int(df["__tier"].iloc[0]) if "__tier" in df.columns else 0
                src = str(df["__source_file"].iloc[0]) if "__source_file" in df.columns else ""
                if not league:
                    league = f"{nation_label} {tier}" if tier else nation_label
                rows.append({
                    "__nation": nation_label,
                    "__league": league,
                    "__tier": tier,
                    "__league_key": f"{nation_label} · {league} · T{tier}" if tier else f"{nation_label} · {league}",
                    "__folder": folder,
                    "__prefix": nation_label,
                    "__src": src,
                })
        return pd.DataFrame(rows).drop_duplicates()

    # -------------------- nation folders and helpers --------------------
    # We will use the global wyscout_folders() helper you defined earlier
    # which returns every nation folder under your Wyscout root.

    def _collect_country_frames(folder: str, country_label: str, tiers: list[int]) -> list[pd.DataFrame]:
        """
        Load Tier CSV/XLSX files for one nation folder and stamp: __nation, __tier, __league_key.
        country_label is the nation folder's basename for example Portugal England Netherlands.
        We match files whose name contains the country_label and a digit matching requested tiers.
        """
        from pathlib import Path
        import glob, re, os

        nation = country_label.strip()
        frames: list[pd.DataFrame] = []

        def _read_and_stamp(path: Path, tier_guess: int | None) -> None:
            try:
                if path.suffix.lower() == ".csv":
                    df_ = read_csv_resilient(str(path))
                else:
                    try:
                        dfs = read_xlsx_resilient(str(path))
                        if not dfs:
                            return
                        df_ = pd.concat(dfs, ignore_index=True, sort=False)
                    except Exception:
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

        # explicit tier files like "<Nation>1.csv"
        for t in tiers:
            for ext in (".csv", ".xlsx"):
                p = Path(folder) / f"{country_label}{t}{ext}"
                if p.exists():
                    _read_and_stamp(p, t)

        # any file in the folder that mentions the nation and contains any requested tier
        for ext in ("*.csv", "*.xlsx"):
            for f in glob.glob(str(Path(folder) / ext)):
                name = Path(f).name
                if country_label.lower().replace(" ", "") in name.lower().replace(" ", ""):
                    for t in tiers:
                        if str(t) in name:
                            _read_and_stamp(Path(f), t)
                            break

        return frames

    def render_country_tab(label: str, folder: str, file_prefix: str, key_prefix: str):
        st.subheader(f"{label} league analysis")

        # Pick tiers to include
        ti1, ti2, ti3 = st.columns(3)
        t1 = ti1.checkbox("Tier 1", value=True, key=f"{key_prefix}_t1")
        t2 = ti2.checkbox("Tier 2", value=True, key=f"{key_prefix}_t2")
        t3 = ti3.checkbox("Tier 3", value=True, key=f"{key_prefix}_t3")
        tiers = [i for i, flag in zip([1, 2, 3], [t1, t2, t3]) if flag]

        # Gather frames
        frames = _collect_country_frames(folder, file_prefix, tiers)

        if not frames:
            st.error(f"No data found for {label} ({'–'.join(map(str, tiers))}).")
            return

        df_all = pd.concat(frames, ignore_index=True, sort=False)
        # Normalise columns if present
        COL_PLAYER   = next((c for c in df_all.columns if c.lower() in {"player", "name", "player name"}), "Player")
        COL_TEAM     = next((c for c in df_all.columns if c.lower() in {"team", "club", "current team", "squad"}), "Team")
        COL_POS      = next((c for c in df_all.columns if c.lower() in {"position", "pos"}), "Position")
        COL_AGE      = next((c for c in df_all.columns if c.lower() == "age"), "Age")
        COL_MIN      = next((c for c in df_all.columns if "minute" in c.lower()), "Minutes played")
        COL_MV       = next((c for c in df_all.columns if "market value" in c.lower() or c.lower() == "mv"), "Market value")
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

        # filters etc
        BASE_COLS = [COL_PLAYER, COL_TEAM, "Foot", COL_POS, COL_AGE, COL_MV, COL_CONTRACT, "__tier", "__source_file"]

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
                age_rng = g1.slider("Age range", value=(amin, amax), min_value=amin, max_value=amax,
                                    key=f"{key_prefix}_age")
            else:
                age_rng = None
        else:
            age_rng = None

        if pd.to_numeric(df_all["_mins"], errors="coerce").notna().any():
            mmin = int(pd.to_numeric(df_all["_mins"], errors="coerce").min())
            mmax = int(pd.to_numeric(df_all["_mins"], errors="coerce").max())
            mins_rng = g2.slider("Minutes played", value=(mmin, mmax), min_value=mmin, max_value=mmax, step=10,
                                 key=f"{key_prefix}_mins")
        else:
            mins_rng = None

        h1, h2 = st.columns(2)
        if pd.to_numeric(df_all["_height_m"], errors="coerce").notna().any():
            hmin = float(pd.to_numeric(df_all["_height_m"], errors="coerce").min())
            hmax = float(pd.to_numeric(df_all["_height_m"], errors="coerce").max())
            height_rng = h1.slider("Height (m)", value=(round(hmin, 2), round(hmax, 2)),
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
            contract_rng = j2.date_input("Contract expires (range)", value=(cmin, cmax),
                                         format="YYYY-MM-DD", key=f"{key_prefix}_contract")
        else:
            contract_rng = None

        helper_cols = {"_mv_eur", "_mins", "_contract_dt", "_height_m"}
        present_base = [c for c in BASE_COLS if c in df_all.columns]
        kpi_candidates = [c for c in df_all.columns if c not in present_base and c not in helper_cols]

        show_kpis = st.multiselect("Pick KPI columns", options=kpi_candidates, default=[],
                                   key=f"{key_prefix}_kpis")

        # filter data
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
            start_dt = pd.to_datetime(contract_rng[0])
            end_dt = pd.to_datetime(contract_rng[1])
            view = view[(pd.to_datetime(view["_contract_dt"], errors="coerce") >= start_dt) &
                        (pd.to_datetime(view["_contract_dt"], errors="coerce") <= end_dt)]

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
                help="If empty, a dummy input = 1 is used",
            )

        run = st.button(f"Run analysis ({label})", type="primary", key=f"{key_prefix}_run")

        st.caption(f"Rows (after filters): {len(view)} / {len(df_all)}")
        if not show_kpis:
            st.info("Pick at least one KPI to analyse.")
            return

        if not run:
            return

        else:
            if run:
                # decide which method to run on the filtered subset `view`
                if not show_kpis and not method.startswith("DEA"):
                    st.warning("Pick at least one KPI.")
                else:
                    # background scoring (we'll compute a single Score but only display raw KPIs)
                    res = pd.DataFrame(index=view.index)

                    if method == "Z-score":
                        # z-avg of chosen KPIs as Score
                        import numpy as np
                        mat = view[show_kpis].apply(pd.to_numeric, errors="coerce")
                        # winsorise+z each column, then average (invert if LOWER_IS_BETTER)
                        zs = []
                        for c in mat.columns:
                            s = _winsorise(mat[c])
                            z = _zscore(s)
                            if not metric_direction(c):  # lower is better → flip sign
                                z = -z
                            zs.append(z)
                        score = np.nanmean(np.vstack(zs), axis=0) if zs else np.full(len(mat), np.nan)

                    elif method.startswith("PCA"):
                        # use PC1 as Score (scaled)
                        try:
                            from sklearn.preprocessing import StandardScaler
                            from sklearn.decomposition import PCA
                            X = view[show_kpis].apply(pd.to_numeric, errors="coerce")
                            X = X.dropna(how="all")
                            Xf = X.fillna(X.mean(numeric_only=True))
                            Z = StandardScaler().fit_transform(Xf.values)
                            pcs = PCA(n_components=1).fit_transform(Z).ravel()
                            # align to original index
                            score = pd.Series(pcs, index=Xf.index).reindex(view.index)
                        except Exception:
                            st.warning("Install scikit-learn for PCA.")
                            score = pd.Series([float("nan")]*len(view), index=view.index)

                    elif method.startswith("DEA"):
                        # DEA efficiency as Score
                        dea_out = dea_block(view, outputs=show_kpis,
                                            inputs=dea_inputs if dea_inputs else None)
                        score = dea_out.set_index(dea_out.index)["DEA_efficiency"].reindex(view.index)
                    else:
                        score = pd.Series([float("nan")]*len(view), index=view.index)

                    # Assemble the display with ONLY raw columns + Score + Rank
                    id_cols = [c for c in ["Player", "Team", "Position", COL_AGE, "__tier"] if c in view.columns]
                    if "__league_key" in view.columns:
                        id_cols.insert(2, "__league_key")  # show after Team
                    raw_cols = [c for c in show_kpis if c in view.columns]
                    out = view[id_cols + raw_cols].copy()
                    out["Score"] = score
                    out["Rank"] = out["Score"].rank(ascending=False, method="min")
                    out = out.sort_values(["Rank", "Score"], ascending=[True, False])

                    st.dataframe(out, use_container_width=True, hide_index=True)
                    export_buttons(out, key_suf=f"_{key_prefix}_analysis_raw")

    # discover nations and build tabs dynamically
    nation_dirs = wyscout_folders()
    if not nation_dirs:
        st.info("No nation folders found under WYS_ROOT_DIR yet.")
        st.stop()

    nation_names = [os.path.basename(p) for p in nation_dirs]
    tabs = st.tabs([n for n in nation_names] + ["📈 Graphs", "U21 development"])

    for i, (n_name, n_dir) in enumerate(zip(nation_names, nation_dirs)):
        with tabs[i]:
            render_country_tab(n_name, n_dir, file_prefix=n_name, key_prefix=f"nat_{i}")

    # indices of extra tabs
    graphs_tab_index = len(nation_names)
    u21_tab_index = len(nation_names) + 1

    # 2) 📈 Graphs tab uses all nations discovered above
    with tabs[graphs_tab_index]:
        st.subheader("Scatter plot across divisions")

        div_df = _discover_divisions(nation_dirs, nation_names)
        if div_df.empty:
            st.info("No divisions found.")
        else:
            div_options = div_df["__league_key"].sort_values().unique().tolist()
            sel_divs = st.multiselect(
                "Peer Leagues / Tiers for Comparison",
                options=div_options,
                default=[],
                key=f"co_divs_{SUF}"
            )

            # 2.2 Load frames only for the selected divisions
            frames = []
            if sel_divs:
                chosen_divs = div_df[div_df["__league_key"].isin(sel_divs)]
                for _, row in chosen_divs.iterrows():
                    folder = row["__folder"]
                    prefix = row["__prefix"]
                    tier = int(row["__tier"] or 0)
                    tiers = [tier] if tier else [1, 2, 3]
                    frames += _collect_country_frames(folder, prefix, tiers)

            if not sel_divs:
                st.info("Select at least one division to load data.")
            elif not frames:
                st.info("No data for the chosen divisions.")
            else:
                # 2.3 We have data: build dfG and all the Graphs logic
                dfG = pd.concat(frames, ignore_index=True, sort=False)

                # ----- Preset selector (must be before filters + KPI widgets) -----
                presets_df = _load_presets()
                preset_names = ["— None —"] + sorted(
                    presets_df["Profile"].dropna().astype(str).unique().tolist()
                )
                pcol1, pcol2 = st.columns([2, 1])
                sel_preset = pcol1.selectbox(
                    "Preset (FCM positional profile)",
                    options=preset_names,
                    index=0,
                    key="g_preset"
                )

                # Read preset values (KPIs + Positions) if chosen
                preset_kpis, preset_positions = [], []
                if sel_preset != "— None —":
                    prow = presets_df[presets_df["Profile"] == sel_preset]
                    if not prow.empty:
                        preset_kpis = _parse_list(prow.iloc[0].get("KPIs", ""))
                        preset_positions = _parse_list(prow.iloc[0].get("Positions", ""))

                # IMPORTANT: set session_state BEFORE widgets are created
                if st.session_state.get("g_preset_last") != sel_preset:
                    st.session_state["g_preset_last"] = sel_preset
                    if sel_preset != "— None —":
                        st.session_state["g_positions"] = preset_positions[:]   # pre-fill Position filter
                        st.session_state["g_kpis"] = preset_kpis[:]             # pre-fill KPI picker
                    else:
                        st.session_state.setdefault("g_positions", [])
                        st.session_state.setdefault("g_kpis", [])

                # Ensure __league_key exists consistently
                if "__league_key" not in dfG.columns:
                    def _mk_key(r):
                        nation = str(r.get("__nation", "")).strip()
                        league = str(r.get("League", "") or r.get("Competition", "") or "").strip()
                        tier = str(r.get("__tier", "")).strip()
                        parts = [p for p in [nation, league, f"T{tier}" if tier else ""] if p]
                        return " · ".join(parts) if parts else "Unknown"
                    dfG["__league_key"] = dfG.apply(_mk_key, axis=1)

                # Normalize key columns
                COL_PLAYER = next((c for c in dfG.columns if c.lower() in {"player","name","player name"}), "Player")
                COL_TEAM   = next((c for c in dfG.columns if c.lower() in {"team","club","current team","squad"}), "Team")

                # Age: compute if needed
                if "Age" not in dfG.columns or pd.to_numeric(dfG["Age"], errors="coerce").isna().all():
                    if "DOB" in dfG.columns:
                        dfG["Age"] = compute_age_series(dfG)
                    else:
                        dfG["Age"] = pd.NA

                # ---------- Filters: Position + Minutes ----------
                pos_all = POS_CHOICES if "POS_CHOICES" in globals() else sorted(
                    dfG.get("Position", pd.Series([], dtype=str)).dropna().unique().tolist()
                )

                def _sanitize_positions(lst: list[str] | None, options: list[str]) -> tuple[list[str], list[str]]:
                    lst = lst or []
                    valid = [p for p in lst if p in options]
                    missing = [p for p in lst if p not in options]
                    return valid, missing

                valid_preset_positions, missing_preset_positions = _sanitize_positions(preset_positions, pos_all)

                if st.session_state.get("g_preset_last_pos") != sel_preset:
                    st.session_state["g_preset_last_pos"] = sel_preset
                    if sel_preset != "— None —":
                        st.session_state["g_positions"] = valid_preset_positions[:]

                if sel_preset != "— None —" and missing_preset_positions:
                    st.caption(f"Dropped positions not in options: {', '.join(missing_preset_positions)}")

                fcol1, fcol2 = st.columns([2,1])
                sel_positions = fcol1.multiselect(
                    "Positions (Wyscout style)",
                    options=pos_all,
                    default=st.session_state.get("g_positions", valid_preset_positions) or valid_preset_positions,
                    key="g_positions"
                )

                # Minutes: normalise to numeric and expose range slider
                if "Minutes played" in dfG.columns:
                    mins_series = pd.to_numeric(dfG["Minutes played"], errors="coerce")
                else:
                    if "_mins" not in dfG.columns:
                        dfG["_mins"] = pd.to_numeric(
                            dfG.get("Minutes played", pd.Series(dtype=str)).map(parse_minutes),
                            errors="coerce"
                        )
                    mins_series = pd.to_numeric(dfG.get("_mins", pd.Series(dtype=float)), errors="coerce")

                if mins_series.notna().any():
                    mn, mx = int(mins_series.min()), int(mins_series.max())
                    sel_min, sel_max = fcol2.slider(
                        "Minutes played",
                        value=(mn, mx), min_value=mn, max_value=mx, step=10, key="g_mins"
                    )
                else:
                    sel_min, sel_max = None, None

                # Apply filters to build plotting dataframe
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

                # KPI choices (numeric only)
                numeric_cols_G = sorted([
                    c for c in dfV.columns
                    if pd.api.types.is_numeric_dtype(pd.to_numeric(dfV[c], errors="coerce"))
                ])

                valid_preset_kpis, missing_preset_kpis = _sanitize_defaults(preset_kpis, numeric_cols_G)

                st.session_state["g_kpis"] = [k for k in st.session_state.get("g_kpis", []) if k in numeric_cols_G]

                if st.session_state.get("g_preset_last_sanitized") != sel_preset:
                    st.session_state["g_preset_last_sanitized"] = sel_preset
                    if sel_preset != "— None —":
                        st.session_state["g_kpis"] = valid_preset_kpis[:]

                if sel_preset != "— None —" and missing_preset_kpis:
                    st.caption(
                        f"Dropped {len(missing_preset_kpis)} preset KPI(s) not present in this dataset: "
                        f"{', '.join(missing_preset_kpis)}"
                    )

                kpG = pcol1.multiselect(
                    "KPIs",
                    numeric_cols_G,
                    default=st.session_state.get("g_kpis", valid_preset_kpis) or valid_preset_kpis,
                    max_selections=30,
                    key="g_kpis"
                )

                if sel_preset != "— None —":
                    if pcol2.button("Apply preset", key="g_apply_preset"):
                        st.session_state["g_kpis"] = preset_kpis
                        st.rerun()

                force_positive = st.checkbox(
                    "Force positive axes (shift if needed)",
                    value=True,
                    key="g_pos_axes"
                )

                # ---------- 2 KPIs: simple scatter ----------
                if len(kpG) == 2:
                    c1, c2 = st.columns(2)
                    x_col = c1.selectbox("X axis", kpG, index=0, key="g_x2")
                    y_col = c2.selectbox("Y axis", kpG, index=1, key="g_y2")

                    dfp = dfV[[COL_PLAYER, COL_TEAM, "Age", "__league_key", x_col, y_col]].copy()
                    dfp[x_col] = pd.to_numeric(dfp[x_col], errors="coerce")
                    dfp[y_col] = pd.to_numeric(dfp[y_col], errors="coerce")
                    dfp = dfp.dropna(subset=[x_col, y_col])

                    if force_positive:
                        minx, miny = float(dfp[x_col].min()), float(dfp[y_col].min())
                        if minx < 0: dfp[x_col] -= minx
                        if miny < 0: dfp[y_col] -= miny

                    import altair as alt

                    if "Age" not in dfV.columns or dfV["Age"].isna().all():
                        if "DOB" in dfV.columns:
                            dfV["Age"] = compute_age_series(dfV)
                        else:
                            dfV["Age"] = pd.NA

                    if "__league_key" not in dfp.columns and "__league_key" in dfV.columns:
                        dfp["__league_key"] = dfV.loc[dfp.index, "__league_key"]

                    tooltip_fields = [
                        alt.Tooltip(COL_PLAYER, title="Player"),
                        alt.Tooltip(COL_TEAM, title="Team"),
                        alt.Tooltip("Age:Q", title="Age"),
                        alt.Tooltip(x_col + ":Q", title=x_col),
                        alt.Tooltip(y_col + ":Q", title=y_col),
                        alt.Tooltip("__league_key:N", title="League")
                    ]

                    chart = (
                        alt.Chart(dfp.reset_index(drop=True))
                        .mark_circle(size=70, opacity=0.85)
                        .encode(
                            x=alt.X(x_col, type="quantitative"),
                            y=alt.Y(y_col, type="quantitative"),
                            color=alt.Color("__league_key:N", title="League"),
                            tooltip=tooltip_fields
                        )
                        .interactive()
                    )

                    st.altair_chart(chart, use_container_width=True)

                    st.markdown("### Top scorers (by chosen KPIs)")
                    rank_kpis = kpG[:] if len(kpG) >= 1 else []
                    if rank_kpis:
                        dfR = dfV[[COL_PLAYER, COL_TEAM, "Age", "__league_key", *rank_kpis]].copy()
                        for c in rank_kpis:
                            dfR[c] = _zscore(_winsorise(pd.to_numeric(dfR[c], errors="coerce")))

                        dfR["__score"] = dfR[rank_kpis].mean(axis=1, skipna=True)
                        agg = (
                            dfR.groupby([COL_PLAYER, COL_TEAM], as_index=False)
                               .agg({
                                   "Age":"first",
                                   "__league_key":"first",
                                   "__score":"mean",
                                   **{k:"first" for k in rank_kpis}
                               })
                        )

                        agg = agg.sort_values("__score", ascending=False).reset_index(drop=True)
                        agg.insert(0, "Rank", range(1, len(agg)+1))
                        agg = agg.rename(columns={"__score":"Score (z-avg)"})
                        st.dataframe(agg, use_container_width=True, hide_index=True)
                    else:
                        st.info("Pick at least one KPI above to compute rankings.")

                # ---------- >2 KPIs: weighted z-score composites ----------
                elif len(kpG) > 2:
                    st.caption("Select two composite axes. We z-score each KPI, apply weights, then average.")
                    left, right = st.columns(2)
                    x_kpis = left.multiselect("X composite KPIs", kpG, key="g_xk")
                    y_kpis = right.multiselect("Y composite KPIs", kpG, key="g_yk")
                    w_left = left.text_input("X weights (comma-sep)", key="g_xw", placeholder="1,1,1")
                    w_right = right.text_input("Y weights (comma-sep)", key="g_yw", placeholder="1,1,1")

                    def _composite(df, cols, w_str):
                        import numpy as np
                        if not cols:
                            return pd.Series(index=df.index, dtype=float)
                        mat = df[cols].apply(pd.to_numeric, errors="coerce").copy()
                        for c in cols:
                            mat[c] = _winsorise(mat[c])
                            mat[c] = _zscore(mat[c])
                        try:
                            weights = [float(x.strip()) for x in (w_str or "").split(",") if x.strip()!=""]
                            if len(weights) != len(cols):
                                weights = [1.0]*len(cols)
                        except Exception:
                            weights = [1.0]*len(cols)
                        comp = (mat.values * np.array(weights)).sum(axis=1) / sum(weights)
                        return pd.Series(comp, index=mat.index)

                    if x_kpis and y_kpis:
                        mat = dfV.copy()
                        dfp = mat[[COL_PLAYER, COL_TEAM, "Age", "__league_key"]].copy()
                        dfp["X"] = _composite(mat, x_kpis, w_left)
                        dfp["Y"] = _composite(mat, y_kpis, w_right)
                        dfp = dfp.dropna(subset=["X","Y"])

                        if force_positive:
                            minx, miny = float(dfp["X"].min()), float(dfp["Y"].min())
                            if minx < 0: dfp["X"] -= minx
                            if miny < 0: dfp["Y"] -= miny

                        import altair as alt
                        chart = (
                            alt.Chart(dfp)
                            .mark_circle(size=70, opacity=0.85)
                            .encode(
                                x=alt.X("X", title=f"Composite X ({', '.join(x_kpis)})"),
                                y=alt.Y("Y", title=f"Composite Y ({', '.join(y_kpis)})"),
                                color=alt.Color("__league_key", title="League / Tier"),
                                tooltip=[
                                    alt.Tooltip(COL_PLAYER, title="Player"),
                                    alt.Tooltip(COL_TEAM,   title="Team"),
                                    alt.Tooltip("Age",      title="Age"),
                                    alt.Tooltip("__league_key", title="League/Tier"),
                                    alt.Tooltip("X", title="Composite X", format=".3f"),
                                    alt.Tooltip("Y", title="Composite Y", format=".3f"),
                                ]
                            )
                            .interactive()
                            .properties(height=520, width="container")
                        )
                        st.altair_chart(chart, use_container_width=True)

                        import numpy as np
                        base = dfV[[COL_PLAYER, COL_TEAM, "Age", "__league_key"] + kpG].copy()
                        for c in kpG:
                            base[c] = pd.to_numeric(base[c], errors="coerce")
                        Z = base[kpG].apply(_winsorise).apply(_zscore)
                        base["Score (z-avg)"] = np.nanmean(Z.values, axis=1)
                        base["Rank"] = base["Score (z-avg)"].rank(ascending=False, method="min")
                        cols = ["Rank", COL_PLAYER, COL_TEAM, "Age", "__league_key", "Score (z-avg)"] + kpG
                        st.markdown("#### Top scorers (by chosen KPIs)")
                        st.dataframe(base.sort_values("Rank").head(15)[cols], use_container_width=True, hide_index=True)

                        export_buttons(base.sort_values("Rank")[cols], key_suf="_graph_multi")
                    else:
                        st.info("Pick at least one KPI for X and one for Y.")
                else:
                    st.info("Pick 2 KPIs for a simple scatter, or >2 to build weighted composites.")

    
    # 3) U21 development tab, now fully standalone
    with tabs[u21_tab_index]:
        render_u21_tab(st, nation_dirs, nation_names)


    st.markdown("----")
    st.markdown("### KPI Presets Manager")

    # Positions for presets do not depend on any loaded dataset
    pos_all_for_presets = POS_CHOICES

    # KPI universe discovered once from all Wyscout files
    numeric_cols_for_presets = _discover_global_numeric_kpis()

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
            options=pos_all_for_presets,
            key="kp_new_positions",
        )
        new_kpis = ncol2.multiselect(
            "KPIs for this profile",
            options=numeric_cols_for_presets,
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
                    "KPIs": ", ".join(new_kpis),
                    "Positions": ", ".join(new_positions),
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
                st.rerun()

        st.markdown("#### Existing presets")
        dfp = _load_presets().copy()
        st.dataframe(dfp, use_container_width=True, hide_index=True)

        ecol1, ecol2, _ = st.columns([1, 1, 2])

        csv_bytes = dfp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        ecol1.download_button(
            "Export presets (CSV)",
            data=csv_bytes,
            file_name="FCM_Positions_KPIs.csv",
            mime="text/csv",
            key="kp_export",
        )

        uploaded = ecol2.file_uploader(
            "Import presets (CSV)", type=["csv"], key="kp_import"
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


# =========================
# 13) SHADOW TEAM PAGE
# =========================
if nav == "🧩 Shadow team":
    st.header("Shadow Team")

    df = load_db(st.session_state.db_csv).copy()  # your DB loader
    # keep a full, unfiltered copy for the options list
    df_all = df.copy()

    # make sure the column exists
    if "Shadow Team Color" not in df.columns:
        df["Shadow Team Color"] = ""

    
    
    # Basic search + filters
    colf1, colf2, colf3, colf4 = st.columns([2,2,2,2])
    with colf1:
        name_q = st.text_input("Search name", "")
    with colf2:
        min_pr = st.slider("Min Potential Rating", 0.0, 4.0, 3.0, 0.5)
    with colf3:
        max_age = st.number_input("Max age", min_value=14, max_value=40, value=28, step=1)
    with colf4:
        nation_filter = st.text_input("Playing Nation filter (optional)", "")

    # Quick normalisers seen elsewhere in your code
    def _split_roles(cell: str) -> list[str]:
        return [x.strip() for x in str(cell or "").split(",") if x.strip()]

    def _age_num(row: pd.Series) -> float:
        try:
            a = float(str(row.get("Age","")).strip())
            return a
        except:
            return float("inf")
    
    # prefill defaults: all players with a non-empty Shadow Team Color, per role


    def _defaults_for_role(role_code: str) -> list[str]:
        mask_role = df["Position"].astype(str).str.contains(rf"\b{re.escape(role_code)}\b", case=False, regex=True, na=False)
        mask_col  = df["Shadow Team Color"].astype(str).str.strip() != ""
        return sorted(df.loc[mask_role & mask_col, "Name"].dropna().astype(str).unique().tolist())


    # Narrow pool by filters
    if name_q:
        df = df[df["Name"].str.contains(name_q, case=False, na=False)]
    if nation_filter.strip():
        df = df[df["Playing Nation"].astype(str).str.contains(nation_filter, case=False, na=False)]

    # convert ratings/age robustly
    df["__PR"] = pd.to_numeric(df.get("Potential Rating (1-4)", 0), errors="coerce").fillna(0.0)
    df["__CR"] = pd.to_numeric(df.get("Current Rating (1-4)", 0), errors="coerce").fillna(0.0)
    df["__AGE"] = pd.to_numeric(df.get("Age", None), errors="coerce")

    df = df[(df["__PR"] >= min_pr) & ((df["__AGE"].isna()) | (df["__AGE"] <= max_age))]

    # Ranking heuristic for the shortlist (tweakable):
    # Primary: Potential Rating, tie-break: Current Rating, then younger first
    df["__RANK_KEY"] = list(zip(-df["__PR"], -df["__CR"], df["__AGE"].fillna(99)))
    df = df.sort_values("__RANK_KEY")

    # Build per-role buckets (top N = 4)
    TOP_N = 30
    buckets = {role: [] for role in ROLE_ORDER}  # ROLE_ORDER exists in your code
    for _, r in df.iterrows():
        roles = [rr.lower() for rr in _split_roles(r.get("Position",""))]
        for role in ROLE_ORDER:
            if role.lower() in roles and len(buckets[role]) < TOP_N:
                buckets[role].append(r)

    tab_overview, tab_table = st.tabs(["⚽ Overview (on-pitch)", "📄 Summary table (export)"])

    # ---------- Overview: on-pitch (multi picks + rendered image) ----------
    import re
    from PIL import Image, ImageDraw, ImageFont
    import io

    st.caption("Pick up to 4 players per FCM role. Selection order = Rank 1 → 4.")

    # --- background image ---
    up_bg = st.file_uploader("Pitch image (PNG)", type=["png"], key="shadow_pitch_upload")
    if up_bg is not None:
        bg_img = Image.open(up_bg).convert("RGBA")
    else:
        bg_img = Image.open("assets/shadow_pitch.png").convert("RGBA")  # adjust path if needed

    # --- helper: options per role, from DB ---
    def _opts_for_role(role_code: str) -> list[str]:
        mask = df_all["Position"].astype(str).str.contains(rf"\b{re.escape(role_code)}\b", case=False, regex=True, na=False)
        return sorted(df_all.loc[mask, "Name"].dropna().astype(str).unique().tolist())

    # --- coordinates for each role title block (x, y) ---
    ROLE_COORDS = {
        "GK": (110, 310),
        "3 - LB/LWB": (470, 20),
        "5L": (390, 150),
        "4 - CCB": (360, 315),
        "5R": (390, 470),
        "2 - RB/RWB": (470, 610),

        "11 - LM": (850, 20),
        "6": (570, 230),
        "8": (690, 345),
        "7 - RM": (830, 610),

        "10a": (795, 450),
        "10 - CAM": (795, 160),

        "11a - LWF": (1020, 80),
        "9 - AF": (1070, 390),
        "9a - TM": (1040, 200),
        "7a - RWF": (1020, 530),
    }

    # map your role codes to displayed labels
    ROLE_LABEL_MAP = {r: r for r in ROLE_ORDER}
    ROLE_LABEL_MAP.update({
        "11a": "11a - LWF",
        "7a": "7a - RWF",
        "9a": "9a - TM",
        "4":  "4 - CCB",
        "2":  "2 - RB/RWB",
        "3":  "3 - LB/LWB",
    })

    # ---- persisted picks in session: { "role label": [name1, name2, ...] } ----
    # Initialise from DB: default to players who already have a Shadow Team Color
    if "shadow_picks" not in st.session_state:
        st.session_state["shadow_picks"] = {
            ROLE_LABEL_MAP.get(r, r): _defaults_for_role(r) for r in ROLE_ORDER
        }

    # ---------- RENDER IMAGE FIRST (from saved picks) ----------
    canvas = bg_img.copy()
    draw = ImageDraw.Draw(canvas)
    
    SHADOW_COLOUR_MAP = {
        "Blue":   (59, 130, 246),   # top from home market
        "Red":    (239, 68, 68),    # top from outside market
        "Green":  (34, 197, 94),    # dev project
        "Purple": (168, 85, 247),   # U19 three star
        "Amber":  (245, 158, 11),   # if you still use it
    }


    # fonts with fallback
    try:
        FONT_PATH_BOLD    = "assets/Inter-Bold.ttf"
        FONT_PATH_MEDIUM  = "assets/Inter-Medium.ttf"
        FONT_PATH_REGULAR = "assets/Inter-Regular.ttf"

        font_big   = ImageFont.truetype(FONT_PATH_BOLD, 24)
        font_mid   = ImageFont.truetype(FONT_PATH_MEDIUM, 20)
        font_small = ImageFont.truetype(FONT_PATH_REGULAR, 18)

        def make_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
            size = max(11, int(size))
            if weight == "bold":
                path = FONT_PATH_BOLD
            elif weight == "medium":
                path = FONT_PATH_MEDIUM
            else:
                path = FONT_PATH_REGULAR
            return ImageFont.truetype(path, size)

    except Exception:
        font_big = font_mid = font_small = ImageFont.load_default()

        def make_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
            return ImageFont.load_default()



    def draw_text(x, y, text, fill, font, outline=(0,0,0), w=2):
        if outline:
            for dx,dy in ((-w,0),(w,0),(0,-w),(0,w),(-w,-w),(-w,w),(w,-w),(w,w)):
                draw.text((x+dx, y+dy), text, font=font, fill=outline)
        draw.text((x, y), text, font=font, fill=fill)

    # write role labels and dynamically spaced names
    for role_lbl, (x0, y0) in ROLE_COORDS.items():
        draw_text(x0, y0, role_lbl, (220, 220, 220), font_small)

        names = st.session_state["shadow_picks"].get(role_lbl, [])
        if not names:
            continue

        # vertical space allocated for this role list
        max_block_height = 180

        # allow more height for roles where you usually carry many names
        if role_lbl in {"9", "11a LWF", "7a RWF"}:
            max_block_height = 220

        lines = max(len(names), 1)
        line_spacing = min(24.0, max_block_height / float(lines))

        # derive font sizes from spacing
        name_font_size = line_spacing * 0.80
        rank_font_size = line_spacing * 0.80

        font_rank = make_font(rank_font_size, weight="bold")
        font_name = make_font(name_font_size, weight="medium")

        y = y0 + 18

        for idx, name in enumerate(names, start=1):
            cur = df.loc[df["Name"].astype(str) == str(name), "Shadow Team Color"]
            tag = str(cur.iloc[0]).strip() if not cur.empty else ""

            num_colour = SHADOW_COLOUR_MAP.get(tag, (209, 213, 219))

            # first choice highlighted slightly
            name_colour = (244, 244, 244) if idx > 1 else (250, 250, 210)

            draw_text(x0, y, f"{idx}.", num_colour, font_rank, outline=(0, 0, 0))
            draw_text(x0 + 28, y, name, name_colour, font_name, outline=(0, 0, 0))

            y += line_spacing


    

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    st.image(buf, caption="Shadow Team Board", use_container_width=True)
    st.download_button("Download PNG", data=buf.getvalue(), file_name="shadow_team.png", mime="image/png")

    if "shadow_picks" not in st.session_state:
        st.session_state["shadow_picks"] = {ROLE_LABEL_MAP.get(r, r): [] for r in ROLE_ORDER}
        # seed from DB colors (uses unfiltered df_all so nothing is lost by filters)
        for role in ROLE_ORDER:
            role_label = ROLE_LABEL_MAP.get(role, role)
            mask_role  = df_all["Position"].astype(str).str.contains(rf"\b{re.escape(role)}\b", case=False, regex=True, na=False)
            mask_color = df_all["Shadow Team Color"].astype(str).str.strip() != ""
            seeded = df_all.loc[mask_role & mask_color, "Name"].dropna().astype(str).unique().tolist()
            st.session_state["shadow_picks"][role_label] = sorted(seeded)[:20]

    # ------------- Import whole Shadow Team from Excel or CSV -------------
    st.subheader("Import Shadow Team from file")

    # one time flag, not strictly required but useful if you later want to show a message only once
    st.session_state.setdefault("shadow_import_applied", False)

    imp_file = st.file_uploader(
        "Upload exported shadow_team_shortlist (Excel or CSV)",
        type=["xlsx", "csv"],
        key="shadow_import_file"
    )

    # Only import when the user clicks the button
    if imp_file is not None and st.button("Apply import", key="shadow_import_button"):
        try:
            # read file
            if imp_file.name.lower().endswith(".csv"):
                imp_df = pd.read_csv(imp_file, dtype=str, keep_default_na=False)
            else:
                imp_df = pd.read_excel(imp_file, dtype=str).fillna("")

            required_cols = {"Pos.", "Rank", "Player Name"}
            if not required_cols.issubset(set(imp_df.columns)):
                st.error(
                    "Import file must contain columns: Pos., Rank, Player Name "
                    "(use the export from this page as template)."
                )
            else:
                imp_df = imp_df.copy()
                imp_df["Pos."] = imp_df["Pos."].astype(str).str.strip()
                imp_df["Player Name"] = imp_df["Player Name"].astype(str).str.strip()
                imp_df["Rank"] = pd.to_numeric(imp_df["Rank"], errors="coerce")

                # build new picks dict from file
                new_picks = {ROLE_LABEL_MAP.get(r, r): [] for r in ROLE_ORDER}

                for role in ROLE_ORDER:
                    label = ROLE_LABEL_MAP.get(role, role)

                    sub = imp_df[imp_df["Pos."].str.upper() == role.upper()].copy()
                    sub = sub.dropna(subset=["Rank"]).sort_values("Rank")

                    new_picks[label] = sub["Player Name"].tolist()

                # store in session so board and summary use it
                st.session_state["shadow_picks"] = new_picks

                # give imported players a default colour if they have none
                mask_imported = df["Name"].astype(str).isin(
                    imp_df["Player Name"].astype(str)
                )
                no_colour = df["Shadow Team Color"].astype(str).str.strip() == ""
                df.loc[mask_imported & no_colour, "Shadow Team Color"] = "Green"

                # persist colours to DB
                df_full = load_db(st.session_state.db_csv).copy()
                for _, r in df.loc[mask_imported].iterrows():
                    name = str(r["Name"])
                    colour = str(r["Shadow Team Color"])
                    df_full.loc[
                        df_full["Name"].astype(str) == name,
                        "Shadow Team Color"
                    ] = colour

                safe_write_db(st.session_state.db_csv, df_full)

                st.session_state["shadow_import_applied"] = True
                st.cache_data.clear()
                st.success("Shadow Team imported. Scroll down, the board and summary now reflect the file.")

        except Exception as e:
            st.error(f"Import failed: {e}")

    st.markdown("---")

    # ---------- SELECTION UI (below the image) + SAVE BUTTON ----------
    with st.form("shadow_form"):
        new_picks = {}
        for role in ROLE_ORDER:
            opts = _opts_for_role(role)
            lbl  = ROLE_LABEL_MAP.get(role, role)

            # take previously saved picks, but only those still present in opts
            saved = st.session_state["shadow_picks"].get(lbl, [])
            default_vals = [p for p in saved if p in opts]

            # show the multiselect safely
            sel = st.multiselect(
                f"{lbl} (max 20)",
                options=opts,
                default=default_vals,            # <- now guaranteed subset of options
                max_selections=20,
                key=f"shadow_sel_{role}"
            )
            new_picks[lbl] = sel

        
        # ----- Color assignment for all currently selected players (across roles) -----
        st.markdown("**Shadow Team Color (single-select per player)**")
        shadow_colors = ["", "Green", "Purple", "Red","Blue", "Grey"]

        # Flatten selected players across all roles; de-duplicate & sort
        selected_players = sorted({p for lst in new_picks.values() for p in lst})

        # For each player show a selectbox with current DB value preselected
        color_inputs = {}
        for name in selected_players:
            cur = df.loc[df["Name"].astype(str) == str(name), "Shadow Team Color"]
            cur_val = str(cur.iloc[0]).strip() if not cur.empty else ""
            # Safe default index
            idx = shadow_colors.index(cur_val) if cur_val in shadow_colors else 0
            color_inputs[name] = st.selectbox(
                f"{name}",
                shadow_colors,
                index=idx,
                key=f"shadow_color_{name}"
            )


        if st.form_submit_button("💾 Save board"):
            # 1) Update selections (session state)
            st.session_state["shadow_picks"] = new_picks

            # 2) Persist color choices back to DB
            for name, col in color_inputs.items():
                df.loc[df["Name"].astype(str) == str(name), "Shadow Team Color"] = col.strip()

            # 3) Write DB + refresh
            import shutil, datetime
            backup_path = st.session_state.db_csv.replace(".csv", f"_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
            shutil.copy(st.session_state.db_csv, backup_path)

            df_full = load_db(st.session_state.db_csv).copy()
            # merge updates from df (filtered) into df_full by Name or ID
            for name, row in df.iterrows():
                df_full.loc[df_full["Name"] == name, "Shadow Team Color"] = row.get("Shadow Team Color", "")
            log_df_identity("About to save", df_full)  # must be the full DB
            safe_write_db(st.session_state.db_csv, df_full)

            st.success("Board & Shadow Team colors saved to database.")
            st.cache_data.clear()
            st.rerun()

    # ---------- end drop-in ----------

        
    # ---------- Summary table (PPT-ready) ----------
    with tab_table:
        st.caption("Shows ONLY the players you picked in Shadow Team (selection order = Rank 1 → n).")

        picks = st.session_state.get("shadow_picks", {})  # {role_label: [name1, name2, ...]}
        rows = []

        def _safe(v): 
            return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)

        # quick lookup by player name (case-insensitive; uses first match if duplicates)
        def _find_row_by_name(name: str) -> pd.Series:
            if "Name" not in df.columns:
                return pd.Series(dtype=object)
            m = df[df["Name"].astype(str).str.casefold() == str(name).casefold()]
            return m.iloc[0] if not m.empty else pd.Series(dtype=object)

        # iterate roles in your ROLE_ORDER; map to the display label used on the board
        for role in ROLE_ORDER:
            role_label = ROLE_LABEL_MAP.get(role, role)   # same mapping used in Overview tab
            selected = picks.get(role_label, [])     # rank order = selection order

            for rank, player_name in enumerate(selected, start=1):
                rec = _find_row_by_name(player_name)

                on_loan = str(rec.get("On loan","")).strip().lower() in {"yes","true","1"}
                if on_loan:
                    club_txt = f"{_safe(rec.get('Loan Club',''))} (loan) → {_safe(rec.get('Parent Club',''))}"
                else:
                    club_txt = _safe(rec.get("Player Current Team",""))

                rows.append({
                    "Pos.": role,  # keep the raw FCM role code here
                    "Rank": rank,
                    "Player Name": player_name,
                    "Age (D.O.B)": f"{_safe(rec.get('Age',''))} ({_safe(rec.get('DOB',''))})",
                    "Pref. Foot (R/L)": _safe(rec.get("Dominant Foot","")),
                    "Club (Loan Club)": club_txt,
                    "Transfer Fee (€)": _safe(rec.get("TM Value","")),
                    "Current Salary (€)": _safe(rec.get("Current Salary","")),
                    "Contract Expiry (MM/YYYY)": _safe(rec.get("Contract Until","")),
                    "Agent / Agency Name": _safe(rec.get("Agency","")),
                    "Agent Contact Number": "",
                    "Spoken to agent? (Y/N)": ""
                })

        if not rows:
            st.info("No players selected yet. Pick players in the Overview tab and click **Save board**.")
        else:
            tbl = pd.DataFrame(rows, columns=[
                "Pos.","Rank","Player Name","Age (D.O.B)","Pref. Foot (R/L)","Club (Loan Club)",
                "Transfer Fee (€)","Current Salary (€)","Contract Expiry (MM/YYYY)",
                "Agent / Agency Name","Agent Contact Number","Spoken to agent? (Y/N)"
            ])

            st.dataframe(tbl, use_container_width=True, hide_index=True, height=420)

            # Exports
            c1, c2 = st.columns(2)
            c1.download_button(
                "Download shortlist (CSV)",
                data=tbl.to_csv(index=False).encode("utf-8-sig"),
                file_name="shadow_team_shortlist.csv",
                mime="text/csv",
                key="shadow_tbl_csv"
            )

            try:
                import io
                with pd.ExcelWriter(io.BytesIO(), engine="xlsxwriter") as w:
                    tbl.to_excel(w, index=False, sheet_name="Shadow Team")
                    data = w.book.filename.getvalue()  # type: ignore
                c2.download_button(
                    "Download shortlist (Excel)",
                    data=data,
                    file_name="shadow_team_shortlist.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="shadow_tbl_xlsx"
                )
            except Exception:
                st.caption("Install xlsxwriter for Excel export. CSV export always works.")

# =========================
# TOURNAMENT PAGE
# =========================
if nav == "🏆 Tournament":
    st.title("Tournament page")

    st.caption("Paste any Transfermarkt match report URL. Example: https://www.transfermarkt.com/spielbericht/index/spielbericht/4619226")

    url = st.text_input("Match report URL", key="tournament_match_url", placeholder="https://www.transfermarkt.com/spielbericht/index/spielbericht/########")

    col1, col2 = st.columns([1,1])
    with col1:
        pause = st.number_input("Delay between player fetches (seconds)", min_value=0.0, max_value=3.0, value=0.6, step=0.1, help="Helps avoid rate-limits")

    if st.button("Extract lineups", type="primary", use_container_width=True):
        if not url.strip():
            st.warning("Please paste a valid Transfermarkt match report URL.")
        else:
            with st.spinner("Fetching lineups and player profiles…"):
                df_lineups = cached_fetch_lineups(url.strip(), float(pause))
            if df_lineups is None or df_lineups.empty:
                st.warning("No players parsed. The page may use a different layout or the URL is not a match report.")
            else:
                st.success(f"Parsed {len(df_lineups)} players.")
                st.dataframe(df_lineups, use_container_width=True)

                # Quick exports
                c1, c2, c3 = st.columns(3)
                csv_bytes = df_lineups.to_csv(index=False).encode("utf-8-sig")
                json_bytes = df_lineups.to_json(orient="records").encode("utf-8")
                c1.download_button("Download CSV", data=csv_bytes, file_name="match_lineups.csv", mime="text/csv")
                c2.download_button("Download JSON", data=json_bytes, file_name="match_lineups.json", mime="application/json")

                # Append into a CSV of your choice (optional)
                with st.expander("Append to an existing CSV (optional)"):
                    out_path = st.text_input("CSV path", value="FCM Scouting/Fixtures/match_lineups.csv")
                    if st.button("Append", type="secondary"):
                        try:
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            if os.path.exists(out_path):
                                existing = pd.read_csv(out_path, dtype=str, keep_default_na=False)
                                merged = pd.concat([existing, df_lineups], ignore_index=True)
                            else:
                                merged = df_lineups
                            merged.to_csv(out_path, index=False, encoding="utf-8-sig")
                            st.success(f"Saved to {out_path}")
                        except Exception as e:
                            st.error(f"Failed to save: {e}")
