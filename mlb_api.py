"""
Thin client for the free public MLB Stats API. No key required.
"""
import requests

BASE = "https://statsapi.mlb.com/api/v1"
CURRENT_SEASON = 2026


def get_live_games(date_str: str) -> list[dict]:
    """Today's schedule with basic game state info."""
    resp = requests.get(
        f"{BASE}/schedule",
        params={"sportId": 1, "date": date_str},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    games = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            games.append({
                "game_pk": g["gamePk"],
                "abstract_state": g["status"].get("abstractGameState"),
                "away_team": g["teams"]["away"]["team"]["name"],
                "home_team": g["teams"]["home"]["team"]["name"],
            })
    return games


def get_lineup(game_pk: int) -> dict:
    """
    Returns each side's confirmed starting lineup INDEPENDENTLY:
      {"away": {...} | None, "home": {...} | None}
    A side is None until its batting order is officially posted.

    July 18 change: previously this returned None unless BOTH sides were
    posted, which made the lineup poster wait for the slower team --
    sometimes an hour after the first lineup dropped. Teams post lineups
    independently, and for betting purposes the FIRST lineup is the
    time-sensitive one, so each side now stands alone.
    """
    resp = requests.get(f"{BASE}/game/{game_pk}/boxscore", timeout=15)
    resp.raise_for_status()
    data = resp.json()

    teams = data.get("teams", {})
    result = {"away": None, "home": None}
    for side in ("away", "home"):
        team_data = teams.get(side, {})
        batting_order = team_data.get("battingOrder", [])
        if not batting_order:
            continue  # this side not posted yet; the other may still be

        players = team_data.get("players", {})
        lineup = []
        for pid in batting_order:
            p = players.get(f"ID{pid}", {})
            person = p.get("person", {})
            position = (p.get("position") or {}).get("abbreviation", "?")
            lineup.append({"name": person.get("fullName", "Unknown"), "position": position})

        result[side] = {
            "team_name": (team_data.get("team") or {}).get("name", "?"),
            "lineup": lineup,
        }

    return result


def get_stat_leaders(category: str, limit: int = 10, season: int = CURRENT_SEASON) -> list[dict]:
    """Fetches league-wide stat leaders for a given category (e.g. 'homeRuns',
    'battingAverage'). Category names are camelCase MLB stat field names."""
    resp = requests.get(
        f"{BASE}/stats/leaders",
        params={"leaderCategories": category, "season": season, "limit": limit,
                "sportId": 1, "statGroup": "hitting"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    leaders = []
    for cat in data.get("leagueLeaders", []):
        for leader in cat.get("leaders", []):
            leaders.append({
                "rank": leader.get("rank"),
                "name": (leader.get("person") or {}).get("fullName"),
                "team": (leader.get("team") or {}).get("abbreviation"),
                "value": leader.get("value"),
            })
    return leaders


def get_situation_codes() -> list[dict]:
    """Fetches the real list of valid sitCodes directly from MLB, so we
    confirm the actual code strings instead of guessing at them."""
    resp = requests.get(f"{BASE}/situationCodes", timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_all_teams() -> list[dict]:
    resp = requests.get(f"{BASE}/teams", params={"sportId": 1}, timeout=15)
    resp.raise_for_status()
    return [
        {"id": t["id"], "name": t["name"], "abbreviation": t["abbreviation"]}
        for t in resp.json().get("teams", [])
    ]


def get_active_roster_hitters(team_id: int) -> list[dict]:
    """Active roster position players (excludes pitchers)."""
    resp = requests.get(
        f"{BASE}/teams/{team_id}/roster", params={"rosterType": "active"}, timeout=15
    )
    resp.raise_for_status()
    hitters = []
    for entry in resp.json().get("roster", []):
        pos = (entry.get("position") or {}).get("abbreviation")
        if pos and pos != "P":
            hitters.append({"id": entry["person"]["id"], "name": entry["person"]["fullName"]})
    return hitters


def get_batting_game_log(person_id: int, season: int = CURRENT_SEASON) -> list[dict]:
    """
    Every game this player has batted in this season, sorted chronologically
    (oldest first, most recent last).
    """
    resp = requests.get(
        f"{BASE}/people/{person_id}/stats",
        params={"stats": "gameLog", "group": "hitting", "season": season, "gameType": "R"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    splits = []
    for stat_block in data.get("stats", []):
        for split in stat_block.get("splits", []):
            stat = split.get("stat", {}) or {}
            splits.append({
                "date": split.get("date"),
                "opponent": (split.get("opponent") or {}).get("name"),
                "ab": stat.get("atBats", 0),
                "hits": stat.get("hits", 0),
                "doubles": stat.get("doubles", 0),
                "triples": stat.get("triples", 0),
                "hr": stat.get("homeRuns", 0),
                "rbi": stat.get("rbi", 0),
                "bb": stat.get("baseOnBalls", 0),
                "so": stat.get("strikeOuts", 0),
                "hbp": stat.get("hitByPitch", 0),
                "sf": stat.get("sacFlies", 0),
                "sb": stat.get("stolenBases", 0),
            })

    splits.sort(key=lambda s: s["date"] or "")
    return splits


def get_platoon_splits(person_id: int, season: int = CURRENT_SEASON) -> dict:
    """
    Season-to-date performance vs LHP and vs RHP. This is a season aggregate
    (not a rolling window) -- computing a rolling platoon split would require
    cross-referencing every opposing starter's handedness per game, which
    isn't reliable to build. Season splits are also the standard way this
    is used in betting/analysis content anyway.
    """
    resp = requests.get(
        f"{BASE}/people/{person_id}/stats",
        params={"stats": "statSplits", "group": "hitting", "season": season,
                "sitCodes": "vl,vr", "gameType": "R"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    result = {"vs_lhp": None, "vs_rhp": None}
    for stat_block in data.get("stats", []):
        for split in stat_block.get("splits", []):
            code = (split.get("split") or {}).get("code")
            stat = split.get("stat", {}) or {}
            parsed = {
                "ab": stat.get("atBats", 0),
                "hits": stat.get("hits", 0),
                "hr": stat.get("homeRuns", 0),
                "rbi": stat.get("rbi", 0),
                "avg": stat.get("avg"),
                "obp": stat.get("obp"),
                "slg": stat.get("slg"),
                "ops": stat.get("ops"),
            }
            if code == "vl":
                result["vs_lhp"] = parsed
            elif code == "vr":
                result["vs_rhp"] = parsed
    return result
