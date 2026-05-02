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
    "filtered_events":    None,
    "filters_applied":    False,
    "search_results":     [],
    "search_done":        False,
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
    return dt.strftime("%H:%M ET") if dt else "TBD"

def fmt_full_et(dt) -> str:
    if not dt:
        return "N/A"
    label = "EDT" if dt.dst() != timedelta(0) else "EST"
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
# CFBD — PLAY-BY-PLAY
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
        # CFBD returns all plays for the week — filter to only this game
        filtered = [p for p in data if str(p.get("gameId") or p.get("game_id") or "") == str(game_id)]
        # If gameId field isn't present in the response, return all (safe fallback)
        return filtered if filtered else data
    except Exception:
        return []

def get_events(cfbd_id: int, year: int, week: int) -> list:
    if st.session_state.cached_game_id == cfbd_id and st.session_state.cached_events is not None:
        return st.session_state.cached_events

    raw        = cfbd_fetch_plays(cfbd_id, year, week)

    # ── Temporary raw field debug (shown in game feed) ──
    if raw:
        st.session_state["_raw_play_sample"] = raw[0]

    events     = []
    prev_away  = 0
    prev_home  = 0

    for p in raw:
        period_num = p.get("period", 0)
        desc       = p.get("playText")    or p.get("play_text")   or ""
        play_type  = p.get("playType")    or p.get("play_type")   or ""
        _clock_raw = p.get("clock") or p.get("clockTime") or ""
        if isinstance(_clock_raw, dict):
            _mins = int(_clock_raw.get("minutes", 0) or 0)
            _secs = int(_clock_raw.get("seconds", 0) or 0)
            clock_val = f"{_mins:02}:{_secs:02}"
        elif isinstance(_clock_raw, str):
            clock_val = _clock_raw
        else:
            clock_val = ""
        away_sc    = int(p.get("awayScore") or p.get("away_score") or 0)
        home_sc    = int(p.get("homeScore") or p.get("home_score") or 0)
        is_score   = (away_sc != prev_away or home_sc != prev_home) and (away_sc + home_sc > 0)
        prev_away  = away_sc
        prev_home  = home_sc
        action_dt  = to_et(p.get("wallclock") or p.get("wallClock") or "")
        down       = p.get("down")     or 0
        distance   = p.get("distance") or 0
        yard_line  = p.get("yardLine") or p.get("yard_line") or 0
        offense    = p.get("offense")  or p.get("offenseTeam") or ""
        down_str   = ""
        if down > 0:
            ords     = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
            dist     = "Goal" if distance == 0 else str(distance)
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

    # Sort by wallclock ascending so plays appear in game order.
    # Falls back to period + clock for plays missing a wallclock timestamp.
    def _sort_key(e):
        if e["action_dt"]:
            return (0, e["action_dt"].timestamp(), 0, 0)
        # No wallclock — sort by period, then countdown clock descending
        # (clock counts down so 15:00 is earlier than 14:55)
        try:
            parts = e["clock_str"].split(":")
            secs_remaining = int(parts[0]) * 60 + int(parts[1])
        except Exception:
            secs_remaining = 0
        return (1, 0, e["period"], -secs_remaining)

    events.sort(key=_sort_key)

    st.session_state.cached_events  = events
    st.session_state.cached_game_id = cfbd_id
    return events

