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

    if "--browser" in sys.argv:
        from gpi_music.browser import Entry

        app.view = "files"
        app.browse_path = "/recalbox/share/roms/music"
        app.browse_entries = [
            Entry("/recalbox/share/roms", "..", True, False),
            Entry("/recalbox/share/roms/music/Album 2019", "Album 2019", True, False),
            Entry("/recalbox/share/roms/music/Podcasts", "Podcasts", True, False),
            Entry("/recalbox/share/roms/music/01 - Ferretown Morning.mp3", "01 - Ferretown Morning.mp3", False, True),
            Entry("/recalbox/share/roms/music/02 - Nightcall.flac", "02 - Nightcall.flac", False, True),
            Entry("/recalbox/share/roms/music/03 - Midnight City.opus", "03 - Midnight City.opus", False, True),
        ]
        app.browse_index = 3
        app.ui.draw_filebrowser(app.browse_path, app.browse_entries, app.browse_index)
        surface.save_png(path)
        print("Previsualización guardada en %s" % path)
        return 0

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


class _EventLog:
    """Escribe los eventos de entrada en un fichero (diagnóstico a distancia).

    El fichero se recorta cuando pasa de 256 KB para que no crezca sin fin en
    la microSD.
    """

    MAX_BYTES = 256 * 1024

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh = None
        try:
            folder = os.path.dirname(os.path.abspath(path))
            if folder:
                os.makedirs(folder, exist_ok=True)
            if os.path.isfile(path) and os.path.getsize(path) > self.MAX_BYTES:
                os.remove(path)
            self._fh = open(path, "a", encoding="utf-8")
        except OSError:
            self._fh = None

    def __call__(self, line: str) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(line + "\n")
            self._fh.flush()
        except OSError:
            pass

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def _display_prefer(name: str) -> str:
    """Traduce la opción ``--display`` al nombre que entiende ``create_display``."""
    if name == "sdl":
        return "pygame"
    if name == "pil":
        return "pil"
    if name == "fb":
        return "fb"
    return "auto"


def _install_faulthandler() -> None:
    """Permite volcar la traza de los hilos si la app se queda colgada.

    Con ``kill -USR1 <pid>`` se escribe la traza de todos los hilos en
    ``/tmp/gpi-music-stack.log``; es la forma rápida de saber dónde se ha
    quedado bloqueada la aplicación.
    """
    try:
        import faulthandler
        import signal

        path = os.environ.get("GPI_MUSIC_STACK_LOG", "/tmp/gpi-music-stack.log")
        handler = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=handler)
        faulthandler.register(signal.SIGUSR1, file=handler, all_threads=True)
    except Exception:  # noqa: BLE001 - el diagnóstico nunca debe romper la app
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gpi-music", description="Reproductor de música para GPi Case")
    parser.add_argument("--config", help="ruta del archivo de configuración")
    parser.add_argument("--fb", default="/dev/fb0", help="dispositivo de framebuffer")
    parser.add_argument("--display", default="auto", choices=("auto", "fb", "sdl", "pil"),
                        help="backend de dibujo: fb (framebuffer directo), sdl (SDL/Dispmanx)")
    parser.add_argument("--scan", action="store_true", help="lista la biblioteca y sale")
    parser.add_argument("--preview", metavar="ARCHIVO", help="guarda un PNG de la interfaz y sale")
    parser.add_argument("--playing", action="store_true", help="con --preview, muestra la vista de reproducción")
    parser.add_argument("--width", type=int, default=320, help="ancho para el modo preview")
    parser.add_argument("--height", type=int, default=240, help="alto para el modo preview")
    parser.add_argument("--no-input", action="store_true", help="no lee los botones (diagnóstico)")
    parser.add_argument("--browse", nargs="?", const="", metavar="CARPETA",
                        help="abre el explorador de archivos al arrancar")
    parser.add_argument("--log-input", metavar="ARCHIVO",
                        help="guarda los eventos de los botones en un fichero")
    parser.add_argument("--fps", type=int, default=0, help="fps del bucle de dibujo")
    parser.add_argument("track", nargs="?", help="pista concreta que se pone a sonar")
    args, _unknown = parser.parse_known_args(argv)

    config = Config.load(args.config)
    if args.fps:
        config.ui.fps = args.fps

    _install_faulthandler()

    if args.preview:
        return _preview(config, args.preview, args.width, args.height)
    if args.scan:
        return _scan(config)

    try:
        display = create_display(args.fb, prefer=_display_prefer(args.display))
    except DisplayError as exc:
        print("gpi-music: %s" % exc, file=sys.stderr)
        print("gpi-music: se continúa sin pantalla (modo headless)", file=sys.stderr)
        display = create_display("")

    backends = available_backends()
    print("gpi-music: backends de dibujo: %s" % ", ".join(
        name for name, ok in backends.items() if ok and name != "framebuffer"), file=sys.stderr)

    reader = None
    event_log = None
    if not args.no_input:
        log_path = args.log_input or config.input.log_path
        if log_path:
            event_log = _EventLog(log_path)
            print("gpi-music: registrando los botones en %s" % log_path, file=sys.stderr)
        reader = InputReader(
            keymap=config.input.keymap,
            repeat_delay=config.input.repeat_delay,
            repeat_rate=config.input.repeat_rate,
            events_log=event_log,
        )
        if not reader.devices:
            print("gpi-music: no se encontraron dispositivos de entrada", file=sys.stderr)
        else:
            print("gpi-music: dispositivos: %s" % ", ".join(reader.devices), file=sys.stderr)

    from .app import App

    app = App(config, display, input_reader=reader, start_track=args.track)
    if args.browse is not None:
        app.start_browse = True
        if args.browse:
            app.browse_path = os.path.abspath(args.browse)
    app.start_scan()
    try:
        app.run()
    finally:
        if reader:
            reader.close()
        if event_log:
            event_log.close()
        display.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
