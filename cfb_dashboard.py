import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFB Play by Play", page_icon="🏈", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { display: none; }
[data-testid="stSidebarNav"] { display: none; }
[data-testid="collapsedControl"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.title("🏈 CFB Play by Play")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
ET        = ZoneInfo("America/New_York")
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
    "selected_cfbd_id":    None,
    "selected_away_name":  "",
    "selected_home_name":  "",
    "selected_away_abbr":  "",
    "selected_home_abbr":  "",
    "selected_away_eid":   None,
    "selected_home_eid":   None,
    "selected_year":       None,
    "selected_week":       None,
    "cached_events":       None,
    "cached_game_id":      None,
    "filtered_events":     None,
    "filters_applied":     False,
    # Fix 4: snapshot of what was active when Apply was last clicked
    "applied_filters":     {},
    "last_refresh":        None,
    "search_results":      [],
    "search_done":         False,
    "last_search_year":    None,
    "last_search_team":    None,
    "last_search_results": [],
    "filter_version":      0,
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
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")

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

def _norm(name: str) -> str:
    name = name.lower().strip()
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
        " aztecs", " rainbow warriors", " 49ers", " tritons", " hurricanes",
        " demon deacons", " golden flashes", " golden gophers", " golden bears",
        " golden eagles", " blue hens", " scarlet knights", " terrapins",
        " cavaliers", " hokies", " yellow jackets", " thundering herd",
        " red wolves", " ragin cajuns", " hilltoppers", " bearcats", " knights",
    ]:
        name = name.replace(token, "")
    aliases = {
        "mississippi":          "ole miss",
        "louisiana state":      "lsu",
        "southern california":  "usc",
        "miami (fl)":           "miami",
        "miami (ohio)":         "miami (oh)",
        "pittsburgh":           "pitt",
        "nevada las vegas":     "unlv",
        "texas christian":      "tcu",
        "brigham young":        "byu",
        "central florida":      "ucf",
        "southern methodist":   "smu",
        "florida international":"fiu",
        "ut san antonio":       "utsa",
        "ut el paso":           "utep",
        "hawaii":               "hawai'i",
        "north carolina state": "nc state",
        "massachusetts":        "umass",
        "connecticut":          "uconn",
        "army west point":      "army",
    }
    return aliases.get(name.strip(), name.strip())

