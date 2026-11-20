"""A player's highlight card: a 1200 x 630 PNG to share from their profile.

The card shows the hero they play most (art from the pack in league/static/hero-art/), their name,
rating and tier (or the interim's points), record, place on the ladder, top three heroes and
latest award, and the DayShift mark. The player can leave out the rating, the place or the award.

`card_data` reads the league's own read models (`boards.player_stats`, which places the player as
the #leaderboard does, MatchAward, and heroes from the postgame data or the scoreboard reads).
`shown` applies the player's choices, and `compose` draws: pure apart from reading fonts and art.
Names in any script fall back letter by letter to the system's fonts, as the bot's leaderboard
images do.
"""

from __future__ import annotations

import io
import math
import os
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

from django.db.models import Max
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from league.domain.engine import Status
from league.models import (
    Champion,
    Community,
    MatchAward,
    MatchParticipant,
    MatchPostgame,
    Player,
    PlayerMatchStat,
    Season,
)
from league.models.scoreboards import AwardKind
from league.services import boards, hero_art

FONTS = Path(__file__).resolve().parent.parent.parent / "bot" / "assets" / "fonts"
WIDTH, HEIGHT = 1200, 630
TOP_HEROES = 3

# DayShift's dark theme. Bubblegum is the mark's alone; the two sides' colours carry the accents.
INK = (17, 16, 25)
SURFACE = (26, 24, 36)
RAISED = (35, 32, 49)
LINE = (50, 46, 68)
CREAM = (243, 239, 230)
MUTED = (168, 162, 181)
FAINT = (148, 142, 163)
BUBBLEGUM = (255, 141, 195)
AMBER = (227, 162, 59)  # The Hidden King.
AMBER_INK = (26, 18, 6)
BLUE = (94, 146, 232)  # The Archmother.
BLUE_INK = (11, 18, 34)
EN_DASH = "\u2013"
CREDIT = "Hero art \u00a9 Valve"

LEAN = math.tan(math.radians(14))  # Everything DayShift leans 14 degrees.
PAD = 64
ART_FOOT = 700  # Where the art panel's slanted edge meets the bottom.
ART_TOP = ART_FOOT + round(LEAN * HEIGHT)  # And the top: the slant runs ahead going up.
CONTENT_RIGHT = ART_FOOT - 40  # Text stays clear of the art all the way down.


@dataclass(frozen=True, slots=True)
class HeroLine:
    name: str
    slug: str  # The art key; "" when the pack has no art for it.
    games: int


@dataclass(frozen=True, slots=True)
class CardData:
    """Everything the card can show, before the player's choices."""

    name: str
    season: str = ""
    rating_label: str = "Rating"  # "Rating", or "Points" while the interim runs.
    rating: int | None = None
    tier: str = ""  # OpenSkill seasons only.
    wins: int = 0
    losses: int = 0
    place: int | None = None  # On the #leaderboard.
    ranked: int = 0  # How many players the leaderboard lists.
    heroes: list[HeroLine] = field(default_factory=list)  # Most played first.
    award: str = ""  # The latest award's name: "MVP" or "Key player".


@dataclass(frozen=True, slots=True)
class Shown:
    """What the card draws: `CardData` with the hidden parts taken out."""

    data: CardData
    show_rating: bool
    show_place: bool
    show_award: bool


# --- Reading the league ----------------------------------------------------------------------


def _community_of(player: Player) -> Community | None:
    """The server the player last played on, else the only one there is."""
    last = (
        MatchParticipant.objects.filter(player=player)
        .select_related("match__community")
        .order_by("-match_id")
        .first()
    )
    if last is not None:
        return last.match.community
    return Community.objects.order_by("pk").first()


def _season_for(player: Player) -> Season | None:
    community = _community_of(player)
    if community is None:
        return None
    return Season.objects.filter(community=community, ended_at__isnull=True).first()


def _completed_matches(player: Player) -> list[int]:
    return list(
        MatchParticipant.objects.filter(
            player=player, removed_reason="", match__status=Status.COMPLETED
        )
        .order_by("match_id")
        .values_list("match_id", flat=True)
    )


