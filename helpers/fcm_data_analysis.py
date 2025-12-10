# fcm_data_analysis.py

from __future__ import annotations

import os
import io
import csv
import glob
import math
import re as _re
import numpy as np
import plotly.graph_objects as go
import pandas as pd
import streamlit as st
import textwrap
import altair as alt
import streamlit.components.v1 as components
import unicodedata


import matplotlib.pyplot as plt
from reportlab.lib.utils import ImageReader

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm


# will be set by render_data_analysis_page the first time it is called
_COMPUTE_AGE_SERIES_FOR_DA = None
_EXPORT_BUTTONS_FOR_DA = None

# ---------- local helpers that belong only to the data analysis page ----------

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


# Path to your FCM squad stats for this season
FCM_PLAYERS_PATH = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\25 26\FCM_players_25_26.csv"


@st.cache_data(show_spinner=False)
def _load_fcm_players_default() -> pd.DataFrame:
    """
    Default FCM players loader for the search tab.
    Uses the resilient CSV reader so weird encodings do not crash.
    """
    if not os.path.exists(FCM_PLAYERS_PATH):
        return pd.DataFrame()

    try:
        # use the robust loader you already defined above
        df = read_csv_resilient(FCM_PLAYERS_PATH)
        df = df.astype(str).fillna("")
        return df
    except Exception as e:
        st.warning(f"Failed to read FCM players CSV: {e}")
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


def _safe_focus_suf() -> str:
    fid = st.session_state.get("profile_focus_id")
    return str(fid) if fid is not None else "analysis"


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

    out_dir = r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Data Reports"
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


POS_CHOICES = [
    "GK",
    "RB", "RWB", "RCB", "CB", "LCB", "LB", "LWB",
    "DMF", "RDMF", "LDMF", "CMF", "RCMF", "LCMF",
    "AMF", "RAMF", "LAMF",
    "RW", "RWF", "RM",
    "LW", "LWF", "LM",
    "CF", "ST", "SS",
]

