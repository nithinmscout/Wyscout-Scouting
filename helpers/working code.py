# helpers/transfermarkt_lineups.py

from __future__ import annotations
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, Optional


@dataclass
class LineupPlayer:
    side: str             # "Home" or "Away"
    team: str             # team label as shown by TM
    shirt: str            # jersey number
    name_short: str       # short name from the lineup
    tm_profile_url: str   # absolute URL


def _abs_tm(url: str) -> str:
    return url if url.startswith("http") else "https://www.transfermarkt.com" + url


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""

def _parse_shirt_from_node(node) -> str:
    """
    Robust jersey parse across TM variants:
    1) numbers inside small spans near the anchor
    2) bubble titles and aria-labels
    3) text fragments like '#19', '19.' or '(19)'
    """
    # Close-by spans commonly hold the number
    num = ""
    for sel in ["span.rn_nummer", "span.sb-nummer", "span.trikotnummer",
                ".aufstellung-spieler .rn_nummer", ".sb-sporty-number"]:
        s = node.select_one(sel)
        if s and s.text.strip().isdigit():
            return s.text.strip()

    # Look up one parent container for any digit-only small span
    parent = node.find_parent(lambda t: t and t.name in ["li","div","span"])
    if parent:
        for s in parent.select("span, small, div"):
            t = (s.text or "").strip()
            if re.fullmatch(r"\d{1,3}", t):
                return t

    # aria-label or title
    for attr in ["title", "aria-label"]:
        val = (node.get(attr) or "").strip()
        m = re.search(r"\b(\d{1,3})\b", val)
        if m:
            return m.group(1)

    # text around the anchor
    label = _text(node.find_parent(lambda t: t and t.name in ["li","div","span"])) or _text(node)
    m = re.search(r"(?:#|\()?\s*(\d{1,3})(?:\)|\b)", label)
    return m.group(1) if m else ""

def _find_lineup_blocks(soup) -> List:
    """
    Return the two lineup containers from a TM match report page.
    We cover several historical variants.
    """
    blocks: List = []

    # 1) Canonical modern formations
    blocks.extend(soup.select("div.sb-formation, div.sb-formation__content, div.sb-aufstellung"))

    # 2) Column wrappers that contain formations
    if not blocks:
        for col in soup.select("div.large-6, div.large-7, div.grid, section"):
            if col.select_one("div.sb-formation, div.sb-formation__content, div.sb-aufstellung"):
                blocks.append(col)

    # 3) Boxes that clearly include many player profile links
    if not blocks:
        candidates = [c for c in soup.select("div.box, div.container, div")
                      if len(c.select("a[href*='/profil/spieler/']")) >= 10]
        if candidates:
            # Prefer the two heaviest containers
            candidates.sort(key=lambda c: len(c.select("a[href*='/profil/spieler/']")), reverse=True)
            blocks = candidates[:2]

    # Deduplicate and keep at most two
    uniq, seen = [], set()
    for b in blocks:
        key = id(b)
        if key not in seen:
            seen.add(key)
            uniq.append(b)
    return uniq[:2]