def hero_counts(player: Player, match_ids: Iterable[int]) -> Counter[int]:
    """Champion ID to games, one hero a match: from the postgame data where a match has it, else
    the latest scoreboard read that matched this player."""
    ids = list(match_ids)
    played: dict[int, int] = {}
    for match_id, data in MatchPostgame.objects.filter(match_id__in=ids).values_list(
        "match_id", "data"
    ):
        for line in (data or {}).get("players", []) if isinstance(data, dict) else []:
            if isinstance(line, dict) and line.get("player_id") == player.pk:
                hero_id = line.get("hero_id")
                if isinstance(hero_id, int):
                    played[match_id] = hero_id
    rows = (
        PlayerMatchStat.objects.filter(player=player, match_id__in=ids, hero__isnull=False)
        .exclude(match_id__in=list(played))
        .order_by("match_id", "read_id")
        .values_list("match_id", "hero_id")
    )
    for match_id, hero_id in rows:  # The latest read of a match wins.
        if hero_id is not None:
            played[match_id] = hero_id
    return Counter(played.values())


def last_award(player: Player) -> str:
    """The player's most recent current award: "MVP", "Key player", or "" for none."""
    mine = MatchAward.objects.filter(player=player).exclude(kind="")
    match_ids = set(mine.values_list("match_id", flat=True))
    if not match_ids:
        return ""
    latest = dict(
        MatchAward.objects.filter(match_id__in=match_ids)
        .values("match_id")
        .annotate(top=Max("revision"))
        .values_list("match_id", "top")
    )
    current = [
        (match_id, kind)
        for match_id, revision, kind in mine.values_list("match_id", "revision", "kind")
        if latest.get(match_id) == revision
    ]
    if not current:
        return ""
    _match_id, kind = max(current)
    return str(AwardKind(kind).label)


def card_data(player: Player, season: Season | None = None) -> CardData:
    season = season or _season_for(player)
    champions = {
        pk: (name, slug) for pk, name, slug in Champion.objects.values_list("pk", "name", "slug")
    }
    counts = hero_counts(player, _completed_matches(player))
    art = hero_art.available()
    top = []
    for hero_id, games in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_HEROES]:
        name, slug = champions.get(hero_id, (f"Hero {hero_id}", ""))
        top.append(HeroLine(name=name, slug=slug if slug in art else "", games=games))
    base = CardData(name=player.display_name, heroes=top, award=last_award(player))
    if season is None:
        return base
    stats = boards.player_stats(season, player)
    return replace(
        base,
        season=stats.season,
        rating_label=stats.rating_label,
        rating=stats.rating,
        tier=stats.tier,
        wins=stats.wins,
        losses=stats.losses,
        place=stats.rank,
        ranked=stats.ranked,
    )


def render(
    player: Player,
    *,
    show_rating: bool = True,
    show_place: bool = True,
    show_award: bool = True,
    season: Season | None = None,
) -> bytes:
    """The player's card as PNG bytes. `season` defaults to the open season where they last
    played."""
    data = card_data(player, season)
    image, _texts = compose(shown(data, show_rating, show_place, show_award))
    return to_png(image)


def shown(data: CardData, show_rating: bool, show_place: bool, show_award: bool) -> Shown:
    return Shown(
        data=data,
        show_rating=show_rating and data.rating is not None,
        show_place=show_place and data.place is not None,
        show_award=show_award and bool(data.award),
    )


# --- Text in any script ----------------------------------------------------------------------
# The brand's fonts cover Latin only, and names are anything. Each character is drawn in the
# first font that has it: the brand font, then the system's (the image installs Noto and an emoji
# font), colour emoji last. The same approach as the bot's images (bot/renderers/fonts.py),
# kept here because league code never imports the bot.

FONT_DIRS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
)
FALLBACKS = (
    "NotoSans-Regular",
    "NotoSansMath-Regular",
    "NotoSansSymbols-Regular",
    "NotoSansSymbols2-Regular",
    "NotoSansCJK-Regular",
    "NotoSansCJKjp-Regular",
    "DejaVuSans",
    "segoeui",
    "seguisym",
    "msyh",
    "malgun",
    "YuGothR",
    "Nirmala",
)
EMOJI_FONTS = ("NotoColorEmoji", "seguiemj")
EMOJI_BITMAP_SIZE = 109  # Noto's colour emoji has this one size; it's drawn at it and scaled.
ELLIPSIS = chr(0x2026)


@dataclass(frozen=True, slots=True)
class _Face:
    path: str
    emoji: bool = False


