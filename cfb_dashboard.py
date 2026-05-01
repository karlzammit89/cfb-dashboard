"""
CFB Dashboard
=============
Schedule grid  → ESPN public API  (no key, date-based, logos + live scores)
Play-by-play   → CollegeFootballData.com REST API (free key, reliable wallclock)

The two sources are joined at game-open time:
  ESPN event  →  CFBD game ID  via team-name + date fuzzy match
  CFBD plays  →  wallclock timestamps set at time-of-play by CFBD ingest

Setup: see README.md or run  streamlit run cfb_dashboard.py
"""

import streamlit as st
import requests
from datetime import datetime, time as dtime, date as ddate, timedelta
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Dashboard", page_icon="🏈", layout="wide")
st.title("🏈 College Football Dashboard")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
ET        = ZoneInfo("America/New_York")
CFBD_BASE = "https://api.collegefootballdata.com"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"

SCORING_EMOJI = {
    "touchdown":   "🏈",
    "field goal":  "🎯",
    "extra point": "✅",
    "two-point":   "2️⃣",
    "safety":      "⚠️",
}
PLAY_EMOJI = {
    "interception": "🚨",
    "fumble":       "💨",
    "sack":         "💥",
    "penalty":      "🟡",
    "punt":         "📐",
    "kickoff":      "🦵",
    "timeout":      "⏳",
    "first down":   "⬆️",
    "no gain":      "🛑",
    "loss":         "📉",
}
MISS_EMOJI = "🤦"

# ──────────────────────────────────────────────────────────────
# SIDEBAR — API KEY
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    cfbd_key = st.text_input(
        "CFBD API Key",
        type="password",
        help="Free key from https://collegefootballdata.com/key",
        placeholder="Paste your key here…",
    )
    if not cfbd_key:
        st.warning("Enter a CFBD API key to open play-by-play.")
    else:
        st.success("API key set ✅")
    st.markdown("---")
    st.markdown("[Get a free CFBD key →](https://collegefootballdata.com/key)")
    st.markdown(
        "Play-by-play `wallclock` timestamps are set at time-of-play "
        "by CFBD's ingest pipeline — far more reliable than ESPN's `modified` field."
    )
    st.markdown("---")
    st.subheader("🔍 Search Games by ID")
    st.markdown("Use this if a game fails to auto-match. Search by team name to find the CFBD game ID, then load it directly.")

    search_team = st.text_input("Team name", placeholder="e.g. Miami", key="id_search_team")
    search_year = st.number_input("Season year", min_value=2000, max_value=2030,
                                  value=datetime.today().year if datetime.today().month > 7 else datetime.today().year - 1,
                                  step=1, key="id_search_year")
    search_type = st.selectbox("Season type", ["both", "regular", "postseason"], key="id_search_type")

    if st.button("🔎 Find Games", key="id_search_btn") and search_team.strip() and cfbd_key:
        try:
            r = requests.get(
                f"{CFBD_BASE}/games",
                headers={"Authorization": f"Bearer {cfbd_key}"},
                params={"year": int(search_year), "team": search_team.strip(), "seasonType": search_type},
                timeout=10,
            )
            r.raise_for_status()
            found = r.json()
            if found:
                st.session_state["id_search_results"] = found
            else:
                st.session_state["id_search_results"] = []
                st.warning("No games found — try a different team name or year.")
        except Exception as e:
            st.error(f"Search failed: {e}")

    results = st.session_state.get("id_search_results", [])
    if results:
        st.markdown(f"**{len(results)} game(s) found — pick one to load:**")
        for g in sorted(results, key=lambda x: x.get("startDate", x.get("start_date", "")), reverse=True):
            # CFBD API v5 uses camelCase; fall back to snake_case for older responses
            g_date  = (g.get("startDate") or g.get("start_date") or "")[:10]
            g_away  = g.get("awayTeam")  or g.get("away_team")  or "?"
            g_home  = g.get("homeTeam")  or g.get("home_team")  or "?"
            g_away_pts = g.get("awayPoints") or g.get("away_points") or ""
            g_home_pts = g.get("homePoints") or g.get("home_points") or ""
            g_id    = g.get("id")
            score_str = f"  ({g_away_pts}–{g_home_pts})" if g_away_pts != "" else ""
            g_label = f"{g_away} @ {g_home}{score_str}  ·  {g_date}  ·  ID: {g_id}"
            if st.button(g_label, key=f"manual_pick_{g_id}"):
                for k in ("cached_events", "cached_game_id", "filtered_events"):
                    st.session_state[k] = None
                st.session_state.filters_applied    = False
                st.session_state.selected_cfbd_id   = g_id
                st.session_state.selected_away_name = g_away
                st.session_state.selected_home_name = g_home
                st.session_state.selected_away_abbr = g_away[:4].upper()
                st.session_state.selected_home_abbr = g_home[:4].upper()
                st.session_state.selected_away_eid  = ""
                st.session_state.selected_home_eid  = ""
                st.session_state["id_search_results"] = []
                st.rerun()

