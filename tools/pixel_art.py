"""Draw Miday's pixel art: the icons, the background tiles, the bear logo and the favicons.

Every picture is a text grid with one character per pixel, so it can be edited
in any text editor. The two bear logos are in tools/art/. After changing a grid,
run this to rebuild static/css/icons.css and static/img/:

    python tools/pixel_art.py

It needs only the standard library.
"""
import base64
import struct
import zlib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "tools" / "art"
CSS_OUT = ROOT / "static" / "css" / "icons.css"
IMG_OUT = ROOT / "static" / "img"

# The logo: a snow-white bear on navy in a bevelled gold frame. Night uses the line drawing.
NAVY, SNOW = "#091128", "#f8f7f2"
# Frame rings from the outside in: outline, bevel (light on the top-left half, dark on
# the bottom-right), gold, inner edge. The outline matches --px-outline in miday.css.
FRAME = {
    "day": ["#3b2316", ("#fff3b0", "#d99a1e"), "#f6c445", "#7a4a12"],
    "night": ["#0e0b16", ("#fff3b0", "#c98a10"), "#ffd257", "#7a4a12"],
}

# Multi-colour "items" keep their own colours.
ITEMS = {
    "up": ({"O": "#3b2316", "S": "#f7d5a8", "H": "#fff1dc", "C": "#5b8fd1"}, [
        "....OO.....",
        "...OHSO....",
        "...OSSO....",
        "..OSSSO....",
        "OOOSSSOOOO.",
        "OCOHSSSSSSO",
        "OCOSSSSSSO.",
        "OCOSSSSSSSO",
        "OCOSSSSSSO.",
        "OCOSSSSSSO.",
        "OOOOOOOOO..",
    ]),
    "star": ({"O": "#7a4a12", "Y": "#f6c445", "W": "#fff3b0"}, [
        "....O....",
        "...OYO...",
        "OOOOYOOOO",
        "OYYYWYYYO",
        ".OYYYYYO.",
        "..OYYYO..",
        ".OYYOYYO.",
        ".OYO.OYO.",
        ".OO...OO.",
    ]),
    "crown": ({"O": "#7a4a12", "Y": "#f6c445", "W": "#fff3b0", "R": "#d0463b"}, [
        "O....O....O",
        "OO..OYO..OO",
        "OYO.OWO.OYO",
        "OYYOYYYOYYO",
        "OYYYYRYYYYO",
        "OYWYYYYYYYO",
        "OOOOOOOOOOO",
    ]),
    "coin": ({"O": "#7a4a12", "Y": "#f6c445", "W": "#fff3b0", "D": "#d99a1e"}, [
        "..OOOOO..",
        ".OYYYYYO.",
        "OYWYDYYYO",
        "OYWDYDYYO",
        "OYYYDYYYO",
        "OYYDYDYYO",
        "OYYYDYYDO",
        ".OYYYYYO.",
        "..OOOOO..",
    ]),
}
ITEMS["down"] = (ITEMS["up"][0], ITEMS["up"][1][::-1])