@cache
def _font_files() -> dict[str, str]:
    found: dict[str, str] = {}
    for folder in FONT_DIRS:
        if not folder.is_dir():
            continue
        for root, _dirs, names in os.walk(folder):
            for name in names:
                stem, extension = os.path.splitext(name)
                if extension.lower() in {".ttf", ".otf", ".ttc"}:
                    found.setdefault(stem.lower(), os.path.join(root, name))
    return found


@cache
def _coverage(path: str) -> frozenset[int]:
    try:
        font = TTFont(path, fontNumber=0, lazy=True)
        cmap = font.getBestCmap() or {}
        font.close()
    except Exception:  # An unreadable font file is no fallback, nothing worse.
        return frozenset()
    return frozenset(cmap)


@cache
def _chain() -> tuple[_Face, ...]:
    files = _font_files()
    faces = [_Face(files[name.lower()]) for name in FALLBACKS if name.lower() in files]
    faces += [_Face(files[n.lower()], emoji=True) for n in EMOJI_FONTS if n.lower() in files]
    return tuple(faces)


@cache
def _face_for(char: str, primary: str) -> _Face | None:
    """The first font that draws `char`; None for the brand font itself, or when none does."""
    point = ord(char)
    if point in _coverage(primary):
        return None
    chain = _chain()
    if unicodedata.category(char) == "So" and point >= 0x1F000:
        chain = tuple(sorted(chain, key=lambda face: not face.emoji))  # Colour emoji first.
    return next((face for face in chain if point in _coverage(face.path)), None)


def _clings(char: str) -> bool:
    """Joiners, variation selectors, skin tones and combining marks stay with the character
    before them."""
    point = ord(char)
    return (
        point in {0x200D, 0xFE0E, 0xFE0F, 0x20E3}
        or 0x1F3FB <= point <= 0x1F3FF
        or bool(unicodedata.combining(char))
    )


def _runs(text: str, primary: str) -> list[tuple[_Face | None, str]]:
    out: list[tuple[_Face | None, str]] = []
    current: _Face | None = None
    buffer = ""
    for char in text:
        face = current if buffer and _clings(char) else _face_for(char, primary)
        if buffer and face != current:
            out.append((current, buffer))
            buffer = ""
        current = face
        buffer += char
    if buffer:
        out.append((current, buffer))
    return out


@cache
def _load(face: _Face, size: int) -> ImageFont.FreeTypeFont:
    if face.emoji:
        try:
            return ImageFont.truetype(face.path, EMOJI_BITMAP_SIZE)
        except OSError:
            pass  # A scalable emoji font (Segoe UI Emoji) takes any size.
    return ImageFont.truetype(face.path, size)


