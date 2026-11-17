"""Descubrimiento de la biblioteca musical.

Tres tipos de fuente:

* **local**: carpetas dentro de la microSD (``~/RetroPie/roms/music``).
* **mount**: montajes de red (Samba/NFS) que aparecen bajo ``/mnt``.
* **mpd**: servidores Music Player Daemon alcanzables por la red.

Todas se funden en una sola lista para que el usuario no tenga que pensar de
dónde viene cada pista.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .metadata import read_metadata

__all__ = ["Track", "Source", "scan_directory", "discover_mounts", "build_library"]


@dataclass
class Track:
    uri: str
    source_id: str
    source_label: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: Optional[float] = None
    remote: bool = False

    @property
    def display(self) -> str:
        if self.artist and self.artist.lower() not in self.title.lower():
            return f"{self.artist} - {self.title}"
        return self.title or os.path.basename(self.uri)


@dataclass
class Source:
    id: str
    label: str
    kind: str  # local | mount | mpd
    tracks: List[Track] = field(default_factory=list)
    available: bool = True
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.tracks)


def _is_hidden(name: str, skip_hidden: bool) -> bool:
    return skip_hidden and name.startswith(".")


def scan_directory(
    root: str,
    extensions: Iterable[str],
    source_id: str,
    source_label: str,
    recursive: bool = True,
    skip_hidden: bool = True,
    max_tracks: int = 20000,
) -> List[Track]:
    """Recorre ``root`` y devuelve las pistas de audio encontradas."""
    exts = {e.lower() for e in extensions}
    tracks: List[Track] = []
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return tracks

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d, skip_hidden))
        if not recursive and dirpath != root:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            if _is_hidden(name, skip_hidden):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in exts:
                continue
            full = os.path.join(dirpath, name)
            tags = read_metadata(full)
            tracks.append(
                Track(
                    uri=full,
                    source_id=source_id,
                    source_label=source_label,
                    title=tags.title,
                    artist=tags.artist,
                    album=tags.album,
                    duration=tags.duration,
                )
            )
            if len(tracks) >= max_tracks:
                return tracks
    return tracks


def discover_mounts(roots: Iterable[str]) -> List[tuple]:
    """Devuelve [(ruta, etiqueta)] de los montajes de red encontrados.

    Se consideran montajes las carpetas de primer nivel dentro de ``/mnt``
    (Samba monta un share por carpeta) y también los subdirectorios
    ``Music``/``Música`` que suelen existir dentro de un share.
    """
    found: List[tuple] = []
    for root in roots:
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if not os.path.isdir(path):
                continue
            music_sub = None
            for candidate in ("Music", "music", "Música", "Musica", "música"):
                sub = os.path.join(path, candidate)
                if os.path.isdir(sub):
                    music_sub = sub
                    break
            found.append((path, name))
            if music_sub:
                found.append((music_sub, f"{name}/{os.path.basename(music_sub)}"))
    return found


def build_library(config, mpd_clients=None) -> List[Source]:
    """Construye la lista de fuentes con sus pistas.

    ``mpd_clients`` es una lista de objetos con ``host``, ``port`` y un método
    ``list_tracks()``; si no se pasa, se crean clientes MPD a partir de la
    configuración.
    """
    sources: List[Source] = []
    lib = config.library

    for path in config.expanded_local_paths():
        label = os.path.basename(path.rstrip("/")) or path
        source = Source(id=f"local:{path}", label=f"{label} (microSD)", kind="local")
        source.tracks = scan_directory(
            path,
            lib.extensions,
            source.id,
            source.label,
            recursive=lib.recursive,
            skip_hidden=lib.skip_hidden,
            max_tracks=lib.max_tracks_per_source,
        )
        source.available = os.path.isdir(path)
        if not source.available:
            source.error = "carpeta no encontrada"
        sources.append(source)

    if lib.scan_mounts:
        for path, label in discover_mounts(config.expanded_mount_roots()):
            source = Source(id=f"mount:{path}", label=f"{label} (red)", kind="mount")
            source.tracks = scan_directory(
                path,
                lib.extensions,
                source.id,
                source.label,
                recursive=lib.recursive,
                skip_hidden=lib.skip_hidden,
                max_tracks=lib.max_tracks_per_source,
            )
            sources.append(source)

    clients = mpd_clients
    if clients is None:
        from .mpd import MPDClient  # import local para no cargar sockets al inicio

        clients = [MPDClient(host, port) for host, port in config.mpd_targets()]
    for client in clients:
        source = Source(
            id=f"mpd:{client.host}:{client.port}",
            label=f"{client.host} (MPD)",
            kind="mpd",
        )
        try:
            source.tracks = client.list_tracks()
        except Exception as exc:  # noqa: BLE001
            source.available = False
            source.error = str(exc) or "sin respuesta"
        sources.append(source)

    return sources