# One-colour "glyphs" are used as CSS masks, so they take the text colour by day and night.
GLYPHS = {
    "plus": [
        "...........",
        "....###....",
        "....###....",
        "....###....",
        ".#########.",
        ".#########.",
        ".#########.",
        "....###....",
        "....###....",
        "....###....",
        "...........",
    ],
    "pencil": [
        "........##.",
        ".......####",
        "......####.",
        ".....####..",
        "....####...",
        "...####....",
        "..####.....",
        ".#.##......",
        ".##........",
        "###........",
        "...........",
    ],
    "trash": [
        "...#####...",
        "###########",
        "...........",
        ".#########.",
        ".#.#.#.#.#.",
        ".#.#.#.#.#.",
        ".#.#.#.#.#.",
        ".#.#.#.#.#.",
        ".#.#.#.#.#.",
        "..#######..",
        "...........",
    ],
    "pin": [
        "...#####...",
        "..#######..",
        ".###...###.",
        ".##.....##.",
        ".##.....##.",
        ".###...###.",
        "..#######..",
        "..#######..",
        "...#####...",
        "....###....",
        ".....#.....",
    ],
    "globe": [
        "...#####...",
        ".##..#..##.",
        ".#..#.#..#.",
        "#...#.#...#",
        "###########",
        "#...#.#...#",
        "#...#.#...#",
        "###########",
        ".#..#.#..#.",
        ".##..#..##.",
        "...#####...",
    ],
    "phone": [
        ".###.......",
        "#####......",
        "#####......",
        ".####......",
        "..###......",
        "..####.....",
        "...####....",
        "....####.##",
        ".....######",
        "......#####",
        ".......###.",
    ],
    "clock": [
        "...#####...",
        ".##.....##.",
        ".#...#...#.",
        "#....#....#",
        "#....#....#",
        "#....####.#",
        "#.........#",
        "#.........#",
        ".#.......#.",
        ".##.....##.",
        "...#####...",
    ],
    "person": [
        "....###....",
        "...#####...",
        "...#####...",
        "...#####...",
        "....###....",
        "...........",
        "..#######..",
        ".#########.",
        ".#########.",
        ".#########.",
        "...........",
    ],
    "people": [
        "..##....##.",
        ".####..####",
        ".####..####",
        "..##....##.",
        "...........",
        "######.####",
        "######.####",
        "######.####",
        "...........",
        "...........",
        "...........",
    ],
    "lock": [
        "...#####...",
        "..##...##..",
        "..#.....#..",
        "..#.....#..",
        ".#########.",
        ".####.####.",
        ".###...###.",
        ".####.####.",
        ".####.####.",
        ".#########.",
        "...........",
    ],
    "unlock": [
        "...#####...",
        "..##...##..",
        "..#.....#..",
        "..#........",
        ".#########.",
        ".####.####.",
        ".###...###.",
        ".####.####.",
        ".####.####.",
        ".#########.",
        "...........",
    ],
    "copy": [
        "....#######",
        "....#.....#",
        "....#.....#",
        "#######...#",
        "#.....#...#",
        "#.....#####",
        "#.....#....",
        "#.....#....",
        "#######....",
        "...........",
        "...........",
    ],
    "save": [
        "#########..",
        "#..####.##.",
        "#..####..##",
        "#..####...#",
        "#.........#",
        "#.#######.#",
        "#.#.....#.#",
        "#.#.....#.#",
        "#.#######.#",
        "###########",
        "...........",
    ],
    "search": [
        "..####.....",
        ".#....#....",
        "#......#...",
        "#......#...",
        "#......#...",
        "#......#...",
        ".#....#....",
        "..#####....",
        "......###..",
        ".......###.",
        "........###",
    ],
    "bubble": [
        ".#########.",
        "###########",
        "##.......##",
        "###########",
        "##.....####",
        "###########",
        ".#########.",
        "..##.......",
        "..#........",
        "...........",
        "...........",
    ],
    "ballot": [
        "..#######..",
        "..#.....#..",
        "..#....##..",
        "..##..#.#..",
        "..#.##..#..",
        "###########",
        "#.........#",
        "#.........#",
        "#.........#",
        "#.........#",
        "###########",
    ],
    "plate": [
        "#.#.#...##.",
        "#.#.#..###.",
        "#.#.#..###.",
        "#####..###.",
        ".###...###.",
        "..#....###.",
        "..#.....#..",
        "..#.....#..",
        "..#.....#..",
        "..#.....#..",
        "..#.....#..",
    ],
    "day": [
        ".....#.....",
        ".#...#...#.",
        "..#.....#..",
        "....###....",
        "...#####...",
        "##.#####.##",
        "...#####...",
        "....###....",
        "..#.....#..",
        ".#...#...#.",
        ".....#.....",
    ],
    "night": [
        "...####....",
        ".####......",
        ".###.......",
        "###........",
        "###........",
        "###........",
        "####.......",
        ".#####...#.",
        "..#######..",
        "....####...",
        "...........",
    ],
    "check": [
        "...........",
        "..........#",
        ".........##",
        "........##.",
        "#......##..",
        "##....##...",
        ".##..##....",
        "..####.....",
        "...##......",
        "...........",
        "...........",
    ],
    "undo": [
        "...#.......",
        "..##.......",
        ".#######...",
        "..##....#..",
        "...#.....#.",
        ".........#.",
        ".........#.",
        "........#..",
        "..######...",
        "...........",
        "...........",
    ],
    "chevron": [
        "...........",
        "..##.......",
        "..###......",
        "...###.....",
        "....###....",
        ".....###...",
        "....###....",
        "...###.....",
        "..###......",
        "..##.......",
        "...........",
    ],
    "alert": [
        "....###....",
        "....###....",
        "....###....",
        "....###....",
        "....###....",
        ".....#.....",
        "...........",
        "....###....",
        "....###....",
        "...........",
        "...........",
    ],
}