def _make_tm_session() -> requests.Session:
    """
    A session with realistic headers and language cookies so TM serves the full HTML.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    # Warm up cookies from homepage to avoid consent/minimal pages
    try:
        s.get("https://www.transfermarkt.com", timeout=15)
        # Hint English preference
        s.cookies.set("tmPreferedLanguage", "en", domain=".transfermarkt.com")
    except Exception:
        pass
    return s


def _fallback_current_team_from_profile_html(soup:BeautifulSoup) -> str:
    """
    Hard fallback to read 'Current club' on player profile pages.
    Works for senior and youth squads.
    """
    # Info table row
    row = None
    for th in soup.select("table.info-table th"):
        if "Current club" in _text(th):
            row = th.find_parent("tr")
            break
    if row:
        a = row.select_one("td a[href*='/verein/']")
        if a: return _text(a)

    # Player header area sometimes lists the club badge link
    a = soup.select_one(".data-header__club a[href*='/verein/'], .dataHeader__box a[href*='/verein/']")
    if a: return _text(a)

    # Any visible club link in the top-area boxes
    a = soup.select_one("a[data-vereinid]")
    if a: return _text(a)

    return ""

def _lineup_blocks_with_side(soup, home_name:str, away_name:str,
                             home_id:Optional[str], away_id:Optional[str]) -> List[Tuple[str,str,object]]:
    """
    Find the two lineup containers and label them with side and team.
    Returns list of (side, team_name, block)
    """
    blocks = []
    # Formation containers
    for div in soup.select("div.sb-formation, div.sb-formation__content, div.sb-aufstellung"):
        if div.find("a", href=re.compile(r"/profil/spieler/")):
            blocks.append(div)

    # If many, keep the first two with the most player links
    blocks = sorted(blocks, key=lambda b: len(b.select("a[href*='/profil/spieler/']")), reverse=True)[:2]

    labelled = []

    for b in blocks:
        cls = " ".join(b.get("class", []))
        side = ""
        if re.search(r"heim|home", cls, re.I):
            side = "Home"
        if re.search(r"gast|away", cls, re.I):
            side = "Away"

        # Team label by nearest team name header
        team_label = ""
        header = b.find_previous(lambda t: t.name in ["h2","h3","h4"] and "line" in _text(t).lower())
        if header:
            m = re.search(r"\|\s*(.+)$", _text(header))
            team_label = m.group(1).strip() if m else ""

        # Fallback: look for a club link near the block
        if not team_label:
            a = b.find_previous("a", href=re.compile(r"/verein/"))
            team_label = _text(a) if a else ""

        # If we got IDs, try to decide side via nearest club id in DOM
        if not side and (home_id or away_id):
            near = b.find_previous("a", href=re.compile(r"/verein/(\d+)"))
            if near:
                m = re.search(r"/verein/(\d+)", near.get("href",""))
                if m:
                    side = "Home" if m.group(1) == home_id else "Away" if m.group(1) == away_id else ""

        labelled.append((side, team_label, b))

    # If still unlabelled, enforce index order
    if len(labelled) == 2:
        if not labelled[0][0]: labelled[0] = ("Home", labelled[0][1] or home_name, labelled[0][2])
        if not labelled[1][0]: labelled[1] = ("Away", labelled[1][1] or away_name, labelled[1][2])

    # Fill team names from header if missing
    labelled = [
        (side, team or (home_name if side=="Home" else away_name), block)
        for side, team, block in labelled
    ]
    return labelled

def _team_name_from_block(block) -> str:
    title = block.find_previous(lambda tag: tag.name in ["h2", "h3", "h4"]
                                and "line" in _text(tag).lower())
    if title:
        m = re.search(r"\|\s*(.+)$", _text(title))
        if m:
            return m.group(1).strip()
    h = block.find(lambda tag: tag.name in ["h2", "h3", "h4"])
    if h and _text(h):
        return _text(h)
    return ""

def _parse_home_away_names_and_ids(soup) -> Tuple[str,str,Optional[str],Optional[str]]:
    """
    Returns (home_name, away_name, home_id, away_id). IDs are TM club IDs when available.
    """
    home = away = None
    home_id = away_id = None

    # Current layout
    h = soup.select_one(".sb-vereinsname--heim")
    g = soup.select_one(".sb-vereinsname--gast")
    if h: home = _text(h)
    if g: away = _text(g)

    # Pull IDs if present
    ha = soup.select_one(".sb-vereinsname--heim a[href*='/verein/']")
    ga = soup.select_one(".sb-vereinsname--gast a[href*='/verein/']")
    if ha:
        m = re.search(r"/verein/(\d+)", ha.get("href",""))
        if m: home_id = m.group(1)
    if ga:
        m = re.search(r"/verein/(\d+)", ga.get("href",""))
        if m: away_id = m.group(1)

    # Older header variants
    if not home or not away:
        team_links = soup.select("a[href*='/verein/']")
        uniq = []
        for a in team_links:
            m = re.search(r"/verein/(\d+)", a.get("href",""))
            name = _text(a)
            if m and name and all(m.group(1)!=x[1] for x in uniq):
                uniq.append((name, m.group(1)))
            if len(uniq) >= 2: break
        if len(uniq) >= 2:
            if not home: home = uniq[0][0]
            if not away: away = uniq[1][0]
            if not home_id: home_id = uniq[0][1]
            if not away_id: away_id = uniq[1][1]

    return home or "", away or "", home_id, away_id

def _extract_players_from_block(block, side:str, team_label:str) -> List[LineupPlayer]:
    players: List[LineupPlayer] = []
    for a in block.select("a[href*='/profil/spieler/']"):
        name_short = _text(a)
        if not name_short:
            continue
        href = _abs_tm(a.get("href",""))
        shirt = _parse_shirt_from_node(a)
        players.append(LineupPlayer(side=side, team=team_label, shirt=shirt,
                                    name_short=name_short, tm_profile_url=href))
    # de-dup by profile
    seen, unique = set(), []
    for p in players:
        if p.tm_profile_url not in seen:
            seen.add(p.tm_profile_url)
            unique.append(p)
    return unique

def fetch_match_lineups(
    url: str,
    pause_seconds: float,
    get_player_info: Callable[[str], Dict],
    normalize_player: Callable[[str], Dict],
    *,
    logger: Optional[Callable[[str], None]] = None
) -> pd.DataFrame:
    """
    Returns DataFrame:
      Side, Team, Shirt, Name short, Full name, DOB, Current team, TM Profile
    """
    def log(msg: str) -> None:
        if logger: 
            try: logger(msg)
            except Exception: 
                pass

    sess = _make_tm_session()

    def _fetch(u: str) -> BeautifulSoup:
        r = sess.get(u, timeout=25)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")

    soup = _fetch(url)
    home_name, away_name, home_id, away_id = _parse_home_away_names_and_ids(soup)
    blocks = _find_lineup_blocks(soup)

    # If nothing found, try the explicit "lineups" view
    if not blocks:
        alt = url if "aufstellung" in url else (url.rstrip("/") + "?view=aufstellung")
        log("No lineup blocks found. Retrying with ?view=aufstellung")
        soup = _fetch(alt)
        home_name, away_name, home_id, away_id = _parse_home_away_names_and_ids(soup)
        blocks = _find_lineup_blocks(soup)

    if not blocks:
        log("Still no lineup blocks after retry. Returning empty DataFrame.")
        return pd.DataFrame()

    labelled_blocks = _lineup_blocks_with_side(soup, home_name, away_name, home_id, away_id)
    if not labelled_blocks:
        # Fall back to simple ordering
        labelled_blocks = []
        for idx, b in enumerate(blocks[:2]):
            side = "Home" if idx == 0 else "Away"
            team = home_name if idx == 0 else away_name
            labelled_blocks.append((side, team, b))

    all_players: List[LineupPlayer] = []
    for side, team_label, block in labelled_blocks:
        all_players.extend(_extract_players_from_block(block, side, team_label))

    rows = []
    for i, p in enumerate(all_players, start=1):
        if i > 1 and pause_seconds > 0:
            time.sleep(pause_seconds)

        full_name = dob = current_team = ""

        # Normalised first
        # 1) Your normalised mapping first
        try:
            norm = normalize_player(p.tm_profile_url) or {}
            if isinstance(norm, tuple):
                mapped = norm[0] or {}
            else:
                mapped = norm
            full_name = mapped.get("Name", "") or full_name
            dob = mapped.get("DOB", "") or dob
            current_team = mapped.get("Player Current Team", "") or current_team
        except Exception as e:
            log(f"normalize_player failed for {p.tm_profile_url}: {e}")


        # Raw helper next
        if not full_name or not dob or not current_team:
            try:
                raw = get_player_info(p.tm_profile_url) or {}
                full_name = full_name or raw.get("player_name","") or ""
                dob = dob or raw.get("date_of_birth","") or ""
                current_team = current_team or raw.get("current_club","") or ""
            except Exception as e:
                log(f"get_player_info failed for {p.tm_profile_url}: {e}")

        # Hard fallback for current club
        if not current_team:
            try:
                r2 = sess.get(p.tm_profile_url, timeout=20)
                if r2.ok:
                    psoup = BeautifulSoup(r2.content, "html.parser")
                    current_team = _fallback_current_team_from_profile_html(psoup) or ""
            except Exception as e:
                log(f"fallback current club fetch failed for {p.tm_profile_url}: {e}")

        rows.append({
            "Side": p.side,
            "Team": p.team,
            "Shirt": p.shirt,
            "Name short": p.name_short,
            "Full name": full_name,
            "DOB": dob,
            "Current team": current_team or "NA",
            "TM Profile": p.tm_profile_url
        })

    df = pd.DataFrame(rows).drop_duplicates(subset=["TM Profile"]).reset_index(drop=True)
    df["Shirt_num"] = pd.to_numeric(df["Shirt"], errors="coerce")
    df = df.sort_values(["Side","Team","Shirt_num","Full name"], na_position="last").drop(columns=["Shirt_num"])
    return df