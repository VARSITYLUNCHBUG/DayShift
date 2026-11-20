"""Text in any script for the drawn images: each character in the first font that has it.

The brand's fonts cover Latin only, and players' names are anything: "SNΞK", Cyrillic, Korean,
Japanese, mathematical letters, symbols, emoji. A name is split into runs, each drawn in the first
font whose character map holds its characters: the brand font, then the system's fallbacks (the
image installs Noto and an emoji font; see the Dockerfile), and colour emoji last. A character no
font has stays in the brand font, which draws it as a box.

Pure apart from reading fonts. Font lookups are cached for the life of the process.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

FONT_DIRS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
)
# Tried in this order, by file name without its extension. The Debian names come first; the
# Windows ones let a developer's machine draw the same names.
FALLBACKS = (
    "NotoSans-Regular",
    "NotoSansMath-Regular",
    "NotoSansSymbols-Regular",
    "NotoSansSymbols2-Regular",
    "NotoSansCJK-Regular",
    "NotoSansCJKjp-Regular",
    "wqy-microhei",
    "DejaVuSans",
    "segoeui",
    "seguisym",
    "msyh",
    "malgun",
    "YuGothR",
    "Nirmala",
)
EMOJI_FONTS = ("NotoColorEmoji", "seguiemj")
# Noto's colour emoji is a bitmap font with one size: it's drawn at that and scaled.
EMOJI_BITMAP_SIZE = 109
# Joiners and modifiers belong to the character before them, whatever font has them.
_CLINGS = {0x200D, 0xFE0E, 0xFE0F, 0x20E3}


@dataclass(frozen=True, slots=True)
class Face:
    path: str
    index: int = 0  # A collection's font number (.ttc).
    emoji: bool = False


@cache
def _files() -> dict[str, str]:
    """Every font file under the font folders, by lower-case name without its extension."""
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
def coverage(path: str, index: int = 0) -> frozenset[int]:
    """The code points a font file draws."""
    try:
        font = TTFont(path, fontNumber=index, lazy=True)
        cmap = font.getBestCmap() or {}
        font.close()
    except Exception:  # A broken or unreadable font file is no fallback, nothing worse.
        return frozenset()
    return frozenset(cmap)


@cache
def _chain() -> tuple[Face, ...]:
    files = _files()
    faces = [Face(files[name.lower()]) for name in FALLBACKS if name.lower() in files]
    faces += [
        Face(files[name.lower()], emoji=True) for name in EMOJI_FONTS if name.lower() in files
    ]
    return tuple(faces)


@cache
def _others() -> tuple[Face, ...]:
    """Every other Noto font, for scripts the main fallbacks don't cover (Arabic, Thai, Tamil,
    Javanese and so on). Only read when a character needs it."""
    chosen = {face.path for face in _chain()}
    return tuple(
        Face(path)
        for name, path in sorted(_files().items())
        if name.startswith("notosans") and name.endswith("-regular") and path not in chosen
    )


@cache
def face_for(char: str, primary: str) -> Face | None:
    """The first font that draws `char`: None for the brand font itself, or when none does."""
    point = ord(char)
    if point in coverage(primary):
        return None
    emoji_like = unicodedata.category(char) == "So" and point >= 0x1F000
    chain = _chain()
    if emoji_like:  # Prefer colour emoji to a font's plain pictograph.
        chain = tuple(sorted(chain, key=lambda face: not face.emoji))
    for face in (*chain, *_others()):
        if point in coverage(face.path, face.index):
            return face
    return None


def _clings(char: str) -> bool:
    point = ord(char)
    skin_tone = 0x1F3FB <= point <= 0x1F3FF
    return point in _CLINGS or skin_tone or bool(unicodedata.combining(char))


def runs(text: str, primary: str) -> Iterator[tuple[Face | None, str]]:
    """`text` as (font, characters) runs. Combining marks and joiners stay with the character
    before them."""
    current: Face | None = None
    buffer = ""
    for char in text:
        face = current if buffer and _clings(char) else face_for(char, primary)
        if buffer and face != current:
            yield current, buffer
            buffer = ""
        current = face
        buffer += char
    if buffer:
        yield current, buffer


@cache
def _load(face: Face, size: int) -> ImageFont.FreeTypeFont:
    if face.emoji:
        try:
            return ImageFont.truetype(face.path, EMOJI_BITMAP_SIZE, index=face.index)
        except OSError:
            pass  # A scalable emoji font (Segoe UI Emoji) takes any size.
    return ImageFont.truetype(face.path, size, index=face.index)


class Writer:
    """Draws text in the brand font with fallbacks, as one string with one anchor."""

    def __init__(self, image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        self.image = image
        self.draw = draw

    def _pieces(
        self, text: str, font: ImageFont.FreeTypeFont
    ) -> list[tuple[str, ImageFont.FreeTypeFont, float, bool]]:
        """(text, font, width, is emoji) for each run."""
        primary = str(font.path)
        out = []
        for face, chunk in runs(text, primary):
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
        while text and self.length(text + "…", font) > width:
            text = text[:-1]
        return text.rstrip() + "…"

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
        if all(primary is font for _t, primary, _w, _e in pieces):
            self.draw.text(xy, text, font=font, fill=fill, anchor=anchor)  # The common case.
            return
        total = sum(width for _t, _f, width, _e in pieces)
        x, y = xy
        across, down = anchor[0], anchor[1]
        x -= {"l": 0, "m": total / 2, "r": total}[across]
        ascent, descent = font.getmetrics()
        baseline = {"a": y + ascent, "m": y + (ascent - descent) / 2, "s": y}[down]
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
        e_ascent, e_descent = emoji_font.getmetrics()
        canvas = Image.new("RGBA", (max(1, int(natural) + 2), e_ascent + e_descent), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text(
            (0, e_ascent), chunk, font=emoji_font, embedded_color=True, anchor="ls"
        )
        scale = font.size / emoji_font.size
        size = (max(1, round(canvas.width * scale)), max(1, round(canvas.height * scale)))
        scaled = canvas.resize(size, Image.Resampling.LANCZOS)
        top = round(baseline - e_ascent * scale)
        self.image.paste(scaled, (round(x), top), scaled)
