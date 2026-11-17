"""Punto de entrada de gpi-music.

    python3 -m gpi_music              # reproductor normal
    python3 -m gpi_music --scan       # lista la biblioteca y sale
    python3 -m gpi_music --preview preview.png   # renderiza la interfaz a PNG
"""

from __future__ import annotations

import argparse
import os
import sys

from .config import Config
from .display import DisplayError, available_backends, create_display
from .input import InputReader
from .library import build_library


def _preview(config: Config, path: str, width: int, height: int) -> int:
    """Genera un PNG de la interfaz (útil para revisar el diseño sin consola)."""
    from .app import App
    from .library import Track

    surface = create_display("", width=width, height=height)
    app = App(config, surface, input_reader=None)
    app.tracks = [
        Track(uri="/home/pi/RetroPie/roms/music/01.mp3", source_id="local", source_label="music (microSD)",
              title="Ferretown Morning", artist="Duke Dumont", album="Jessi", duration=214),
        Track(uri="/home/pi/RetroPie/roms/music/02.mp3", source_id="local", source_label="music (microSD)",
              title="Nightcall", artist="Kavinsky", album="OutRun", duration=258),
        Track(uri="/mnt/nas/Music/03.flac", source_id="mount", source_label="nas (red)",
              title="Midnight City", artist="M83", album="Hurry Up, We're Dreaming", duration=244),
        Track(uri="nas/04.mp3", source_id="mpd", source_label="192.168.100.50 (MPD)",
              title="Digital Love", artist="Daft Punk", album="Discovery", duration=301),
        Track(uri="/home/pi/RetroPie/roms/music/05.ogg", source_id="local", source_label="music (microSD)",
              title="Sunset Lover", artist="Petit Biscuit", album="Presence", duration=209),
    ]
    app.index = 1
    app.playing = app.tracks[1]
    app.paused = False
    app.volume = 0.7
    app.shuffle = True
    app.view = "playing" if "--playing" in sys.argv else "library"

    if app.view == "library":
        app.ui.draw_library(app.tracks, app.index, app.tracks[app.index].source_label, len(app.tracks))
    else:
        app.ui.draw_now_playing(app.playing, 96.0, app.playing.duration, False, app.volume, "ALEATORIO")
    surface.save_png(path)
    print("Previsualización guardada en %s" % path)
    return 0


def _scan(config: Config) -> int:
    sources = build_library(config)
    total = 0
    for source in sources:
        print("== %s (%s)" % (source.label, source.kind))
        if source.error:
            print("   error: %s" % source.error)
        for track in source.tracks:
            duration = "%.0fs" % track.duration if track.duration else "--"
            print("   [%7s] %s - %s" % (duration, track.artist, track.title))
        total += source.count
        print("   -> %d pistas" % source.count)
    print("Total: %d pistas" % total)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gpi-music", description="Reproductor de música para GPi Case")
    parser.add_argument("--config", help="ruta del archivo de configuración")
    parser.add_argument("--fb", default="/dev/fb0", help="dispositivo de framebuffer")
    parser.add_argument("--scan", action="store_true", help="lista la biblioteca y sale")
    parser.add_argument("--preview", metavar="ARCHIVO", help="guarda un PNG de la interfaz y sale")
    parser.add_argument("--playing", action="store_true", help="con --preview, muestra la vista de reproducción")
    parser.add_argument("--width", type=int, default=320, help="ancho para el modo preview")
    parser.add_argument("--height", type=int, default=240, help="alto para el modo preview")
    parser.add_argument("--no-input", action="store_true", help="no lee los botones (diagnóstico)")
    parser.add_argument("--fps", type=int, default=0, help="fps del bucle de dibujo")
    parser.add_argument("track", nargs="?", help="pista concreta que se pone a sonar")
    args, _unknown = parser.parse_known_args(argv)

    config = Config.load(args.config)
    if args.fps:
        config.ui.fps = args.fps

    if args.preview:
        return _preview(config, args.preview, args.width, args.height)
    if args.scan:
        return _scan(config)

    try:
        display = create_display(args.fb)
    except DisplayError as exc:
        print("gpi-music: %s" % exc, file=sys.stderr)
        print("gpi-music: se continúa sin pantalla (modo headless)", file=sys.stderr)
        display = create_display("")

    backends = available_backends()
    print("gpi-music: backends de dibujo: %s" % ", ".join(
        name for name, ok in backends.items() if ok and name != "framebuffer"), file=sys.stderr)

    reader = None
    if not args.no_input:
        reader = InputReader()
        if not reader.devices:
            print("gpi-music: no se encontraron dispositivos de entrada", file=sys.stderr)

    from .app import App

    app = App(config, display, input_reader=reader, start_track=args.track)
    app.start_scan()
    try:
        app.run()
    finally:
        if reader:
            reader.close()
        display.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