# ──────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────
_defaults = {
    "selected_cfbd_id":   None,   # CFBD integer game ID
    "selected_away_name": "",
    "selected_home_name": "",
    "selected_away_abbr": "",
    "selected_home_abbr": "",
    "selected_away_eid":  None,   # ESPN team ID (for logo URL)
    "selected_home_eid":  None,
    "cached_events":      None,
    "cached_game_id":     None,
    "filtered_events":    None,
    "filters_applied":    False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def to_et(raw: str):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ET)
    except Exception:
        return None

def fmt_et(dt) -> str:
    return dt.strftime("%-I:%M %p ET") if dt else "TBD"

def fmt_full_et(dt) -> str:
    if not dt:
        return "N/A"
    label = "EDT" if dt.dst() != timedelta(0) else "EST"
    return dt.strftime(f"%Y-%m-%d %H:%M:%S {label}")

def espn_logo(team_id) -> str:
    return f"https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"

def cfbd_headers() -> dict:
    return {"Authorization": f"Bearer {cfbd_key}"}

def period_label(p: int) -> str:
    return f"Q{p}" if p <= 4 else f"OT{p - 4}"

def _emoji(play_type: str, desc: str, is_scoring: bool) -> str:
    pt = (play_type or "").lower()
    d  = (desc or "").lower()
    if any(x in d for x in ["no good", "incomplete", "missed", "failed"]):
        return MISS_EMOJI
    for k, v in SCORING_EMOJI.items():
        if k in pt or k in d:
            return v if is_scoring else "🏈"
    for k, v in PLAY_EMOJI.items():
        if k in pt or k in d:
            return v
    return "🏈"

