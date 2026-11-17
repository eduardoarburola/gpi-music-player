#!/usr/bin/env python3
"""Genera una vista en ASCII de la interfaz (para el README, sin binarios).

    python3 scripts/preview_ascii.py [imagen.png] [columnas]
"""

from __future__ import annotations

import sys

from PIL import Image

RAMP = " .:-=+*#%@"


def to_ascii(path: str, columns: int = 76) -> str:
    image = Image.open(path).convert("L")
    width, height = image.size
    rows = max(1, int(columns * (height / width) / 2.0))
    small = image.resize((columns, rows))
    pixels = list(small.getdata())
    lines = []
    for y in range(rows):
        line = "".join(RAMP[min(len(RAMP) - 1, p * len(RAMP) // 256)]
                        for p in pixels[y * columns:(y + 1) * columns])
        lines.append(line.rstrip())
    return "\n".join(lines)


def main(argv) -> int:
    path = argv[0] if argv else "docs/library.png"
    columns = int(argv[1]) if len(argv) > 1 else 76
    print(to_ascii(path, columns))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
