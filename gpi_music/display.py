"""Fábrica de la pantalla.

Elige el backend de dibujo según lo que haya instalado:

* **Pillow** → dibuja en memoria y vuelca al framebuffer (``/dev/fb0``).
* **pygame** (SDL2) → abre la ventana directamente sobre el framebuffer, que es
  lo que hay en Recalbox 9 (no hay Pillow ni pip).

En ambos casos se expone la misma interfaz: ``size``, ``image``, ``draw``,
``present()``, ``clear()``, ``save_png()`` y ``close()``.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from . import shim

__all__ = ["create_display", "DisplayError", "available_backends"]


class DisplayError(Exception):
    """No hay forma de dibujar en la pantalla."""


def available_backends() -> dict:
    """Qué backends hay disponibles en este sistema."""
    result = {"pil": shim.HAVE_PIL, "pygame": False, "framebuffer": False}
    try:
        import pygame  # noqa: F401

        result["pygame"] = True
    except ImportError:
        pass
    result["framebuffer"] = os.path.exists("/dev/fb0")
    return result


def _framebuffer_size() -> Tuple[int, int]:
    """Tamaño real del framebuffer (320×240 en la GPi Case, 640×480 en la 2W)."""
    for name in ("virtual_width", "width"):
        try:
            with open("/sys/class/graphics/fb0/" + name, encoding="utf-8") as fh:
                width = int(fh.read().strip())
            if width:
                break
        except (OSError, ValueError):
            width = 0
    else:
        width = 0
    try:
        with open("/sys/class/graphics/fb0/virtual_height", encoding="utf-8") as fh:
            height = int(fh.read().strip())
    except (OSError, ValueError):
        height = 0
    if not width or not height:
        return (320, 240)
    return (width, height)


class PygameDisplay:
    """Pantalla gestionada por pygame (SDL2) sobre el framebuffer."""

    def __init__(self, width: int = 0, height: int = 0) -> None:
        import pygame

        if shim.HAVE_PIL:
            raise DisplayError("el backend pygame no está disponible (Pillow tiene prioridad)")

        if not width or not height:
            width, height = _framebuffer_size()
        self.width, self.height = width, height
        self._pygame = pygame

        # En la consola no hay X ni Wayland: hay que forzar el driver del
        # framebuffer. Si ya hay uno definido en el entorno, se respeta.
        #
        # La imagen de Recalbox para la GPi Case compila SDL con el driver
        # "RPI" (Dispmanx) y sin fbcon/kmsdrm/dummy, así que lo primero es
        # dejar que SDL elija solo; los drivers de framebuffer son el plan B.
        forced = os.environ.get("SDL_VIDEODRIVER")
        candidates = [forced] if forced else [None, "fbcon", "kmsdrm"]
        for driver in candidates:
            if driver:
                os.environ["SDL_VIDEODRIVER"] = driver
            else:
                os.environ.pop("SDL_VIDEODRIVER", None)
            try:
                pygame.display.init()
                break
            except Exception:  # noqa: BLE001
                continue

        if not pygame.display.get_init():
            raise DisplayError("no se pudo inicializar la pantalla (SDL2)")

        try:
            self._surface = pygame.display.set_mode((self.width, self.height))
        except Exception as exc:  # noqa: BLE001
            raise DisplayError("no se pudo abrir la pantalla: %s" % exc) from exc

        pygame.font.init()
        # El shim dibuja directamente sobre la Surface de la pantalla.
        self.image = shim.Image.from_surface(self._surface)
        self.draw = shim.ImageDraw.Draw(self.image)

    @property
    def size(self):
        return (self.width, self.height)

    def present(self) -> None:
        self._pygame.display.flip()

    def clear(self, color=(0, 0, 0)) -> None:
        self._surface.fill(tuple(color))

    def save_png(self, path: str) -> None:
        self._pygame.image.save(self._surface, path)

    def close(self) -> None:
        try:
            self._pygame.display.quit()
            self._pygame.quit()
        except Exception:  # noqa: BLE001
            pass


class PygameMemoryDisplay:
    """Pantalla en memoria (sin tocar el framebuffer).

    Sirve para las vistas previas y para el modo de pruebas: crea una Surface
    de pygame normal, sin inicializar el vídeo, así que funciona incluso en
    compilaciones de SDL sin driver de vídeo (el ``dummy`` de Recalbox, por
    ejemplo, no está compilado).
    """

    def __init__(self, width: int = 320, height: int = 240) -> None:
        import pygame

        if shim.HAVE_PIL:
            raise DisplayError("el backend pygame no está disponible (Pillow tiene prioridad)")

        self.width = width or 320
        self.height = height or 240
        self._pygame = pygame

        if not self._pygame.font.get_init():
            self._pygame.font.init()

        self._surface = self._pygame.Surface((self.width, self.height))
        self._surface.fill((0, 0, 0))

        self.image = shim.Image.from_surface(self._surface)
        self.draw = shim.ImageDraw.Draw(self.image)

    @property
    def size(self):
        return (self.width, self.height)

    def present(self) -> None:
        """En memoria no hay nada que presentar."""

    def clear(self, color=(0, 0, 0)) -> None:
        self._surface.fill(tuple(color))

    def save_png(self, path: str) -> None:
        self._pygame.image.save(self._surface, path)

    def close(self) -> None:
        try:
            self._pygame.font.quit()
        except Exception:  # noqa: BLE001
            pass


class FramebufferDisplay:
    """Dibuja con pygame en memoria y vuelca los píxeles a ``/dev/fb0``.

    Evita el driver de vídeo de SDL (Dispmanx) de la GPi Case. Con ese driver,
    ``pygame.display.flip()`` se queda bloqueado para siempre si otro proceso
    (EmulationStation) todavía tiene la pantalla: la consola se queda con la
    imagen congelada y los botones dejan de responder. Escribiendo directamente
    en el framebuffer no hay nada que sincronizar con nadie.
    """

    def __init__(self, device: str = "/dev/fb0", width: int = 0, height: int = 0) -> None:
        import pygame

        if shim.HAVE_PIL:
            raise DisplayError("el backend de framebuffer con pygame no se usa con Pillow")

        from .fb import _detect_fb_info

        try:
            self.width, self.height, self.bpp, self.stride = _detect_fb_info(device)
        except Exception as exc:  # noqa: BLE001
            raise DisplayError("no se pudo detectar el framebuffer: %s" % exc) from exc
        if self.bpp != 32:
            raise DisplayError("el framebuffer es de %d bpp (solo se soporta 32)" % self.bpp)
        try:
            self._fd = os.open(device, os.O_WRONLY)
        except OSError as exc:
            raise DisplayError("no se pudo abrir %s: %s" % (device, exc)) from exc

        self.device = device
        self._pygame = pygame
        # Solo la fuente: sin display.init() no se abre el driver de vídeo.
        if not pygame.font.get_init():
            pygame.font.init()
        self._surface = pygame.Surface((self.width, self.height))
        self._surface.fill((0, 0, 0))
        self.image = shim.Image.from_surface(self._surface)
        self.draw = shim.ImageDraw.Draw(self.image)

    @property
    def size(self):
        return (self.width, self.height)

    def present(self) -> None:
        """Vuelca el lienzo al framebuffer."""
        data = self._pack()
        try:
            os.lseek(self._fd, 0, os.SEEK_SET)
            written = 0
            view = memoryview(data)
            while written < len(data):
                written += os.write(self._fd, view[written:])
        except OSError:
            pass

    def _pack(self) -> bytes:
        raw = self.image.tobytes("raw", "BGRX")
        row_bytes = self.width * 4
        if self.stride in (0, row_bytes):
            return raw
        pad = self.stride - row_bytes
        if pad <= 0:
            return raw
        out = bytearray()
        for pos in range(0, len(raw), row_bytes):
            out += raw[pos:pos + row_bytes]
            out += b"\x00" * pad
        return bytes(out)

    def clear(self, color=(0, 0, 0)) -> None:
        self._surface.fill(tuple(color))

    def save_png(self, path: str) -> None:
        self._pygame.image.save(self._surface, path)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


def create_display(fb_device: str = "/dev/fb0", prefer: Optional[str] = None,
                   width: int = 0, height: int = 0):
    """Crea la pantalla con el mejor backend disponible.

    ``prefer`` puede ser "pil", "pygame", "fb" o "auto" (por defecto).  Si
    ``fb_device`` es una cadena vacía se fuerza el modo memoria (sin tocar la
    pantalla real), que es el que usan las vistas previas.
    """
    prefer = (prefer or "auto").lower()
    memory_mode = not fb_device

    if memory_mode:
        if shim.HAVE_PIL:
            from .fb import Surface

            return Surface(device="", width=width or 320, height=height or 240)
        return PygameMemoryDisplay(width=width or 320, height=height or 240)

    if prefer in ("auto", "pil") and shim.HAVE_PIL:
        from .fb import Surface

        try:
            return Surface(device=fb_device, width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            if prefer == "pil":
                raise DisplayError(str(exc)) from exc

    if prefer in ("auto", "fb", "pygame"):
        # 1) Framebuffer directo: no depende del driver de vídeo de SDL.
        if prefer in ("auto", "fb"):
            try:
                return FramebufferDisplay(device=fb_device)
            except DisplayError:
                if prefer == "fb":
                    raise
        # 2) SDL2 sobre el framebuffer (plan B).
        try:
            return PygameDisplay(width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            if prefer == "pygame":
                raise DisplayError(str(exc)) from exc

    # Último recurso: memoria (permite previsualizar y probar sin pantalla).
    if shim.HAVE_PIL:
        from .fb import Surface

        return Surface(device="", width=width or 320, height=height or 240)

    return PygameMemoryDisplay(width=width or 320, height=height or 240)
