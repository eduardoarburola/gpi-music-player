"""Cliente mínimo de MPD (Music Player Daemon).

Implementa solo lo necesario para el reproductor: listar la biblioteca, ver el
estado y controlar la reproducción. Sin dependencias externas, para que
funcione en un Raspberry Pi Zero sin instalar nada extra.
"""

from __future__ import annotations

import socket
import time
from typing import Dict, List, Optional, Tuple

from .library import Track

__all__ = ["MPDClient", "MPDError"]

DEFAULT_TIMEOUT = 4.0


class MPDError(Exception):
    """Error devuelto por el servidor MPD."""


class MPDClient:
    def __init__(self, host: str, port: int = 6600, password: str = "", timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buffer = b""

    # ------------------------------------------------------------ conexión ---
    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock
        greeting = self._read_line()
        if not greeting.startswith("OK MPD"):
            self.close()
            raise MPDError(f"saludo inesperado de MPD: {greeting!r}")
        if self.password:
            self.command("password %s" % self.password)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._buffer = b""

    def __enter__(self) -> "MPDClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------- protocolo ---
    def _read_line(self) -> str:
        assert self._sock is not None
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise MPDError("el servidor MPD cerró la conexión")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip("\r")

    def command(self, cmd: str) -> List[str]:
        """Envía un comando y devuelve las líneas de la respuesta."""
        self.connect()
        assert self._sock is not None
        self._sock.sendall((cmd + "\n").encode("utf-8"))
        lines: List[str] = []
        while True:
            line = self._read_line()
            if line == "OK":
                return lines
            if line.startswith("ACK"):
                raise MPDError(line)
            lines.append(line)

    def command_pairs(self, cmd: str) -> List[Dict[str, str]]:
        """Igual que ``command`` pero devuelve pares clave/valor."""
        pairs: List[Dict[str, str]] = []
        for line in self.command(cmd):
            if ": " in line:
                key, value = line.split(": ", 1)
                pairs.append({key: value})
            elif ":" in line:
                key, value = line.split(":", 1)
                pairs.append({key: value})
        return pairs

    # ------------------------------------------------------------ biblioteca ---
    def list_tracks(self) -> List[Track]:
        """Devuelve la biblioteca completa como lista de pistas."""
        tracks: List[Track] = []
        current: Optional[Track] = None
        label = f"{self.host} (MPD)"
        source_id = f"mpd:{self.host}:{self.port}"
        for pair in self.command_pairs("listallinfo"):
            if "file" in pair:
                current = Track(
                    uri=pair["file"],
                    source_id=source_id,
                    source_label=label,
                    remote=True,
                )
                tracks.append(current)
                continue
            if current is None:
                continue
            key = next(iter(pair))
            value = pair[key]
            if key in ("Title", "title"):
                current.title = value
            elif key in ("Artist", "artist"):
                current.artist = value
            elif key in ("Album", "album"):
                current.album = value
            elif key in ("Time", "duration"):
                try:
                    current.duration = float(value)
                except ValueError:
                    pass
        return tracks

    # -------------------------------------------------------------- control ---
    def status(self) -> Dict[str, str]:
        status: Dict[str, str] = {}
        for pair in self.command_pairs("status"):
            status.update(pair)
        return status

    def play(self) -> None:
        self.command("play")

    def play_id(self, index: int) -> None:
        self.command("playid %d" % index)

    def pause(self) -> None:
        self.command("pause")

    def stop(self) -> None:
        self.command("stop")

    def next(self) -> None:
        self.command("next")

    def previous(self) -> None:
        self.command("previous")

    def add(self, uri: str) -> None:
        self.command('add "%s"' % uri.replace('"', '\\"'))

    def seek(self, seconds: float) -> None:
        self.command("seekcur %d" % int(seconds))

    def set_volume(self, volume: float) -> None:
        self.command("setvol %d" % int(max(0, min(100, round(volume * 100)))))

    def ping(self) -> bool:
        """Devuelve True si el servidor responde."""
        try:
            self.connect()
            self.command("ping")
            return True
        except (OSError, MPDError):
            return False
