from __future__ import annotations

# =========================
# 1) STANDARD LIB IMPORTS
# =========================
import os, io, re, datetime as dt, base64, uuid, csv
from datetime import datetime, date
from typing import Dict, Any, Optional, List


#--------------------------------------------------------------------------------
# placeholder default avatar (1x1 transparent PNG) as a base64 string, so we always have something to show even if image loading fails
#--------------------------------------------------------------------------------
DEFAULT_AVATAR_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAG/UlEQVR4nO3dPVocRxSGUfCjdRAQaQkE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "EwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQEEwQE"
    "ABBMACCYAEAwAYBgAgDBBACCCQAEEwAI9i/3VhlRWOzAAwAAAABJRU5ErkJggg=="
)

def _default_avatar_bytes() -> bytes:
    return base64.b64decode(DEFAULT_AVATAR_PNG_B64)

def _st_image_with_fallback(src, *, width=None, use_container_width=False):
    try:
        if src:
            st.image(src, width=width, use_container_width=use_container_width)
        else:
            st.image(_default_avatar_bytes(), width=width, use_container_width=use_container_width)
    except Exception:
        st.image(_default_avatar_bytes(), width=width, use_container_width=use_container_width)


# =========================
# 2) THIRD-PARTY IMPORTS
# =========================
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import unicodedata
import json

from helpers import recruitment_data_analysis as recruitment_da
from helpers.player_reports_page import render_player_reports_page
from pathlib import Path

def resolve_app_root() -> Path:
    env = os.environ.get("SCOUTING_APP_ROOT")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent

ROOT = resolve_app_root()
os.environ["SCOUTING_APP_ROOT"] = str(ROOT)

# Wyscout lives under a different root in your folder structure (commonly APP_ROOT / "25 26")
def resolve_app_root() -> Path:
    env = os.environ.get("SCOUTING_APP_ROOT")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent

def resolve_wys_root(root: Path) -> Path:
    """
    Returns the real Wyscout season root, cross platform.
    Supports:
      Scouting Workspace/25 26
      Scouting Workspace/25-26
      Scouting Workspace/25_26
      Scouting Workspace/2526
      Scouting Workspace/25/26  (nested folders: 25 then 26)
    """
    # New structure: <app_root>/Wyscout Season Data/<season>/
    base_candidates = [
        root / "Wyscout Season Data",  # your new folder
        root / "Wyscout data",         # older name
        root / "Scouting Workspace",         # legacy fallback
    ]

    base = next((b for b in base_candidates if b.exists()), base_candidates[0])

    st.sidebar.caption(f"WYSROOTDIR = {os.environ.get('WYSROOTDIR')}")

    # If someone set WYSROOTDIR explicitly, trust it first
    env = os.environ.get("WYSROOTDIR")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p.resolve()

    candidates = [
        base / "25 26",
        base / "25-26",
        base / "25_26",
        base / "2526",
        base / "25.26",
        base / "25" / "26",          # mac style "25/26" (nested)
    ]

    # Also auto detect any folder name containing 25 and 26
    if base.exists():
        try:
            for p in base.iterdir():
                if p.is_dir() and re.search(r"25\D*26", p.name):
                    candidates.append(p)
        except Exception:
            pass

    for c in candidates:
        if c.exists():
            return c.resolve()

    # final fallback, even if missing
    return (base / "25 26").resolve()

ROOT = resolve_app_root()
os.environ["SCOUTING_APP_ROOT"] = str(ROOT)

WYS_ROOT = resolve_wys_root(ROOT)
os.environ["WYSROOTDIR"] = str(WYS_ROOT)

PHOTO_DIR = ROOT / "Scouting Workspace" / "player photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# Photos are under APP_ROOT/player photos (not APP_ROOT/Scouting Workspace/player photos)
PHOTO_DIR = ROOT / "Scouting Workspace" / "player photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# Keep any legacy names your code uses
PHOTODIR = PHOTO_DIR
IMAGES_DIR = PHOTO_DIR

# Backwards compatible alias for older code that still uses BASE_DIR
BASE_DIR = ROOT

# Safe image fallback used by player cards and report views
PLACEHOLDER_PATH = _default_avatar_bytes()


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
st.set_page_config(page_title="Recruitment Intelligence Workspace", layout="wide")

DEFAULT_DB_CSV    = "Scout DB (1).csv"
DEFAULT_DEPTH_CSV = "reference_depth.csv"

# Pitch positions as columns in the depth CSV (keep as-is to match your CSV)
DEPTH_POSITIONS = [
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
    "Shortlist Status Code","Player Height","TM Value","Highest TM Value","Contract Until","Agency",
    "Player Nationality","Current Salary","Player weight","Dominant Foot","Source","DOB","Strengths",
    "Weaknesses","Fixture Date","Scout Report By","Created time","Last edited time","Untitled Database",
    "Current Rating (1-4)","Division","Playing Nation","Loan Club","Parent Club","On loan",
    "Full Report Path","Photo URL","Photo Path"
]

# ---- Wyscout league folders (module-level, used by loaders & linkage UI)
# Use the already-resolved ROOT (Path) above.
os.environ["SCOUTING_APP_ROOT"] = str(ROOT)

WYS_BELGIUM_DIR = str(WYS_ROOT / "Belgium")
WYS_DUTCH_DIR   = str(WYS_ROOT / "Dutch")
WYS_FRANCE_DIR  = str(WYS_ROOT / "France")

# Stable focus key based on a persistent UUID per row
ROW_ID_COL = "Row ID"

# File locations
THIS_DIR = Path(__file__).resolve().parent          # .../Databases/Scouting Workspace
ROOT     = THIS_DIR.parent                          # .../Databases   (Belgium, Dutch, France folders live here)
BASE_DIR = ROOT                                     # keep your existing BASE_DIR usage working

# Used by safe_resolve_photo() and any relative path resolution
os.environ["SCOUTING_APP_ROOT"] = str(ROOT)

# Possible logo locations
POSSIBLE_LOGOS = [
    BASE_DIR / "Scouting Workspace" / "workspace_logo.png",
    BASE_DIR / "Scouting Workspace" / "workspace_logo.png",
    BASE_DIR / "workspace_logo.png",
    BASE_DIR / "workspace_logo.png",
]

def find_logo() -> Optional[str]:
    for p in POSSIBLE_LOGOS:
        if p.exists():
            return str(p)
    return None

