"""
Generates a visual "mini Savant-style" player card as a PNG image.

IMPORTANT: this uses AVG/OBP/SLG/OPS/HR/RBI -- stats already reliably pulled
from MLB's Stats API -- NOT true Statcast percentiles (xwOBA, barrel%, exit
velo, chase%, etc). Real Savant percentile cards rank a player against every
qualified hitter in MLB using deep batted-ball data, which isn't something
this bot can reliably compute. The colored bars here are scaled against
fixed, reasonable MLB-wide ranges, not true percentile ranks -- labeled
honestly rather than pretending to be something they're not.
"""
from PIL import Image, ImageDraw, ImageFont
import io
import os
import requests

WIDTH, HEIGHT = 760, 660
PHOTO_SIZE = 170
LOGO_SIZE = 55
BG_COLOR = (15, 20, 30)
CARD_COLOR = (25, 32, 45)
WHITE = (240, 240, 240)
GREY = (150, 155, 165)

# (label, low, high) -- the range each stat's bar is scaled against.
# These are reasonable fixed MLB-wide bounds, not computed percentiles.
STAT_RANGES = {
    "avg": ("AVG", 0.150, 0.350),
    "obp": ("OBP", 0.250, 0.450),
    "slg": ("SLG", 0.300, 0.650),
    "ops": ("OPS", 0.550, 1.050),
}


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold
        else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)  # safe fallback if fonts aren't installed


def _fetch_headshot(player_id: int, size: int = PHOTO_SIZE) -> Image.Image | None:
    """Fetches an MLB player headshot. Returns None on any failure -- a
    missing photo should never break the card."""
    try:
        url = f"https://img.mlbstatic.com/mlb-photos/image/upload/w_{size},q_auto:best/v1/people/{player_id}/headshot/67/current"
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return img.resize((size, size))
    except Exception:
        return None


def _load_logo() -> Image.Image | None:
    """Loads the LiveBetMike logo badge. Returns None if the file isn't
    present -- a missing logo should never break card generation."""
    try:
        path = os.path.join(os.path.dirname(__file__), "logo.png")
        return Image.open(path).convert("RGB").resize((LOGO_SIZE, LOGO_SIZE))
    except Exception:
        return None


def _color_for_ratio(ratio: float) -> tuple:
    """Red -> yellow -> green gradient based on a 0-1 ratio."""
    ratio = max(0.0, min(1.0, ratio))
    if ratio < 0.5:
        t = ratio / 0.5
        r, g, b = 200, int(60 + t * 140), 60
    else:
        t = (ratio - 0.5) / 0.5
        r, g, b = int(200 - t * 150), 200, 60
    return (r, g, b)


def build_hitter_card(name: str, team: str, season: dict, tag: str | None,
                       streaks: list[str] | None = None, player_id: int | None = None) -> bytes:
    """
    season: the dict from stats_hitting.summarize_batting (has avg/obp/slg/ops/hr/rbi/count)
    tag: hot/cold tag string or None
    streaks: list of notable streak label strings
    player_id: MLB person ID, used to fetch a headshot photo (optional -- card
               still renders fine without one if the fetch fails)

    Returns PNG image bytes, ready to attach to a Discord message.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title = _load_font(34, bold=True)
    font_sub = _load_font(18)
    font_label = _load_font(20, bold=True)
    font_value = _load_font(20, bold=True)
    font_small = _load_font(16)

    # Photo, top-right
    if player_id:
        photo = _fetch_headshot(player_id)
        if photo:
            photo_x = WIDTH - PHOTO_SIZE - 30
            mask = Image.new("L", (PHOTO_SIZE, PHOTO_SIZE), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, PHOTO_SIZE, PHOTO_SIZE), radius=16, fill=255)
            img.paste(photo, (photo_x, 25), mask)

    # Header
    draw.text((30, 25), name, font=font_title, fill=WHITE)
    draw.text((30, 68), f"{team} • {season.get('count', 0)} games this season", font=font_sub, fill=GREY)

    if tag:
        tag_color = (200, 60, 60) if "Cold" in tag else (60, 180, 90)
        draw.rounded_rectangle((30, 100, 230, 138), radius=8, fill=tag_color)
        draw.text((45, 108), tag, font=font_label, fill=WHITE)

    # Stat bars
    y = 210
    bar_x = 230
    bar_width = 380
    bar_height = 34

    for key, (label, low, high) in STAT_RANGES.items():
        value = season.get(key)
        draw.text((30, y + 6), label, font=font_label, fill=WHITE)

        draw.rounded_rectangle((bar_x, y, bar_x + bar_width, y + bar_height), radius=6, fill=CARD_COLOR)
        if value is not None:
            ratio = (value - low) / (high - low)
            ratio = max(0.02, min(1.0, ratio))
            fill_width = int(bar_width * ratio)
            draw.rounded_rectangle(
                (bar_x, y, bar_x + max(fill_width, 20), y + bar_height),
                radius=6, fill=_color_for_ratio(ratio),
            )
            draw.text((bar_x + bar_width + 15, y + 6), f"{value:.3f}", font=font_value, fill=WHITE)
        else:
            draw.text((bar_x + bar_width + 15, y + 6), "--", font=font_value, fill=GREY)

        y += bar_height + 16

    # HR / RBI as simple stat boxes (no bar, just numbers -- counting stats
    # don't scale the same way rate stats do)
    box_y = y + 10
    for i, (label, key) in enumerate((("HR", "hr"), ("RBI", "rbi"))):
        box_x = 30 + i * 200
        draw.rounded_rectangle((box_x, box_y, box_x + 180, box_y + 70), radius=8, fill=CARD_COLOR)
        draw.text((box_x + 15, box_y + 10), label, font=font_small, fill=GREY)
        draw.text((box_x + 15, box_y + 30), str(season.get(key, 0)), font=font_title, fill=WHITE)

    # Streaks
    if streaks:
        streak_y = box_y + 95
        draw.text((30, streak_y), "Active Streaks", font=font_label, fill=WHITE)
        for i, s in enumerate(streaks[:3]):
            draw.text((30, streak_y + 35 + i * 26), s, font=font_small, fill=GREY)

    logo = _load_logo()
    footer_text_x = 30
    if logo:
        mask = Image.new("L", (LOGO_SIZE, LOGO_SIZE), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, LOGO_SIZE, LOGO_SIZE), radius=10, fill=255)
        img.paste(logo, (30, HEIGHT - LOGO_SIZE - 15), mask)
        footer_text_x = 30 + LOGO_SIZE + 12

    draw.text((footer_text_x, HEIGHT - 48), "@LiveBetMike", font=font_label, fill=(80, 190, 235))
    draw.text((footer_text_x, HEIGHT - 24), "Data: MLB Stats API (not Statcast percentiles)", font=font_small, fill=GREY)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
