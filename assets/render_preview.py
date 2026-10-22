"""Render clearoutside.draw() to a PNG with a Pillow-backed fake PicoGraphics (Inky Frame 4.0, 640x400).

Usage: python assets/render_preview.py (needs Pillow and curl).
"""
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
REPO = HERE.parent
FONT_FILE = HERE / "font8_data.cpp"
FONT_URL = "https://raw.githubusercontent.com/pimoroni/pimoroni-pico/main/libraries/bitmap_fonts/font8_data.cpp"
WIDTH, HEIGHT = 640, 400
LAT, LON = "52.23", "21.01"  # Warsaw
# Measured Inky 7-colour panel colors (Pimoroni inky library SATURATED_PALETTE), order: black, white, green, blue, red, yellow, orange.
PALETTE = ((57, 48, 57), (255, 255, 255), (58, 91, 70), (61, 59, 94), (156, 72, 75), (208, 190, 71), (177, 106, 73))

sys.path.insert(0, str(REPO / "src"))
import clearoutside  # noqa: E402


def load_font8(path: Path) -> tuple[list[int], list[list[int]]]:
    # Pimoroni's bitmap8 font source, downloaded on first use.
    if not path.exists():
        subprocess.run(["curl", "-sfL", "-o", str(path), FONT_URL], check=True)
    src = path.read_text()
    widths_block = src.split(".widths = {")[1].split("}")[0]
    widths = [int(w) for w in re.findall(r"\b\d+\b", re.sub(r"//.*", "", widths_block))]
    data_block = src.split(".data = {")[1]
    data = [int(b, 16) for b in re.findall(r"0x[0-9a-fA-F]{2}", re.sub(r"//.*", "", data_block))]
    glyphs = [data[i * 5:(i + 1) * 5] for i in range(96)]
    return widths, glyphs


class FakePicoGraphics:
    def __init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH, HEIGHT), PALETTE[1])
        self.pixels = self.image.load()
        self.pen = 0
        self.rgb_pens: list[tuple[int, int, int]] = []
        self.widths, self.glyphs = load_font8(FONT_FILE)

    def get_bounds(self) -> tuple[int, int]:
        return WIDTH, HEIGHT

    def create_pen(self, r: int, g: int, b: int) -> int:
        self.rgb_pens.append((r, g, b))
        return 100 + len(self.rgb_pens) - 1

    def set_font(self, name: str) -> None:
        assert name == "bitmap8"

    def set_pen(self, pen: int) -> None:
        self.pen = pen

    def clear(self) -> None:
        self.rectangle(0, 0, WIDTH, HEIGHT)

    def _color(self, x: int, y: int) -> tuple[int, int, int]:
        if self.pen < 100:
            return PALETTE[self.pen]
        # RGB pens are dithered on the panel; a mid gray becomes a black/white checkerboard.
        return PALETTE[0] if (x + y) % 2 == 0 else PALETTE[1]

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        for py in range(max(0, y), min(HEIGHT, y + h)):
            for px in range(max(0, x), min(WIDTH, x + w)):
                self.pixels[px, py] = self._color(px, py)

    def _char_width(self, c: str, scale: int) -> int:
        i = ord(c) - 32
        return self.widths[i] * scale if 0 <= i < 96 else 0

    def text(self, t: str, x: int, y: int, wrap: int, scale: int = 2, spacing: int = 1) -> None:
        # Port of bitmap::text() word wrapping (rotation 0, ASCII only).
        space = self._char_width(" ", scale) + spacing * scale
        char_offset = line_offset = 0
        for word in re.split(r"(?<= )", t):
            stripped = word.rstrip(" ")
            word_width = sum(self._char_width(c, scale) + spacing * scale for c in stripped)
            if char_offset and char_offset + word_width > wrap:
                char_offset, line_offset = 0, line_offset + 9 * scale
            for c in word:
                if c == " ":
                    char_offset += space
                    continue
                i = ord(c) - 32
                if not 0 <= i < 96:
                    continue
                for cx in range(self.widths[i]):
                    col = self.glyphs[i][cx]
                    for cy in range(8):
                        if col >> cy & 1:
                            self.rectangle(x + char_offset + cx * scale, y + line_offset + cy * scale, scale, scale)
                char_offset += self._char_width(c, scale) + spacing * scale

    def update(self) -> None:
        pass


def fetch_lines():
    url = f"https://{clearoutside.HOST}/forecast/{LAT}/{LON}?view={clearoutside.VIEW}"
    html = subprocess.run(["curl", "-sfL", "-A", "inky-frame", url], capture_output=True, check=True).stdout
    yield from html.splitlines(keepends=True)


if __name__ == "__main__":
    data = clearoutside.parse(fetch_lines(), keep=())
    graphics = FakePicoGraphics()
    clearoutside.draw(graphics, data)
    out = HERE / "frame_preview.png"
    graphics.image.save(out)
    print(f"Image saved to '{out}'")