class _Writer:
    """Draws one string, in the brand font with fallbacks, at one anchor."""

    def __init__(self, image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        self.image = image
        self.draw = draw

    def _pieces(
        self, text: str, font: ImageFont.FreeTypeFont
    ) -> list[tuple[str, ImageFont.FreeTypeFont, float, bool]]:
        out = []
        for face, chunk in _runs(text, str(font.path)):
            if face is None:
                out.append((chunk, font, self.draw.textlength(chunk, font=font), False))
                continue
            loaded = _load(face, int(font.size))
            width = self.draw.textlength(chunk, font=loaded, embedded_color=face.emoji)
            if face.emoji and loaded.size != font.size:
                width *= font.size / loaded.size
            out.append((chunk, loaded, width, face.emoji))
        return out

    def length(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        return sum(width for _text, _font, width, _emoji in self._pieces(text, font))

    def fit(self, text: str, font: ImageFont.FreeTypeFont, width: float) -> str:
        """`text`, cut with an ellipsis to fit `width`."""
        if self.length(text, font) <= width:
            return text
        while text and self.length(text + ELLIPSIS, font) > width:
            text = text[:-1]
        return text.rstrip() + ELLIPSIS

    def text(
        self,
        xy: tuple[float, float],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple[int, int, int],
        anchor: str = "la",
    ) -> None:
        """Pillow's draw.text for anchors l, m or r across and a, m or s down."""
        pieces = self._pieces(text, font)
        if all(piece_font is font for _t, piece_font, _w, _e in pieces):
            self.draw.text(xy, text, font=font, fill=fill, anchor=anchor)
            return
        total = sum(width for _t, _f, width, _e in pieces)
        x, y = xy
        x -= {"l": 0, "m": total / 2, "r": total}[anchor[0]]
        ascent, descent = font.getmetrics()
        baseline = {"a": y + ascent, "m": y + (ascent - descent) / 2, "s": y}[anchor[1]]
        for chunk, piece_font, width, emoji in pieces:
            if emoji:
                self._emoji(x, baseline, chunk, piece_font, font)
            else:
                self.draw.text((x, baseline), chunk, font=piece_font, fill=fill, anchor="ls")
            x += width

    def _emoji(
        self,
        x: float,
        baseline: float,
        chunk: str,
        emoji_font: ImageFont.FreeTypeFont,
        font: ImageFont.FreeTypeFont,
    ) -> None:
        """Colour emoji, drawn at the emoji font's own size and scaled to sit on the line."""
        natural = self.draw.textlength(chunk, font=emoji_font, embedded_color=True)
        ascent, descent = emoji_font.getmetrics()
        canvas = Image.new("RGBA", (max(1, int(natural) + 2), ascent + descent), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text(
            (0, ascent), chunk, font=emoji_font, embedded_color=True, anchor="ls"
        )
        scale = font.size / emoji_font.size
        size = (max(1, round(canvas.width * scale)), max(1, round(canvas.height * scale)))
        scaled = canvas.resize(size, Image.Resampling.LANCZOS)
        self.image.paste(scaled, (round(x), round(baseline - ascent * scale)), scaled)


# --- Drawing ---------------------------------------------------------------------------------


@cache
def _font(family: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / f"{family}.ttf"), size)
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


def _display(size: int) -> ImageFont.FreeTypeFont:
    return _font("BricolageGrotesque", size, 800)


def _body(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    return _font("Figtree", size, weight)


@cache
def _art(slug: str) -> Image.Image | None:
    path = hero_art.art_file(slug)
    if not slug or not path.is_file():
        return None
    with Image.open(path) as image:
        return image.convert("RGBA")


def _cover(image: Image.Image, width: int, height: int, focus_y: float = 0.15) -> Image.Image:
    """`image` scaled to cover width x height, cropped around the middle across and `focus_y`
    down, as CSS object-fit: cover does."""
    scale = max(width / image.width, height / image.height)
    scaled = image.resize(
        (math.ceil(image.width * scale), math.ceil(image.height * scale)), Image.Resampling.LANCZOS
    )
    left = (scaled.width - width) // 2
    top = round((scaled.height - height) * focus_y)
    return scaled.crop((left, top, left + width, top + height))


def _mark(draw: ImageDraw.ImageDraw, left: float, top: float, height: float) -> float:
    """The DayShift mark: three stripes, bubblegum, cream, bubblegum, 2u wide with 1u gaps,
    leaning 14 degrees. Returns its right edge."""
    unit = height / 100 * 11  # The brand's u: the cap height is 100, a stripe 22 and a gap 11.
    stripe, gap, lean = 2 * unit, unit, LEAN * height
    x = left
    for colour in (BUBBLEGUM, CREAM, BUBBLEGUM):
        draw.polygon(
            [
                (x + lean, top),
                (x + lean + stripe, top),
                (x + stripe, top + height),
                (x, top + height),
            ],
            fill=colour,
        )
        x += stripe + gap
    return x - gap + lean


def _pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    ink: tuple[int, int, int],
) -> float:
    """A rounded label, its left edge at x and its middle at y. Returns its right edge."""
    x, y = xy
    width = draw.textlength(text, font=font) + 32
    height = font.size + 20
    shadow = (x, y - height / 2 + 4, x + width, y + height / 2 + 4)
    draw.rounded_rectangle(shadow, radius=height / 2, fill=(0, 0, 0))
    draw.rounded_rectangle(
        (x, y - height / 2, x + width, y + height / 2), radius=height / 2, fill=fill
    )
    draw.text((x + 16, y), text, font=font, fill=ink, anchor="lm")
    return x + width


def _art_panel(image: Image.Image, slug: str) -> None:
    """The most-played hero down the right, behind a 14-degree edge."""
    width = WIDTH - ART_FOOT
    mask = Image.new("L", (width, HEIGHT), 0)
    ImageDraw.Draw(mask).polygon(
        [(ART_TOP - ART_FOOT, 0), (width, 0), (width, HEIGHT), (0, HEIGHT)], fill=255
    )
    art = _art(slug)
    if art is None:
        panel = Image.new("RGBA", (width, HEIGHT), (*RAISED, 255))
        draw = ImageDraw.Draw(panel)
        _mark(draw, width / 2 - 70, HEIGHT / 2 - 80, 160)
    else:
        panel = Image.new("RGBA", (width, HEIGHT), (*SURFACE, 255))
        panel.alpha_composite(_cover(art, width, HEIGHT))
    image.paste(panel.convert("RGB"), (ART_FOOT, 0), mask)


def _thumb(image: Image.Image, slug: str, xy: tuple[int, int], size: tuple[int, int]) -> None:
    width, height = size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=255)
    art = _art(slug)
    if art is None:
        tile = Image.new("RGB", size, RAISED)
    else:
        backed = Image.new("RGBA", size, (*SURFACE, 255))
        backed.alpha_composite(_cover(art, width, height))
        tile = backed.convert("RGB")
    image.paste(tile, xy, mask)


def compose(card: Shown) -> tuple[Image.Image, list[str]]:
    """The card, and every string drawn on it (for the tests: what's hidden isn't there)."""
    data = card.data
    image = Image.new("RGB", (WIDTH, HEIGHT), INK)
    draw = ImageDraw.Draw(image)
    write = _Writer(image, draw)
    texts: list[str] = []

    def text(
        xy: tuple[float, float],
        value: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple[int, int, int],
        anchor: str = "ls",
        width: float | None = None,
    ) -> float:
        shown_text = write.fit(value, font, width) if width is not None else value
        write.text(xy, shown_text, font=font, fill=fill, anchor=anchor)
        texts.append(shown_text)
        return xy[0] + write.length(shown_text, font)

    _art_panel(image, data.heroes[0].slug if data.heroes else "")

    # The mark and the name of the place.
    right = _mark(draw, PAD, 52, 40)
    text((right + 16, 88), "DAYSHIFT", _display(30), CREAM)

    # Who.
    y = 196
    text((PAD, y), data.name, _display(72), CREAM, width=CONTENT_RIGHT - PAD)
    if data.season:
        text((PAD, y + 44), data.season, _body(24), MUTED, width=CONTENT_RIGHT - PAD)

    # The numbers.
    y = 336
    x = float(PAD)
    if card.show_rating and data.rating is not None:
        x = text((x, y), f"{data.rating:,}", _display(84), CREAM) + 14
        label = data.tier or data.rating_label
        _pill(draw, (x, y - 30), label, _body(20, 800), AMBER, AMBER_INK)
        texts.append(label)
        y += 58
    record = f"{data.wins}{EN_DASH}{data.losses}"
    line_end = text((PAD, y), record, _display(36), CREAM)
    line_end = text((line_end + 10, y), "record", _body(22), MUTED)
    if card.show_place and data.place is not None:
        place = f"#{data.place} of {data.ranked}" if data.ranked else f"#{data.place}"
        _pill(draw, (line_end + 24, y - 13), place, _body(20, 800), BLUE, BLUE_INK)
        texts.append(place)

    # Heroes, and the latest award.
    y += 36
    if data.heroes:
        text((PAD, y + 22), "TOP HEROES", _body(15, 800), FAINT)
        x = float(PAD)
        top = y + 36
        for hero in data.heroes:
            _thumb(image, hero.slug, (round(x), top), (54, 73))
            text((x + 66, top + 32), hero.name, _body(20, 700), CREAM, width=110)
            games = f"{hero.games} game" + ("" if hero.games == 1 else "s")
            text((x + 66, top + 58), games, _body(16, 600), MUTED)
            x += 196
    if card.show_award and data.award:
        label = f"Last award: {data.award}"
        _pill(draw, (PAD, HEIGHT - 52), label, _body(20, 800), CREAM, INK)
        texts.append(label)

    if any(_art(hero.slug) is not None for hero in data.heroes):  # Valve's art needs its credit.
        credit_font = _body(14, 600)
        credit_width = draw.textlength(CREDIT, font=credit_font)
        draw.rounded_rectangle(
            (WIDTH - 32 - credit_width, HEIGHT - 38, WIDTH - 16, HEIGHT - 12), radius=13, fill=INK
        )
        text((WIDTH - 24, HEIGHT - 20), CREDIT, credit_font, CREAM, anchor="rs")
    return image, texts


def to_png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