# =========================
# 4) GLOBAL CSS
# =========================
st.markdown("""
<style>
:root {
  --riw-bg: #0b1120;
  --riw-panel: rgba(15, 23, 42, 0.72);
  --riw-panel-strong: rgba(15, 23, 42, 0.92);
  --riw-border: rgba(148, 163, 184, 0.18);
  --riw-border-strong: rgba(148, 163, 184, 0.32);
  --riw-text: #e5e7eb;
  --riw-muted: #94a3b8;
  --riw-accent: #38bdf8;
  --riw-good: #22c55e;
  --riw-warning: #f59e0b;
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.10), transparent 34rem),
    radial-gradient(circle at top right, rgba(34, 197, 94, 0.08), transparent 30rem),
    linear-gradient(180deg, #08111f 0%, #0b1120 48%, #111827 100%);
}

.block-container {
  padding-top: 1.2rem;
  padding-bottom: 3rem;
  max-width: 1440px;
}

section[data-testid="stSidebar"] {
  background: rgba(2, 6, 23, 0.92);
  border-right: 1px solid var(--riw-border);
}
section[data-testid="stSidebar"] .stButton > button {
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.72);
  color: #e5e7eb;
  font-weight: 650;
  min-height: 42px;
  transition: all .16s ease;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  border-color: rgba(56, 189, 248, 0.54);
  background: rgba(30, 41, 59, 0.90);
  transform: translateY(-1px);
}
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] span {
  color: #cbd5e1;
}

.riw-hero {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.94), rgba(15, 23, 42, 0.70)),
    radial-gradient(circle at top right, rgba(56, 189, 248, 0.22), transparent 24rem);
  border-radius: 28px;
  padding: 28px 30px;
  margin-bottom: 20px;
  box-shadow: 0 22px 70px rgba(2, 6, 23, 0.34);
}
.riw-kicker {
  color: #38bdf8;
  text-transform: uppercase;
  letter-spacing: .14em;
  font-size: .78rem;
  font-weight: 800;
  margin-bottom: 8px;
}
.riw-hero h1 {
  margin: 0 0 10px 0;
  color: #f8fafc;
  font-size: clamp(2rem, 4vw, 3.6rem);
  line-height: 1.02;
  letter-spacing: -0.04em;
}
.riw-hero p {
  color: #cbd5e1;
  max-width: 980px;
  font-size: 1.04rem;
  line-height: 1.65;
  margin: 0;
}
.riw-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}
.riw-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.72);
  color: #dbeafe;
  font-size: .84rem;
  font-weight: 650;
}
.riw-card {
  border: 1px solid var(--riw-border);
  border-radius: 22px;
  background: rgba(15, 23, 42, 0.74);
  padding: 18px 18px;
  min-height: 118px;
  box-shadow: 0 18px 45px rgba(2, 6, 23, 0.22);
}
.riw-card-title {
  color: #94a3b8;
  font-size: .82rem;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom: 8px;
}
.riw-card-value {
  color: #f8fafc;
  font-size: 2.1rem;
  font-weight: 850;
  line-height: 1;
  letter-spacing: -0.03em;
}
.riw-card-sub {
  color: #94a3b8;
  margin-top: 8px;
  font-size: .90rem;
}
.riw-section-title {
  margin-top: 26px;
  margin-bottom: 10px;
  color: #f8fafc;
  font-size: 1.35rem;
  font-weight: 850;
  letter-spacing: -0.02em;
}
.riw-workflow-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 22px;
  background: rgba(15, 23, 42, 0.64);
  padding: 18px;
  min-height: 160px;
}
.riw-workflow-card h3 {
  color: #f8fafc;
  font-size: 1.05rem;
  margin: 0 0 8px 0;
}
.riw-workflow-card p {
  color: #aebdd0;
  margin: 0;
  line-height: 1.55;
  font-size: .94rem;
}
.riw-pill {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(56, 189, 248, 0.12);
  color: #bae6fd;
  border: 1px solid rgba(56, 189, 248, 0.20);
  font-size: .75rem;
  font-weight: 750;
  margin-bottom: 10px;
}

.header-logo { display:flex; justify-content:flex-end; align-items:flex-start; padding-top:8px; }
.header-logo img { width:72px; height:auto; border-radius:14px; }

.chips { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.chip { padding:3px 9px; border-radius:12px;
  background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.16);
  font-size:12px; line-height:16px; white-space:nowrap; }
.chip-first { font-weight:800; font-size:15px; padding:4px 10px; }
.chip-second { font-size:13px; }
.depth-card { padding:8px 10px; border:1px solid rgba(148, 163, 184, 0.18); border-radius:14px;
  background:rgba(15, 23, 42, 0.58); }
.depth-label { font-weight:800; font-size:13px; margin-bottom:4px; letter-spacing:.4px; }
.pitch { border-radius:22px; padding:14px 10px;
  background:radial-gradient(ellipse at center, rgba(22, 101, 52, 0.30), rgba(15, 23, 42, 0.36));
  border:1px solid rgba(148, 163, 184, 0.16); }
hr { margin: .7rem 0; }
div[data-baseweb="input"] input { height:36px; font-size:13px; }
.badge { display:inline-block; padding:2px 8px; border-radius:999px;
  border:1px solid rgba(255,255,255,0.2); background:rgba(255,255,255,0.08);
  font-size:12px; margin-left:8px; }
.player-grid{ display:grid; grid-template-columns:repeat(4, 1fr); gap:14px; }
@media (max-width: 1300px){ .player-grid{grid-template-columns:repeat(3,1fr)} }
@media (max-width: 900px){  .player-grid{grid-template-columns:repeat(2,1fr)} }
@media (max-width: 600px){  .player-grid{grid-template-columns:1fr} }
.player-card{ background:rgba(15, 23, 42, 0.62); border:1px solid rgba(148, 163, 184, 0.15); border-radius:16px; padding:10px; }
.player-card .stImage img{ width:100% !important; height:120px !important; object-fit:cover !important; border-radius:10px; }
.player-card h4{ margin:8px 0 2px; }
.player-card .meta{ font-size:0.85rem; opacity:.82; margin-bottom:6px; }
.small-expander > details > summary { font-size:12px !important; opacity:.85; }

/* UX refinements for scouting workflow */
.ux-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 8px 0 14px 0;
}
.ux-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.66);
  color: #dbeafe;
  padding: 6px 10px;
  font-size: .82rem;
  font-weight: 700;
}
.ux-chip-muted {
  color: #94a3b8;
  background: rgba(15, 23, 42, 0.38);
}
.ux-status-legend {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin: 10px 0 16px 0;
}
.ux-status-pill {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.54);
  border-radius: 14px;
  padding: 9px 10px;
  color: #dbeafe;
  font-size: .82rem;
  line-height: 1.35;
}
.ux-status-dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  margin-right: 7px;
}
.ux-context-bar {
  position: sticky;
  top: 0.35rem;
  z-index: 999;
  border: 1px solid rgba(148, 163, 184, 0.20);
  background: rgba(2, 6, 23, 0.88);
  backdrop-filter: blur(12px);
  border-radius: 18px;
  padding: 12px 14px;
  margin: 6px 0 14px 0;
  box-shadow: 0 16px 42px rgba(2, 6, 23, 0.30);
}
.ux-context-title {
  color: #f8fafc;
  font-size: 1.05rem;
  font-weight: 850;
  margin-bottom: 7px;
}
.ux-context-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ux-mini-card {
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.44);
  border-radius: 14px;
  padding: 10px 12px;
  min-height: 56px;
}
.ux-mini-label {
  color: #94a3b8;
  font-size: .68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.ux-mini-value {
  color: #f8fafc;
  font-size: .96rem;
  font-weight: 800;
  margin-top: 3px;
}
.ux-empty-state {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.58);
  border-radius: 20px;
  padding: 18px;
  margin: 12px 0;
}
.ux-empty-title {
  color: #f8fafc;
  font-size: 1.05rem;
  font-weight: 850;
  margin-bottom: 6px;
}
.ux-empty-text {
  color: #cbd5e1;
  font-size: .92rem;
  line-height: 1.45;
}
.ux-action-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.58);
  border-radius: 18px;
  padding: 12px;
  margin-bottom: 8px;
}
@media (max-width: 900px) {
  .ux-status-legend { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
""", unsafe_allow_html=True)



# =========================
# 5) SHARED HELPERS
# =========================

# ---- Files & images
IMAGES_DIR = os.path.join("Scouting Workspace", "player photos")
os.makedirs(IMAGES_DIR, exist_ok=True)

def safe_resolve_photo(row: pd.Series) -> str | None:
    """Resolve Photo Path or Photo URL to an absolute path or URL, with name-based fallback."""
    url = str(row.get("Photo URL", "") or "").strip()
    raw = str(row.get("Photo Path", "") or "").strip()

    # 1) URLs work directly
    if url.startswith("http"):
        return url

    # 2) Resolve Photo Path to a real file
    if raw:
        rawnorm = os.path.normpath(raw.replace("\\", os.sep).replace("/", os.sep))

        # already absolute and exists
        if os.path.isabs(rawnorm) and os.path.exists(rawnorm):
            return rawnorm

        # relative, resolve from app root
        root = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent))
        absolute_path = root / rawnorm
        if absolute_path.exists():
            return str(absolute_path)

    # 3) Fallback: look inside IMAGES_DIR by sanitised player name
    safe_name = re.sub(r"[^\w\-. ]", "_", str(row.get("Name", "player"))).strip("_") or "player"
    root = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent))

    candidate_dirs = [
        Path(IMAGES_DIR),
        root / IMAGES_DIR,
    ]

    for d in candidate_dirs:
        if not d.exists():
            continue
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = d / f"{safe_name}.{ext}"
            if p.exists():
                return str(p)

    return None


