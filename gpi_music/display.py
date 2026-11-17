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
        forced = os.environ.get("SDL_VIDEODRIVER")
        candidates = [forced] if forced else ["fbcon", "kmsdrm", None]
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


def create_display(fb_device: str = "/dev/fb0", prefer: Optional[str] = None,
                   width: int = 0, height: int = 0):
    """Crea la pantalla con el mejor backend disponible.

    ``prefer`` puede ser "pil", "pygame" o "auto" (por defecto).
    """
    prefer = (prefer or "auto").lower()

    if prefer in ("auto", "pil") and shim.HAVE_PIL:
        from .fb import Surface

        try:
            return Surface(device=fb_device, width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            if prefer == "pil":
                raise DisplayError(str(exc)) from exc

    if prefer in ("auto", "pygame"):
        try:
            return PygameDisplay(width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            if prefer == "pygame":
                raise DisplayError(str(exc)) from exc

    # Último recurso: memoria (permite previsualizar y probar sin pantalla).
    if shim.HAVE_PIL:
        from .fb import Surface

        return Surface(device="", width=width or 320, height=height or 240)

    raise DisplayError(
        "no hay backend de dibujo disponible (instala Pillow o pygame)"
    )
