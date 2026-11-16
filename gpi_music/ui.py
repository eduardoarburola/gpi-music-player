"""Interfaz gráfica del reproductor (dibujo sobre el lienzo de la pantalla).

Pensada para la pantalla de 2.8" del GPi Case (320×240) pero escala sola a
640×480 (GPi Case 2W) porque todos los tamaños se derivan del ancho.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

__all__ = ["Theme", "UI", "PIXEL_THEME", "RETRO_THEME"]


@dataclass
class Theme:
    background: Tuple[int, int, int] = (16, 12, 24)
    panel: Tuple[int, int, int] = (28, 22, 42)
    accent: Tuple[int, int, int] = (255, 214, 92)
    accent_dim: Tuple[int, int, int] = (120, 104, 72)
    text: Tuple[int, int, int] = (236, 236, 245)
    text_dim: Tuple[int, int, int] = (140, 136, 160)
    highlight: Tuple[int, int, int] = (58, 44, 88)
    good: Tuple[int, int, int] = (126, 214, 130)
    warn: Tuple[int, int, int] = (240, 160, 90)
    bad: Tuple[int, int, int] = (232, 106, 106)


PIXEL_THEME = Theme()
RETRO_THEME = Theme(
    background=(8, 12, 8),
    panel=(16, 28, 16),
    accent=(120, 240, 120),
    accent_dim=(48, 112, 48),
    text=(200, 255, 200),
    text_dim=(96, 150, 96),
    highlight=(20, 52, 20),
    good=(120, 240, 120),
    warn=(240, 220, 120),
    bad=(240, 120, 120),
)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Fallbacks para previsualizar en el PC.
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def _load_font(size: int, bold: bool = False):
    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ] + candidates
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        box = draw.textbbox((0, 0), text, font=font)
        return box[2] - box[0]
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Corta el texto con '…' para que quepa en el ancho dado."""
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _text_width(draw, text[:mid] + ellipsis, font) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ellipsis


