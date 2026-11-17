"""Configuración de gpi-music.

La configuración vive en ``~/.config/gpi-music/config.json`` (o en la ruta
indicada por la variable de entorno ``GPI_MUSIC_CONFIG``). El archivo es
opcional: si no existe se usan los valores por defecto y se escribe uno nuevo
la primera vez que se guarda.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/gpi-music/config.json")

AUDIO_EXTENSIONS = [
    ".mp3",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".flac",
    ".m4a",
    ".mp4",
    ".aac",
    ".wma",
]


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def detect_platform() -> str:
    """Detecta la distribución de la consola: recalbox, retropie o generic."""
    if os.path.isdir("/recalbox/share"):
        return "recalbox"
    if os.path.isdir("/opt/retropie"):
        return "retropie"
    return "generic"


def default_local_paths() -> List[str]:
    """Carpetas de música según la plataforma detectada."""
    platform = detect_platform()
    if platform == "recalbox":
        return ["/recalbox/share/roms/music", "/recalbox/share/music"]
    if platform == "retropie":
        return ["~/RetroPie/roms/music", "~/Music"]
    return ["~/Music", os.path.join(os.path.expanduser("~"), "music")]


@dataclass
class LibraryConfig:
    """Dónde buscar música."""

    # Carpetas locales montadas en la microSD.
    local_paths: List[str] = field(default_factory=default_local_paths)
    # Montajes de red (Samba/NFS) que se montan en /mnt.
    scan_mounts: bool = True
    mount_roots: List[str] = field(default_factory=lambda: ["/mnt"])
    # Servidores MPD (host, puerto). Lista de [host, puerto].
    mpd_hosts: List[List[Any]] = field(default_factory=list)
    extensions: List[str] = field(default_factory=lambda: list(AUDIO_EXTENSIONS))
    recursive: bool = True
    # Oculta archivos ocultos y carpetas del sistema.
    skip_hidden: bool = True
    # Máximo de pistas por fuente (evita escanear bibliotecas enormes).
    max_tracks_per_source: int = 20000


@dataclass
class PlayerConfig:
    """Cómo suena."""

    volume: float = 0.7
    # auto | mpv | mpg123 | ffmpeg
    backend: str = "auto"
    shuffle: bool = False
    repeat: bool = False
    # Salta a la siguiente pista en cuanto termina la actual (sinGapless real).
    gapless: bool = True
    # Mezclador ALSA opcional para el volumen por software.
    alsa_mixer: str = ""
    # Segundos de salto rápido.
    seek_step: int = 15


@dataclass
class UiConfig:
    """Cómo se ve."""

    theme: str = "pixel"
    # Tamaño de fuente base; se ajusta si la pantalla es pequeña.
    font_size: int = 15
    show_cover: bool = True
    show_source_badge: bool = True
    # Frames por segundo del bucle de redibujado.
    fps: int = 20


@dataclass
class Config:
    library: LibraryConfig = field(default_factory=LibraryConfig)
    player: PlayerConfig = field(default_factory=PlayerConfig)
    ui: UiConfig = field(default_factory=UiConfig)

    # -------------------------------------------------------------- carga ---
    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        path = path or os.environ.get("GPI_MUSIC_CONFIG") or DEFAULT_CONFIG_PATH
        cfg = cls.default()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                raw = {}
            cfg = cfg.merge(raw)
        cfg.path = path  # type: ignore[attr-defined]
        return cfg

    def merge(self, raw: Dict[str, Any]) -> "Config":
        """Devuelve una copia con ``raw`` aplicado encima de los valores actuales."""
        data = asdict(self)
        for section, values in raw.items():
            if isinstance(values, dict) and isinstance(data.get(section), dict):
                data[section].update(values)
            elif section in data:
                data[section] = values
        return _from_dict(data)

    # ------------------------------------------------------------ guardado ---
    def save(self, path: Optional[str] = None) -> str:
        path = path or getattr(self, "path", None) or DEFAULT_CONFIG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return path

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # ------------------------------------------------------------- utiles ---
    def expanded_local_paths(self) -> List[str]:
        return [_expand(p) for p in self.library.local_paths]

    def expanded_mount_roots(self) -> List[str]:
        return [_expand(p) for p in self.library.mount_roots]

    def mpd_targets(self) -> List[tuple]:
        targets = []
        for entry in self.library.mpd_hosts:
            try:
                host = str(entry[0])
                port = int(entry[1]) if len(entry) > 1 else 6600
            except (TypeError, ValueError, IndexError):
                continue
            targets.append((host, port))
        return targets


def _from_dict(data: Dict[str, Any]) -> Config:
    lib = LibraryConfig(**_filter(LibraryConfig, data.get("library", {})))
    pla = PlayerConfig(**_filter(PlayerConfig, data.get("player", {})))
    ui = UiConfig(**_filter(UiConfig, data.get("ui", {})))
    return Config(library=lib, player=pla, ui=ui)


def _filter(cls, values: Any) -> Dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    out = {k: v for k, v in values.items() if k in valid}
    # Copia profunda de listas/dicts para no compartir referencias.
    return copy.deepcopy(out)
