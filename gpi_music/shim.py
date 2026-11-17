"""Compatibilidad de dibujo: Pillow si está, pygame (SDL2) si no.

Recalbox 9 no trae Pillow (ni pip), pero sí pygame2. Este módulo expone siempre
los mismos nombres (``Image``, ``ImageDraw``, ``ImageFont``) con el subconjunto
de API que usa el reproductor, de modo que la interfaz funciona igual en ambos
entornos.

* ``HAVE_PIL``  -> True si se está usando Pillow de verdad.
* ``BACKEND``   -> "pil" o "pygame".
"""

from __future__ import annotations

HAVE_PIL = False
BACKEND = "pygame"

try:  # Entorno con Pillow (RetroPie, PC de desarrollo).
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    HAVE_PIL = True
    BACKEND = "pil"
except ImportError:  # pragma: no cover - depende del entorno
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


if not HAVE_PIL:
    # ------------------------------------------------------------------
    # Sustituto compatible con pygame.
    # ------------------------------------------------------------------
    try:
        import os

        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame  # type: ignore
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ImportError(
            "gpi-music necesita Pillow o pygame para dibujar la pantalla "
            "(sudo apt-get install python3-pil python3-pygame)"
        ) from exc

    class _PygameImage:
        """Equivalente mínimo de ``PIL.Image`` sobre una Surface de pygame."""

        def __init__(self, surface=None, size=(1, 1), color=(0, 0, 0), mode="RGB"):
            if surface is None:
                surface = pygame.Surface(size)
                surface.fill(color)
            self._surface = surface
            self.mode = mode

        # -- properties -------------------------------------------------
        @property
        def size(self):
            return self._surface.get_size()

        # -- API --------------------------------------------------------
        def paste(self, color, box=None):
            if box is None:
                self._surface.fill(color)
            else:
                self._surface.fill(color, box)

        def convert(self, mode):
            return self

        def tobytes(self, encoder_name="raw", rawmode="RGB"):
            if encoder_name not in ("raw", None):
                raise ValueError("solo se admite el codificador 'raw'")
            width, height = self.size
            data = _surface_to_bytes(self._surface, "RGB")
            if rawmode == "RGB":
                return data
            if rawmode == "BGR":
                return _rgb_to_bgr(data)
            if rawmode == "BGRX":
                return _rgb_to_bgrx(data)
            return data

        def save(self, path, format=None):
            pygame.image.save(self._surface, path)

        def getdata(self):
            """Píxeles como lista de tuplas (r, g, b)."""
            data = _surface_to_bytes(self._surface, "RGB")
            return [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]

        def get_surface(self):
            return self._surface

    def _surface_to_bytes(surface, fmt="RGB"):
        try:
            return pygame.image.tobytes(surface, fmt)
        except AttributeError:  # pragma: no cover - pygame antiguo
            return pygame.image.tostring(surface, fmt)

    def _rgb_to_bgr(data: bytes) -> bytes:
        out = bytearray(len(data))
        out[0::3] = data[2::3]
        out[1::3] = data[1::3]
        out[2::3] = data[0::3]
        return bytes(out)

    def _rgb_to_bgrx(data: bytes) -> bytes:
        out = bytearray(len(data) // 3 * 4)
        out[0::4] = data[2::3]
        out[1::4] = data[1::3]
        out[2::4] = data[0::3]
        return bytes(out)

    def _anchor_offset(x, y, width, height, anchor):
        """Calcula el desplazamiento del texto según el ancla (como Pillow).

        Horizontal: l = izquierda, m = centro, r = derecha.
        Vertical: a = ascender (el texto baja desde y), t = top, m = middle,
        s = baseline, b/d = bottom/descender.
        """
        anchor = (anchor or "la").lower()
        if "r" in anchor:
            x -= width
        elif "m" in anchor:
            x -= width // 2
        if anchor.endswith("m"):
            y -= height // 2
        elif anchor.endswith("s"):
            y -= int(height * 0.8)
        elif anchor.endswith("b") or anchor.endswith("d"):
            y -= height
        # "a" y "t": el texto empieza en y (se dibuja hacia abajo).
        return x, y

    class _PygameFont:
        """Equivalente de ``PIL.ImageFont`` con pygame."""

        def __init__(self, size=14, bold=False):
            self.size = size
            self.bold = bold
            if not pygame.font.get_init():
                pygame.font.init()
            self._font = pygame.font.Font(None, size)
            self._font.set_bold(bold)

        def getbbox(self, text):
            width, height = self._font.size(text)
            return (0, 0, width, height)

        def getheight(self):
            return self._font.get_height()

    class _PygameDraw:
        """Equivalente de ``PIL.ImageDraw`` con pygame."""

        def __init__(self, image):
            self.image = image
            self._surface = image.get_surface()

        def rectangle(self, box, fill=None, outline=None, width=1):
            x0, y0, x1, y1 = [int(round(v)) for v in box]
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            rect = pygame.Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))
            if fill is not None:
                pygame.draw.rect(self._surface, tuple(fill), rect)
            if outline is not None:
                pygame.draw.rect(self._surface, tuple(outline), rect, max(1, int(width)))

        def text(self, xy, text, font=None, fill=None, anchor="la"):
            font = font or _PygameFont()
            color = tuple(fill or (255, 255, 255))
            surface = font._font.render(str(text), True, color)
            x, y = xy
            width, height = surface.get_size()
            x, y = _anchor_offset(x, y, width, height, anchor)
            self._surface.blit(surface, (int(x), int(y)))

        def textbbox(self, xy, text, font=None, anchor=None):
            font = font or _PygameFont()
            width, height = font._font.size(text)
            x, y = xy
            x, y = _anchor_offset(x, y, width, height, anchor or "la")
            return (int(x), int(y), int(x + width), int(y + height))

        def textsize(self, text, font=None):
            font = font or _PygameFont()
            return font._font.size(text)

    class _PygameImageModule:
        """Namespace con la misma forma que ``PIL.Image``."""

        @staticmethod
        def new(mode, size, color=(0, 0, 0)):
            surface = pygame.Surface(tuple(size))
            surface.fill(tuple(color))
            return _PygameImage(surface=surface, size=size, color=color, mode=mode)

        @staticmethod
        def frombytes(mode, size, data):
            surface = pygame.Surface(tuple(size))
            raw = bytes(data)
            expected = size[0] * size[1] * 3
            if len(raw) < expected:
                raw = raw + b"\x00" * (expected - len(raw))
            try:
                surface = pygame.image.fromstring(raw, tuple(size), "RGB")
            except Exception:  # pragma: no cover
                pass
            return _PygameImage(surface=surface, size=size, mode=mode)

        @staticmethod
        def from_surface(surface):
            """Envuelve una Surface existente (la de la pantalla de pygame)."""
            return _PygameImage(surface=surface, size=surface.get_size())

    class _PygameImageDrawModule:
        @staticmethod
        def Draw(image, mode=None):
            return _PygameDraw(image)

    class _PygameImageFontModule:
        @staticmethod
        def truetype(path, size=12, *args, **kwargs):
            raise OSError("el backend pygame no carga fuentes TTF: %s" % path)

        @staticmethod
        def load_default(size=None):
            return _PygameFont(size=size or 14)

    Image = _PygameImageModule()  # type: ignore[assignment]
    ImageDraw = _PygameImageDrawModule()  # type: ignore[assignment]
    ImageFont = _PygameImageFontModule()  # type: ignore[assignment]