class UI:
    """Dibuja las vistas del reproductor sobre un ``Surface``."""

    def __init__(self, surface, theme: Optional[Theme] = None, base_font_size: int = 15) -> None:
        self.surface = surface
        self.theme = theme or PIXEL_THEME
        self.width, self.height = surface.size
        # Factor de escala para pantallas grandes (GPi Case 2W).
        self.scale = max(1, int(round(self.width / 320.0)))
        self.base = max(9, int(round(base_font_size * self.scale)))
        self.font = _load_font(self.base)
        self.font_bold = _load_font(self.base, bold=True)
        self.font_small = _load_font(max(8, self.base - 3))
        self.font_large = _load_font(int(self.base * 1.6), bold=True)
        self.font_huge = _load_font(int(self.base * 2.2), bold=True)
        self._scroll = 0

    # ------------------------------------------------------------ helpers ---
    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return self.surface.draw

    def text(self, xy, message: str, font=None, fill=None, anchor: str = "la") -> None:
        self.draw.text(
            xy,
            message,
            font=font or self.font,
            fill=fill or self.theme.text,
            anchor=anchor,
        )

    def text_clipped(self, xy, message: str, max_width: int, font=None, fill=None, anchor="la") -> None:
        clipped = _truncate(self.draw, message, font or self.font, max_width)
        self.text(xy, clipped, font=font, fill=fill, anchor=anchor)

    def panel(self, box, fill=None, outline=None, radius: int = 0) -> None:
        self.draw.rectangle(box, fill=fill or self.theme.panel, outline=outline, width=1)

    def header(self, title: str, right: str = "") -> None:
        pad = 4 * self.scale
        self.panel((0, 0, self.width, self.height // 6), fill=self.theme.panel)
        self.text((pad, pad), title, font=self.font_bold, fill=self.theme.accent)
        if right:
            self.text((self.width - pad, pad), right, font=self.font_small,
                      fill=self.theme.text_dim, anchor="ra")

    def footer(self, hints: List[Tuple[str, str]]) -> None:
        """Pinta la barra de ayuda inferior: [(tecla, acción)]."""
        height = 14 * self.scale
        top = self.height - height
        self.panel((0, top, self.width, self.height), fill=self.theme.panel)
        x = 4 * self.scale
        for key, label in hints:
            key_w = _text_width(self.draw, key, self.font_small) + 4 * self.scale
            self.text((x, top + 2 * self.scale), key, font=self.font_small, fill=self.theme.accent)
            self.text((x + key_w, top + 2 * self.scale), label, font=self.font_small,
                      fill=self.theme.text_dim)
            x += key_w + _text_width(self.draw, label, self.font_small) + 10 * self.scale
            if x > self.width - 40 * self.scale:
                break

    def progress_bar(self, box, fraction: float, color=None) -> None:
        x0, y0, x1, y1 = box
        self.draw.rectangle(box, fill=self.theme.highlight)
        inner_w = max(0, x1 - x0 - 2)
        filled = int(inner_w * max(0.0, min(1.0, fraction)))
        if filled > 0:
            self.draw.rectangle((x0 + 1, y0 + 1, x0 + 1 + filled, y1 - 1),
                                fill=color or self.theme.accent)

    # -------------------------------------------------------------- vistas ---
    def draw_scanning(self, message: str = "Escaneando biblioteca…") -> None:
        self.surface.clear(self.theme.background)
        self.text((self.width // 2, self.height // 2 - 8), message,
                  font=self.font_bold, fill=self.theme.accent, anchor="mm")
        self.text((self.width // 2, self.height // 2 + 14), "…",
                  font=self.font, fill=self.theme.text_dim, anchor="mm")

    def draw_message(self, message: str, sub: str = "") -> None:
        self.surface.clear(self.theme.background)
        self.text((self.width // 2, self.height // 2), message,
                  font=self.font_bold, fill=self.theme.accent, anchor="mm")
        if sub:
            self.text((self.width // 2, self.height // 2 + 20), sub,
                      font=self.font_small, fill=self.theme.text_dim, anchor="mm")

    def draw_library(self, tracks, index: int, source_label: str, total: int, status: str = "") -> None:
        self.surface.clear(self.theme.background)
        self.header("MÚSICA", status or ("%d pistas" % total))

        list_top = self.height // 6 + 4 * self.scale
        row_h = 16 * self.scale
        visible = max(1, (self.height - list_top - 16 * self.scale) // row_h)
        pad = 4 * self.scale

        if not tracks:
            self.draw_message("No hay música todavía", "Añade archivos en la carpeta Música")
            return

        # Mantiene la selección dentro de la ventana visible.
        if index < self._scroll:
            self._scroll = index
        elif index >= self._scroll + visible:
            self._scroll = index - visible + 1
        self._scroll = max(0, min(self._scroll, max(0, len(tracks) - visible)))

        for row in range(visible):
            pos = self._scroll + row
            if pos >= len(tracks):
                break
            track = tracks[pos]
            top = list_top + row * row_h
            selected = pos == index
            if selected:
                self.draw.rectangle((pad - 2, top, self.width - pad - 6, top + row_h - 2),
                                    fill=self.theme.highlight)
            color = self.theme.accent if selected else self.theme.text
            badge = self._badge(track.source_label)
            label = track.display
            max_w = self.width - 2 * pad - (60 * self.scale if badge else 0)
            self.text_clipped((pad, top + 2 * self.scale), label, max_w,
                              font=self.font, fill=color)
            if badge:
                self.text((self.width - pad - 4 * self.scale, top + 2 * self.scale), badge,
                          font=self.font_small, fill=self.theme.text_dim, anchor="ra")

        # Barra de desplazamiento.
        if len(tracks) > visible:
            bar_h = self.height - list_top - 16 * self.scale
            x = self.width - 4 * self.scale
            self.draw.rectangle((x, list_top, x + 2 * self.scale, list_top + bar_h),
                                fill=self.theme.highlight)
            pos = list_top + int((bar_h - 20 * self.scale) * (index / max(1, len(tracks) - 1)))
            self.draw.rectangle((x, pos, x + 2 * self.scale, pos + 18 * self.scale),
                                fill=self.theme.accent)

        self.footer([("↑↓", "mover"), ("A", "reproducir"), ("B", "salir")])

    def _badge(self, source_label: str) -> str:
        if "MPD" in source_label:
            return "MPD"
        if "(red)" in source_label:
            return "RED"
        if "(microSD)" in source_label:
            return "SD"
        return ""

    def draw_now_playing(self, track, position: float, duration: Optional[float],
                         paused: bool, volume: float, extras: str = "") -> None:
        self.surface.clear(self.theme.background)
        pad = 6 * self.scale

        # Cabecera con el estado.
        state = "Pausa" if paused else "Sonando"
        self.header(state, track.source_label)

        top = self.height // 6 + 8 * self.scale
        self.text_clipped((pad, top), track.title or "—", self.width - 2 * pad,
                          font=self.font_bold, fill=self.theme.text)
        if track.artist:
            self.text_clipped((pad, top + 18 * self.scale), track.artist, self.width - 2 * pad,
                              font=self.font, fill=self.theme.accent)
        if track.album:
            self.text_clipped((pad, top + 34 * self.scale), track.album, self.width - 2 * pad,
                              font=self.font_small, fill=self.theme.text_dim)

        # Barra de progreso (58% de la altura).
        bar_y = int(self.height * 0.58)
        self.progress_bar((pad, bar_y, self.width - pad, bar_y + 9 * self.scale),
                          (position / duration) if duration else 0.0)
        elapsed = _format_time(position)
        total = _format_time(duration) if duration else "--:--"
        self.text((pad, bar_y + 13 * self.scale), elapsed, font=self.font_small, fill=self.theme.text_dim)
        self.text((self.width - pad, bar_y + 13 * self.scale), total,
                  font=self.font_small, fill=self.theme.text_dim, anchor="ra")

        if extras:
            self.text((pad, top + 51 * self.scale), extras, font=self.font_small,
                      fill=self.theme.warn)

        # Volumen (78% de la altura).
        vol_y = int(self.height * 0.78)
        self.text((pad, vol_y), "Vol", font=self.font_small, fill=self.theme.text_dim)
        self.progress_bar((pad + 30 * self.scale, vol_y, self.width - pad, vol_y + 8 * self.scale),
                          volume, color=self.theme.good)
        self.text((self.width - pad, vol_y + 11 * self.scale), "%d%%" % int(volume * 100),
                  font=self.font_small, fill=self.theme.text_dim, anchor="ra")

        self.footer([("A", "pausa"), ("X", "siguiente"), ("B", "salir")])

    def draw_options(self, options: List[str], index: int, title: str = "Opciones") -> None:
        self.surface.clear(self.theme.background)
        self.header(title)
        pad = 6 * self.scale
        top = self.height // 6 + 10 * self.scale
        row_h = 20 * self.scale
        for row, option in enumerate(options):
            selected = row == index
            if selected:
                self.draw.rectangle((pad - 2, top + row * row_h - 2, self.width - pad, top + row * row_h + 14 * self.scale),
                                    fill=self.theme.highlight)
            marker = "▶ " if selected else "   "
            self.text((pad, top + row * row_h), marker + option,
                      font=self.font_bold if selected else self.font,
                      fill=self.theme.accent if selected else self.theme.text)
        self.footer([("▲▼", "mover"), ("A", "elegir"), ("B", "atrás")])


def _format_time(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(seconds)
    return "%d:%02d" % (total // 60, total % 60)
