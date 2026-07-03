"""
Thin client for the free public MLB Stats API. No key required.
"""
import requests

BASE = "https://statsapi.mlb.com/api/v1"
CURRENT_SEASON = 2026


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
