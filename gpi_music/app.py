"""Aplicación: biblioteca, reproducción y navegación con los botones."""

from __future__ import annotations

import os
import random
import signal
import threading
import time
from typing import List, Optional

from .config import Config
from .browser import Entry, list_directory, parent_directory
from .input import (
    ACTION_BACK,
    ACTION_BROWSE,
    ACTION_CONFIRM,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_MENU,
    ACTION_MUTE,
    ACTION_NEXT,
    ACTION_PREV,
    ACTION_RIGHT,
    ACTION_TOGGLE,
    ACTION_UP,
    ACTION_VOLUME_DOWN,
    ACTION_VOLUME_UP,
    InputReader,
)
from .library import Source, Track, build_library
from .metadata import read_metadata
from .player import PlaybackEngine, create_engine
from .ui import UI

__all__ = ["App"]

VIEW_SCANNING = "scanning"
VIEW_LIBRARY = "library"
VIEW_PLAYING = "playing"
VIEW_OPTIONS = "options"
VIEW_MESSAGE = "message"
VIEW_FILES = "files"
VIEW_DEBUG = "debug"


class App:
    def __init__(
        self,
        config: Config,
        display,
        input_reader: Optional[InputReader] = None,
        engine: Optional[PlaybackEngine] = None,
        start_track: Optional[str] = None,
    ) -> None:
        self.config = config
        self.display = display
        self.surface = display  # alias compatible
        self.inputs = input_reader
        self.engine = engine or create_engine(config.player.backend, config.player.alsa_mixer)
        self.ui = UI(display, base_font_size=config.ui.font_size)
        self.start_track = start_track
        self.start_browse = False

        self.view = VIEW_SCANNING
        self.sources: List[Source] = []
        self.tracks: List[Track] = []
        self.index = 0
        self.playing: Optional[Track] = None
        self.paused = False
        self.volume = config.player.volume
        self.shuffle = config.player.shuffle
        self.repeat = config.player.repeat
        self.options_index = 0
        self.message = ""
        self.message_sub = ""
        # Explorador de archivos.
        self.browse_path = ""
        self.browse_entries: List[Entry] = []
        self.browse_index = 0
        self.browse_show_all = False
        # Cola de reproducción para los ficheros sueltos del explorador.
        self.play_queue: Optional[List[Track]] = None
        self.play_queue_index = 0
        self._menu_from = VIEW_LIBRARY
        self._debug_return = VIEW_LIBRARY
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_error = ""
        self._running = True
        self._mpd_clients = {}

    # ------------------------------------------------------------ scanning ---
    def start_scan(self) -> None:
        """Lanza el escaneo de la biblioteca en segundo plano."""

        def worker() -> None:
            try:
                self.sources = build_library(self.config)
                tracks: List[Track] = []
                for source in self.sources:
                    tracks.extend(source.tracks)
                self.tracks = tracks
                self._scan_error = ""
            except Exception as exc:  # noqa: BLE001
                self._scan_error = str(exc)
                self.sources = []
                self.tracks = []

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _scan_done(self) -> bool:
        return self._scan_thread is None or not self._scan_thread.is_alive()

    def _maybe_start_requested_track(self) -> None:
        """Si EmulationStation lanzó una pista concreta, la pone a sonar."""
        if not self.start_track or not self.tracks:
            return
        wanted = os.path.abspath(os.path.expanduser(self.start_track))
        for position, track in enumerate(self.tracks):
            if os.path.abspath(track.uri) == wanted:
                self.index = position
                self.play_track(track)
                self.view = VIEW_PLAYING
                self.start_track = None
                return

    # ------------------------------------------------------------ explorador ---
    def _browser_start_path(self) -> str:
        """Carpeta por la que se abre el explorador."""
        for path in self.config.expanded_local_paths():
            if os.path.isdir(path):
                return path
        return "/"

    def open_browser(self, path: Optional[str] = None) -> None:
        """Abre el explorador de archivos (o vuelve a la biblioteca)."""
        if self.view == VIEW_FILES:
            self.view = VIEW_LIBRARY
            return
        self.browse_path = os.path.abspath(path or self.browse_path or self._browser_start_path())
        self._reload_browser()
        self.view = VIEW_FILES

    def _reload_browser(self) -> None:
        extensions = self.config.library.extensions
        entries = list_directory(
            self.browse_path,
            extensions,
            show_hidden=self.browse_show_all,
            show_all=self.browse_show_all,
        )
        # La primera fila es la carpeta superior.
        parent = parent_directory(self.browse_path)
        rows: List[Entry] = [Entry(parent, "..", True, False)]
        rows.extend(entries)
        self.browse_entries = rows
        self.browse_index = 0

    def _browse_to(self, path: str) -> None:
        self.browse_path = os.path.abspath(path)
        self._reload_browser()

    def browse_move(self, delta: int) -> None:
        if not self.browse_entries:
            return
        self.browse_index = max(0, min(len(self.browse_entries) - 1, self.browse_index + delta))

    def browse_activate(self) -> None:
        """A: entra en la carpeta o reproduce el archivo."""
        if not self.browse_entries:
            return
        entry = self.browse_entries[self.browse_index]
        if entry.name == "..":
            self.browse_back()
            return
        if entry.is_dir:
            self._browse_to(entry.path)
            return
        if entry.is_audio:
            self._play_browser_entry(entry)

    def browse_back(self) -> None:
        """B: sube un nivel; en la raíz vuelve a la biblioteca."""
        parent = parent_directory(self.browse_path)
        if parent == self.browse_path:
            self.view = VIEW_LIBRARY
            return
        self._browse_to(parent)

    def browse_toggle_filter(self) -> None:
        """X: muestra u oculta los archivos que no son de audio."""
        self.browse_show_all = not self.browse_show_all
        self._reload_browser()

    def _browser_queue(self) -> List[Track]:
        """Pistas de audio de la carpeta actual, para encadenar la reproducción."""
        label = os.path.basename(self.browse_path.rstrip("/")) or self.browse_path
        source_id = "browser:%s" % self.browse_path
        queue: List[Track] = []
        for entry in self.browse_entries:
            if entry.is_audio:
                queue.append(Track(uri=entry.path, source_id=source_id,
                                   source_label="%s (microSD)" % label))
        return queue

    def _play_browser_entry(self, entry: Entry) -> None:
        queue = self._browser_queue()
        position = 0
        for pos, item in enumerate(queue):
            if item.uri == entry.path:
                position = pos
                break
        track = queue[position] if queue else Track(uri=entry.path, source_id="browser", source_label="archivo")
        self.play_queue = queue
        self.play_queue_index = position
        self._enrich(track)
        self.play_track(track)
        self.view = VIEW_PLAYING

    def _enrich(self, track: Track) -> None:
        """Rellena los metadatos de una pista suelta (explorador)."""
        try:
            tags = read_metadata(track.uri)
        except Exception:  # noqa: BLE001
            return
        if tags.title:
            track.title = tags.title
        if tags.artist:
            track.artist = tags.artist
        if tags.album:
            track.album = tags.album
        if tags.duration:
            track.duration = tags.duration

    def add_current_folder_to_library(self) -> None:
        """Añade la carpeta actual a la biblioteca y vuelve a escanear."""
        path = self.browse_path
        paths = self.config.library.local_paths
        if path not in paths:
            paths.append(path)
        try:
            self.config.save()
        except OSError as exc:
            self.message = "No se pudo guardar la configuración"
            self.message_sub = str(exc)[:60]
            self.view = VIEW_MESSAGE
            return
        self.view = VIEW_SCANNING
        self.start_scan()

    # ------------------------------------------------------------- playback ---
    def _current(self) -> Optional[Track]:
        if not self.tracks:
            return None
        self.index = max(0, min(self.index, len(self.tracks) - 1))
        return self.tracks[self.index]

    def _mpd_client_for(self, track: Track):
        from .mpd import MPDClient

        key = track.source_id
        if key not in self._mpd_clients:
            _, host, port = key.split(":")
            self._mpd_clients[key] = MPDClient(host, int(port))
        return self._mpd_clients[key]

    def play_track(self, track: Track) -> None:
        self.playing = track
        self.paused = False
        try:
            if track.remote:
                client = self._mpd_client_for(track)
                client.add(track.uri)
                client.play()
            else:
                self.engine.play(track.uri, track.duration)
                self.engine.set_volume(self.volume)
        except Exception as exc:  # noqa: BLE001
            self.playing = None
            self.message = "No se pudo reproducir"
            self.message_sub = str(exc)[:60]
            self.view = VIEW_MESSAGE

    def stop_playback(self) -> None:
        if self.playing is not None and self.playing.remote:
            try:
                self._mpd_client_for(self.playing).stop()
            except Exception:  # noqa: BLE001
                pass
        else:
            self.engine.stop()
        self.playing = None
        self.paused = False

    def toggle_pause(self) -> None:
        if self.playing is None:
            return
        if self.playing.remote:
            try:
                client = self._mpd_client_for(self.playing)
                client.pause() if not self.paused else client.play()
            except Exception:  # noqa: BLE001
                pass
        else:
            self.engine.toggle_pause()
        self.paused = not self.paused

    def next_track(self) -> None:
        if self.play_queue:
            self.play_queue_index = (self.play_queue_index + 1) % len(self.play_queue)
            track = self.play_queue[self.play_queue_index]
            self._enrich(track)
            self.play_track(track)
            return
        if not self.tracks:
            return
        if self.shuffle:
            self.index = random.randrange(len(self.tracks))
        else:
            self.index = (self.index + 1) % len(self.tracks)
        track = self._current()
        if track:
            self.play_track(track)

    def prev_track(self) -> None:
        if self.play_queue:
            self.play_queue_index = (self.play_queue_index - 1) % len(self.play_queue)
            track = self.play_queue[self.play_queue_index]
            self._enrich(track)
            self.play_track(track)
            return
        if not self.tracks:
            return
        if self.shuffle:
            self.index = random.randrange(len(self.tracks))
        else:
            self.index = (self.index - 1) % len(self.tracks)
        track = self._current()
        if track:
            self.play_track(track)

    def seek(self, seconds: float) -> None:
        if self.playing is None:
            return
        if self.playing.remote:
            try:
                client = self._mpd_client_for(self.playing)
                status = client.status()
                current = _status_elapsed(status)
                client.seek(current + seconds)
            except Exception:  # noqa: BLE001
                pass
        else:
            self.engine.seek(seconds)

    def set_volume(self, value: float) -> None:
        self.volume = max(0.0, min(1.0, value))
        self.engine.set_volume(self.volume)

    # ------------------------------------------------------------ posición ---
    def playback_position(self) -> float:
        if self.playing is None:
            return 0.0
        if self.playing.remote:
            try:
                status = self._mpd_client_for(self.playing).status()
                return _status_elapsed(status)
            except Exception:  # noqa: BLE001
                return 0.0
        return self.engine.position()

    def playback_duration(self) -> Optional[float]:
        if self.playing is None:
            return None
        if self.playing.remote:
            try:
                status = self._mpd_client_for(self.playing).status()
                return _status_duration(status)
            except Exception:  # noqa: BLE001
                return None
        return self.playing.duration or self.engine.duration

    def playback_finished(self) -> bool:
        if self.playing is None:
            return False
        if self.playing.remote:
            try:
                status = self._mpd_client_for(self.playing).status()
                return status.get("state") == "stopped"
            except Exception:  # noqa: BLE001
                return False
        return self.engine.is_finished()

    # ---------------------------------------------------------------- loop ---
    def handle_action(self, action: str) -> None:
        if action == ACTION_VOLUME_UP:
            self.set_volume(self.volume + 0.1)
            return
        if action == ACTION_VOLUME_DOWN:
            self.set_volume(self.volume - 0.1)
            return
        if action == ACTION_MUTE:
            self.set_volume(0.0 if self.volume > 0 else self.config.player.volume)
            return

        if action == ACTION_BROWSE:
            # El botón de archivos abre o cierra el explorador desde cualquier vista.
            if self.view == VIEW_DEBUG:
                self.view = self._debug_return
            else:
                self.open_browser()
            return

        if self.view == VIEW_LIBRARY:
            if action == ACTION_UP:
                self.index = max(0, self.index - 1)
            elif action == ACTION_DOWN:
                self.index = min(max(0, len(self.tracks) - 1), self.index + 1)
            elif action == ACTION_CONFIRM:
                track = self._current()
                if track:
                    self.play_track(track)
                    self.view = VIEW_PLAYING
            elif action == ACTION_BACK:
                self.stop_playback()
                self._quit()
            elif action == ACTION_MENU:
                self._menu_from = VIEW_LIBRARY
                self.options_index = 0
                self.view = VIEW_OPTIONS
            elif action == ACTION_NEXT:
                self.next_track()
                self.view = VIEW_PLAYING
            elif action == ACTION_PREV:
                self.prev_track()
                self.view = VIEW_PLAYING
        elif self.view == VIEW_PLAYING:
            if action == ACTION_CONFIRM or action == ACTION_TOGGLE:
                self.toggle_pause()
            elif action == ACTION_BACK:
                self.stop_playback()
                self.play_queue = None
                self.view = VIEW_LIBRARY
            elif action == ACTION_NEXT:
                self.next_track()
            elif action == ACTION_PREV:
                self.prev_track()
            elif action == ACTION_LEFT:
                self.seek(-self.config.player.seek_step)
            elif action == ACTION_RIGHT:
                self.seek(self.config.player.seek_step)
            elif action == ACTION_MENU:
                self._menu_from = VIEW_PLAYING
                self.options_index = 0
                self.view = VIEW_OPTIONS
        elif self.view == VIEW_FILES:
            if action == ACTION_UP:
                self.browse_move(-1)
            elif action == ACTION_DOWN:
                self.browse_move(1)
            elif action == ACTION_CONFIRM:
                self.browse_activate()
            elif action == ACTION_BACK:
                self.browse_back()
            elif action == ACTION_TOGGLE:
                self.browse_toggle_filter()
            elif action == ACTION_MENU:
                self._menu_from = VIEW_FILES
                self.options_index = 0
                self.view = VIEW_OPTIONS
            elif action == ACTION_NEXT:
                self.browse_move(5)
            elif action == ACTION_PREV:
                self.browse_move(-5)
        elif self.view == VIEW_OPTIONS:
            options = self._options()
            if action == ACTION_UP:
                self.options_index = (self.options_index - 1) % len(options)
            elif action == ACTION_DOWN:
                self.options_index = (self.options_index + 1) % len(options)
            elif action == ACTION_CONFIRM:
                self._run_option(options[self.options_index])
            elif action == ACTION_BACK:
                self.view = self._menu_from
        elif self.view == VIEW_DEBUG:
            if action in (ACTION_CONFIRM, ACTION_BACK, ACTION_MENU):
                self.view = self._debug_return
        elif self.view == VIEW_MESSAGE:
            if action in (ACTION_CONFIRM, ACTION_BACK):
                self.view = VIEW_LIBRARY

    def _options(self) -> List[str]:
        options = [
            "Aleatorio: %s" % ("sí" if self.shuffle else "no"),
            "Repetir: %s" % ("sí" if self.repeat else "no"),
            "Volumen: %d%%" % int(self.volume * 100),
        ]
        if self._menu_from == VIEW_FILES:
            options.append("Añadir carpeta a la biblioteca")
        options.append("Explorar archivos")
        options.append("Diagnóstico de botones")
        options.append("Escanear de nuevo")
        options.append("Salir a EmulationStation")
        return options

    def _run_option(self, option: str) -> None:
        if option.startswith("Aleatorio"):
            self.shuffle = not self.shuffle
        elif option.startswith("Repetir"):
            self.repeat = not self.repeat
        elif option.startswith("Volumen"):
            self.set_volume((self.volume + 0.1) % 1.01)
        elif option == "Añadir carpeta a la biblioteca":
            self.add_current_folder_to_library()
        elif option == "Explorar archivos":
            self.open_browser()
        elif option == "Diagnóstico de botones":
            self._debug_return = self._menu_from
            self.view = VIEW_DEBUG
        elif option == "Escanear de nuevo":
            self.view = VIEW_SCANNING
            self.start_scan()
        elif option == "Salir a EmulationStation":
            self.stop_playback()
            self._quit()

    # ----------------------------------------------------------------- run ---
    def _quit(self) -> None:
        self._running = False

    def stop(self) -> None:
        self.stop_playback()
        if hasattr(self.engine, "close"):
            self.engine.close()

    def run(self) -> None:
        frame_time = 1.0 / max(1, self.config.ui.fps)
        signal.signal(signal.SIGTERM, lambda *_: self._quit())
        signal.signal(signal.SIGINT, lambda *_: self._quit())

        while self._running:
            started = time.monotonic()

            if self.view == VIEW_SCANNING:
                if self._scan_done():
                    if self._scan_error:
                        self.message = "Error al escanear"
                        self.message_sub = self._scan_error[:60]
                        self.view = VIEW_MESSAGE
                    else:
                        self.view = VIEW_LIBRARY
                        self._maybe_start_requested_track()
                        if self.start_browse:
                            self.start_browse = False
                            self.open_browser()
                else:
                    self.ui.draw_scanning()
                    self.display.present()
                    time.sleep(frame_time)
                    continue

            if self.inputs is not None:
                for action in self.inputs.poll():
                    self.handle_action(action)

            # Avance automático al terminar la pista.
            if self.view == VIEW_PLAYING and self.playing is not None:
                if self.playback_finished():
                    if self.repeat:
                        self.play_track(self.playing)
                    else:
                        self.next_track()

            self.render()
            self.display.present()

            elapsed = time.monotonic() - started
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)

        self.stop()

    # --------------------------------------------------------------- render ---
    def _debug_lines(self) -> List[str]:
        """Líneas de la pantalla de diagnóstico de botones."""
        lines: List[str] = []
        if self.inputs is None:
            lines.append("sin lector de entrada")
            return lines
        names = ", ".join(os.path.basename(d) for d in self.inputs.devices)
        lines.append("dispositivos: %s" % (names or "ninguno"))
        lines.extend(self.inputs.events)
        return lines

    def render(self) -> None:
        if self.view == VIEW_SCANNING:
            self.ui.draw_scanning()
        elif self.view == VIEW_MESSAGE:
            self.ui.draw_message(self.message, self.message_sub)
        elif self.view == VIEW_OPTIONS:
            self.ui.draw_options(self._options(), self.options_index)
        elif self.view == VIEW_FILES:
            status = "todo" if self.browse_show_all else "audio"
            self.ui.draw_filebrowser(self.browse_path, self.browse_entries, self.browse_index, status)
        elif self.view == VIEW_DEBUG:
            self.ui.draw_debug(self._debug_lines())
        elif self.view == VIEW_PLAYING:
            track = self.playing
            if track is None:
                self.view = VIEW_LIBRARY
                return
            extras = ""
            if self.shuffle:
                extras += "ALEATORIO  "
            if self.repeat:
                extras += "REPETIR  "
            self.ui.draw_now_playing(
                track,
                self.playback_position(),
                self.playback_duration(),
                self.paused,
                self.volume,
                extras.strip(),
            )
        else:
            source_label = ""
            track = self._current()
            if track:
                source_label = track.source_label
            self.ui.draw_library(self.tracks, self.index, source_label, len(self.tracks))


def _status_elapsed(status: dict) -> float:
    if "elapsed" in status:
        try:
            return float(status["elapsed"])
        except ValueError:
            pass
    time_field = status.get("time", "")
    if ":" in time_field:
        left = time_field.split(":", 1)[0]
        try:
            return float(left)
        except ValueError:
            return 0.0
    return 0.0


def _status_duration(status: dict) -> Optional[float]:
    if "duration" in status:
        try:
            return float(status["duration"])
        except ValueError:
            pass
    time_field = status.get("time", "")
    if ":" in time_field:
        right = time_field.split(":", 1)[1]
        try:
            return float(right)
        except ValueError:
            return None
    return None