# ══════════════════════════════════════════════════════════════
# GAME FEED VIEW
# ══════════════════════════════════════════════════════════════
if st.session_state.selected_cfbd_id:

    cfbd_id   = st.session_state.selected_cfbd_id
    away_abbr = st.session_state.selected_away_abbr
    home_abbr = st.session_state.selected_home_abbr
    away_eid  = st.session_state.selected_away_eid
    home_eid  = st.session_state.selected_home_eid
    g_year    = st.session_state.get("selected_year") or datetime.today().year
    g_week    = st.session_state.get("selected_week") or 1

    if st.button("⬅ Back"):
        for k in ("cached_events", "cached_game_id", "filtered_events"):
            st.session_state[k] = None
        st.session_state.filters_applied  = False
        st.session_state.selected_cfbd_id = None
        st.rerun()

    with st.spinner("Loading play-by-play…"):
        events = get_events(cfbd_id, g_year, g_week)

    if not events:
        st.warning("No plays returned. The game may not be indexed yet, or the week number may be wrong. Try searching again with the correct week.")
        st.stop()

    live_away = events[-1]["away_score"]
    live_home = events[-1]["home_score"]

    c1, c2, c3 = st.columns([1, 6, 1])
    with c1:
        if away_eid:
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

    # Raw field inspector — helps diagnose wrong field names
    with st.expander("🛠 Raw play field debug (first play)", expanded=False):
        sample = st.session_state.get("_raw_play_sample")
        if sample:
            st.json(sample)
        else:
            st.write("No sample available.")

    st.divider()

    all_dts        = [e["action_dt"] for e in events if e["action_dt"]]
    gs_default     = min(all_dts) if all_dts else None
    ge_default     = max(all_dts) if all_dts else None
    all_periods    = sorted({e["period_label"] for e in events},
        key=lambda x: (x.startswith("OT"), int(x[1:]) if x.startswith("Q") else int(x[2:]) + 100))
    all_play_types = sorted({e["play_type"] for e in events if e["play_type"]})
    all_offenses   = sorted({e["offense"] for e in events if e["offense"]})

    USE_Q  = st.checkbox("🏈 Filter by Quarter / OT")
    USE_T  = st.checkbox("🕐 Filter by Wall-Clock Time (ET)")
    USE_SC = st.checkbox("🔥 Scoring Plays Only")
    USE_PT = st.checkbox("📋 Filter by Play Type")
    USE_TM = st.checkbox("🏟️ Filter by Possession")

    sel_quarters = sel_types = sel_offenses = []
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
    if USE_PT:
        sel_types = st.multiselect("Play types", options=all_play_types)
    if USE_TM:
        sel_offenses = st.multiselect("Offense", options=all_offenses)

    if st.button("🚀 Apply Filters"):
        def passes(e):
            if USE_Q  and sel_quarters  and e["period_label"] not in sel_quarters:  return False
            if USE_T  and START_DT and END_DT:
                if not e["action_dt"] or not (START_DT <= e["action_dt"] <= END_DT): return False
            if USE_SC and not e["is_scoring"]:                                        return False
            if USE_PT and sel_types    and e["play_type"] not in sel_types:          return False
            if USE_TM and sel_offenses and e["offense"]   not in sel_offenses:       return False
            return True
        st.session_state.filtered_events = [e for e in events if passes(e)]
        st.session_state.filters_applied = True

    fa       = st.session_state.filters_applied
    filtered = st.session_state.filtered_events if fa else events

    if fa:
        n, t = len(filtered), len(events)
        if n == 0:
            st.warning("⚠️ No plays match — adjust filters and click Apply again.")
            st.stop()
        if USE_Q:  st.info(f"🏈 Quarter: {', '.join(sel_quarters or ['none'])} — {n}/{t}")
        if USE_T and START_DT:
            st.info(f"🕐 {START_DT.strftime('%H:%M')} → {END_DT.strftime('%H:%M')} ET — {n}/{t}")
        if USE_SC: st.info(f"🔥 Scoring only — {n}/{t}")
        if USE_PT: st.info(f"📋 {', '.join(sel_types or ['none'])} — {n}/{t}")
        if USE_TM: st.info(f"🏟️ {', '.join(sel_offenses or ['none'])} — {n}/{t}")

    for e in filtered:
        st.subheader(f"{e['emoji']} {e['period_label']} | ⏱️ {e['clock_str']}")
        meta_parts = []
        if e["play_type"]: meta_parts.append(f"**{e['play_type']}**")
        if e["offense"]:   meta_parts.append(f"{e['offense']} ball")
        if meta_parts:     st.caption("  ·  ".join(meta_parts))
        st.markdown(f"📊 **Score:** {e['score_str']}" + (" &nbsp; 🔥 *Scoring Play!*" if e["is_scoring"] else ""))
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

    col_a, col_b = st.columns([3, 1])
    with col_a:
        search_team = st.text_input("Team name", placeholder="e.g. Alabama, Miami, Ohio State", label_visibility="collapsed")
    with col_b:
        search_year = st.number_input(
            "Year", min_value=2000, max_value=2030,
            value=datetime.today().year if datetime.today().month > 7 else datetime.today().year - 1,
            step=1, label_visibility="collapsed",
        )
    if st.button("🔎 Find Games", use_container_width=True):
        if not cfbd_key:
            st.error("No CFBD API key found. Add CFBD_API_KEY to your Streamlit secrets.")
        elif not search_team.strip():
            st.warning("Enter a team name first.")
        else:
            with st.spinner(f"Searching CFBD for {search_team}…"):
                try:
                    r = requests.get(
                        f"{CFBD_BASE}/games", headers=cfbd_headers(),
                        params={"year": int(search_year), "team": search_team.strip()},
                        timeout=10,
                    )
                    r.raise_for_status()
                    found = r.json()
                    st.session_state.search_results = found if isinstance(found, list) else []
                    st.session_state.search_done    = True
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
            g_date     = (g.get("startDate") or g.get("start_date") or "")[:10]
            g_away     = g.get("awayTeam")   or g.get("away_team")  or "?"
            g_home     = g.get("homeTeam")   or g.get("home_team")  or "?"
            g_away_pts = g.get("awayPoints") or g.get("away_points") or ""
            g_home_pts = g.get("homePoints") or g.get("home_points") or ""
            g_id       = g.get("id")
            g_week     = g.get("week") or "?"
            score_str  = f"  {g_away_pts}–{g_home_pts}" if g_away_pts != "" else ""
            btn_label  = f"{g_away} @ {g_home}{score_str}  ·  {g_date}  ·  Week {g_week}"

            if st.button(btn_label, key=f"pick_{g_id}", use_container_width=True):
                for k in ("cached_events", "cached_game_id", "filtered_events"):
                    st.session_state[k] = None
                st.session_state.filters_applied    = False
                st.session_state.selected_cfbd_id   = g_id
                st.session_state.selected_away_name = g_away
                st.session_state.selected_home_name = g_home
                st.session_state.selected_away_abbr = g_away[:6].upper()
                st.session_state.selected_home_abbr = g_home[:6].upper()
                st.session_state.selected_away_eid  = ""
                st.session_state.selected_home_eid  = ""
                st.session_state.selected_year      = int(g.get("season") or g.get("year") or search_year)
                st.session_state.selected_week      = int(g.get("week") or 1)
                st.session_state.search_results     = []
                st.session_state.search_done        = False
                st.rerun()
