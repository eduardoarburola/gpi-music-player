"""Motores de reproducción de audio.

Tres backends, con detección automática:

* **mpv** (preferido): trae control fino (pausa, seek exacto, volumen,
  posición) vía su socket IPC JSON.
* **mpg123 / ogg123 / ffplay**: reproductores de línea de comandos, Ideales
  para un Raspberry Pi Zero porque consumen muy poco.

Los backends de línea de comandos no informs posición: se estima con el reloj
del sistema usando la duración que ya se conoce por los tags.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from typing import Dict, Optional

__all__ = ["available_backends", "create_engine", "PlaybackEngine"]

# Comando por extensión para los backends de línea de comandos.
_COMMANDS = {
    ".mp3": ["mpg123", "-q"],
    ".ogg": ["ogg123", "-q"],
    ".oga": ["ogg123", "-q"],
    ".opus": ["ogg123", "-q"],
    ".wav": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ".flac": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ".m4a": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ".mp4": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ".aac": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ".wma": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
}


def available_backends() -> Dict[str, bool]:
    """Qué reproductores están instalados en el sistema."""
    names = ["mpv", "mpg123", "ogg123", "ffplay", "ffmpeg", "amixer", "pactl"]
    return {name: shutil.which(name) is not None for name in names}


class PlaybackError(Exception):
    pass


class PlaybackEngine:
    """Interfaz común de los motores de reproducción."""

    def __init__(self) -> None:
        self.duration: Optional[float] = None
        self.volume = 0.7

    # ------------------------------------------------------------- playback ---
    def play(self, uri: str, duration: Optional[float] = None) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def toggle_pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def seek(self, seconds: float) -> None:
        raise NotImplementedError

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def position(self) -> float:
        raise NotImplementedError

    def is_playing(self) -> bool:
        raise NotImplementedError

    def is_finished(self) -> bool:
        raise NotImplementedError


class MpvEngine(PlaybackEngine):
    """mpv con IPC por socket Unix: control preciso de la reproducción."""

    def __init__(self, socket_path: Optional[str] = None) -> None:
        super().__init__()
        self.socket_path = socket_path or "/tmp/gpi-music-mpv.sock"
        self._proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._buffer = b""
        self._paused = False
        self._ended = False
        self._position = 0.0

    # ------------------------------------------------------------- interno ---
    def _start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        cmd = [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--no-terminal",
            "--idle=yes",
            "--keep-open=no",
            "--audio-display=no",
            "--input-ipc-server=%s" % self.socket_path,
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.05)
        time.sleep(0.15)

    def _connect(self) -> Optional[socket.socket]:
        if self._sock is not None:
            return self._sock
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(self.socket_path)
        except OSError:
            return None
        self._sock = sock
        self._buffer = b""
        return sock

    def _send(self, command) -> Optional[dict]:
        sock = self._connect()
        if sock is None:
            return None
        try:
            sock.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
        except OSError:
            self._sock = None
            return None
        while True:
            newline = self._buffer.find(b"\n")
            if newline == -1:
                try:
                    chunk = sock.recv(8192)
                except (socket.timeout, OSError):
                    return None
                if not chunk:
                    return None
                self._buffer += chunk
                continue
            line = self._buffer[:newline]
            self._buffer = self._buffer[newline + 1:]
            try:
                return json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue

    def _property(self, name: str):
        response = self._send(["get_property", name])
        if response and response.get("error") == "success":
            return response.get("data")
        return None

    # -------------------------------------------------------------- pública ---
    def play(self, uri: str, duration: Optional[float] = None) -> None:
        self._start()
        self.duration = duration
        self._ended = False
        self._position = 0.0
        self._paused = False
        self._send(["loadfile", uri, "replace"])
        self._send(["set_property", "volume", int(self.volume * 100)])

    def pause(self) -> None:
        self._send(["set_property", "pause", True])
        self._paused = True

    def resume(self) -> None:
        self._send(["set_property", "pause", False])
        self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        self._send(["stop"])
        self._ended = True

    def seek(self, seconds: float) -> None:
        self._send(["seek", float(seconds), "relative"])

    def set_volume(self, volume: float) -> None:
        super().set_volume(volume)
        self._send(["set_property", "volume", int(self.volume * 100)])

    def position(self) -> float:
        value = self._property("time-pos")
        if isinstance(value, (int, float)):
            self._position = float(value)
        return self._position

    def is_playing(self) -> bool:
        return not self._paused and not self._ended

    def is_finished(self) -> bool:
        state = self._property("eof-reached")
        if state:
            self._ended = True
        return self._ended

    def close(self) -> None:
        self.stop()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None


class CommandEngine(PlaybackEngine):
    """Reproducción con reproductores de línea de comandos (mpg123, ogg123...)."""

    def __init__(self, volume_mixer: str = "") -> None:
        super().__init__()
        self._proc: Optional[subprocess.Popen] = None
        self._started = 0.0
        self._paused = False
        self._ended = False
        self._offset = 0.0
        self.volume_mixer = volume_mixer

    def _command_for(self, uri: str):
        ext = os.path.splitext(uri)[1].lower()
        cmd = list(_COMMANDS.get(ext, []))
        if not cmd:
            return None
        if shutil.which(cmd[0]) is None:
            return None
        cmd.append(uri)
        return cmd

    def play(self, uri: str, duration: Optional[float] = None) -> None:
        self.stop()
        cmd = self._command_for(uri)
        if cmd is None:
            raise PlaybackError("no hay reproductor disponible para %s" % os.path.splitext(uri)[1])
        self.duration = duration
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._started = time.monotonic()
        self._offset = 0.0
        self._paused = False
        self._ended = False

    def pause(self) -> None:
        if self._proc is None:
            return
        if not self._paused:
            self._offset += time.monotonic() - self._started
        self._paused = True

    def resume(self) -> None:
        if self._proc is None or not self._paused:
            return
        self._started = time.monotonic()
        self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None
        self._ended = True

    def seek(self, seconds: float) -> None:
        # Sin control fino: se reinicia la pista desde el punto pedido.
        if self._proc is None:
            return
        uri = self._proc.args[-1]
        self._offset = max(0.0, self.position() + seconds)
        self._paused = False
        self._ended = False
        self._started = time.monotonic()
        try:
            self._proc.terminate()
            self._proc.wait(timeout=1.5)
        except Exception:  # noqa: BLE001
            pass
        self._proc = subprocess.Popen(
            self._proc.args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def set_volume(self, volume: float) -> None:
        super().set_volume(volume)
        if not self.volume_mixer:
            return
        mixer = self.volume_mixer
        percent = int(round(self.volume * 100))
        try:
            subprocess.run(
                ["amixer", "-q", "sset", mixer, "%d%%" % percent],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def position(self) -> float:
        if self._proc is None:
            return 0.0
        if self._paused:
            return self._offset
        elapsed = self._offset + (time.monotonic() - self._started)
        if self.duration and elapsed > self.duration:
            return self.duration
        return elapsed

    def is_playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._paused

    def is_finished(self) -> bool:
        if self._ended:
            return True
        if self._proc is not None and self._proc.poll() is not None:
            self._ended = True
        return self._ended


def create_engine(preference: str = "auto", volume_mixer: str = "") -> PlaybackEngine:
    """Crea el motor de reproducción según la preferencia y lo disponible."""
    if preference == "mpv" and shutil.which("mpv"):
        return MpvEngine()
    if preference not in ("auto", "", None):
        # Preferencia explícita de un motor de línea de comandos.
        return CommandEngine(volume_mixer)
    if shutil.which("mpv"):
        return MpvEngine()
    return CommandEngine(volume_mixer)