def _norm(name: str) -> str:
    """Aggressively normalise a team name for fuzzy matching."""
    name = name.lower().strip()
    # remove common words that differ between ESPN and CFBD
    for token in [
        " university", " college", " state", " st.", " a&m",
        " crimson tide", " tigers", " bulldogs", " gators", " seminoles",
        " volunteers", " rebels", " wildcats", " tar heels", " blue devils",
        " longhorns", " sooners", " cornhuskers", " buckeyes", " wolverines",
        " nittany lions", " fighting irish", " spartans", " hoosiers",
        " aggies", " cowboys", " bears", " rams", " eagles", " panthers",
        " mountaineers", " razorbacks", " gamecocks", " trojans", " bruins",
        " ducks", " beavers", " huskies", " cougars", " utes", " falcons",
        " owls", " cardinals", " red raiders", " horned frogs", " mustangs",
        " mean green", " bobcats", " roadrunners", " miners", " lobos",
        " aztecs", " rainbow warriors", " 49ers", " tritons",
        " hurricanes", " demon deacons", " golden flashes", " golden gophers",
        " golden bears", " golden eagles", " blue hens", " scarlet knights",
        " terrapins", " terps", " cavaliers", " hokies", " yellow jackets",
        " thundering herd", " red wolves", " ragin cajuns", " hilltoppers",
        " flames", " flames", " bearcats", " golden panthers", " knights",
        " cardinals", " leopards", " greyhounds", " bison", " anteaters",
    ]:
        name = name.replace(token, "")
    # well-known ESPN↔CFBD mismatches
    aliases = {
        "mississippi":          "ole miss",
        "louisiana state":      "lsu",
        "southern california":  "usc",
        "miami (fl)":           "miami",
        "miami (ohio)":         "miami (oh)",
        "miami":                "miami",          # ESPN "Miami Hurricanes" → just "miami" → CFBD "Miami"
        "indiana":              "indiana",        # already correct, keep explicit
        "pittsburgh":           "pitt",
        "nevada las vegas":     "unlv",
        "texas christian":      "tcu",
        "brigham young":        "byu",
        "central florida":      "ucf",
        "southern methodist":   "smu",
        "florida international":"fiu",
        "middle tennessee":     "middle tennessee",
        "ut san antonio":       "utsa",
        "ut el paso":           "utep",
        "hawaii":               "hawai'i",
        "north carolina":       "north carolina",
        "north carolina state": "nc state",
        "massachusetts":        "umass",
        "connecticut":          "uconn",
        "army west point":      "army",
        "louisiana":            "louisiana",
        "appalachian":          "appalachian state",
        "ole miss":             "ole miss",
    }
    name = name.strip()
    return aliases.get(name, name)

# ──────────────────────────────────────────────────────────────
# ESPN — SCHEDULE  (no API key, date-based)
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def espn_scoreboard(date_str: str) -> dict:
    """date_str = YYYYMMDD"""
    return requests.get(
        f"{ESPN_BASE}/scoreboard?dates={date_str}&groups=80&limit=200",
        timeout=10,
    ).json()

@st.cache_data(ttl=120, show_spinner=False)
def parse_espn_schedule(date_str: str) -> list:
    raw   = espn_scoreboard(date_str)
    games = []
    for event in raw.get("events", []):
        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        stype       = comp.get("status", {}).get("type", {})
        sname       = stype.get("name", "").upper()

        if "FINAL" in sname:
            status, is_final, is_live = stype.get("shortDetail", "Final"), True, False
        elif "PROGRESS" in sname or "HALFTIME" in sname:
            status, is_final, is_live = stype.get("shortDetail", "Live"), False, True
        else:
            status, is_final, is_live = "Scheduled", False, False

        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        at, ht = away.get("team", {}), home.get("team", {})

        et_dt = to_et(event.get("date", ""))
        period = comp.get("status", {}).get("period", 0) or 0

        games.append({
            "espn_id":     event.get("id"),
            "away_name":   at.get("displayName", "Away"),
            "home_name":   ht.get("displayName", "Home"),
            "away_abbr":   at.get("abbreviation", "AWY"),
            "home_abbr":   ht.get("abbreviation", "HME"),
            "away_eid":    at.get("id", ""),
            "home_eid":    ht.get("id", ""),
            "away_logo":   espn_logo(at.get("id", "")),
            "home_logo":   espn_logo(ht.get("id", "")),
            "away_score":  int(away.get("score", 0) or 0),
            "home_score":  int(home.get("score", 0) or 0),
            "time_str":    fmt_et(et_dt),
            "status":      status,
            "is_live_or_final": is_final or is_live,
            "is_ot":       period > 4 and (is_final or is_live),
            "venue":       comp.get("venue", {}).get("fullName", ""),
            # used for CFBD lookup
            # Bowl games played in Jan/Feb belong to the PREVIOUS year's season in CFBD
            "game_date":   et_dt.date().isoformat() if et_dt else "",
            "season_year": (et_dt.year - 1) if (et_dt and et_dt.month <= 2) else (et_dt.year if et_dt else datetime.today().year),
        })

    return sorted(games, key=lambda x: x["time_str"])

