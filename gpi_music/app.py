"""Aplicación: biblioteca, reproducción y navegación con los botones."""

from __future__ import annotations

import os
import random
import signal
import threading
import time
from typing import List, Optional

from .config import Config
from .input import (
    ACTION_BACK,
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
from .player import PlaybackEngine, create_engine
from .ui import UI

__all__ = ["App"]

VIEW_SCANNING = "scanning"
VIEW_LIBRARY = "library"
VIEW_PLAYING = "playing"
VIEW_OPTIONS = "options"
VIEW_MESSAGE = "message"


class App:
    def __init__(
        self,
        config: Config,
        surface,
        input_reader: Optional[InputReader] = None,
        engine: Optional[PlaybackEngine] = None,
        start_track: Optional[str] = None,
    ) -> None:
        self.config = config
        self.surface = surface
        self.inputs = input_reader
        self.engine = engine or create_engine(config.player.backend, config.player.alsa_mixer)
        self.ui = UI(surface, base_font_size=config.ui.font_size)
        self.start_track = start_track

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
                self.options_index = 0
                self.view = VIEW_OPTIONS
        elif self.view == VIEW_OPTIONS:
            options = self._options()
            if action == ACTION_UP:
                self.options_index = (self.options_index - 1) % len(options)
            elif action == ACTION_DOWN:
                self.options_index = (self.options_index + 1) % len(options)
            elif action == ACTION_CONFIRM:
                self._run_option(options[self.options_index])
            elif action == ACTION_BACK:
                self.view = VIEW_PLAYING if self.playing else VIEW_LIBRARY
        elif self.view == VIEW_MESSAGE:
            if action in (ACTION_CONFIRM, ACTION_BACK):
                self.view = VIEW_LIBRARY

    def _options(self) -> List[str]:
        return [
            "Aleatorio: %s" % ("sí" if self.shuffle else "no"),
            "Repetir: %s" % ("sí" if self.repeat else "no"),
            "Volumen: %d%%" % int(self.volume * 100),
            "Escanear de nuevo",
            "Salir a EmulationStation",
        ]

    def _run_option(self, option: str) -> None:
        if option.startswith("Aleatorio"):
            self.shuffle = not self.shuffle
        elif option.startswith("Repetir"):
            self.repeat = not self.repeat
        elif option.startswith("Volumen"):
            self.set_volume((self.volume + 0.1) % 1.01)
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
                else:
                    self.ui.draw_scanning()
                    self.surface.present()
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
            self.surface.present()

            elapsed = time.monotonic() - started
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)

        self.stop()

    # --------------------------------------------------------------- render ---
    def render(self) -> None:
        if self.view == VIEW_SCANNING:
            self.ui.draw_scanning()
        elif self.view == VIEW_MESSAGE:
            self.ui.draw_message(self.message, self.message_sub)
        elif self.view == VIEW_OPTIONS:
            self.ui.draw_options(self._options(), self.options_index)
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
