"""
Aggregate hitting stats and streak detection, computed from raw per-game
splits returned by mlb_api.get_batting_game_log.

Rate stats (AVG/OBP/SLG/OPS) are computed from summed raw counting stats
across the window, not averaged from MLB's per-game rate fields -- same
approach as the ERA calc in the pitching bots, and the only correct way to
aggregate a rate stat over multiple games.
"""

HOT_OPS_THRESHOLD = 0.900
COLD_OPS_THRESHOLD = 0.550
MIN_GAMES_FOR_TAG = 5
MIN_PA_FOR_HOT_COLD = 20  # over the Last-10 window

# Streak thresholds worth calling out automatically
NOTABLE_HIT_STREAK = 5
NOTABLE_WALK_STREAK = 5
NOTABLE_HR_STREAK = 3


def summarize_batting(splits: list[dict], n: int) -> dict | None:
    """splits: chronological (oldest-first). n: how many most recent games."""
    recent = splits[-n:]
    if not recent:
        return None

    ab = sum(s["ab"] for s in recent)
    hits = sum(s["hits"] for s in recent)
    doubles = sum(s["doubles"] for s in recent)
    triples = sum(s["triples"] for s in recent)
    hr = sum(s["hr"] for s in recent)
    bb = sum(s["bb"] for s in recent)
    so = sum(s["so"] for s in recent)
    hbp = sum(s.get("hbp", 0) for s in recent)
    sf = sum(s.get("sf", 0) for s in recent)
    rbi = sum(s["rbi"] for s in recent)
    sb = sum(s.get("sb", 0) for s in recent)
    pa = ab + bb + hbp + sf  # standard PA approximation (omits rare sac bunts)

    avg = round(hits / ab, 3) if ab > 0 else None

    obp_denom = ab + bb + hbp + sf
    obp = round((hits + bb + hbp) / obp_denom, 3) if obp_denom > 0 else None

    singles = hits - doubles - triples - hr
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hr
    slg = round(total_bases / ab, 3) if ab > 0 else None

    ops = round(obp + slg, 3) if (obp is not None and slg is not None) else None

    return {
        "count": len(recent),
        "ab": ab, "hits": hits, "hr": hr, "rbi": rbi, "bb": bb, "so": so, "sb": sb, "pa": pa,
        "avg": avg, "obp": obp, "slg": slg, "ops": ops,
    }


def current_streak(splits: list[dict], stat_key: str) -> int:
    """
    Counts consecutive games (most recent backward) where stat_key >= 1.
    Since `splits` only contains games the player actually appeared in,
    consecutive list entries ARE consecutive games played -- an off day
    or a game they didn't play never breaks the streak, matching how hit
    streaks are conventionally counted.
    """
    streak = 0
    for s in reversed(splits):
        if s.get(stat_key, 0) >= 1:
            streak += 1
        else:
            break
    return streak


def get_active_streaks(splits: list[dict]) -> dict:
    """Returns current streak lengths for hits, walks, and home runs."""
    return {
        "hit_streak": current_streak(splits, "hits"),
        "walk_streak": current_streak(splits, "bb"),
        "hr_streak": current_streak(splits, "hr"),
    }


def notable_streak_labels(streaks: dict) -> list[str]:
    """Human-readable labels for any streak that clears the 'notable' bar."""
    labels = []
    if streaks["hit_streak"] >= NOTABLE_HIT_STREAK:
        labels.append(f"🔥 {streaks['hit_streak']}-game hit streak")
    if streaks["walk_streak"] >= NOTABLE_WALK_STREAK:
        labels.append(f"👀 Walked in {streaks['walk_streak']} straight games")
    if streaks["hr_streak"] >= NOTABLE_HR_STREAK:
        labels.append(f"💣 Homered in {streaks['hr_streak']} straight games")
    return labels


def hot_cold_tag(summary: dict | None) -> str | None:
    if not summary or summary["count"] < MIN_GAMES_FOR_TAG or summary["ops"] is None:
        return None
    if summary.get("pa", 0) < MIN_PA_FOR_HOT_COLD:
        return None
    if summary["ops"] >= HOT_OPS_THRESHOLD:
        return "🔥 Hot"
    if summary["ops"] <= COLD_OPS_THRESHOLD:
        return "🥶 Cold"
    return None
