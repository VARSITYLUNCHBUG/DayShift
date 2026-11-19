"""The #leaderboard as images: ten players to a PNG, drawn in DayShift's colours and type.

Pure: rows in, PNG bytes out, no I/O but reading the bundled fonts. The fonts are Figtree and
Bricolage Grotesque (SIL Open Font License, bot/assets/fonts/), the brand's two families: Bricolage
for the title, Figtree for everything people read. Both are variable fonts, set by weight here.
"""

from __future__ import annotations

import io
from datetime import datetime
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from league.services.leaderboards import Row

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
PER_IMAGE = 10

# The brand's dark theme (docs/brand.md): ink ground, surface rows, cream text, bubblegum for
# DayShift itself. Medal colours mark the top three only.
INK = (17, 16, 25)
SURFACE = (26, 24, 36)
LINE = (50, 46, 68)
CREAM = (243, 239, 230)
MUTED = (168, 162, 181)
FAINT = (148, 142, 163)
BUBBLEGUM = (255, 141, 195)
EN_DASH = "\u2013"  # Records and ranges, the way the brand writes scores.
MEDALS = {1: (242, 193, 78), 2: (201, 206, 214), 3: (208, 138, 82)}

SCALE = 2  # Drawn at twice the size Discord shows, so it stays sharp on high-density screens.
# Wider than tall: Discord caps how tall it shows an image, so a tall one shrinks to a third of the
# message. At this shape ten rows fill the message's width.
WIDTH = 1100 * SCALE
PAD = 36 * SCALE
HEADER = 104 * SCALE
COLUMN_HEADS = 32 * SCALE
ROW = 48 * SCALE
FOOTER = 44 * SCALE

# Every image is the same size, ten row slots high, whatever it holds: one look for the channel.
HEIGHT = HEADER + COLUMN_HEADS + ROW * PER_IMAGE + FOOTER

# Where each column starts (left) or ends (right), across the 1100-wide card.
X_RANK = PAD + 24 * SCALE  # The rank badge's centre.
X_NAME = PAD + 62 * SCALE
X_RATING = 780 * SCALE  # Right edge.
X_RECORD = 920 * SCALE  # Right edge.
X_RATE = WIDTH - PAD - 24 * SCALE  # Right edge, clear of the row's end.


@cache
def _font(family: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / f"{family}.ttf"), size * SCALE)
    values: list[float] = []
    for axis in font.get_variation_axes():
        raw = axis.get("name", b"")
        name = (raw.decode() if isinstance(raw, bytes) else str(raw)).lower()
        low, high = float(axis.get("minimum") or 0), float(axis.get("maximum") or 0)
        if name == "weight":
            values.append(float(weight))
        elif name == "optical size":
            values.append(min(max(float(size), low), high))
        else:
            values.append(float(axis.get("default") or low))
    font.set_variation_by_axes(values)
    return font


def _title(size: int) -> ImageFont.FreeTypeFont:
    return _font("BricolageGrotesque", size, 800)


