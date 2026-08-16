"""
Render recorded console output to a PNG.

Same approach and the same reason as in the sibling projects:
several places that accept a portfolio image only take raster formats, and
drawing rich's styled segments with Pillow avoids pulling in cairo or a headless
browser just to rasterise an SVG.

The console must be built with `record=True`.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

FONT_CANDIDATES = (
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/System/Library/Fonts/SFNSMono.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Andale Mono.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
    ("/usr/share/fonts/TTF/DejaVuSansMono.ttf", 0),
    ("C:/Windows/Fonts/consola.ttf", 0),
)

BACKGROUND = (13, 17, 23)
FOREGROUND = (220, 223, 228)
PADDING = 28


def export_png(console: Console, path: Path, font_size: int = 15) -> None:
    """Write everything recorded by `console` to `path` as a PNG.

    Raises:
        ValueError: If the console recorded nothing.
    """
    from PIL import Image, ImageDraw

    lines = _segments_to_lines(console)
    if not lines:
        raise ValueError("nothing was recorded — build the Console with record=True")

    regular, bold = _load_fonts(font_size)
    char_width, line_height = _metrics(regular, font_size)

    columns = max((sum(len(text) for text, _, _ in line) for line in lines), default=1)
    width = columns * char_width + 2 * PADDING
    height = len(lines) * line_height + 2 * PADDING

    image = Image.new("RGB", (int(width), int(height)), BACKGROUND)
    draw = ImageDraw.Draw(image)

    for row, line in enumerate(lines):
        x = PADDING
        y = PADDING + row * line_height
        for text, colour, is_bold in line:
            if text.strip():
                draw.text((x, y), text, font=bold if is_bold else regular, fill=colour)
            x += len(text) * char_width

    image.save(path, "PNG")


def _segments_to_lines(console: Console):
    lines: list[list[tuple[str, tuple[int, int, int], bool]]] = [[]]
    for segment in console._record_buffer:  # rich keeps the styled output here
        colour, is_bold = _style_of(segment.style)
        parts = segment.text.split("\n")
        for index, part in enumerate(parts):
            if index > 0:
                lines.append([])
            if part:
                lines[-1].append((part, colour, is_bold))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _style_of(style):
    if style is None:
        return FOREGROUND, False
    colour = FOREGROUND
    if style.color is not None:
        try:
            triplet = style.color.get_truecolor()
            colour = (triplet.red, triplet.green, triplet.blue)
        except Exception:
            colour = FOREGROUND
    return colour, bool(style.bold)


def _load_fonts(size: int):
    from PIL import ImageFont

    for path, index in FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            regular = ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
        try:
            bold = ImageFont.truetype(path, size, index=index + 1)
        except OSError:
            bold = regular
        return regular, bold
    return ImageFont.load_default(), ImageFont.load_default()


def _metrics(font, font_size: int) -> tuple[int, int]:
    try:
        width = font.getlength("M")
    except AttributeError:
        width = font_size * 0.6
    # Rounded, not floored: a fractional advance would accumulate across a wide
    # line and visibly bend the table borders.
    return max(1, round(width)), round(font_size * 1.35)
