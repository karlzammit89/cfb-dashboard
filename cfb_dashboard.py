import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Dashboard", page_icon="🏈", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { display: none; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="collapsedControl"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.title("🏈 College Football Dashboard")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
ET         = ZoneInfo("America/New_York")
CFBD_BASE = "https://api.collegefootballdata.com"

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
# API KEY — from Streamlit secrets
# ──────────────────────────────────────────────────────────────
cfbd_key = st.secrets.get("CFBD_API_KEY", "")

def cfbd_headers() -> dict:
    return {"Authorization": f"Bearer {cfbd_key}"}

# ──────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────
_defaults = {
    "selected_cfbd_id":   None,
    "selected_away_name": "",
    "selected_home_name": "",
    "selected_away_abbr": "",
    "selected_home_abbr": "",
    "selected_away_eid":  None,
    "selected_home_eid":  None,
    "selected_year":      None,
    "selected_week":      None,
    "cached_events":      None,
    "cached_game_id":     None,
    "last_refresh":       None,
    "search_results":     [],
    "search_done":        False,
    "last_search_year":    None,
    "last_search_team":    None,
    "last_search_results": [],
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

def fmt_full_et(dt) -> str:
    if not dt:
        return "N/A"
    return dt.strftime(f"%Y-%m-%d %H:%M:%S ET")

def espn_logo(team_id) -> str:
    return f"https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png"

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

# ──────────────────────────────────────────────────────────────
# CFBD — FETCH DATA
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def cfbd_fetch_plays(game_id: int, year: int, week: int) -> list:
    try:
        r = requests.get(f"{CFBD_BASE}/plays", headers=cfbd_headers(),
            params={"gameId": game_id, "year": year, "week": week}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        filtered = [p for p in data if str(p.get("gameId") or p.get("game_id") or "") == str(game_id)]
        return filtered if filtered else data
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_game_scores(game_id: int) -> tuple:
    try:
        r = requests.get(f"{CFBD_BASE}/games", headers=cfbd_headers(),
            params={"id": game_id}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            g = data[0]
            away_sc = g.get("awayPoints") or g.get("away_points") or 0
            home_sc = g.get("homePoints") or g.get("home_points") or 0
            return int(away_sc), int(home_sc)
    except Exception:
        pass
    return None, None

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_all_cfbd_teams() -> list:
    try:
        r = requests.get(f"{CFBD_BASE}/teams", headers=cfbd_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            fbs = [t.get("school", "") for t in data if t.get("school") and (t.get("classification") or "").lower() == "fbs"]
            return sorted(fbs, key=str.lower)
    except Exception:
        pass
    return []

def get_events(cfbd_id: int, year: int, week: int) -> list:
    if st.session_state.cached_game_id == cfbd_id and st.session_state.cached_events is not None:
        return st.session_state.cached_events

    raw = cfbd_fetch_plays(cfbd_id, year, week)
    events = []
    prev_away, prev_home = 0, 0

    for p in raw:
        period_num = p.get("period", 0)
        drive_num = p.get("driveNumber") or p.get("drive_number") or ""
        desc = p.get("playText") or p.get("play_text") or ""
        play_type = p.get("playType") or p.get("play_type") or ""
        
        _clock_raw = p.get("clock") or p.get("clockTime") or ""
        if isinstance(_clock_raw, dict):
            clock_val = f"{int(_clock_raw.get('minutes', 0)):02}:{int(_clock_raw.get('seconds', 0)):02}"
        else:
            clock_val = str(_clock_raw)

        offense_sc = int(p.get("offenseScore") or 0)
        defense_sc = int(p.get("defenseScore") or 0)
        home_team = (p.get("home") or "").lower()
        offense_tm = (p.get("offense") or "").lower()
        
        if offense_tm == home_team:
            home_sc, away_sc = offense_sc, defense_sc
        else:
            away_sc, home_sc = offense_sc, defense_sc

        is_score = bool(p.get("scoring", False)) and ((away_sc + home_sc) > (prev_away + prev_home))
        prev_away, prev_home = away_sc, home_sc
        
        action_dt = to_et(p.get("wallclock") or p.get("wallClock") or "")
        down = p.get("down") or 0
        distance = p.get("distance") or 0
        ytg = p.get("yardsToGoal") or p.get("yardLine") or 0
        offense = p.get("offense") or ""
        
        down_str = ""
        if down > 0:
            ords = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            dist = "Goal" if distance == 0 else str(distance)
            off_abbr = (offense.split()[0] if offense else "OFF").upper()
            yard_str = f"{off_abbr} {100 - ytg}" if ytg > 50 else f"OPP {ytg}"
            down_str = f"{ords.get(down,'?')} & {dist} at {yard_str}"

        events.append({
            "period_label":  period_label(period_num),
            "clock_str":     clock_val,
            "desc":          desc,
            "play_type":     play_type,
            "score_str":     f"{away_sc} – {home_sc}",
            "is_scoring":    is_score,
            "action_dt":     action_dt,
            "action_dt_str": fmt_full_et(action_dt),
            "down_str":      down_str,
            "yards_gained":  p.get("yardsGained") or p.get("yards_gained"),
            "offense":       offense,
            "drive_num":     drive_num,
            "emoji":         _emoji(play_type, desc, is_score),
            "period":        period_num
        })

    def _sort_key(e):
        if e["action_dt"]: return (0, e["action_dt"].timestamp(), 0, 0)
        try:
            parts = e["clock_str"].split(":")
            secs = int(parts[0]) * 60 + int(parts[1])
        except: secs = 0
        return (1, 0, e["period"], -secs)

    events.sort(key=_sort_key)
    st.session_state.cached_events = events
    st.session_state.cached_game_id = cfbd_id
    return events

# ══════════════════════════════════════════════════════════════
# GAME FEED VIEW
# ══════════════════════════════════════════════════════════════
if st.session_state.selected_cfbd_id:
    cfbd_id = st.session_state.selected_cfbd_id
    g_year = st.session_state.get("selected_year") or datetime.today().year
    g_week = st.session_state.get("selected_week") or 1

    # Navigation Header
    btn_col1, btn_col2, btn_col3, btn_col4, _ = st.columns([1, 2, 1, 1.5, 2.5], gap="small")
    
    with btn_col1:
        if st.button("⬅ Back", use_container_width=True):
            st.session_state.selected_cfbd_id = None
            st.rerun()

    with btn_col2:
        _last_team = st.session_state.get("last_search_team", "")
        if _last_team and st.button(f"⬅ Back to Search", use_container_width=True):
            st.session_state.selected_cfbd_id = None
            st.session_state.search_done = True
            st.rerun()
            
    with btn_col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.session_state.last_refresh = datetime.now(ET)
            st.rerun()

    with btn_col4:
        if st.session_state.last_refresh:
            st.markdown(f"""<div style="background-color:#2e7d32;color:white;padding:8px;border-radius:4px;font-size:14px;font-weight:bold;">
                Last refresh {st.session_state.last_refresh.strftime('%H:%M:%S ET')}</div>""", unsafe_allow_html=True)

    with st.spinner("Loading plays..."):
        events = get_events(cfbd_id, g_year, g_week)

    if not events:
        st.warning("No plays found for this game.")
        st.stop()

    # Score Header
    live_away, live_home = fetch_game_scores(cfbd_id)
    if live_away is None:
        live_away = events[-1]["away_score"] if events else 0
        live_home = events[-1]["home_score"] if events else 0

    st.markdown(f"""<div style="text-align:center; font-size:28px; font-weight:bold; margin: 20px 0;">
        {st.session_state.selected_away_name} {live_away} – {live_home} {st.session_state.selected_home_name}
        </div>""", unsafe_allow_html=True)
    
    st.divider()

    # Display Feed (No Filters)
    for e in events:
        st.subheader(f"{e['emoji']} {e['period_label']} | ⏱️ {e['clock_str']}")
        if e["play_type"]:
            st.caption(f"**{e['play_type']}**  ·  {e['offense']} ball")
        
        drive_txt = f"🚗 **Drive {e['drive_num']}** &nbsp;|&nbsp; " if e['drive_num'] else ""
        st.markdown(f"{drive_txt}📊 **Score:** {e['score_str']}" + (" &nbsp; 🔥 *Scoring Play!*" if e["is_scoring"] else ""))
        
        if e["down_str"]: st.markdown(f"📏 **Down & Distance:** {e['down_str']}")
        if e["yards_gained"] is not None: st.markdown(f"📐 **Yards Gained:** {e['yards_gained']}")
        st.markdown(f"📋 **Play:** {e['desc']}")
        st.markdown(f"🕐 **Wall Clock (ET):** `{e['action_dt_str']}`")
        st.divider()

# ══════════════════════════════════════════════════════════════
# HOME — SEARCH GAMES
# ══════════════════════════════════════════════════════════════
else:
    st.markdown("Search by team name to find a game.")
    all_teams = fetch_all_cfbd_teams()
    
    col_a, col_b = st.columns([3, 1])
    with col_a:
        search_team = st.selectbox("Team", options=[""] + all_teams, format_func=lambda x: "Select a team..." if x == "" else x)
    with col_b:
        search_year = st.number_input("Year", min_value=2000, max_value=2030, value=2024)

    if st.button("🔎 Find Games", use_container_width=True):
        if not cfbd_key:
            st.error("Missing CFBD API key.")
        elif not search_team:
            st.warning("Select a team.")
        else:
            r = requests.get(f"{CFBD_BASE}/games", headers=cfbd_headers(), params={"year": int(search_year), "team": search_team})
            st.session_state.search_results = r.json() if r.status_code == 200 else []
            st.session_state.search_done = True
            st.session_state.last_search_team = search_team
            st.session_state.selected_year = search_year

    if st.session_state.search_done and st.session_state.search_results:
        for g in st.session_state.search_results:
            g_id = g.get("id")
            g_away = g.get("awayTeam")
            g_home = g.get("homeTeam")
            has_started = g.get("awayPoints") is not None
            
            with st.container(border=True):
                st.write(f"**{g_away} @ {g_home}**")
                st.write(f"{g.get('startDate')[:10]} | Week {g.get('week')}")
                if st.button(f"View Game {g_id}", key=f"btn_{g_id}", disabled=not has_started):
                    st.session_state.selected_cfbd_id = g_id
                    st.session_state.selected_away_name = g_away
                    st.session_state.selected_home_name = g_home
                    st.session_state.selected_week = g.get("week")
                    st.rerun()