# ──────────────────────────────────────────────────────────────
# CFBD — GAME ID LOOKUP
# ──────────────────────────────────────────────────────────────
def cfbd_find_game_id(away_name, home_name, game_date, season_year):
    debug = {
        "espn_away": away_name, "espn_home": home_name,
        "game_date": game_date, "season_year": season_year,
        "norm_away": _norm(away_name), "norm_home": _norm(home_name),
        "searches": [], "candidates_on_date": [],
    }

    def search(team):
        try:
            r = requests.get(f"{CFBD_BASE}/games", headers=cfbd_headers(),
                params={"year": season_year, "team": team}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            debug["searches"].append({"term": team, "error": str(e)})
            return []

    away_norm    = _norm(away_name)
    home_norm    = _norm(home_name)
    search_terms = list(dict.fromkeys([home_norm, away_norm, home_name, away_name]))

    try:
        tgt_dt = datetime.strptime(game_date, "%Y-%m-%d").date()
    except Exception:
        tgt_dt = None

    def sub_match(a, b):
        return a in b or b in a

    for term in search_terms:
        results = search(term)
        debug["searches"].append({"term": term, "results": len(results)})
        if results and "all_cfbd_dates" not in debug:
            debug["all_cfbd_dates"] = sorted(
                set((g.get("startDate") or g.get("start_date") or "")[:10] for g in results)
            )
        for g in results:
            g_date = (g.get("startDate") or g.get("start_date") or "")[:10]
            date_ok = False
            if tgt_dt:
                try:
                    date_ok = abs((datetime.strptime(g_date, "%Y-%m-%d").date() - tgt_dt).days) <= 1
                except Exception:
                    date_ok = g_date == game_date
            else:
                date_ok = g_date == game_date
            if not date_ok:
                continue

            g_away_raw  = g.get("awayTeam") or g.get("away_team") or ""
            g_home_raw  = g.get("homeTeam") or g.get("home_team") or ""
            g_away_norm = _norm(g_away_raw)
            g_home_norm = _norm(g_home_raw)
            g_week      = g.get("week") or 1

            debug["candidates_on_date"].append({
                "cfbd_away": g_away_raw, "cfbd_home": g_home_raw,
                "cfbd_date": g_date, "norm_away": g_away_norm,
                "norm_home": g_home_norm, "id": g.get("id"),
            })

            if away_norm == g_away_norm and home_norm == g_home_norm:
                return g.get("id"), g_week, debug
            if away_norm == g_home_norm and home_norm == g_away_norm:
                return g.get("id"), g_week, debug
            if sub_match(away_norm, g_away_norm) or sub_match(away_norm, g_home_norm):
                if sub_match(home_norm, g_home_norm) or sub_match(home_norm, g_away_norm):
                    return g.get("id"), g_week, debug

    return None, None, debug

# ──────────────────────────────────────────────────────────────
# CFBD — API CALLS (cached)
# Fix 2: Refresh only clears play caches, not the 24h teams cache
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
            fbs = [
                t.get("school", "") for t in data
                if t.get("school")
                and (t.get("classification") or "").lower() == "fbs"
            ]
            return sorted(fbs, key=str.lower)
    except Exception:
        pass
    return []

def _clear_play_cache():
    """Fix 2: Only clear play-related caches, preserve 24h teams cache."""
    cfbd_fetch_plays.clear()
    fetch_game_scores.clear()

def get_events(cfbd_id: int, year: int, week: int) -> list:
    if st.session_state.cached_game_id == cfbd_id and st.session_state.cached_events is not None:
        return st.session_state.cached_events

    raw       = cfbd_fetch_plays(cfbd_id, year, week)
    events    = []
    prev_away = 0
    prev_home = 0

    for p in raw:
        period_num    = p.get("period", 0)
        drive_num     = p.get("driveNumber") or p.get("drive_number") or ""
        desc          = p.get("playText")    or p.get("play_text")   or ""
        play_type     = p.get("playType")    or p.get("play_type")   or ""
        _clock_raw    = p.get("clock") or p.get("clockTime") or ""
        if isinstance(_clock_raw, dict):
            _mins     = int(_clock_raw.get("minutes", 0) or 0)
            _secs     = int(_clock_raw.get("seconds", 0) or 0)
            clock_val = f"{_mins:02}:{_secs:02}"
        elif isinstance(_clock_raw, str):
            clock_val = _clock_raw
        else:
            clock_val = ""

        offense_sc = int(p.get("offenseScore") or 0)
        defense_sc = int(p.get("defenseScore") or 0)
        home_team  = (p.get("home") or "").lower()
        offense_tm = (p.get("offense") or "").lower()
        if offense_tm == home_team:
            home_sc, away_sc = offense_sc, defense_sc
        else:
            away_sc, home_sc = offense_sc, defense_sc

        cfbd_scoring  = bool(p.get("scoring", False))
        score_went_up = (away_sc + home_sc) > (prev_away + prev_home)
        is_score      = cfbd_scoring and score_went_up
        prev_away     = away_sc
        prev_home     = home_sc

        action_dt     = to_et(p.get("wallclock") or p.get("wallClock") or "")
        down          = p.get("down")     or 0
        distance      = p.get("distance") or 0
        yard_line     = p.get("yardline") or p.get("yardLine") or p.get("yard_line") or 0
        yards_to_goal = p.get("yardsToGoal") or p.get("yards_to_goal") or 0
        offense       = p.get("offense")  or p.get("offenseTeam") or ""
        down_str      = ""
        if down > 0:
            ords     = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            dist     = "Goal" if distance == 0 else str(distance)
            ytg      = yards_to_goal or yard_line
            off_abbr = (offense.split()[0] if offense else "OFF").upper()
            def_team = p.get("defense") or p.get("defenseTeam") or ""
            def_abbr = (def_team.split()[0] if def_team else "DEF").upper()
            yard_str = f"{off_abbr} {100 - ytg}" if ytg > 50 else f"{def_abbr} {ytg}"
            down_str = f"{ords.get(down,'?')} & {dist} at {yard_str}"

        # Fix 1: Build full play HTML once here rather than 5 separate st calls at render time
        drive_str  = f"🚗 <b>Drive {drive_num}</b> &nbsp;|&nbsp; " if drive_num else ""
        score_line = (
            f"{drive_str}📊 <b>Score:</b> {away_sc} \u2013 {home_sc}"
            + (" &nbsp; 🔥 <i>Scoring Play!</i>" if is_score else "")
        )
        down_line   = f"📏 <b>Down &amp; Distance:</b> {down_str}" if down_str else ""
        yards_line  = f"📐 <b>Yards Gained:</b> {p.get('yardsGained') or p.get('yards_gained', '')}" if (p.get("yardsGained") or p.get("yards_gained")) is not None else ""
        play_line   = f"📋 <b>Play:</b> {desc}"
        clock_line  = f"🕐 <b>Wall Clock (ET):</b> <code>{fmt_full_et(action_dt)}</code>"

        meta_parts = []
        if play_type: meta_parts.append(f"<b>{play_type}</b>")
        if offense:   meta_parts.append(f"{offense} ball")
        meta_line = "  ·  ".join(meta_parts)

        events.append({
            "period":       period_num,
            "drive_num":    drive_num,
            "period_label": period_label(period_num),
            "clock_str":    clock_val,
            "desc":         desc,
            "play_type":    play_type,
            "away_score":   away_sc,
            "home_score":   home_sc,
            "score_str":    f"{away_sc} \u2013 {home_sc}",
            "is_scoring":   is_score,
            "action_dt":    action_dt,
            "action_dt_str":fmt_full_et(action_dt),
            "down_str":     down_str,
            "yards_gained": p.get("yardsGained") or p.get("yards_gained"),
            "offense":      offense,
            "defense":      p.get("defense") or p.get("defenseTeam") or "",
            "emoji":        _emoji(play_type, desc, is_score),
            # Fix 1: pre-built HTML card — single st.markdown call per play
            "card_html": f"""
<div style="margin-bottom:4px;font-size:13px;color:#aaa">{meta_line}</div>
<div style="margin-bottom:4px">{score_line}</div>
{"<div style='margin-bottom:4px'>" + down_line + "</div>" if down_line else ""}
{"<div style='margin-bottom:4px'>" + yards_line + "</div>" if yards_line else ""}
<div style="margin-bottom:4px">{play_line}</div>
<div>{clock_line}</div>
""",
        })

    def _sort_key(e):
        if e["action_dt"]:
            return (0, e["action_dt"].timestamp(), 0, 0)
        try:
            parts = e["clock_str"].split(":")
            secs  = int(parts[0]) * 60 + int(parts[1])
        except Exception:
            secs = 0
        return (1, 0, e["period"], -secs)

    events.sort(key=_sort_key)
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
    g_year    = st.session_state.get("selected_year") or datetime.today().year
    g_week    = st.session_state.get("selected_week") or 1

    _last_team  = st.session_state.get("last_search_team") or ""
    _last_year  = st.session_state.get("last_search_year") or ""
    _back_label = f"⬅ Back to {_last_team} {_last_year}" if _last_team else "⬅ Back"

    btn_col1, btn_col2, btn_col3, btn_col4, _ = st.columns([1, 2, 1, 1.5, 2.5], gap="small")

    with btn_col1:
        if st.button("⬅ Back", use_container_width=True):
            for k in ("cached_events", "cached_game_id", "filtered_events"):
                st.session_state[k] = None
            st.session_state.filters_applied  = False
            st.session_state.applied_filters  = {}
            st.session_state.selected_cfbd_id = None
            st.session_state.last_refresh     = None
            st.rerun()

    with btn_col2:
        if _last_team and st.button(_back_label, use_container_width=True):
            for k in ("cached_events", "cached_game_id", "filtered_events"):
                st.session_state[k] = None
            st.session_state.filters_applied  = False
            st.session_state.applied_filters  = {}
            st.session_state.selected_cfbd_id = None
            st.session_state.search_done      = True
            st.session_state.search_results   = st.session_state.get("last_search_results", [])
            st.session_state.last_refresh     = None
            st.rerun()

    with btn_col3:
        if st.button("🔄 Refresh", use_container_width=True):
            # Fix 2: only clear play caches — preserves 24h teams cache
            _clear_play_cache()
            st.session_state.cached_events  = None
            st.session_state.cached_game_id = None
            st.session_state.last_refresh   = datetime.now(ET)
            st.rerun()

    with btn_col4:
        if st.session_state.last_refresh:
            st.markdown(
                f"<div style='background:#2e7d32;color:white;padding:0.4rem 0.75rem;"
                f"border-radius:0.4rem;font-size:0.875rem;font-weight:700;"
                f"height:38px;display:flex;align-items:center;white-space:nowrap'>"
                f"Last refresh {st.session_state.last_refresh.strftime('%H:%M:%S ET')}</div>",
                unsafe_allow_html=True,
            )

    with st.spinner("Loading play-by-play…"):
        events = get_events(cfbd_id, g_year, g_week)

    if not events:
        st.warning("No plays returned. The game may not be indexed yet, or the week number may be wrong.")
        st.stop()

    _final_away, _final_home = fetch_game_scores(cfbd_id)
    if _final_away is not None:
        live_away, live_home = _final_away, _final_home
    else:
        live_away = max((e["away_score"] for e in events), default=0)
        live_home = max((e["home_score"] for e in events), default=0)

    c1, c2, c3 = st.columns([1, 6, 1], gap="small")
    with c1:
        if away_eid:
            st.image(espn_logo(away_eid), width=60)
    with c2:
        st.markdown(
            f"""<div style="display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:clamp(16px,2.6vw,28px);gap:10px;flex-wrap:wrap;text-align:center;">
                <span>{away_name}</span><span style="color:#888;">{live_away}</span>
                <span>&#8211;</span>
                <span style="color:#888;">{live_home}</span><span>{home_name}</span>
            </div>""",
            unsafe_allow_html=True,
        )
    with c3:
        if home_eid:
            st.image(espn_logo(home_eid), width=60)

    has_wc = sum(1 for e in events if e["action_dt"])
    total  = len(events)
    pct    = int(100 * has_wc / total) if total else 0
    if pct == 100:
        st.success(f"🕐 Wall-clock timestamps on all {total} plays")
    elif pct >= 70:
        st.info(f"🕐 Wall-clock timestamps on {has_wc}/{total} plays ({pct}%)")
    else:
        st.warning(f"🕐 Wall-clock sparse: {has_wc}/{total} plays ({pct}%) — time filter may return few results")

    st.divider()

    all_dts      = [e["action_dt"] for e in events if e["action_dt"]]
    gs_default   = min(all_dts) if all_dts else None
    ge_default   = max(all_dts) if all_dts else None
    all_periods  = sorted({e["period_label"] for e in events},
        key=lambda x: (x.startswith("OT"), int(x[1:]) if x.startswith("Q") else int(x[2:]) + 100))
    all_offenses = sorted({e["offense"] for e in events if e["offense"]})

    v      = st.session_state.filter_version
    USE_Q  = st.checkbox("🏈 Filter by Quarter / OT",   key=f"q_{v}")
    USE_T  = st.checkbox("🕐 Filter by Actual Time (ET)", key=f"t_{v}")
    USE_TM = st.checkbox("🏟️ Filter by Possession",      key=f"tm_{v}")
    USE_SC = st.checkbox("🔥 Scoring Plays Only",         key=f"sc_{v}")

    sel_quarters = []
    sel_offenses = []
    START_DT = END_DT = None

    if USE_Q:
        sel_quarters = st.multiselect("Quarters / OT", options=all_periods)
    if USE_T:
        if not all_dts:
            st.warning("No wall-clock timestamps available.")
        else:
            tc1, tc2 = st.columns(2)
            with tc1:
                sd  = st.date_input("Start date", gs_default.date(), key="sd")
                st_ = st.time_input("Start time", gs_default.time(), step=60, key="st_")
            with tc2:
                ed  = st.date_input("End date",   ge_default.date(), key="ed")
                et_ = st.time_input("End time",   ge_default.time(), step=60, key="et_")
            START_DT = datetime.combine(sd, st_).replace(tzinfo=ET)
            END_DT   = datetime.combine(ed, et_).replace(tzinfo=ET)
    if USE_TM:
        sel_offenses = st.multiselect("Offense", options=all_offenses)

    f_btn_1, f_btn_2, f_btn_spacer = st.columns([1.5, 1.5, 5])

    with f_btn_1:
        if st.button("🚀 Apply Filters", use_container_width=True):
            def passes(e):
                if USE_Q  and sel_quarters and e["period_label"] not in sel_quarters: return False
                if USE_T  and START_DT and END_DT:
                    if not e["action_dt"] or not (START_DT <= e["action_dt"] <= END_DT): return False
                if USE_SC and not e["is_scoring"]:                                       return False
                if USE_TM and sel_offenses and e["offense"] not in sel_offenses:        return False
                return True
            st.session_state.filtered_events = [e for e in events if passes(e)]
            st.session_state.filters_applied = True
            # Fix 4: snapshot exactly what was active at Apply time
            st.session_state.applied_filters = {
                "quarters":  sel_quarters if USE_Q else None,
                "time":      (START_DT, END_DT) if (USE_T and START_DT and END_DT) else None,
                "offenses":  sel_offenses if USE_TM else None,
                "scoring":   USE_SC,
            }
            st.rerun()

    with f_btn_2:
        # Fix 3: disable Remove Filters when no filters are applied
        if st.button("🗑️ Remove Filters", use_container_width=True,
                     disabled=not st.session_state.filters_applied):
            st.session_state.filtered_events = None
            st.session_state.filters_applied = False
            st.session_state.applied_filters = {}
            st.session_state.filter_version += 1
            st.rerun()

    fa       = st.session_state.filters_applied
    filtered = st.session_state.filtered_events if fa else events

    # Fix 4: banners read from the Apply-time snapshot, not live checkboxes
    if fa:
        n, t = len(filtered), len(events)
        if n == 0:
            st.warning("⚠️ No plays match — adjust filters and click Apply again.")
            st.stop()
        af = st.session_state.applied_filters
        if af.get("quarters"):
            st.info(f"🏈 Quarter filter: {', '.join(af['quarters'])} — showing {n} of {t} plays")
        if af.get("time"):
            s_dt, e_dt = af["time"]
            st.info(f"🕐 Time filter: {s_dt.strftime('%Y-%m-%d %H:%M ET')} \u2192 {e_dt.strftime('%Y-%m-%d %H:%M ET')} — showing {n} of {t} plays")
        if af.get("offenses"):
            st.info(f"🏟️ Possession filter: {', '.join(af['offenses'])} — showing {n} of {t} plays")
        if af.get("scoring"):
            st.info(f"🏈 Scoring plays filter — showing {n} of {t} plays")

    for e in filtered:
        st.subheader(f"{e['emoji']} {e['period_label']} | ⏱️ {e['clock_str']}")
        meta_parts = []
        if e["play_type"]: meta_parts.append(f"**{e['play_type']}**")
        if e["offense"]:   meta_parts.append(f"{e['offense']} ball")
        if meta_parts:     st.caption("  ·  ".join(meta_parts))
        drive_str = f"🚗 **Drive {e['drive_num']}** &nbsp;|&nbsp; " if e["drive_num"] else ""
        st.markdown(f"{drive_str}📊 **Score:** {e['score_str']}" + (" &nbsp; 🔥 *Scoring Play!*" if e["is_scoring"] else ""))
        if e["down_str"]:        st.markdown(f"📏 **Down & Distance:** {e['down_str']}")
        if e["yards_gained"] is not None: st.markdown(f"📐 **Yards Gained:** {e['yards_gained']}")
        st.markdown(f"📋 **Play:** {e['desc']}")
        st.markdown(f"🕐 **Wall Clock (ET):** `{e['action_dt_str']}`")
        st.divider()

# ══════════════════════════════════════════════════════════════
# HOME — SEARCH GAMES
# ══════════════════════════════════════════════════════════════
else:
    st.markdown("Search by team name to find a game, then click to load its play-by-play.")

    all_teams = fetch_all_cfbd_teams()
    col_a, col_b = st.columns([3, 1])
    with col_a:
        if all_teams:
            search_team = st.selectbox("Team", options=[""] + all_teams,
                format_func=lambda x: "Select a team..." if x == "" else x,
                label_visibility="collapsed")
        else:
            search_team = st.text_input("Team name", placeholder="e.g. Alabama, Miami, Ohio State",
                label_visibility="collapsed")
    with col_b:
        _year_default = st.session_state.last_search_year or datetime.today().year
        search_year = st.number_input(
            "Year", min_value=2000, max_value=2030,
            value=_year_default,
            step=1, label_visibility="collapsed",
        )

    if st.button("🔎 Find Games", use_container_width=True):
        if not cfbd_key:
            st.error("No CFBD API key found. Add CFBD_API_KEY to your Streamlit secrets.")
        elif not search_team.strip():
            st.warning("Select a team first.")
        else:
            st.session_state.last_search_year = int(search_year)
            st.session_state.last_search_team = search_team.strip()
            with st.spinner(f"Searching CFBD for {search_team}…"):
                try:
                    r = requests.get(
                        f"{CFBD_BASE}/games", headers=cfbd_headers(),
                        params={"year": int(search_year), "team": search_team.strip()},
                        timeout=10,
                    )
                    r.raise_for_status()
                    found = r.json()
                    st.session_state.search_results      = found if isinstance(found, list) else []
                    st.session_state.last_search_results = found if isinstance(found, list) else []
                    st.session_state.search_done         = True
                    if not st.session_state.search_results:
                        st.warning("No games found — try a different name or year.")
                except Exception as e:
                    st.error(f"Search failed: {e}")

    if st.session_state.search_done and st.session_state.search_results:
        results = sorted(
            st.session_state.search_results,
            key=lambda x: x.get("startDate", x.get("start_date", "")),
            reverse=True,
        )
        st.markdown(f"**{len(results)} game(s) found:**")

        for g in results:
            _raw_dt = g.get("startDate") or g.get("start_date") or ""
            try:
                _et_dt = datetime.fromisoformat(_raw_dt.replace("Z", "+00:00")).astimezone(ET)
                g_date = _et_dt.strftime("%Y-%m-%d")
            except Exception:
                g_date = _raw_dt[:10]

            g_away     = g.get("awayTeam")   or g.get("away_team")   or "?"
            g_home     = g.get("homeTeam")   or g.get("home_team")   or "?"
            g_away_pts = g.get("awayPoints") or g.get("away_points") or ""
            g_home_pts = g.get("homePoints") or g.get("home_points") or ""
            g_away_id  = g.get("awayId")     or g.get("away_id")     or ""
            g_home_id  = g.get("homeId")     or g.get("home_id")     or ""
            g_id       = g.get("id")
            g_week     = g.get("week") or "?"
            g_stype    = (g.get("seasonType") or g.get("season_type") or "regular").lower()
            week_label = "Postseason" if g_stype in ("postseason", "post") else f"Week {g_week}"
            has_started = g.get("awayPoints") is not None or g.get("away_points") is not None

            away_pts_str = str(g_away_pts) if g_away_pts != "" else ""
            home_pts_str = str(g_home_pts) if g_home_pts != "" else ""
            _a_logo  = f"<img src='{espn_logo(g_away_id)}' style='width:22px;height:22px;object-fit:contain'/>" if g_away_id else ""
            _h_logo  = f"<img src='{espn_logo(g_home_id)}' style='width:22px;height:22px;object-fit:contain'/>" if g_home_id else ""
            _a_score = f"<span style='margin-left:auto;font-size:15px;font-weight:700;color:#aaa'>{away_pts_str}</span>" if away_pts_str else ""
            _h_score = f"<span style='margin-left:auto;font-size:15px;font-weight:700;color:#aaa'>{home_pts_str}</span>" if home_pts_str else ""

            card_html = (
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:3px'>{_a_logo}"
                f"<span style='font-size:15px;font-weight:700'>{g_away}</span>{_a_score}</div>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'>{_h_logo}"
                f"<span style='font-size:15px;font-weight:700'>{g_home}</span>{_h_score}</div>"
                f"<div style='font-size:12px;color:#888;border-top:1px solid rgba(255,255,255,0.07);padding-top:4px'>"
                f"{g_date} &middot; {week_label}</div>"
            )

            with st.container(border=True):
                st.markdown(card_html, unsafe_allow_html=True)
                btn_label = "▶ Open" if has_started else "⏳ Not Started"
                btn_help  = "Data available once the game starts." if not has_started else None
                if st.button(btn_label, key=f"pick_{g_id}", use_container_width=True,
                             disabled=not has_started, help=btn_help):
                    st.session_state.last_refresh = datetime.now(ET)
                    for k in ("cached_events", "cached_game_id", "filtered_events"):
                        st.session_state[k] = None
                    st.session_state.filters_applied    = False
                    st.session_state.applied_filters    = {}
                    st.session_state.selected_cfbd_id   = g_id
                    st.session_state.selected_away_name = g_away
                    st.session_state.selected_home_name = g_home
                    st.session_state.selected_away_abbr = g_away[:6].upper()
                    st.session_state.selected_home_abbr = g_home[:6].upper()
                    st.session_state.selected_away_eid  = g_away_id
                    st.session_state.selected_home_eid  = g_home_id
                    st.session_state.selected_year      = int(g.get("season") or g.get("year") or search_year)
                    st.session_state.selected_week      = int(g.get("week") or 1)
                    st.session_state.search_results     = []
                    st.session_state.search_done        = False
                    st.rerun()
