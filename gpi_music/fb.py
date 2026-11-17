"""Superficie de dibujo sobre el framebuffer de la consola (``/dev/fb0``).

En el GPi Case la pantalla va por el bus DPI, así que el framebuffer del kernel
es el que hay que pintar. El formato se detecta en tiempo de ejecución:

* 32 bpp → ``BGRX``
* 24 bpp → ``BGR`` (con relleno hasta el *stride*)
* 16 bpp → RGB565 (numpy si está disponible; si no, una paleta de 256 tonos)

Si no hay framebuffer (por ejemplo en un escritorio) la superficie funciona
igual en memoria, lo que permite previsualizar la interfaz en un PNG.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

try:  # Pillow es obligatorio para el reproductor (o pygame, vía el shim).
    from .shim import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - se informa al usuario
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    raise ImportError(
        "gpi-music necesita Pillow o pygame para dibujar la pantalla"
    ) from exc

__all__ = ["Surface", "FBError"]


class FBError(Exception):
    pass


def _read_sysfs(name: str) -> str:
    try:
        with open("/sys/class/graphics/fb0/" + name, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _detect_fb_info(device: str) -> Tuple[int, int, int, int]:
    """Devuelve (ancho, alto, bpp, stride)."""
    width = int(_read_sysfs("virtual_width") or 0)
    height = int(_read_sysfs("virtual_height") or 0)
    bpp = int(_read_sysfs("bits_per_pixel") or 0)
    stride = int(_read_sysfs("stride") or 0)

    if not stride:
        # fbset da la información completa; si no está, se estima.
        try:
            import subprocess

            out = subprocess.run(
                ["fbset", "-i", device], capture_output=True, text=True, timeout=3
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("geometry"):
                    parts = line.split()
                    if len(parts) >= 4:
                        width = int(parts[1].split("x")[0])
                        height = int(parts[2].split("x")[0])
                elif line.startswith("depth"):
                    parts = line.split()
                    if len(parts) >= 2:
                        bpp = int(parts[1])
                elif line.startswith("stride"):
                    parts = line.split()
                    if len(parts) >= 2:
                        stride = int(parts[1])
        except Exception:  # noqa: BLE001
            pass

    if not width or not height:
        raise FBError("no se pudo detectar la resolución del framebuffer")
    if not bpp:
        bpp = 16
    if not stride:
        stride = width * max(3, bpp // 8)
    return width, height, bpp, stride


def _to5(value: int) -> int:
    """Mapea 0..5 a 0..31 (5 bits)."""
    return value * 31 // 5


def _to6(value: int) -> int:
    """Mapea 0..5 a 0..63 (6 bits)."""
    return value * 63 // 5


def _build_565_palette():
    """Paleta de 256 colores que aproxima el espacio RGB565 (si el backend lo soporta)."""
    palette = Image.new("P", (1, 1))
    data: List[int] = []
    for r in range(6):
        for g in range(6):
            for b in range(6):
                data.extend((_to5(r) * 255 // 31, _to6(g) * 255 // 63, _to5(b) * 255 // 31))
    for i in range(216, 256):
        v = int(i * 255 / 255)
        data.extend((v, v, v))
    try:
        palette.putpalette(data)
    except (AttributeError, ValueError):  # backend sin modo P
        return None
    return palette


class Surface:
    """Lienzo de la aplicación: mantiene una imagen y la vuelca al framebuffer."""

    def __init__(self, device: str = "/dev/fb0", width: int = 0, height: int = 0) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.bpp = 0
        self.stride = 0
        self.image: Optional[Image.Image] = None
        self._fd: Optional[int] = None
        self._palette = None
        self._numpy = None

        if device and os.path.exists(device):
            try:
                self.width, self.height, self.bpp, self.stride = _detect_fb_info(device)
                self._fd = os.open(device, os.O_WRONLY)
            except (OSError, FBError) as exc:
                raise FBError("no se pudo abrir %s: %s" % (device, exc)) from exc
        if not width or not height:
            # Modo memoria (previsualización / tests).
            width = width or 320
            height = height or 240
            self.width, self.height = width, height

        self.image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)
        if self.bpp == 16:
            try:
                import numpy  # type: ignore

                self._numpy = numpy
            except ImportError:
                self._palette = _build_565_palette()

    # --------------------------------------------------------------- utils ---
    @property
    def size(self) -> Tuple[int, int]:
        return self.width, self.height

    def clear(self, color=(0, 0, 0)) -> None:
        if self.image is not None:
            self.image.paste(color, (0, 0, self.width, self.height))

    # ------------------------------------------------------------- desenho ---
    def present(self) -> None:
        """Vuelca la imagen actual al framebuffer."""
        if self._fd is None or self.image is None:
            return
        data = self._pack(self.image)
        try:
            os.lseek(self._fd, 0, os.SEEK_SET)
            written = 0
            view = memoryview(data)
            while written < len(data):
                written += os.write(self._fd, view[written:])
        except OSError:
            pass

    def _pack(self, image: Image.Image) -> bytes:
        bpp = self.bpp or 24
        if bpp == 32:
            raw = image.convert("RGB").tobytes("raw", "BGRX")
            return self._pad_rows(raw, self.width * 4)
        if bpp == 24:
            raw = image.convert("RGB").tobytes("raw", "BGR")
            return self._pad_rows(raw, self.width * 3)
        if bpp == 16:
            return self._pack_565(image)
        # Fallback: 32 bpp es lo más habitual.
        return image.convert("RGB").tobytes("raw", "BGRX")

    def _pad_rows(self, raw: bytes, row_bytes: int) -> bytes:
        if self.stride in (0, row_bytes):
            return raw
        pad = self.stride - row_bytes
        if pad <= 0:
            return raw
        padding = b"\x00" * pad
        out = bytearray()
        for i in range(0, len(raw), row_bytes):
            out += raw[i:i + row_bytes]
            out += padding
        return bytes(out)

    def _pack_565(self, image: Image.Image) -> bytes:
        rgb = image.convert("RGB")
        if self._numpy is not None:
            numpy = self._numpy
            arr = numpy.asarray(rgb, dtype=numpy.uint16)
            r = (arr[:, :, 0] >> 3) << 11
            g = (arr[:, :, 1] >> 2) << 5
            b = arr[:, :, 2] >> 3
            packed = (r | g | b).astype(numpy.uint16)
            return packed.astype("<u2").tobytes()
        # Fallback sin numpy: paleta de 256 tonos -> 565.
        if self._palette is None:
            self._palette = _build_565_palette()
        if self._palette is None:
            return self._pack_565_slow(rgb)
        indexed = rgb.quantize(palette=self._palette)
        table = []
        for r in range(6):
            for g in range(6):
                for b in range(6):
                    value = (_to5(r) << 11) | (_to6(g) << 5) | _to5(b)
                    table.append(value.to_bytes(2, "little"))
        for i in range(216, 256):
            value = (i << 8) | i
            table.append(value.to_bytes(2, "little"))
        out = bytearray()
        for index in indexed.tobytes():
            out += table[index]
        return bytes(out)

    def _pack_565_slow(self, image) -> bytes:
        """Conversión RGB565 píxel a píxel (último recurso, sin numpy ni paleta)."""
        out = bytearray()
        for r, g, b in image.getdata():
            value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out += value.to_bytes(2, "little")
        return bytes(out)

    # ------------------------------------------------------------- salida ---
    def save_png(self, path: str) -> None:
        """Guarda el lienzo actual como PNG (para previsualizar en el PC)."""
        if self.image is None:
            raise FBError("no hay imagen que guardar")
        self.image.save(path)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