# ──────────────────────────────────────────────────────────────
# CFBD — GAME ID LOOKUP
# Matches ESPN game → CFBD integer ID by team name + date
# ──────────────────────────────────────────────────────────────
def cfbd_find_game_id(away_name: str, home_name: str, game_date: str, season_year: int):
    """
    Returns (cfbd_id, debug_info) where debug_info is a dict describing
    what was tried, so the UI can show the user exactly what happened.
    """
    debug = {
        "espn_away":    away_name,
        "espn_home":    home_name,
        "game_date":    game_date,
        "season_year":  season_year,
        "norm_away":    _norm(away_name),
        "norm_home":    _norm(home_name),
        "searches":     [],
        "candidates_on_date": [],
    }

    def search(team: str):
        try:
            r = requests.get(
                f"{CFBD_BASE}/games",
                headers=cfbd_headers(),
                params={"year": season_year, "team": team, "seasonType": "both"},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            debug["searches"].append({"team": team, "error": str(e)})
            return []

    away_norm = _norm(away_name)
    home_norm = _norm(home_name)

    # Search using normalised forms first (cleaner for CFBD), then full ESPN names as fallback
    search_terms = list(dict.fromkeys([home_norm, away_norm, home_name, away_name]))

    try:
        tgt_dt = datetime.strptime(game_date, "%Y-%m-%d").date()
    except Exception:
        tgt_dt = None

    def sub_match(a, b):
        return a in b or b in a

    for term in search_terms:
        candidate_games = search(term)
        debug["searches"].append({"term": term, "results": len(candidate_games)})
        # Record ALL dates returned so user can see what CFBD actually has
        if candidate_games and "all_cfbd_dates" not in debug:
            debug["all_cfbd_dates"] = sorted(
                set((g.get("start_date") or "")[:10] for g in candidate_games)
            )

        for g in candidate_games:
            g_date = (g.get("startDate") or g.get("start_date") or "")[:10]

            # Allow ±1 day — CFBD stores dates in UTC so a late-night ET
            # kickoff can land on the next calendar day, and some bowl games
            # are indexed with a slight date offset.
            date_ok = False
            if tgt_dt:
                try:
                    g_dt = datetime.strptime(g_date, "%Y-%m-%d").date()
                    date_ok = abs((g_dt - tgt_dt).days) <= 1
                except Exception:
                    date_ok = (g_date == game_date)
            else:
                date_ok = (g_date == game_date)

            if not date_ok:
                continue

            g_away_raw  = g.get("awayTeam") or g.get("away_team") or ""
            g_home_raw  = g.get("homeTeam") or g.get("home_team") or ""
            g_away_norm = _norm(g_away_raw)
            g_home_norm = _norm(g_home_raw)

            debug["candidates_on_date"].append({
                "cfbd_away": g_away_raw,
                "cfbd_home": g_home_raw,
                "cfbd_date": g_date,
                "norm_away": g_away_norm,
                "norm_home": g_home_norm,
                "id":        g.get("id"),
            })

            # Pass 1 — exact normalised match (either home/away orientation)
            if away_norm == g_away_norm and home_norm == g_home_norm:
                return g.get("id"), debug
            if away_norm == g_home_norm and home_norm == g_away_norm:
                return g.get("id"), debug

            # Pass 2 — substring match (handles truncated/partial names)
            away_hit = sub_match(away_norm, g_away_norm) or sub_match(away_norm, g_home_norm)
            home_hit = sub_match(home_norm, g_home_norm) or sub_match(home_norm, g_away_norm)
            if away_hit and home_hit:
                return g.get("id"), debug

    return None, debug

# ──────────────────────────────────────────────────────────────
# CFBD — PLAY-BY-PLAY  (wallclock field = time-of-play UTC)
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cfbd_fetch_plays(game_id: int) -> list:
    try:
        r = requests.get(
            f"{CFBD_BASE}/plays",
            headers=cfbd_headers(),
            params={"gameId": game_id},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def get_events(cfbd_id: int) -> list:
    if st.session_state.cached_game_id == cfbd_id and st.session_state.cached_events is not None:
        return st.session_state.cached_events

    raw        = cfbd_fetch_plays(cfbd_id)
    events     = []
    prev_total = 0

    for p in raw:
        period_num = p.get("period", 0)
        desc       = p.get("playText") or p.get("play_text") or ""
        play_type  = p.get("playType") or p.get("play_type") or ""
        clock_val  = p.get("clock") or p.get("clockTime") or ""
        away_sc    = int(p.get("awayScore") or p.get("away_score") or 0)
        home_sc    = int(p.get("homeScore") or p.get("home_score") or 0)
        total      = away_sc + home_sc
        is_score   = total > prev_total
        prev_total = total

        # ── WALLCLOCK ── dedicated field, set at time-of-play
        action_dt = to_et(p.get("wallclock") or p.get("wallClock") or "")

        # Down & distance
        down      = p.get("down") or 0
        distance  = p.get("distance") or 0
        yard_line = p.get("yardLine") or p.get("yard_line") or 0
        offense   = p.get("offense") or p.get("offenseTeam") or ""

        down_str = ""
        if down > 0:
            ords = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            dist = "Goal" if distance == 0 else str(distance)
            down_str = f"{ords.get(down,'?')} & {dist} at {yard_line}"

        events.append({
            "period":        period_num,
            "period_label":  period_label(period_num),
            "clock_str":     clock_val,
            "desc":          desc,
            "play_type":     play_type,
            "away_score":    away_sc,
            "home_score":    home_sc,
            "score_str":     f"{away_sc} – {home_sc}",
            "is_scoring":    is_score,
            "action_dt":     action_dt,
            "action_dt_str": fmt_full_et(action_dt),
            "down_str":      down_str,
            "yards_gained":  p.get("yardsGained") or p.get("yards_gained"),
            "offense":       offense,
            "defense":       p.get("defense") or p.get("defenseTeam") or "",
            "emoji":         _emoji(play_type, desc, is_score),
        })

    st.session_state.cached_events  = events
    st.session_state.cached_game_id = cfbd_id
    return events

# ══════════════════════════════════════════════════════════════
# GAME FEED VIEW
# ══════════════════════════════════════════════════════════════
if st.session_state.selected_cfbd_id:

    cfbd_id   = st.session_state.selected_cfbd_id
    away_name = st.session_state.selected_away_name
    home_name = st.session_state.selected_home_name
    away_abbr = st.session_state.selected_away_abbr
    home_abbr = st.session_state.selected_home_abbr
    away_eid  = st.session_state.selected_away_eid
    home_eid  = st.session_state.selected_home_eid

    if st.button("⬅ Back to Schedule"):
        for k in ("cached_events", "cached_game_id", "filtered_events"):
            st.session_state[k] = None
        st.session_state.filters_applied  = False
        st.session_state.selected_cfbd_id = None
        st.rerun()

    with st.spinner("Loading play-by-play from CollegeFootballData.com…"):
        events = get_events(cfbd_id)

    if not events:
        st.warning(
            "No plays returned from CFBD. The game may not be indexed yet "
            "(completed games are usually available within an hour of final whistle)."
        )
        st.stop()

    # Score from last play
    live_away = events[-1]["away_score"]
    live_home = events[-1]["home_score"]

    # ── Header ──
    c1, c2, c3 = st.columns([1, 6, 1])
    with c1:
        st.image(espn_logo(away_eid), width=60)
    with c2:
        st.markdown(
            f"""<div style="display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:clamp(16px,2.6vw,28px);gap:10px;flex-wrap:wrap;text-align:center;">
                <span>{away_abbr}</span><span style="color:#888;">{live_away}</span>
                <span>–</span>
                <span style="color:#888;">{live_home}</span><span>{home_abbr}</span>
            </div>""",
            unsafe_allow_html=True,
        )
    with c3:
        st.image(espn_logo(home_eid), width=60)

    # Wallclock coverage indicator
    has_wc = sum(1 for e in events if e["action_dt"])
    total  = len(events)
    pct    = int(100 * has_wc / total) if total else 0
    if pct == 100:
        st.success(f"🕐 Wall-clock timestamps on all {total} plays (100%)")
    elif pct >= 70:
        st.info(f"🕐 Wall-clock timestamps on {has_wc}/{total} plays ({pct}%)")
    else:
        st.warning(f"🕐 Wall-clock timestamps sparse: {has_wc}/{total} plays ({pct}%) — time filter may return few results")

    st.divider()

    # ── Filter setup ──
    all_dts   = [e["action_dt"] for e in events if e["action_dt"]]
    gs_default = min(all_dts) if all_dts else None
    ge_default = max(all_dts) if all_dts else None

    all_periods = sorted(
        {e["period_label"] for e in events},
        key=lambda x: (x.startswith("OT"), int(x[1:]) if x.startswith("Q") else int(x[2:]) + 100),
    )
    all_play_types = sorted({e["play_type"] for e in events if e["play_type"]})
    all_offenses   = sorted({e["offense"] for e in events if e["offense"]})

    USE_Q  = st.checkbox("🏈 Filter by Quarter / OT", value=False)
    USE_T  = st.checkbox("🕐 Filter by Wall-Clock Time (ET)", value=False)
    USE_SC = st.checkbox("🔥 Scoring Plays Only", value=False)
    USE_PT = st.checkbox("📋 Filter by Play Type", value=False)
    USE_TM = st.checkbox("🏟️ Filter by Possession", value=False)

    sel_quarters = sel_types = sel_offenses = []
    START_DT = END_DT = None

    if USE_Q:
        sel_quarters = st.multiselect("Quarters / OT", options=all_periods, default=[])

    if USE_T:
        if not all_dts:
            st.warning("No wall-clock timestamps available for this game — time filter disabled.")
        else:
            st.markdown("**Start (ET)**")
            tc1, tc2 = st.columns(2)
            with tc1:
                sd = st.date_input("Start date", gs_default.date(), key="sd")
            with tc2:
                st_ = st.time_input("Start time", gs_default.time(), step=60, key="st")
            st.markdown("**End (ET)**")
            te1, te2 = st.columns(2)
            with te1:
                ed = st.date_input("End date", ge_default.date(), key="ed")
            with te2:
                et_ = st.time_input("End time", ge_default.time(), step=60, key="et")
            START_DT = datetime.combine(sd, st_).replace(tzinfo=ET)
            END_DT   = datetime.combine(ed, et_).replace(tzinfo=ET)

    if USE_PT:
        sel_types = st.multiselect("Play types", options=all_play_types, default=[])

    if USE_TM:
        sel_offenses = st.multiselect("Offense (possession)", options=all_offenses, default=[])

    if st.button("🚀 Apply Filters"):
        def passes(e):
            if USE_Q and sel_quarters and e["period_label"] not in sel_quarters:
                return False
            if USE_T and START_DT and END_DT:
                if not e["action_dt"] or not (START_DT <= e["action_dt"] <= END_DT):
                    return False
            if USE_SC and not e["is_scoring"]:
                return False
            if USE_PT and sel_types and e["play_type"] not in sel_types:
                return False
            if USE_TM and sel_offenses and e["offense"] not in sel_offenses:
                return False
            return True

        st.session_state.filtered_events = [e for e in events if passes(e)]
        st.session_state.filters_applied = True

    fa = st.session_state.filters_applied
    filtered = st.session_state.filtered_events if fa else events

    if fa:
        n, t = len(filtered), len(events)
        if n == 0:
            st.warning("⚠️ No plays match — adjust filters and click Apply again.")
            st.stop()
        if USE_Q:  st.info(f"🏈 Quarter filter: {', '.join(sel_quarters or ['none'])} — {n}/{t} plays")
        if USE_T and START_DT:
            st.info(f"🕐 Time filter: {START_DT.strftime('%H:%M')} → {END_DT.strftime('%H:%M')} ET — {n}/{t} plays")
        if USE_SC: st.info(f"🔥 Scoring only — {n}/{t} plays")
        if USE_PT: st.info(f"📋 Play type: {', '.join(sel_types or ['none'])} — {n}/{t} plays")
        if USE_TM: st.info(f"🏟️ Possession: {', '.join(sel_offenses or ['none'])} — {n}/{t} plays")

    # ── Render plays ──
    for e in filtered:
        st.subheader(f"{e['emoji']} {e['period_label']} | ⏱️ {e['clock_str']}")

        meta_parts = []
        if e["play_type"]:   meta_parts.append(f"**{e['play_type']}**")
        if e["offense"]:     meta_parts.append(f"{e['offense']} ball")
        if meta_parts:       st.caption("  ·  ".join(meta_parts))

        if e["is_scoring"]:
            st.markdown(f"📊 **Score:** {e['score_str']} &nbsp; 🔥 *Scoring Play!*")
        else:
            st.markdown(f"📊 **Score:** {e['score_str']}")

        if e["down_str"]:
            st.markdown(f"📏 **Down & Distance:** {e['down_str']}")

        if e["yards_gained"] is not None:
            st.markdown(f"📐 **Yards Gained:** {e['yards_gained']}")

        st.markdown(f"📋 **Play:** {e['desc']}")
        st.markdown(f"🕐 **Wall Clock (ET):** `{e['action_dt_str']}`")

        st.divider()

# ══════════════════════════════════════════════════════════════
# SCHEDULE VIEW
# ══════════════════════════════════════════════════════════════
else:
    date     = st.date_input("Select date", datetime.today(), format="YYYY-MM-DD")
    date_str = date.strftime("%Y%m%d")
    st.markdown(f"## CFB Schedule — {date.strftime('%Y-%m-%d')}")

    with st.spinner("Loading schedule from ESPN…"):
        games = parse_espn_schedule(date_str)

    if not games:
        st.info("No games found. College football is primarily played on Saturdays (Sep–Jan).")
        st.stop()

    if not cfbd_key:
        st.warning("⚠️ Enter a CFBD API key in the sidebar to open play-by-play for any game.")

    st.markdown("""
<style>
.sched-team-row { display:flex; align-items:center; gap:10px; margin-bottom:4px; }
.sched-team-row img { width:34px; height:34px; object-fit:contain; }
.sched-team-name { font-size:20px; font-weight:800; letter-spacing:0.4px; }
.sched-score { font-size:20px; font-weight:800; color:#aaa; margin-left:auto; }
.sched-meta { font-size:13px; color:#999; margin-top:4px;
    border-top:1px solid rgba(255,255,255,0.08); padding-top:5px; }
.sched-extra { display:inline-block; background:#e67e22; color:#fff;
    font-size:11px; font-weight:700; padding:1px 6px; border-radius:4px;
    margin-left:6px; vertical-align:middle; }
.sched-venue { font-size:11px; color:#777; margin-top:2px; }
</style>
""", unsafe_allow_html=True)

    cols = st.columns(2)
    for i, g in enumerate(games):
        a_sc  = f'<span class="sched-score">{g["away_score"]}</span>' if g["is_live_or_final"] else ""
        h_sc  = f'<span class="sched-score">{g["home_score"]}</span>' if g["is_live_or_final"] else ""
        ot    = ' <span class="sched-extra">OT</span>' if g["is_ot"] else ""
        meta  = f'{g["time_str"]} &middot; {g["status"]}{ot}'
        venue = f'<div class="sched-venue">📍 {g["venue"]}</div>' if g["venue"] else ""

        html = f"""
<div class="sched-team-row">
  <img src="{g['away_logo']}"/><span class="sched-team-name">{g['away_abbr']}</span>{a_sc}
</div>
<div class="sched-team-row">
  <img src="{g['home_logo']}"/><span class="sched-team-name">{g['home_abbr']}</span>{h_sc}
</div>
<div class="sched-meta">{meta}</div>{venue}"""

        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(html, unsafe_allow_html=True)
                if st.button(
                    f"▶  Open  {g['away_abbr']} @ {g['home_abbr']}",
                    key=f"go_{g['espn_id']}",
                    use_container_width=True,
                    disabled=(not cfbd_key),
                ):
                    with st.spinner("Matching game in CFBD…"):
                        cfbd_id, debug = cfbd_find_game_id(
                            g["away_name"], g["home_name"],
                            g["game_date"], g["season_year"],
                        )
                    if not cfbd_id:
                        st.error(
                            f"Could not match **{g['away_abbr']} @ {g['home_abbr']}** "
                            f"in CollegeFootballData.com. See debug info below."
                        )
                        with st.expander("🔍 Debug — what was tried", expanded=True):
                            st.markdown(f"**ESPN sent:** `{debug['espn_away']}` @ `{debug['espn_home']}`")
                            st.markdown(f"**Normalised to:** `{debug['norm_away']}` @ `{debug['norm_home']}`")
                            st.markdown(f"**Date searched:** `{debug['game_date']}`  |  **Season:** `{debug['season_year']}`")
                            st.markdown("**API searches made:**")
                            for s in debug["searches"]:
                                if "error" in s:
                                    st.markdown(f"- `{s.get('term','?')}` → ❌ error: {s['error']}")
                                else:
                                    st.markdown(f"- `{s.get('term','?')}` → {s['results']} game(s) returned")
                            if debug["candidates_on_date"]:
                                st.markdown(f"**Games found near {debug['game_date']} in CFBD:**")
                                for c in debug["candidates_on_date"]:
                                    st.markdown(
                                        f"- `{c['cfbd_away']}` @ `{c['cfbd_home']}` "
                                        f"· CFBD date: `{c.get('cfbd_date','?')}` "
                                        f"· normalised: `{c['norm_away']}` @ `{c['norm_home']}`"
                                    )
                                st.info(
                                    "👆 Copy the CFBD team name(s) above and report them — "
                                    "they can be added to the alias table to fix this automatically."
                                )
                            else:
                                st.warning(
                                    "No games were found near this date in CFBD. "
                                    "This bowl game may not be indexed yet — CFBD can take "
                                    "several days to add postseason games after they are played."
                                )
                                if debug.get("all_cfbd_dates"):
                                    st.markdown("**Dates CFBD actually has for this team (season 2025):**")
                                    st.code(", ".join(debug["all_cfbd_dates"]))
                                    st.markdown(
                                        "If you see the right game date above but it didn't match, "
                                        "report it and the team names will be fixed."
                                    )
                                st.markdown("👈 **Use the Manual Game Override in the sidebar** to load by CFBD game ID directly.")
                    else:
                        for k in ("cached_events", "cached_game_id", "filtered_events"):
                            st.session_state[k] = None
                        st.session_state.filters_applied      = False
                        st.session_state.selected_cfbd_id     = cfbd_id
                        st.session_state.selected_away_name   = g["away_name"]
                        st.session_state.selected_home_name   = g["home_name"]
                        st.session_state.selected_away_abbr   = g["away_abbr"]
                        st.session_state.selected_home_abbr   = g["home_abbr"]
                        st.session_state.selected_away_eid    = g["away_eid"]
                        st.session_state.selected_home_eid    = g["home_eid"]
                        st.rerun()
