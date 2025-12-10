# streamlit_app.py
# put this at the top of Opta.py, before any other imports
import sys
import asyncio

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import json
import time
from urllib.parse import urlparse, parse_qs

import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright

st.set_page_config(page_title="Opta Analyst Chalkboard Scraper", layout="wide")
st.title("Opta Analyst Chalkboard Scraper")

default_url = "https://theanalyst.com/opta-football-match-centre?competitionId=dm5ka0os1e3dxcp3vh05kmp33&seasonId=dbxs75cag7zyip5re0ppsanmc&matchId=86x27wjaeyld15ukqaidjyxp0"
url = st.text_input("Match Centre URL", value=default_url)

with st.expander("Advanced"):
    ua = st.text_input(
        "User agent",
        value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    wait_after_click = st.number_input("Seconds to wait after clicking Chalkboard", 1, 15, 5)
    headless = st.checkbox("Headless browser", value=True)
    chromium_sandbox = st.checkbox("Enable Chromium sandbox", value=False)
    show_raw = st.checkbox("Show raw JSON packets", value=False)

st.sidebar.header("Browser console")
console_log = st.sidebar.empty()

def parse_ids_from_url(u: str):
    parsed = urlparse(u)
    qs = parse_qs(parsed.query)
    comp = qs.get("competitionId", [None])[0]
    season = qs.get("seasonId", [None])[0]
    match = qs.get("matchId", [None])[0]
    return comp, season, match

def looks_like_event_payload(url: str, content_type: str):
    u = url.lower()
    ct = (content_type or "").lower()
    return (
        "chalk" in u
        or "event" in u
        or "viz" in u
        or "match" in u and "data" in u
        or "json" in ct
        or ct.startswith("application/json")
    )

def normalise_events(obj):
    buckets = []
    if isinstance(obj, dict):
        for k in ["events", "actions", "data", "items", "result", "payload"]:
            if k in obj and isinstance(obj[k], list):
                buckets.append(obj[k])
        for v in obj.values():
            if isinstance(v, dict):
                for k in ["events", "actions", "data", "items"]:
                    if k in v and isinstance(v[k], list):
                        buckets.append(v[k])
    elif isinstance(obj, list):
        buckets.append(obj)

    rows = []
    for arr in buckets:
        for ev in arr:
            if not isinstance(ev, dict):
                continue
            rows.append(
                {
                    "minute": ev.get("minute") or ev.get("min") or ev.get("timeMin"),
                    "second": ev.get("second") or ev.get("sec") or ev.get("timeSec"),
                    "team": ev.get("team") or ev.get("teamName") or ev.get("team_id"),
                    "player": ev.get("player") or ev.get("playerName") or ev.get("participantName"),
                    "event_type": ev.get("type") or ev.get("eventType") or ev.get("name"),
                    "outcome": ev.get("outcome") or ev.get("result") or ev.get("outcomeType"),
                    "x": ev.get("x") or ev.get("startX") or ev.get("posX"),
                    "y": ev.get("y") or ev.get("startY") or ev.get("posY"),
                    "raw": ev,
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    def pick(v, keys):
        if isinstance(v, dict):
            for k in keys:
                if k in v and isinstance(v[k], (str, int, float)):
                    return v[k]
        return v

    df["team"] = df["team"].apply(lambda v: pick(v, ["name", "teamName", "id"]))
    df["player"] = df["player"].apply(lambda v: pick(v, ["name", "playerName", "id"]))

    for c in ["minute", "second", "x", "y"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df

def fetch_packets(match_url, user_agent, wait_seconds, headless, use_sandbox):
    comp, season, match = parse_ids_from_url(match_url)
    if not all([comp, season, match]):
        raise ValueError("URL must include competitionId, seasonId, and matchId")

    captured = []
    console_buffer = []

    with sync_playwright() as p:
        launch_args = {}
        if not use_sandbox:
            launch_args["args"] = ["--no-sandbox", "--disable-setuid-sandbox"]

        browser = p.chromium.launch(headless=headless, **launch_args)
        context = browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1366, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        page = context.new_page()

        def on_console(msg):
            try:
                console_buffer.append(f"{msg.type.upper()}: {msg.text}")
                console_log.write("\n".join(console_buffer[-50:]))
            except Exception:
                pass

        page.on("console", on_console)

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
            except Exception:
                ct = ""
            if looks_like_event_payload(resp.url, ct):
                try:
                    if "application/json" in ct or resp.url.endswith(".json"):
                        data = resp.json()
                        captured.append({"url": resp.url, "status": resp.status, "json": data})
                except Exception:
                    pass

        page.on("response", on_response)

        page.goto(match_url, wait_until="domcontentloaded")

        # Handle cookie banners if present
        selectors_accept = [
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Accept all cookies')",
            "[aria-label='Accept all']",
        ]
        for sel in selectors_accept:
            try:
                page.locator(sel).first.click(timeout=1500)
                time.sleep(0.5)
                break
            except Exception:
                pass

        # Wait for the tab list to render
        try:
            page.wait_for_selector("role=tab", timeout=8000)
        except Exception:
            pass

        # Click the Chalkboard tab
        tab_selectors = [
            "role=tab[name='Chalkboard']",
            "text=Chalkboard",
            "//button[contains(., 'Chalkboard')]",
            "//a[contains(., 'Chalkboard')]",
        ]
        clicked = False
        for sel in tab_selectors:
            try:
                el = page.locator(sel).first
                el.click(timeout=2000)
                clicked = True
                break
            except Exception:
                continue

        # If not clicked, try keyboard navigation across tabs
        if not clicked:
            try:
                first_tab = page.locator("role=tab").first
                first_tab.focus()
                for _ in range(8):
                    page.keyboard.press("ArrowRight")
                    time.sleep(0.2)
                page.keyboard.press("Enter")
                clicked = True
            except Exception:
                pass

        # Give time for network calls
        for _ in range(2):
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            page.mouse.wheel(0, 2000)
            time.sleep(wait_seconds)

        browser.close()

    return captured

def render_events(packets):
    if not packets:
        st.warning("No JSON packets captured. Increase the wait time, ensure the tab loads, or try headful mode.")
        return

    if show_raw:
        for i, pkt in enumerate(packets, 1):
            with st.expander(f"Packet {i}  {pkt['url']}"):
                st.json(pkt["json"])

    frames = []
    for pkt in packets:
        try:
            df = normalise_events(pkt["json"])
            if not df.empty:
                df["source_url"] = pkt["url"]
                frames.append(df)
        except Exception as e:
            st.info(f"Normaliser note on {pkt['url']}: {e}")

    if not frames:
        st.warning("Captured JSON, but could not find event arrays. Open Show raw JSON and look for keys to add in normalise_events.")
        return

    events = pd.concat(frames, ignore_index=True).drop_duplicates()
    st.success(f"Parsed {len(events):,} chalkboard events")

    c1, c2, c3 = st.columns(3)
    with c1:
        pf = st.text_input("Filter player contains", "")
    with c2:
        tf = st.text_input("Filter team contains", "")
    with c3:
        ef = st.text_input("Filter event type contains", "")

    view = events.copy()
    if pf:
        view = view[view["player"].astype(str).str.contains(pf, case=False, na=False)]
    if tf:
        view = view[view["team"].astype(str).str.contains(tf, case=False, na=False)]
    if ef:
        view = view[view["event_type"].astype(str).str.contains(ef, case=False, na=False)]

    cols = [c for c in ["minute", "second", "team", "player", "event_type", "outcome", "x", "y", "source_url"] if c in view.columns]
    st.dataframe(view[cols].sort_values(["minute", "second"], na_position="last"), use_container_width=True)

    st.download_button("Download CSV", view.to_csv(index=False).encode("utf-8"), "chalkboard_events.csv", "text/csv")

if st.button("Fetch Chalkboard"):
    try:
        with st.spinner("Loading Chalkboard and capturing events"):
            packets = fetch_packets(url, ua, wait_after_click, headless, chromium_sandbox)
        render_events(packets)
    except Exception as e:
        st.error("An error occurred. See details below.")
        st.exception(e)