def _text(size: int, weight: int = 500) -> ImageFont.FreeTypeFont:
    return _font("Figtree", size, weight)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    """The name, cut with an ellipsis to fit its column."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _mark(draw: ImageDraw.ImageDraw, right: int, top: int) -> None:
    """The DayShift mark: three kit stripes, bubblegum, cream, bubblegum, leaning 14 degrees."""
    height, width, gap, lean = 44 * SCALE, 9 * SCALE, 5 * SCALE, 11 * SCALE
    x = right - 3 * width - 2 * gap - lean
    for colour in (BUBBLEGUM, CREAM, BUBBLEGUM):
        draw.polygon(
            [
                (x + lean, top),
                (x + lean + width, top),
                (x + width, top + height),
                (x, top + height),
            ],
            fill=colour,
        )
        x += width + gap


def _rank_badge(draw: ImageDraw.ImageDraw, rank: int, centre_y: int) -> None:
    radius = 16 * SCALE
    box = (X_RANK - radius, centre_y - radius, X_RANK + radius, centre_y + radius)
    medal = MEDALS.get(rank)
    if medal:
        draw.ellipse(box, fill=medal)
        colour = INK
    else:
        draw.ellipse(box, outline=LINE, width=2 * SCALE)
        colour = MUTED
    font = _text(16 if rank < 100 else 13, 800)
    draw.text((X_RANK, centre_y), str(rank), font=font, fill=colour, anchor="mm")


def render(
    rows: list[Row],
    *,
    season_name: str,
    rating_label: str,
    total: int,
    updated_at: datetime,
) -> bytes:
    """One image: up to ten rows, under the title and the range they cover. Always the same
    size: slots a short page doesn't use stay as empty table rows."""
    height = HEIGHT
    image = Image.new("RGB", (WIDTH, height), INK)
    draw = ImageDraw.Draw(image)

    # A bubblegum edge down the left, the brand's mark for a DayShift moment.
    draw.rectangle((0, 0, 6 * SCALE, height), fill=BUBBLEGUM)
    draw.text((PAD, 20 * SCALE), "Leaderboard", font=_title(40), fill=CREAM)
    first, last = (rows[0].rank, rows[-1].rank) if rows else (0, 0)
    span = f"{first}{EN_DASH}{last} of {total}" if rows else "0 players"
    draw.text(
        (PAD, 72 * SCALE),
        f"{season_name}  ·  {rating_label}  ·  {span}",
        font=_text(16, 600),
        fill=MUTED,
    )
    _mark(draw, WIDTH - PAD, 30 * SCALE)

    # Column headings.
    y = HEADER + COLUMN_HEADS // 2
    heads = _text(13, 700)
    draw.text((X_NAME, y), "PLAYER", font=heads, fill=FAINT, anchor="lm")
    draw.text((X_RATING, y), rating_label.upper(), font=heads, fill=FAINT, anchor="rm")
    draw.text((X_RECORD, y), f"W{EN_DASH}L", font=heads, fill=FAINT, anchor="rm")
    draw.text((X_RATE, y), "WIN %", font=heads, fill=FAINT, anchor="rm")
    draw.line((PAD, HEADER + COLUMN_HEADS, WIDTH - PAD, HEADER + COLUMN_HEADS), fill=LINE, width=2)

    name_font = _text(24, 600)
    number_font = _text(24, 800)
    small_font = _text(20, 600)
    for slot in range(PER_IMAGE):
        if slot % 2 == 0:
            top = HEADER + COLUMN_HEADS + slot * ROW
            draw.rectangle((PAD, top, WIDTH - PAD, top + ROW), fill=SURFACE)
    if not rows:
        middle = HEADER + COLUMN_HEADS + ROW * PER_IMAGE // 2
        empty = "Nobody has played yet."
        draw.text((WIDTH // 2, middle), empty, font=name_font, fill=MUTED, anchor="mm")
    for index, row in enumerate(rows):
        top = HEADER + COLUMN_HEADS + index * ROW
        middle = top + ROW // 2
        _rank_badge(draw, row.rank, middle)
        name = _fit(draw, row.name, name_font, X_RATING - X_NAME - 120 * SCALE)
        draw.text((X_NAME, middle), name, font=name_font, fill=CREAM, anchor="lm")
        draw.text((X_RATING, middle), str(row.rating), font=number_font, fill=CREAM, anchor="rm")
        record = f"{row.wins}{EN_DASH}{row.losses}"
        draw.text((X_RECORD, middle), record, font=small_font, fill=MUTED, anchor="rm")
        rate = row.win_rate
        label = EN_DASH if rate is None else f"{rate:.0%}"
        draw.text((X_RATE, middle), label, font=small_font, fill=CREAM, anchor="rm")

    footer_y = height - FOOTER // 2
    stamp = updated_at.strftime("%d %b %Y, %H:%M UTC").lstrip("0")
    draw.text(
        (PAD, footer_y),
        f"Updated {stamp}  ·  refreshes every hour",
        font=_text(14, 500),
        fill=FAINT,
        anchor="lm",
    )
    draw.text((WIDTH - PAD, footer_y), "DAYSHIFT", font=_text(14, 800), fill=FAINT, anchor="rm")

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def split(rows: list[Row]) -> list[list[Row]]:
    """As few groups as fit `PER_IMAGE` each, their sizes differing by one at most, the larger
    ones first."""
    count = max(1, -(-len(rows) // PER_IMAGE))
    size, extra = divmod(len(rows), count)
    groups, start = [], 0
    for index in range(count):
        end = start + size + (1 if index < extra else 0)
        groups.append(rows[start:end])
        start = end
    return groups


def images(
    rows: list[Row], *, season_name: str, rating_label: str, updated_at: datetime
) -> list[bytes]:
    """Every player, highest first, over as few images as hold ten each, shared out evenly: 23
    players are 8, 8 and 7, not 10, 10 and 3. One image even when nobody has played."""
    groups = split(rows)
    return [
        render(
            group,
            season_name=season_name,
            rating_label=rating_label,
            total=len(rows),
            updated_at=updated_at,
        )
        for group in groups
    ]