# 16 x 16 tiles for the page background: grass by day, a starry sky by night.
TILES = {
    "grass": ({".": "#7cbf4c", "d": "#6aab3d", "l": "#93d062"}, [
        "................", "..d.............", ".dld........l...", "..............d.",
        "......d....d.ld.", ".....dl.........", "................", "...........d....",
        "..l.......dld...", ".d..............", "......l.........", ".....d.d.....d..",
        "............dl..", "..d.............", ".ld.............", "........d.......",
    ]),
    "night": ({".": "#1d2442", "d": "#182038", "s": "#f3e7b0", "f": "#6d77a8"}, [
        "................", "...s............", "................", "...........f....",
        "................", "......d.........", ".f..............", "............s...",
        "................", "....d...........", "................", "........f.......",
        "..s.............", "................", "..........d.....", "................",
    ]),
}


def svg(colors, rows):
    """A crisp SVG of a grid: one rect per run of same-coloured pixels."""
    width, height = len(rows[0]), len(rows)
    parts = []
    for y, row in enumerate(rows):
        x = 0
        while x < width:
            ch = row[x]
            if ch not in colors:
                x += 1
                continue
            run = 1
            while x + run < width and row[x + run] == ch:
                run += 1
            parts.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{colors[ch]}"/>')
            x += run
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'shape-rendering="crispEdges">{"".join(parts)}</svg>')


def css_url(markup):
    return 'url("data:image/svg+xml,' + quote(markup, safe="") + '")'


def rgba(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


def png(pixels, scale=1):
    """Encode rows of RGBA tuples (None = transparent) as a PNG, each pixel scale x scale."""
    raw = bytearray()
    for row in pixels:
        line = b"".join(bytes(rgba(c) if c else (0, 0, 0, 0)) * scale for c in row)
        raw += (b"\x00" + line) * scale
    width, height = len(pixels[0]) * scale, len(pixels) * scale

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def bear(name):
    rows = (ART / f"bear-{name}.txt").read_text().split()
    assert len(rows) == 62 and all(len(r) == 62 for r in rows), name
    return [[SNOW if ch == "#" else NAVY for ch in row] for row in rows]


def framed(pixels, rings):
    """The bear inside square rings of colour; a (light, dark) pair draws a bevel."""
    width = len(rings)
    size = len(pixels) + 2 * width
    out = []
    for y in range(size):
        row = []
        for x in range(size):
            k = min(x, y, size - 1 - x, size - 1 - y)
            if k >= width:
                row.append(pixels[y - width][x - width])
                continue
            ring = rings[k]
            if isinstance(ring, tuple):
                ring = ring[0] if x + y < size - 1 else ring[1]
            row.append(ring)
        out.append(row)
    return out


def main():
    IMG_OUT.mkdir(exist_ok=True)
    logos = {mode: png(framed(bear(mode), FRAME[mode])) for mode in ("day", "night")}
    for mode, data in logos.items():
        (IMG_OUT / f"logo-{mode}.png").write_bytes(data)

    # One favicon for both themes: the browser shows the one for the device's light or dark setting.
    size = 62 + 2 * len(FRAME["day"])
    images = "".join(
        f'<image class="{mode}" width="{size}" height="{size}" href="data:image/png;base64,{base64.b64encode(data).decode()}"/>'
        for mode, data in logos.items()
    )
    (IMG_OUT / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
        "<style>.night{display:none}@media (prefers-color-scheme:dark){.day{display:none}.night{display:inline}}</style>"
        f"{images}</svg>\n", newline="\n"
    )
    # Home-screen icon: no frame (phones round the corners), trimmed to 60 x 60 and drawn 3x = 180 px.
    trimmed = [row[1:-1] for row in bear("day")[1:-1]]
    (IMG_OUT / "apple-touch-icon.png").write_bytes(png(trimmed, scale=3))

    lines = ["/* Generated by tools/pixel_art.py from its text grids. Edit those and re-run it; don't edit this file. */"]
    for name, rows in GLYPHS.items():
        assert len(rows) == 11 and all(len(r) == 11 for r in rows), name
        lines.append(f".px-g-{name} {{ --g: {css_url(svg({'#': '#000'}, rows))}; }}")
    for name, (colors, rows) in ITEMS.items():
        assert len({len(r) for r in rows}) == 1, name
        lines.append(f".px-{name} {{ background-image: {css_url(svg(colors, rows))}; }}")
    tiles = "; ".join(f"--px-tile-{name}: {css_url(svg(colors, rows))}" for name, (colors, rows) in TILES.items())
    lines.append(f":root {{ {tiles}; }}")
    CSS_OUT.write_text("\n".join(lines) + "\n", newline="\n")
    print(f"{CSS_OUT.relative_to(ROOT)}: {len(GLYPHS)} glyphs, {len(ITEMS)} items, {len(TILES)} tiles")
    print(f"{IMG_OUT.relative_to(ROOT)}: logo-day.png, logo-night.png, favicon.svg, apple-touch-icon.png")


if __name__ == "__main__":
    main()