def map_player_to_wyscout_context(player_row: dict) -> tuple[str | None, int | None]:
    nation_raw = str(player_row.get("Playing Nation", "")).strip().lower()
    division_raw = str(player_row.get("Division", "")).strip()

    nation_map = {
        "belgium": "Belgium",
        "belgian": "Belgium",
        "netherlands": "Dutch",
        "holland": "Dutch",
        "dutch": "Dutch",
        "france": "France",
        "french": "France",
    }
    nation = nation_map.get(nation_raw)

    m = re.search(r"(\d+)", division_raw)
    tier = int(m.group(1)) if m else None

    return nation, tier


def download_image_to_disk(url: str, player_name: str) -> Optional[str]:
    if not url or not requests:
        return None
    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0"
        r = requests.get(url, headers={"User-Agent": ua}, timeout=15)
        r.raise_for_status()

        ext = ".jpg"
        ct = r.headers.get("Content-Type", "").lower()
        if "png" in ct:
            ext = ".png"

        safe = re.sub(r"[^\w\-. ]", "_", player_name).strip("_") or "player"

        out = PHOTODIR / f"{safe}{ext}"          # <-- changed
        with open(out, "wb") as f:              # Path works in open()
            f.write(r.content)

        return str(out)                         # <-- changed (store as string)
    except Exception:
        return None




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

def _safe_bool_mask(mask, index) -> pd.Series:
    """Return a real boolean Series, even when pandas/pyarrow returns nullable or string masks."""
    try:
        if isinstance(mask, pd.Series):
            s = mask.reindex(index)
        else:
            s = pd.Series(mask, index=index)
    except Exception:
        return pd.Series(False, index=index, dtype=bool)

    def _as_bool(value) -> bool:
        if value is True:
            return True
        if value is False or value is None:
            return False
        try:
            if pd.isna(value):
                return False
        except Exception:
            pass
        text = str(value).strip().casefold()
        return text in {"true", "1", "yes", "y"}

    return s.map(_as_bool).fillna(False).astype(bool)

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
        "Germany":"DE","France":"FR","Spain":"ES","Italy":"IT","England":"GB","Belgium":"BE",
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

BACKUP_DIR = Path(os.environ.get("SCOUTING_APP_ROOT", Path(__file__).resolve().parent.parent)) / "Player DB backups"


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
WYS_ROOT_DIR = str(WYS_ROOT)


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