FCM_KPI_PACKS: dict[str, list[str]] = {
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
    "Wide forwards": [
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


def _restrict_to_three_nations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only rows from Belgium, Netherlands and France
    based on the '__nation' stamp created in _collect_country_frames.
    """
    if "__nation" not in df.columns:
        return df

    mask = df["__nation"].astype(str).isin(THREE_NATION_FILTER)
    return df[mask].copy()

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


def render_player_comparison_tab(*, nation_dirs: list[str], key_prefix: str = "cmp",) -> None:
    """
    Compare up to 4 players on a radar and a phase-grouped metric table.

    Radar and table values are expressed as percentiles against:
      1. Each player's own league positional peers, or
      2. Denmark tier-1 positional peers (Superliga) if that mode is selected.
    """
    import html
    import re

    # build the combined Wyscout master table from all configured leagues
    master = _build_global_wyscout_master(nation_dirs)
    if master is None or master.empty:
        st.info("No league data available for comparison.")
        return

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
        elif mode == "Denmark 1 positional peers":
            cohort = master.copy()

            # you may already have a more precise DK1 cohort elsewhere;
            # if so, you can drop this block and call that helper here.
            dk_mask = pd.Series(True, index=cohort.index)

            # try to infer Denmark Superliga rows
            if "Nation group" in cohort.columns:
                dk_mask &= cohort["Nation group"].astype(str).str.contains("Denmark", case=False, na=False)

            league_cols = [c for c in ["League", "Competition", "Tournament"] if c in cohort.columns]
            if league_cols:
                # treat anything with "Superliga" in the league name as DK1
                league_str = cohort[league_cols[0]].astype(str)
                dk_mask &= league_str.str.contains("Superliga", case=False, na=False)

            if "Tier" in cohort.columns:
                # keep first tier only where Tier is available
                with pd.option_context("mode.chained_assignment", None):
                    tier_vals = pd.to_numeric(cohort["Tier"], errors="coerce")
                dk_mask &= tier_vals.eq(1).fillna(False)

            cohort = cohort[dk_mask].copy()
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

    pct_mode = st.radio(
        "Percentile reference group",
        options=[
            "Own league positional peers",
            "Denmark 1 positional peers",
        ],
        index=0,
        horizontal=True,
        key=f"{key_prefix}_pct_mode",
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

    id_cols = [c for c in ["Player", "Team", "Position", COL_AGE, "__tier"] if c in view.columns]
    if "__league_key" in view.columns:
        id_cols.insert(2, "__league_key")
    raw_cols = [c for c in show_kpis if c in view.columns]
    out = view[id_cols + raw_cols].copy()
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

    render_analysis_block(
        label=label,
        df_all=df_all,
        key_prefix=key_prefix,
        dea_block=dea_block,
        export_buttons=export_buttons,
        _winsorise=_winsorise,
        _zscore=_zscore,
        metric_direction=metric_direction,
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


    st.title("Data analysis")

    SUF = _safe_focus_suf()

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

    

    # -------------------------------------------------------------------
    # NATION SELECTION PANEL
    # -------------------------------------------------------------------
    nation_names = [os.path.basename(p) for p in nation_dirs]
    tabs = st.tabs(["Leagues", "📈 Graphs","🔍 Search","🆚 Compare"])


    # 1) LEAGUE ANALYSIS TAB
    with tabs[0]:
        st.subheader("League and tier selection")

        div_df = _discover_divisions()
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
                        st.rerun()
            div_options = div_df["__league_key"].sort_values().unique().tolist()

            leagues_col, all_col = st.columns([3, 1])

            with leagues_col:
                sel_divs = st.multiselect(
                    "Select leagues / tiers to analyse",
                    options=div_options,
                    default=[],                    # empty by default
                    key=f"da_leagues_{SUF}",
                )

            with all_col:
                include_all_leagues_da = st.checkbox(
                    "All leagues",
                    value=False,
                    key=f"da_include_all_leagues_{SUF}",
                )

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

                    render_analysis_block(
                        label=label,
                        df_all=df_all,
                        key_prefix=f"multi_{SUF}",
                        dea_block=dea_block,
                        export_buttons=export_buttons,
                        _winsorise=_winsorise,
                        _zscore=_zscore,
                        metric_direction=metric_direction,
                    )
                    
                    # update league search history
                    league_history: list[dict] = st.session_state.get("da_league_history", [])

                    entry = {
                        "sel_divs": list(sel_divs),
                        "include_all_leagues": bool(include_all_leagues_da),
                        "label": label or "League search",
                    }

                    if not league_history or league_history[-1] != entry:
                        league_history.append(entry)
                        # keep only last 5
                        if len(league_history) > 5:
                            league_history = league_history[-5:]
                        st.session_state["da_league_history"] = league_history




    # 2) graphs tab uses all nations
    with tabs[1]:
        st.subheader("Scatter plot across divisions")

        div_df = _discover_divisions()

        # always define frames so later code is safe
        frames: list[pd.DataFrame] = []

        if div_df.empty:
            st.info("No divisions found.")
        else:
            # recent graph searches
            graph_history: list[dict] = st.session_state.get("g_graph_history", [])
            if graph_history:
                st.markdown("#### Recent graph searches")
                for i, item in enumerate(reversed(graph_history)):
                    label = item.get("label", "Previous graph search")
                    if st.button(label, key=f"g_hist_{i}"):
                        # restore previous filters before widgets are created
                        st.session_state[f"co_divs_{SUF}"] = item.get("sel_divs", [])
                        st.session_state[f"g_include_all_leagues_{SUF}"] = item.get(
                            "include_all_leagues", False
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

            leagues_col, all_col = st.columns([3, 1])

            with leagues_col:
                sel_divs = st.multiselect(
                    "Peer Leagues / Tiers for Comparison",
                    options=div_options,
                    default=[],
                    key=f"co_divs_{SUF}",
                )

            with all_col:
                include_all_leagues = st.checkbox(
                    "All leagues",
                    value=False,
                    key=f"g_include_all_leagues_{SUF}",
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
        pcol1, pcol2 = st.columns([2, 1])
        
        

        sel_preset = pcol1.selectbox(
            "Preset (FCM positional profile)",
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
                sel_age_min, sel_age_max = fcol2.slider(
                    "Age",
                    value=(a_min, a_max),
                    min_value=100,
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

        kpG = pcol1.multiselect(
            "KPIs",
            numeric_cols_G,
            default=st.session_state.get("g_kpis", valid_preset_kpis) or valid_preset_kpis,
            max_selections=30,
            key="g_kpis",
        )

        if sel_preset != "— None —":
            if pcol2.button("Apply preset", key="g_apply_preset"):
                st.session_state["g_kpis"] = preset_kpis
                st.experimental_rerun()

                force_positive = st.checkbox(
            "Force positive axes (shift if needed)",
            value=force_positive,
            key="g_pos_axes",
        )

        show_medians = st.checkbox(
            "Show median lines",
            value=show_medians,
            key="g_show_medians",
        )

        show_trend = st.checkbox(
            "Show trend line (OLS)",
            value=show_trend,
            key="g_show_trend",
        )

        pos_all  # keep for preset manager later

        # ---------- scatter and rankings ----------

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
                if minx < 0:
                    dfp[x_col] -= minx
                if miny < 0:
                    dfp[y_col] -= miny

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
                alt.Tooltip("__league_key:N", title="League"),
            ]

            base_scatter = (
                alt.Chart(dfp.reset_index(drop=True))
                .mark_circle(size=70, opacity=0.85)
                .encode(
                    x=alt.X(x_col, type="quantitative"),
                    y=alt.Y(y_col, type="quantitative"),
                    color=alt.Color("__league_key:N", title="League"),
                    tooltip=tooltip_fields,
                )
                .interactive()
            )

            layers = [base_scatter]

            # optional median lines
            if show_medians and not dfp.empty:
                x_med = float(dfp[x_col].median())
                y_med = float(dfp[y_col].median())

                x_rule = (
                    alt.Chart(pd.DataFrame({x_col: [x_med]}))
                    .mark_rule(strokeDash=[4, 4])
                    .encode(
                        x=alt.X(x_col, type="quantitative"),
                    )
                )

                y_rule = (
                    alt.Chart(pd.DataFrame({y_col: [y_med]}))
                    .mark_rule(strokeDash=[4, 4])
                    .encode(
                        y=alt.Y(y_col, type="quantitative"),
                    )
                )

                layers.extend([x_rule, y_rule])

            # optional trend line (OLS)
            if show_trend and not dfp.empty:
                trend = (
                    alt.Chart(dfp.reset_index(drop=True))
                    .transform_regression(x_col, y_col)
                    .mark_line()
                    .encode(
                        x=alt.X(x_col, type="quantitative"),
                        y=alt.Y(y_col, type="quantitative"),
                    )
                )
                layers.append(trend)

            chart = alt.layer(*layers).resolve_scale(color="independent")

            # update graph search history
            graph_history: list[dict] = st.session_state.get("g_graph_history", [])

            entry: dict = {
                "sel_divs": list(sel_divs),
                "include_all_leagues": bool(include_all_leagues),
                "sel_preset": sel_preset,
                "positions": list(sel_positions),
                "mins": (sel_min, sel_max),
                "ages": (sel_age_min, sel_age_max),
                "kpis": list(kpG),
                "x_col": x_col,
                "y_col": y_col,
                "force_positive": bool(st.session_state.get("g_pos_axes", True)),
                "show_medians": bool(st.session_state.get("g_show_medians", False)),
                "show_trend": bool(st.session_state.get("g_show_trend", False)),
            }

            label_parts: list[str] = []
            if include_all_leagues:
                label_parts.append("All leagues")
            elif sel_divs:
                label_parts.append(f"{len(sel_divs)} leagues")

            if sel_preset != "— None —":
                label_parts.append(sel_preset)

            if sel_positions:
                label_parts.append("/".join(sorted(sel_positions)))

            entry["label"] = " | ".join(label_parts) or "Graph search"

            if not graph_history or graph_history[-1] != entry:
                graph_history.append(entry)
                if len(graph_history) > 5:
                    graph_history = graph_history[-5:]
                st.session_state["g_graph_history"] = graph_history


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
                    .agg(
                        {
                            "Age": "first",
                            "__league_key": "first",
                            "__score": "mean",
                            **{k: "first" for k in rank_kpis},
                        }
                    )
                )
                agg = agg.sort_values("__score", ascending=False).reset_index(drop=True)
                agg.insert(0, "Rank", range(1, len(agg) + 1))
                agg = agg.rename(columns={"__score": "Score (z-avg)"})
                st.dataframe(agg, use_container_width=True, hide_index=True)
            else:
                st.info("Pick at least one KPI above to compute rankings.")

        elif len(kpG) > 2:
            st.caption(
                "Select two composite axes. We z-score each KPI, apply weights, then average."
            )
            left, right = st.columns(2)
            x_kpis = left.multiselect("X composite KPIs", kpG, key="g_xk")
            y_kpis = right.multiselect("Y composite KPIs", kpG, key="g_yk")
            w_left = left.text_input(
                "X weights (comma-sep)", key="g_xw", placeholder="1,1,1"
            )
            w_right = right.text_input(
                "Y weights (comma-sep)", key="g_yw", placeholder="1,1,1"
            )

            def _composite(df, cols, w_str):
                if not cols:
                    return pd.Series(index=df.index, dtype=float)
                mat = df[cols].apply(pd.to_numeric, errors="coerce").copy()
                for c in cols:
                    mat[c] = _winsorise(mat[c])
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
                comp = (mat.values * np.array(weights)).sum(axis=1) / sum(weights)
                return pd.Series(comp, index=mat.index)

            if x_kpis and y_kpis:
                mat = dfV.copy()
                dfp = mat[[COL_PLAYER, COL_TEAM, "Age", "__league_key"]].copy()
                dfp["X"] = _composite(mat, x_kpis, w_left)
                dfp["Y"] = _composite(mat, y_kpis, w_right)
                dfp = dfp.dropna(subset=["X", "Y"])

                if force_positive:
                    minx, miny = float(dfp["X"].min()), float(dfp["Y"].min())
                    if minx < 0:
                        dfp["X"] -= minx
                    if miny < 0:
                        dfp["Y"] -= miny

                chart = (
                    alt.Chart(dfp)
                    .mark_circle(size=70, opacity=0.85)
                    .encode(
                        x=alt.X("X", title=f"Composite X ({', '.join(x_kpis)})"),
                        y=alt.Y("Y", title=f"Composite Y ({', '.join(y_kpis)})"),
                        color=alt.Color("__league_key", title="League / Tier"),
                        tooltip=[
                            alt.Tooltip(COL_PLAYER, title="Player"),
                            alt.Tooltip(COL_TEAM, title="Team"),
                            alt.Tooltip("Age", title="Age"),
                            alt.Tooltip("__league_key", title="League/Tier"),
                            alt.Tooltip("X", title="Composite X", format=".3f"),
                            alt.Tooltip("Y", title="Composite Y", format=".3f"),
                        ],
                    )
                    .interactive()
                    .properties(height=520, width="container")
                )
                st.altair_chart(chart, use_container_width=True)

                base = dfV[[COL_PLAYER, COL_TEAM, "Age", "__league_key"] + kpG].copy()
                for c in kpG:
                    base[c] = pd.to_numeric(base[c], errors="coerce")
                Z = base[kpG].apply(_winsorise).apply(_zscore)
                base["Score (z-avg)"] = np.nanmean(Z.values, axis=1)
                base["Rank"] = base["Score (z-avg)"].rank(ascending=False, method="min")
                cols = [
                    "Rank",
                    COL_PLAYER,
                    COL_TEAM,
                    "Age",
                    "__league_key",
                    "Score (z-avg)",
                ] + kpG
                st.markdown("#### Top scorers (by chosen KPIs)")
                st.dataframe(
                    base.sort_values("Rank").head(100)[cols],
                    use_container_width=True,
                    hide_index=True,
                )
                export_buttons(base.sort_values("Rank")[cols], key_suf="_graph_multi")
            else:
                st.info("Pick at least one KPI for X and one for Y.")
        else:
            st.info("Pick 2 KPIs for a simple scatter, or more than 2 to build weighted composites.")

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
                    st.experimental_rerun()

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
    
    with tabs[2]:
        render_player_search_tab(
            nation_dirs=nation_dirs,              # ← use the list, not the function
            compute_age_series=compute_age_series,
            _load_presets=_load_presets,
            _parse_list=_parse_list,
            _sanitize_defaults=_sanitize_defaults,
        )

    with tabs[3]:
        render_player_comparison_tab(
            nation_dirs=nation_dirs,
        )

        
def render_player_search_tab(
    *,
    nation_dirs: list[str],
    compute_age_series,
    _load_presets,
    _parse_list,
    _sanitize_defaults,
) -> None:
    """
    Search a single player across the global Wyscout master and show:
      - cohort comparison vs league
      - FCM cohort comparison
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

    # If a similarity section or back button requested a jump,
    # set the selectbox value *before* the widget is created.
    goto_name = st.session_state.pop("goto_player_name", None)
    if goto_name and goto_name in player_labels:
        st.session_state["search_player_name"] = goto_name

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

    # ---------------- FCM comparison cohort ----------------

    fcm_df = _load_fcm_players_default()
    if not fcm_df.empty:
        # normalise column names a bit
        fcm_cols_lower = {c.lower(): c for c in fcm_df.columns}
        fcm_player_col = fcm_cols_lower.get("player", next(iter(fcm_df.columns)))
        fcm_team_col   = fcm_cols_lower.get("team", fcm_cols_lower.get("club", fcm_player_col))
        fcm_pos_col    = fcm_cols_lower.get("position", fcm_cols_lower.get("pos", None))

        if fcm_pos_col is not None and sel_role != "All":
            fcm_pos_series = fcm_df[fcm_pos_col].astype(str).str.upper()
            fcm_mask = fcm_pos_series.str.contains(rf"\b{_re.escape(sel_role.upper())}\b", regex=True)
            fcm_cohort = fcm_df[fcm_mask].copy()
        else:
            fcm_cohort = fcm_df.copy()
    else:
        fcm_cohort = pd.DataFrame()

    st.markdown("### Secondary comparison")

    compare_mode = st.radio(
        "Comparison reference",
        ["FCM player", "Denmark 1 positional peers"],
        index=0,
        horizontal=True,
        key="search_compare_mode",
    )

    selected_fcm_player = None
    dk1_cohort = pd.DataFrame()

    if compare_mode == "FCM player":
        if fcm_cohort.empty:
            st.caption("No FCM positional cohort found in the FCM players CSV.")
        else:
            fcm_names = (
                fcm_cohort[fcm_player_col]
                .dropna()
                .astype(str)
                .sort_values()
                .unique()
                .tolist()
            )
            selected_fcm_player = st.selectbox(
                "FCM player to compare with",
                options=[""] + fcm_names,
                index=0,
                key="search_fcm_player_name",
            )
    elif compare_mode == "Denmark 1 positional peers":
        # Denmark · T1 positional cohort
        dk1_keys = [
            k for k in all_leagues
            if "Denmark" in k and ("T1" in k or "· T1" in k)
        ]
        dk1_cohort = master[master["__league_key"].isin(dk1_keys)].copy()
        if sel_role != "All" and COL_POS in dk1_cohort.columns:
            s_dk = dk1_cohort[COL_POS].astype(str).str.upper()
            m_dk = s_dk.str.contains(rf"\b{_re.escape(sel_role.upper())}\b", regex=True)
            dk1_cohort = dk1_cohort[m_dk]

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
        "Preset (FCM positional profile)",
        options=preset_names,
        key="search_preset",
    )

    preset_kpis: list[str] = []
    if sel_preset != "— None —":
        prow = presets_df[presets_df["Profile"] == sel_preset]
        if not prow.empty:
            preset_kpis = _parse_list(prow.iloc[0].get("KPIs", ""))

        # Fallback to hard-coded KPI packs if CSV is missing / messy
        if not preset_kpis and sel_preset in FCM_KPI_PACKS:
            preset_kpis = FCM_KPI_PACKS[sel_preset][:]


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

        if compare_mode == "FCM player" and selected_fcm_player and not fcm_cohort.empty:
            ref_row = fcm_cohort[fcm_cohort[fcm_player_col].astype(str) == selected_fcm_player]
            if not ref_row.empty and m in fcm_cohort.columns:
                ref_val = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")
                secondary_pcts[m] = _percentile_rank(fcm_cohort[m], ref_val)
                secondary_label = f"FCM: {selected_fcm_player}"
            else:
                secondary_pcts[m] = float("nan")

        elif compare_mode == "Denmark 1 positional peers" and not dk1_cohort.empty and m in dk1_cohort.columns:
            secondary_pcts[m] = _percentile_rank(dk1_cohort[m], raw_val)
            secondary_label = "Denmark T1 positional peers"
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
        if not fcm_cohort.empty:
            st.metric("FCM cohort size", len(fcm_cohort))

        if not fcm_cohort.empty:
            st.markdown("#### FCM players in this role")
            cols_to_show = [c for c in ["Player", "Team", "Position", "Age", "Minutes played"] if c in fcm_cohort.columns]
            if cols_to_show:
                st.dataframe(
                    fcm_cohort[cols_to_show]
                    .drop_duplicates()
                    .sort_values("Player"),
                    use_container_width=True,
                    hide_index=True,
                )
      
        if compare_mode == "FCM player" and selected_fcm_player and not fcm_cohort.empty:
            ref_row = fcm_cohort[fcm_cohort["Player"].astype(str) == selected_fcm_player]
            if not ref_row.empty:
                st.markdown("#### Raw KPI comparison (FM-style)")

                fcm_vals: dict[str, float] = {}
                for m in sel_kpis:
                    fcm_vals[m] = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")

                # Wide table: one row per metric, two value columns with bars
                comp_records = []
                for m in sel_kpis:
                    comp_records.append(
                        {
                            "Metric": m,
                            sel_player: player_vals.get(m, np.nan),
                            selected_fcm_player: fcm_vals.get(m, np.nan),
                        }
                    )

                comp_df = pd.DataFrame(comp_records)
                for col in [sel_player, selected_fcm_player]:
                    comp_df[col] = pd.to_numeric(comp_df[col], errors="coerce")

                st.dataframe(
                    comp_df.set_index("Metric")
                        .style.format("{:.2f}")
                        .bar(subset=[sel_player, selected_fcm_player], axis=1),
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

        # Secondary polygon: FCM player or DK T1 cohort
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
        if compare_mode == "FCM player" and selected_fcm_player and not fcm_cohort.empty:
            ref_row = fcm_cohort[fcm_cohort[fcm_player_col].astype(str) == selected_fcm_player]
            if not ref_row.empty and m in fcm_cohort.columns:
                ref_val = pd.to_numeric(ref_row.iloc[0].get(m, np.nan), errors="coerce")
                secondary_pcts[m] = _percentile_rank(fcm_cohort[m], ref_val)
                secondary_label = f"FCM: {selected_fcm_player}"
            else:
                secondary_pcts[m] = float("nan")
        elif compare_mode == "Denmark 1 positional peers" and not dk1_cohort.empty and m in dk1_cohort.columns:
            secondary_pcts[m] = _percentile_rank(dk1_cohort[m], raw_val)
            secondary_label = "Denmark T1 positional peers"
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

                feat_cols = sim_kpis
                feats = (
                    pool_group[feat_cols]
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                    .values
                )
                target_vec = (
                    pd.to_numeric(target_row[feat_cols], errors="coerce")
                    .fillna(0.0)
                    .values
                )
                

                tv_norm = np.linalg.norm(target_vec)
                if tv_norm == 0.0 or feats.size == 0:
                    st.caption("Not enough numeric variation to compute similarity.")
                else:
                    denom = np.linalg.norm(feats, axis=1) * tv_norm + 1e-9
                    sims = (feats @ target_vec) / denom

                    pool_group["Similarity"] = sims
                    pool_group["Similarity"] = pool_group["Similarity"].round(3)

                    # Keep a copy for later (export etc.)
                    sim_all = pool_group.copy()

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
                r"G:\My Drive\FC Midtjlland\Databases\FCM Scouting\Data Reports"
            )
        except Exception as e:
            st.error(f"Failed to export PDF: {e}")