# Wyscout raw → Role profile label (primary best-effort)
# Tune these as you like; many-to-one mapping is fine for cohorting
WS_POS_TO_ROLE_PROFILE = {
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

def map_ws_position_to_role_profile(pos_text: str) -> str:
    p = str(pos_text or "").upper().strip()
    return WS_POS_TO_ROLE_PROFILE.get(p, "")

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
    out["_role_profiles"] = roles_multi.apply(lambda lst: [WS_POS_TO_ROLE_PROFILE.get(p, "") for p in lst if WS_POS_TO_ROLE_PROFILE.get(p, "")])

    out["_group"] = out["_groups"].apply(lambda L: L[0] if L else "")
    out["_role_profile_guess"] = out["_role_profiles"].apply(lambda L: L[0] if L else "")
    out["_is_gk"] = out["_group"].eq("GK")
    return out


# 10) Build a cohort
def build_cohort(master: pd.DataFrame,
                 cohort_type: str,
                 role_profile: str | None = None,
                 general_group: str | None = None,
                 nations: list[str] | None = None,
                 min_minutes: int = 600) -> pd.DataFrame:
    """
    cohort_type: "ROLE_PROFILE" or "GROUP"
    role_profile: e.g., "11a - LWF"
    general_group: one of {"GK","FB","CB","DM","CMAM","W","CF"}
    nations: filter by ["Belgium","Netherlands","France"] if provided
    """
    df = enrich_with_groups(master)
    if nations:
        df = df[df["__nation"].isin(nations)].copy()
    df = filter_season_and_minutes(df, min_minutes=min_minutes)

    if cohort_type == "ROLE_PROFILE":
        if not role_profile:
            return df.iloc[0:0]
        # match on our guessed reference label
        df = df[df["_role_profiles"].apply(lambda L: role_profile in L)].copy()
    else:  # "GROUP"
        if not general_group:
            return df.iloc[0:0]
        df = df[df["_groups"].apply(lambda L: general_group in L)].copy()
    return df

# 11) Choose metric pack based on the cohort
def metrics_for_cohort(df_cohort: pd.DataFrame, cohort_type: str, role_profile: str | None, general_group: str | None) -> dict[str, list[str]]:
    if df_cohort.empty:
        return {}
    if df_cohort["_is_gk"].any() and df_cohort["_is_gk"].all():
        return GK_PACK
    # outfield: pick group by general group (more stable)
    grp = general_group
    if cohort_type == "ROLE_PROFILE":
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
    role_profile: str | None,
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
        role_profile=role_profile,
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
        if cohort_type == "ROLE_PROFILE" and not grp:
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
    league_col  = _first_present(ztab, ["Competition", "League", "Competition Name"])
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
    "referenceidtjylland": "Reference Club",
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

def _parse_division(nation_text: str, division_text: str) -> tuple[str | None, str | None]:
    """
    Infer (nation, tier) from Playing Nation + Division.

    Supports:
      - synonyms like "Ligue 1", "Eredivisie"
      - generic entries like "1st tier", "2nd tier"
    """
    import re

    div_raw = str(division_text or "")
    nat_raw = str(nation_text or "")

    div_n = _norm_str(div_raw)
    nat_n = _norm_str(nat_raw)

    # 1) Tier from generic text like "1st tier", "tier 2"
    tier = None
    if ("tier" in div_n) or ("1st" in div_n) or ("2nd" in div_n) or ("3rd" in div_n):
        if ("1st" in div_n) or ("first" in div_n) or ("tier1" in div_n) or ("tier 1" in div_n):
            tier = "1"
        elif ("2nd" in div_n) or ("second" in div_n) or ("tier2" in div_n) or ("tier 2" in div_n):
            tier = "2"
        elif ("3rd" in div_n) or ("third" in div_n) or ("tier3" in div_n) or ("tier 3" in div_n):
            tier = "3"
        else:
            m = re.search(r"\b(\d+)\b", div_raw)
            if not m:
                m = re.search(r"(\d+)", div_raw)
            if m:
                tier = m.group(1)


    # 2) Division synonyms (if present, they also carry tier)
    for k, (nat, syn_tier) in LEAGUE_SYNONYMS.items():
        if k in div_n:
            return nat, (tier or syn_tier)

    # 3) Fallback from nation text only
    if "france" in nat_n:
        return "France", tier
    if "nether" in nat_n or "dutch" in nat_n or nat_n == "nl":
        return "Netherlands", tier
    if "belg" in nat_n:
        return "Belgium", tier
    if "england" in nat_n or nat_n == "eng":
        return "England", tier
    if "spain" in nat_n or nat_n == "es":
        return "Spain", tier
    if "german" in nat_n or nat_n == "de":
        return "Germany", tier
    if "italy" in nat_n or nat_n == "it":
        return "Italy", tier

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
    df = pd.DataFrame({pos: [""]*DEPTH_SLOTS for pos in DEPTH_POSITIONS})
    df.index = [f"{i+1}" for i in range(DEPTH_SLOTS)]
    return df

@st.cache_data(show_spinner=False)
def load_depth(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        df = blank_depth_df()
        df.to_csv(path, index=True)
        return df
    df = pd.read_csv(path, index_col=0, dtype=str, keep_default_na=False)
    for pos in DEPTH_POSITIONS:
        if pos not in df.columns: df[pos] = ""
    if len(df) < DEPTH_SLOTS:
        extra = DEPTH_SLOTS - len(df)
        df = pd.concat([df, pd.DataFrame({c:[""]*extra for c in df.columns})], ignore_index=True)
    if len(df) > DEPTH_SLOTS:
        df = df.iloc[:DEPTH_SLOTS].copy()
    df.index = [f"{i+1}" for i in range(DEPTH_SLOTS)]
    df = df[[c for c in DEPTH_POSITIONS]]
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
    def _safe_card_text(value, fallback: str = "Not added") -> str:
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

    def _status_colour(status: str) -> str:
        return {
            "Green": "#22c55e",
            "Purple": "#a855f7",
            "Blue": "#3b82f6",
            "Red": "#ef4444",
            "Grey": "#94a3b8",
            "Gray": "#94a3b8",
        }.get(str(status).strip(), "#64748b")

    with st.container(border=True):
        img_src = safe_resolve_photo(r) or PLACEHOLDER_PATH

        on_loan = str(r.get("On loan", "")).strip().lower() in {"yes", "true", "1"}
        loan_club = str(r.get("Loan Club", "")).strip()
        parent_club = str(r.get("Parent Club", "")).strip()
        team = str(r.get("Player Current Team", "")).strip()
        visible_team = f"{loan_club} to {parent_club}" if on_loan and loan_club and parent_club else (loan_club or team)

        name = _safe_card_text(r.get("Name", ""))
        pos = _safe_card_text(r.get("Position", ""))
        age = _safe_card_text(r.get("Age", ""))
        foot = _safe_card_text(r.get("Dominant Foot", ""))
        tmv = _safe_card_text(r.get("TM Value", ""))
        cr = _safe_card_text(r.get("Current Rating (1-4)", ""), "")
        pr = _safe_card_text(r.get("Potential Rating (1-4)", ""), "")
        watched = _safe_card_text(r.get("Watched", ""), "")
        status = _safe_card_text(r.get("Shortlist Status", ""), "")
        has_report = bool(str(r.get("Full Report Path", "")).strip())
        wyscout_id = str(r.get("Wyscout Player ID", "") or "").strip()
        wyscout_label = "Wyscout linked" if wyscout_id else "Wyscout not linked"
        report_label = "Report uploaded" if has_report else "No report"

        col_img, col_info = st.columns([1, 3])

        with col_img:
            try:
                st.image(img_src, width=110)
            except Exception:
                st.image(PLACEHOLDER_PATH, width=110)

        with col_info:
            st.markdown(f"**{name}**")
            st.caption(f"{visible_team or 'Club not added'} | {pos} | Age {age}")
            st.markdown(
                f"""
                <div class="ux-chip-row">
                    <span class="ux-chip">Foot: {foot}</span>
                    <span class="ux-chip">Value: {tmv}</span>
                    <span class="ux-chip">CR/PR: {cr or 'NA'}/{pr or 'NA'}</span>
                    <span class="ux-chip" style="border-color:{_status_colour(status)}55;">
                        <span class="ux-status-dot" style="background:{_status_colour(status)};"></span>{status or 'No status'}
                    </span>
                    <span class="ux-chip ux-chip-muted">{wyscout_label}</span>
                    <span class="ux-chip ux-chip-muted">{report_label}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if watched:
                st.caption(f"Watched: {watched}")

            if show_more:
                with st.expander("More", expanded=False):
                    strengths = r.get("Strengths", "")
                    weaknesses = r.get("Weaknesses", "")

                    if strengths:
                        st.write("Strengths")
                        st.write(strengths)

                    if weaknesses:
                        st.write("Weaknesses")
                        st.write(weaknesses)

                    source_url = str(r.get("Source", "") or "").strip()
                    if source_url.startswith(("http://", "https://")):
                        st.link_button("Transfermarkt", source_url, type="secondary")

                    if has_report:
                        st.markdown(f"[Open full report]({r['Full Report Path']})")

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
PRESET_PATH = Path("Scouting Workspace/Player Profiling/Role_Profile_KPIs.csv")
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
PUBLIC_NAV_ITEMS = [
    ("Overview", "nav_overview"),
    ("Player Intelligence", "nav_player_intelligence"),
    ("Data Lab", "nav_data_lab"),
    ("Shortlist Board", "nav_shortlist"),
    ("Settings", "nav_settings"),
]

if "db_csv" not in st.session_state:
    st.session_state.db_csv = DEFAULT_DB_CSV
if "depth_csv" not in st.session_state:
    st.session_state.depth_csv = DEFAULT_DEPTH_CSV
if "nav" not in st.session_state:
    st.session_state.nav = "Overview"
if st.session_state.nav not in {label for label, _ in PUBLIC_NAV_ITEMS}:
    st.session_state.nav = "Overview"
if "profile_focus_id" not in st.session_state:
    st.session_state.profile_focus_id = None

with st.sidebar:
    st.markdown("""
    <div style="padding: 8px 4px 16px 4px;">
      <div style="color:#f8fafc;font-size:1.05rem;font-weight:850;letter-spacing:-0.02em;">Recruitment Intelligence</div>
      <div style="color:#94a3b8;font-size:.82rem;margin-top:4px;line-height:1.45;">Player reports, data benchmarking and shortlist decisions in one focused workspace.</div>
    </div>
    """, unsafe_allow_html=True)

    def menu_btn(label: str, key: str):
        active = st.session_state.nav == label
        btn = st.button(label, use_container_width=True, type=("primary" if active else "secondary"), key=key)
        if btn:
            st.session_state.nav = label
            st.rerun()

    for label, key in PUBLIC_NAV_ITEMS:
        menu_btn(label, key)

    if st.session_state.nav == "Player Intelligence" and st.session_state.get("profile_focus_id"):
        st.markdown("---")
        if st.button("Back to player list", use_container_width=True, key="back_to_reports_list"):
            st.session_state.profile_focus_id = None
            st.rerun()

nav = st.session_state.nav


# =========================
# 11) FILE SETTINGS PAGE
# =========================

if nav == "Settings":
    st.header("Settings")
    st.caption("Keep the working pages clean. Use this page for paths, data health, cache controls and debug mode.")

    def _settings_non_empty_count(series: pd.Series) -> int:
        return int(series.fillna("").astype(str).str.strip().ne("").sum()) if isinstance(series, pd.Series) else 0


    if "debug_mode" not in st.session_state:
        st.session_state["debug_mode"] = False

    tab_active, tab_folders, tab_health, tab_cache = st.tabs([
        "Active database",
        "Folders",
        "Data health",
        "Cache and debug",
    ])

    with tab_active:
        st.subheader("Player database")
        dbp = st.text_input("Player DB CSV path", value=st.session_state.db_csv, key="settings_db_csv")
        if st.button("Use this player database", key="settings_use_db"):
            st.session_state.db_csv = dbp
            st.cache_data.clear()
            st.success("Player database path updated.")

        st.caption(f"Active player database: {st.session_state.db_csv}")

        st.subheader("Shortlist board database")
        dpp = st.text_input("Depth CSV path", value=st.session_state.depth_csv, key="settings_depth_csv")
        if st.button("Use this shortlist database", key="settings_use_depth"):
            st.session_state.depth_csv = dpp
            st.cache_data.clear()
            st.success("Shortlist database path updated.")

        st.caption(f"Active shortlist database: {st.session_state.depth_csv}")

    with tab_folders:
        st.subheader("Folder setup")
        folder_rows = [
            ("App root", ROOT),
            ("Wyscout data root", WYS_ROOT),
            ("Player photos", PHOTO_DIR),
            ("Reports folder", ROOT / "Scouting Workspace" / "full reports done"),
        ]

        for label, path in folder_rows:
            path = Path(path)
            st.markdown(
                f"""
                <div class="ux-mini-card">
                    <div class="ux-mini-label">{label}</div>
                    <div class="ux-mini-value">{path}</div>
                    <div class="ux-empty-text">Exists: {'Yes' if path.exists() else 'No'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.caption("The app resolves these paths with pathlib, so the same project can run on macOS and Windows as long as the root paths exist.")

    with tab_health:
        st.subheader("Data health")
        try:
            health_df = load_db(st.session_state.db_csv).copy()
        except Exception as e:
            st.error(f"Could not load player database: {e}")
            health_df = pd.DataFrame()

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Players", len(health_df))
        h2.metric("Reports", _settings_non_empty_count(health_df.get("Full Report Path", pd.Series(dtype=str))))
        h3.metric("Photos", _settings_non_empty_count(health_df.get("Photo Path", pd.Series(dtype=str))))
        h4.metric("Wyscout IDs", _settings_non_empty_count(health_df.get("Wyscout Player ID", pd.Series(dtype=str))))

        missing_cols = [
            c for c in [
                "Name",
                "Player Current Team",
                "Position",
                "Age",
                "Shortlist Status",
                "Wyscout Player ID",
                "Full Report Path",
            ]
            if c not in health_df.columns
        ]
        if missing_cols:
            st.warning("Missing useful columns: " + ", ".join(missing_cols))
        else:
            st.success("Core player columns are present.")

        with st.expander("Wyscout folder check", expanded=False):
            try:
                discovered = wyscout_folders()
            except Exception as e:
                discovered = []
                st.error(f"Could not discover Wyscout folders: {e}")

            if not discovered:
                st.info("No Wyscout folders discovered.")
            for folder in discovered:
                csvs = sorted(Path(folder).glob("*.csv"))
                st.write(f"{folder}: {len(csvs)} CSV files")

        with st.expander("CSV read errors", expanded=False):
            errs = st.session_state.get("wyscout_read_errors", [])
            if errs:
                st.code("\n".join(errs[-40:]))
                if st.button("Clear CSV read errors", key="settings_clear_wyscout_read_errors"):
                    st.session_state["wyscout_read_errors"] = []
                    st.rerun()
            else:
                st.caption("No CSV read errors logged.")

    with tab_cache:
        st.subheader("Cache and debug")
        st.session_state["debug_mode"] = st.toggle(
            "Show debug panels inside scouting pages",
            value=bool(st.session_state.get("debug_mode", False)),
            key="settings_debug_mode_toggle",
        )

        st.caption("Leave debug mode off during normal scouting work. Turn it on when checking Wyscout paths, metric mappings or position matching.")

        if st.button("Clear Streamlit cache", key="settings_clear_cache"):
            st.cache_data.clear()
            st.success("Cache cleared.")

    st.stop()

# =========================
# 12) HOME PAGE
# =========================
def _sort_newest_first(df_in: pd.DataFrame) -> pd.DataFrame:
    t1 = pd.to_datetime(df_in.get("Created time", ""), errors="coerce")
    t2 = pd.to_datetime(df_in.get("Last edited time", ""), errors="coerce")
    order = t1.fillna(t2)
    return df_in.assign(__sort=order).sort_values("__sort", ascending=False, na_position="last").drop(columns="__sort", errors="ignore")

def _safe_non_empty_count(series: pd.Series) -> int:
    return int(series.fillna("").astype(str).str.strip().ne("").sum()) if isinstance(series, pd.Series) else 0

def _pct(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{round((part / total) * 100):.0f}%"

def _metric_card(title: str, value: str | int, subtitle: str):
    st.markdown(
        f"""
        <div class="riw-card">
          <div class="riw-card-title">{title}</div>
          <div class="riw-card-value">{value}</div>
          <div class="riw-card-sub">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _workflow_card(label: str, title: str, body: str):
    st.markdown(
        f"""
        <div class="riw-workflow-card">
          <div class="riw-pill">{label}</div>
          <h3>{title}</h3>
          <p>{body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

if nav == "Overview":
    df = load_db(st.session_state.db_csv).copy()
    df = _sort_newest_first(df)

    total_players = len(df)
    completed_reports = _safe_non_empty_count(df.get("Full Report Path", pd.Series(dtype=str)))
    needs_deep_dive = int(df.get("Watched", pd.Series(dtype=str)).fillna("").astype(str).str.contains("deep", case=False, na=False).sum())
    shortlist_count = _safe_non_empty_count(df.get("Shortlist Status", pd.Series(dtype=str)))

    st.markdown(
        """
        <div class="riw-hero">
          <div class="riw-kicker">Public portfolio version</div>
          <h1>Recruitment Intelligence Workspace</h1>
          <p>A club neutral scouting data product built around practical recruitment decisions. The workflow brings together player monitoring, report tracking, Wyscout style benchmarking, role based radars and shortlist management without cluttering the app with operational extras.</p>
          <div class="riw-chip-row">
            <span class="riw-chip">Role profiling</span>
            <span class="riw-chip">Player reports</span>
            <span class="riw-chip">Radar presets</span>
            <span class="riw-chip">Shortlist planning</span>
            <span class="riw-chip">Recruitment data analysis</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        _metric_card("Tracked players", total_players, "Players currently held in the recruitment database")
    with m2:
        _metric_card("Completed reports", completed_reports, f"{_pct(completed_reports, total_players)} of tracked players have a report link")
    with m3:
        _metric_card("Deep dive queue", needs_deep_dive, "Players marked for closer video or data review")
    with m4:
        _metric_card("Shortlisted", shortlist_count, "Players carrying a shortlist status")

    st.markdown('<div class="riw-section-title">Core workflow</div>', unsafe_allow_html=True)
    w1, w2, w3 = st.columns(3)
    with w1:
        _workflow_card("Step 1", "Player Intelligence", "Review player cards, reports, notes, role fit, linked Wyscout IDs and scouting status from a single focused workspace.")
        if st.button("Open Player Intelligence", use_container_width=True, key="home_open_reports"):
            st.session_state.nav = "Player Intelligence"
            st.rerun()
    with w2:
        _workflow_card("Step 2", "Data Lab", "Compare players against role relevant cohorts, build radars, use preset KPI profiles and export ranking evidence cleanly.")
        if st.button("Open Data Lab", use_container_width=True, key="home_open_data"):
            st.session_state.nav = "Data Lab"
            st.rerun()
    with w3:
        _workflow_card("Step 3", "Shortlist Board", "Move from longlist to role based shortlist, manage ranked options and export a clean recruitment board.")
        if st.button("Open Shortlist Board", use_container_width=True, key="home_open_shortlist"):
            st.session_state.nav = "Shortlist Board"
            st.rerun()

    st.markdown('<div class="riw-section-title">Workspace snapshot</div>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)

    with s1:
        st.markdown("#### Role coverage")
        role_rows = []
        for role in ROLE_ORDER:
            if "Position" in df.columns:
                mask_role = _safe_bool_mask(
                    df["Position"].astype(str).apply(lambda x: role.lower() in [r.lower() for r in split_roles(x)]),
                    df.index,
                )
                count = int(mask_role.sum())
            else:
                count = 0
            role_rows.append({"Role": role, "Players": count})
        role_table = pd.DataFrame(role_rows).sort_values("Players", ascending=False)
        st.dataframe(role_table, use_container_width=True, hide_index=True, height=280)

    with s2:
        st.markdown("#### Market coverage")
        if "Playing Nation" in df.columns and total_players:
            nations = (
                df["Playing Nation"].fillna("").astype(str).str.strip()
                .replace("", pd.NA).dropna().value_counts().reset_index()
            )
            nations.columns = ["Market", "Players"]
            st.dataframe(nations.head(12), use_container_width=True, hide_index=True, height=280)
        else:
            st.info("No market data available yet.")


# =========================
# 13) PLAYER REPORTS PAGE
# =========================
# =========================
# 13) PLAYER REPORTS PAGE
# =========================
if nav == "Player Intelligence":    
    render_player_reports_page(
        load_db=load_db,
        safe_write_db=safe_write_db,
        PHOTO_DIR=PHOTO_DIR,
        DEFAULT_DB_CSV=DEFAULT_DB_CSV,
        compute_age_series=compute_age_series,
        ROLE_ORDER=ROLE_ORDER,
        normalize_roles_to_options=normalize_roles_to_options,   # IMPORTANT: fixes NameError
        _idx_by_row_id=_idx_by_row_id,
        load_wyscout_master=load_wyscout_master,
        try_auto_attach_wyscout_id=try_auto_attach_wyscout_id,
        find_wyscout_candidates=find_wyscout_candidates,
        _sort_newest_first=_sort_newest_first,                   # IMPORTANT: fixes sort_newest_first mismatch
        wyscoutfolders=wyscout_folders,
        _parse_division=_parse_division,                         # needed for cohort label logic
        render_player_card=render_player_card,
        ROW_ID_COL=ROW_ID_COL,
        _safe_unlink=_safe_unlink,
        profile_editor=profile_editor,
        log_df_identity=log_df_identity,
        scrape_transfermarkt=scrape_transfermarkt,
        download_image_to_disk=download_image_to_disk,
        _embed_pdf_data_uri=_embed_pdf_data_uri,
        _render_pdf_as_images=_render_pdf_as_images,
        app_root=ROOT,
        wys_root=WYS_ROOT,
    )
# =========================
# 15) DATA ANALYSIS PAGE
# =========================
if nav == "Data Lab":
    recruitment_da.render_data_analysis_page(
        wyscout_folders=wyscout_folders,
        dea_block=dea_block,
        export_buttons=export_buttons,
        _winsorise=_winsorise,
        _zscore=_zscore,
        metric_direction=metric_direction,
        compute_age_series=compute_age_series,
        _load_presets=_load_presets,
        _save_presets=_save_presets,
        _parse_list=_parse_list,
        _sanitize_defaults=_sanitize_defaults,
    )


# =========================
# 13) SHORTLIST BOARD PAGE
# =========================
if nav == "Shortlist Board":
    st.header("Shortlist Board")
    st.caption(
        "Build a role based Shadow Team from the scouting database. The pitch is rendered with mplsoccer, "
        "so it no longer depends on any PNG background image."
    )

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

    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
        from mplsoccer import Pitch
    except Exception as e:
        st.error("The Shortlist Board needs mplsoccer. Add mplsoccer to requirements.txt, then run pip install -r requirements.txt.")
        st.caption(f"Import error: {e}")
        st.stop()

    df = load_db(st.session_state.db_csv).copy()
    df_all = df.copy()

    if "Shortlist Status" not in df.columns:
        df["Shortlist Status"] = ""
    if "Shortlist Status" not in df_all.columns:
        df_all["Shortlist Status"] = ""

    ROLE_LABEL_MAP = {r: r for r in ROLE_ORDER}
    ROLE_LABEL_MAP.update({
        "11a": "11a - LWF",
        "7a": "7a - RWF",
        "9a": "9a - TM",
        "4": "4 - CCB",
        "2": "2 - RB/RWB",
        "3": "3 - LB/LWB",
    })

    STATUS_COLOUR_MAP = {
        "Blue": "#3b82f6",
        "Red": "#ef4444",
        "Green": "#22c55e",
        "Purple": "#a855f7",
        "Amber": "#f59e0b",
        "Grey": "#94a3b8",
        "Gray": "#94a3b8",
        "": "#e5e7eb",
    }

    ROLE_COORDS = {
        "GK": (10, 40),
        "3 - LB/LWB": (29, 12),
        "5L": (32, 27),
        "4 - CCB": (26, 40),
        "5R": (32, 53),
        "2 - RB/RWB": (29, 68),
        "11 - LM": (54, 12),
        "6": (49, 36),
        "8": (63, 48),
        "7 - RM": (54, 68),
        "10 - CAM": (78, 30),
        "10a": (82, 51),
        "11a - LWF": (100, 13),
        "9a - TM": (101, 31),
        "9 - AF": (104, 48),
        "7a - RWF": (100, 67),
    }

    ROLE_DISPLAY_ORDER = [ROLE_LABEL_MAP.get(r, r) for r in ROLE_ORDER]

    def _split_roles(cell: str) -> list[str]:
        parts = re.split(r"[,/;|]+", str(cell or ""))
        return [p.strip() for p in parts if p.strip()]

    def _role_mask(data: pd.DataFrame, role_code: str) -> pd.Series:
        if "Position" not in data.columns:
            return pd.Series(False, index=data.index)
        target = str(role_code).strip().casefold()
        short_target = target.split(" - ")[0].strip()

        def _matches(cell: str) -> bool:
            roles = [x.casefold() for x in _split_roles(cell)]
            for role in roles:
                role_short = role.split(" - ")[0].strip()
                if role == target or role_short == short_target:
                    return True
            return False

        return _safe_bool_mask(data["Position"].astype(str).map(_matches), data.index)

    def _safe_text(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        return str(v)

    def _status_for_player(name: str) -> str:
        hit = df_all[df_all["Name"].astype(str).str.casefold() == str(name).casefold()]
        if hit.empty:
            return ""
        return str(hit.iloc[0].get("Shortlist Status", "")).strip()

    def _row_for_player(name: str) -> pd.Series:
        hit = df_all[df_all["Name"].astype(str).str.casefold() == str(name).casefold()]
        return hit.iloc[0] if not hit.empty else pd.Series(dtype=object)

    def _defaults_for_role(role_code: str) -> list[str]:
        mask_role = _safe_bool_mask(_role_mask(df_all, role_code), df_all.index)
        mask_status = _safe_bool_mask(df_all["Shortlist Status"].astype(str).str.strip() != "", df_all.index)
        out = df_all.loc[mask_role & mask_status].copy()
        if out.empty:
            return []
        out["__PR"] = pd.to_numeric(out.get("Potential Rating (1-4)", 0), errors="coerce").fillna(0.0)
        out["__CR"] = pd.to_numeric(out.get("Current Rating (1-4)", 0), errors="coerce").fillna(0.0)
        out["__AGE"] = pd.to_numeric(out.get("Age", None), errors="coerce")
        out = out.sort_values(["__PR", "__CR", "__AGE"], ascending=[False, False, True])
        return out["Name"].dropna().astype(str).drop_duplicates().tolist()

    def _options_for_role(role_code: str, pool: pd.DataFrame, saved: list[str]) -> list[str]:
        mask_role = _safe_bool_mask(_role_mask(pool, role_code), pool.index)
        opts = pool.loc[mask_role, "Name"].dropna().astype(str).drop_duplicates().tolist()
        for name in saved:
            if name and name not in opts and (df_all["Name"].astype(str) == str(name)).any():
                opts.append(str(name))
        return sorted(opts, key=str.casefold)

    if "shortlist_picks" not in st.session_state:
        st.session_state["shortlist_picks"] = {
            ROLE_LABEL_MAP.get(role, role): _defaults_for_role(role) for role in ROLE_ORDER
        }

    st.markdown(
        """
        <style>
        .stApp, .block-container, [data-testid="stSidebar"] {
            font-family: Inter, Aptos, Segoe UI, Arial, sans-serif;
        }
        .shadow-card {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.72);
            border-radius: 18px;
            padding: 14px 16px;
            min-height: 84px;
        }
        .shadow-card .label {
            color: #94a3b8;
            font-size: 0.78rem;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }
        .shadow-card .value {
            color: #f8fafc;
            font-size: 1.55rem;
            font-weight: 760;
            line-height: 1.15;
            margin-top: 4px;
        }
        .shadow-card .note {
            color: #cbd5e1;
            font-size: 0.82rem;
            margin-top: 2px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    picks = st.session_state.get("shortlist_picks", {})
    selected_players = sorted({p for names in picks.values() for p in names if str(p).strip()})
    filled_roles = sum(1 for role in ROLE_DISPLAY_ORDER if picks.get(role))
    status_count = int((df_all["Shortlist Status"].astype(str).str.strip() != "").sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="shadow-card"><div class="label">Selected players</div><div class="value">{len(selected_players)}</div><div class="note">Across all roles</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="shadow-card"><div class="label">Filled roles</div><div class="value">{filled_roles} / {len(ROLE_ORDER)}</div><div class="note">Role coverage</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="shadow-card"><div class="label">Status tagged</div><div class="value">{status_count}</div><div class="note">In the full database</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="shadow-card"><div class="label">Database rows</div><div class="value">{len(df_all)}</div><div class="note">Loaded from active file</div></div>', unsafe_allow_html=True)

    with st.expander("Filters for player selection", expanded=True):
        colf1, colf2, colf3, colf4 = st.columns([2, 1.3, 1.1, 2])
        with colf1:
            name_q = st.text_input("Search name", key="shortlist_search_name")
        with colf2:
            min_pr = st.slider("Min Potential Rating", 0.0, 4.0, 3.0, 0.5, key="shortlist_min_pr")
        with colf3:
            max_age = st.number_input("Max age", min_value=14, max_value=40, value=28, step=1, key="shortlist_max_age")
        with colf4:
            nation_filter = st.text_input("Playing Nation filter", key="shortlist_nation_filter")

    pool_df = df_all.copy()
    if name_q:
        pool_df = pool_df[pool_df["Name"].astype(str).str.contains(name_q, case=False, na=False)]
    if nation_filter.strip() and "Playing Nation" in pool_df.columns:
        pool_df = pool_df[pool_df["Playing Nation"].astype(str).str.contains(nation_filter, case=False, na=False)]

    pool_df["__PR"] = pd.to_numeric(pool_df.get("Potential Rating (1-4)", 0), errors="coerce").fillna(0.0)
    pool_df["__CR"] = pd.to_numeric(pool_df.get("Current Rating (1-4)", 0), errors="coerce").fillna(0.0)
    pool_df["__AGE"] = pd.to_numeric(pool_df.get("Age", None), errors="coerce")
    pool_df = pool_df[(pool_df["__PR"] >= float(min_pr)) & ((pool_df["__AGE"].isna()) | (pool_df["__AGE"] <= int(max_age)))]
    pool_df = pool_df.sort_values(["__PR", "__CR", "__AGE"], ascending=[False, False, True])

    def _build_shortlist_table() -> pd.DataFrame:
        rows = []
        current_picks = st.session_state.get("shortlist_picks", {})
        for role in ROLE_ORDER:
            label = ROLE_LABEL_MAP.get(role, role)
            for rank, player_name in enumerate(current_picks.get(label, []), start=1):
                rec = _row_for_player(player_name)
                on_loan = str(rec.get("On loan", "")).strip().lower() in {"yes", "true", "1"}
                if on_loan:
                    club_txt = f"{_safe_text(rec.get('Loan Club', ''))} loan to {_safe_text(rec.get('Parent Club', ''))}".strip()
                else:
                    club_txt = _safe_text(rec.get("Player Current Team", ""))

                rows.append({
                    "Pos.": role,
                    "Rank": rank,
                    "Player Name": player_name,
                    "Status": _safe_text(rec.get("Shortlist Status", "")),
                    "Age (D.O.B)": f"{_safe_text(rec.get('Age', ''))} ({_safe_text(rec.get('DOB', ''))})",
                    "Pref. Foot (R/L)": _safe_text(rec.get("Dominant Foot", "")),
                    "Club (Loan Club)": club_txt,
                    "Transfer Fee (€)": _safe_text(rec.get("TM Value", "")),
                    "Current Salary (€)": _safe_text(rec.get("Current Salary", "")),
                    "Contract Expiry (MM/YYYY)": _safe_text(rec.get("Contract Until", "")),
                    "Agent / Agency Name": _safe_text(rec.get("Agency", "")),
                    "Agent Contact Number": "",
                    "Spoken to agent? (Y/N)": "",
                })
        return pd.DataFrame(rows)

    def _render_pitch_board(max_names: int = 4) -> bytes:
        plt.rcParams.update({
            "font.family": "DejaVu Sans",
            "axes.unicode_minus": False,
        })
        pitch = Pitch(
            pitch_type="statsbomb",
            pitch_color="#07111f",
            line_color="#cbd5e1",
            linewidth=1.55,
            goal_type="box",
            pad_left=3,
            pad_right=3,
            pad_top=3,
            pad_bottom=3,
        )
        fig, ax = pitch.draw(figsize=(15.8, 10.2), constrained_layout=True)
        fig.set_facecolor("#07111f")
        ax.set_facecolor("#07111f")

        ax.text(60, -3.5, "FCM Shadow Team", ha="center", va="center", fontsize=19, fontweight="bold", color="#f8fafc")
        ax.text(60, 83.2, "Ranked by role profile. Colour strip shows shortlist status.", ha="center", va="center", fontsize=10.5, color="#cbd5e1")

        current_picks = st.session_state.get("shortlist_picks", {})

        def _card(ax_obj, label: str, x: float, y: float, names: list[str]) -> None:
            shown = [str(n) for n in names[:max_names] if str(n).strip()]
            hidden_count = max(0, len(names) - len(shown))
            line_count = max(1, len(shown)) + (1 if hidden_count else 0)
            width = 23.0
            height = 7.6 + (line_count * 4.6)
            left = max(1.5, min(120.0 - width - 1.5, x - width / 2.0))
            top = max(1.5, min(80.0 - height - 1.5, y - height / 2.0))

            box = FancyBboxPatch(
                (left, top),
                width,
                height,
                boxstyle="round,pad=0.45,rounding_size=1.8",
                linewidth=1.1,
                edgecolor="#334155",
                facecolor="#0f172a",
                alpha=0.93,
                zorder=5,
            )
            ax_obj.add_patch(box)
            ax_obj.text(left + 1.3, top + 3.0, label, ha="left", va="center", fontsize=7.8, fontweight="bold", color="#e2e8f0", zorder=6)

            if not shown:
                ax_obj.text(left + 1.3, top + 7.0, "No player selected", ha="left", va="center", fontsize=6.9, color="#64748b", zorder=6)
                return

            y_text = top + 7.2
            for idx, name in enumerate(shown, start=1):
                status = _status_for_player(name)
                colour = STATUS_COLOUR_MAP.get(status, "#e5e7eb")
                ax_obj.add_patch(
                    FancyBboxPatch(
                        (left + 1.15, y_text - 1.45),
                        1.25,
                        2.9,
                        boxstyle="round,pad=0.05,rounding_size=0.35",
                        linewidth=0,
                        facecolor=colour,
                        alpha=1.0,
                        zorder=7,
                    )
                )
                display_name = name if len(name) <= 20 else f"{name[:18]}…"
                ax_obj.text(left + 3.0, y_text, f"{idx}. {display_name}", ha="left", va="center", fontsize=6.85, color="#f8fafc", zorder=7)
                y_text += 4.6

            if hidden_count:
                ax_obj.text(left + 3.0, y_text, f"+ {hidden_count} more", ha="left", va="center", fontsize=6.7, color="#94a3b8", zorder=7)

        for label in ROLE_DISPLAY_ORDER:
            if label not in ROLE_COORDS:
                continue
            _card(ax, label, ROLE_COORDS[label][0], ROLE_COORDS[label][1], current_picks.get(label, []))

        legend_x = 2.0
        legend_y = 82.0
        ax.text(legend_x, legend_y, "Status:", ha="left", va="center", fontsize=8.4, color="#cbd5e1", fontweight="bold")
        lx = legend_x + 9.0
        for status in ["Green", "Purple", "Red", "Blue", "Grey"]:
            colour = STATUS_COLOUR_MAP.get(status, "#e5e7eb")
            ax.scatter(lx, legend_y, s=36, color=colour, zorder=8)
            ax.text(lx + 1.6, legend_y, status, ha="left", va="center", fontsize=7.8, color="#cbd5e1")
            lx += 13.2

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=220, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    tab_pitch, tab_select, tab_table = st.tabs(["Pitch Board", "Selection and Status", "Summary and Export"])

    with tab_pitch:
        top_left, top_right = st.columns([1, 3])
        with top_left:
            players_on_pitch = st.slider("Players shown per role", min_value=3, max_value=8, value=4, step=1, key="shortlist_pitch_max_names")
        with top_right:
            st.caption("This visual is built from the saved selections. Use the Selection and Status tab to change the board, then save.")

        pitch_png = _render_pitch_board(max_names=int(players_on_pitch))
        st.image(pitch_png, caption="Shortlist Board", use_container_width=True)
        st.download_button("Download pitch board PNG", data=pitch_png, file_name="shortlist_board.png", mime="image/png", key="shortlist_pitch_png_download")

    with tab_select:
        st.caption("Pick players by role. Existing selected players stay available even when the filters are changed, so you do not lose the board accidentally.")

        with st.form("shortlist_form"):
            new_picks = {}
            for role in ROLE_ORDER:
                label = ROLE_LABEL_MAP.get(role, role)
                saved = st.session_state.get("shortlist_picks", {}).get(label, [])
                opts = _options_for_role(role, pool_df, saved)
                default_vals = [p for p in saved if p in opts]
                sel = st.multiselect(
                    f"{label} (max 20)",
                    options=opts,
                    default=default_vals,
                    max_selections=20,
                    key=f"shortlist_sel_{role}",
                )
                new_picks[label] = sel

            st.markdown("**Shortlist Status**")
            status_options = ["", "Green", "Purple", "Red", "Blue", "Grey"]
            selected_names = sorted({p for names in new_picks.values() for p in names if str(p).strip()}, key=str.casefold)
            color_inputs = {}

            if not selected_names:
                st.info("No players selected yet.")
            else:
                status_cols = st.columns(2)
                for i, name in enumerate(selected_names):
                    cur_val = _status_for_player(name)
                    idx = status_options.index(cur_val) if cur_val in status_options else 0
                    with status_cols[i % 2]:
                        color_inputs[name] = st.selectbox(
                            name,
                            status_options,
                            index=idx,
                            key=f"shortlist_status_{re.sub(r'[^A-Za-z0-9_]+', '_', name)}",
                        )

            saved = st.form_submit_button("Save board", use_container_width=True)
            if saved:
                st.session_state["shortlist_picks"] = new_picks

                df_full = load_db(st.session_state.db_csv).copy()
                if "Shortlist Status" not in df_full.columns:
                    df_full["Shortlist Status"] = ""

                for name, status in color_inputs.items():
                    mask = df_full["Name"].astype(str).str.casefold() == str(name).casefold()
                    df_full.loc[mask, "Shortlist Status"] = str(status).strip()

                try:
                    import shutil
                    import datetime
                    src = str(st.session_state.db_csv)
                    backup_path = src.replace(".csv", f"_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
                    if os.path.exists(src):
                        shutil.copy(src, backup_path)
                except Exception:
                    pass

                log_df_identity("About to save", df_full)
                safe_write_db(st.session_state.db_csv, df_full)
                st.success("Shortlist board saved to database.")
                st.cache_data.clear()
                st.rerun()

        st.markdown("---")
        st.subheader("Import Shortlist Board from file")
        imp_file = st.file_uploader(
            "Upload exported shortlist board Excel or CSV",
            type=["xlsx", "csv"],
            key="shortlist_import_file",
        )

        if imp_file is not None and st.button("Apply import", key="shortlist_import_button"):
            try:
                if imp_file.name.lower().endswith(".csv"):
                    imp_df = pd.read_csv(imp_file, dtype=str, keep_default_na=False)
                else:
                    imp_df = pd.read_excel(imp_file, dtype=str).fillna("")

                required_cols = {"Pos.", "Rank", "Player Name"}
                if not required_cols.issubset(set(imp_df.columns)):
                    st.error("Import file must contain Pos., Rank and Player Name columns. Use the export from this page as the template.")
                else:
                    imp_df = imp_df.copy()
                    imp_df["Pos."] = imp_df["Pos."].astype(str).str.strip()
                    imp_df["Player Name"] = imp_df["Player Name"].astype(str).str.strip()
                    imp_df["Rank"] = pd.to_numeric(imp_df["Rank"], errors="coerce")

                    new_picks = {ROLE_LABEL_MAP.get(role, role): [] for role in ROLE_ORDER}
                    for role in ROLE_ORDER:
                        label = ROLE_LABEL_MAP.get(role, role)
                        sub = imp_df[imp_df["Pos."].str.casefold() == str(role).casefold()].copy()
                        sub = sub.dropna(subset=["Rank"]).sort_values("Rank")
                        new_picks[label] = sub["Player Name"].dropna().astype(str).tolist()

                    st.session_state["shortlist_picks"] = new_picks

                    df_full = load_db(st.session_state.db_csv).copy()
                    if "Shortlist Status" not in df_full.columns:
                        df_full["Shortlist Status"] = ""
                    imported_names = set(imp_df["Player Name"].dropna().astype(str).tolist())
                    for name in imported_names:
                        mask = df_full["Name"].astype(str).str.casefold() == str(name).casefold()
                        blank = df_full.loc[mask, "Shortlist Status"].astype(str).str.strip() == ""
                        if mask.any():
                            df_full.loc[mask[mask].index[blank.values], "Shortlist Status"] = "Green"

                    safe_write_db(st.session_state.db_csv, df_full)
                    st.success("Shortlist Board imported. The pitch and summary now reflect the file.")
                    st.cache_data.clear()
                    st.rerun()

            except Exception as e:
                st.error(f"Import failed: {e}")

    with tab_table:
        st.caption("Shows only the selected players, ordered by role and rank.")
        tbl = _build_shortlist_table()

        if tbl.empty:
            st.info("No players selected yet. Pick players in the Selection and Status tab and click Save board.")
        else:
            display_cols = [
                "Pos.",
                "Rank",
                "Player Name",
                "Status",
                "Age (D.O.B)",
                "Pref. Foot (R/L)",
                "Club (Loan Club)",
                "Transfer Fee (€)",
                "Current Salary (€)",
                "Contract Expiry (MM/YYYY)",
                "Agent / Agency Name",
                "Agent Contact Number",
                "Spoken to agent? (Y/N)",
            ]
            tbl = tbl[display_cols]
            st.dataframe(tbl, use_container_width=True, hide_index=True, height=460)

            col_dl1, col_dl2 = st.columns(2)
            col_dl1.download_button(
                "Download shortlist CSV",
                data=tbl.to_csv(index=False).encode("utf-8-sig"),
                file_name="shortlist_board.csv",
                mime="text/csv",
                key="shortlist_tbl_csv",
            )

            try:
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
                    tbl.to_excel(writer, index=False, sheet_name="Shortlist Board")
                col_dl2.download_button(
                    "Download shortlist Excel",
                    data=out.getvalue(),
                    file_name="shortlist_board.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="shortlist_tbl_xlsx",
                )
            except Exception:
                st.caption("Install xlsxwriter for Excel export. CSV export always works.")