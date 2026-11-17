"""Explorador de archivos para buscar música en la microSD o en la red.

Permite recorrer el sistema de archivos de la consola con los botones y
reproducir cualquier archivo de audio que no esté en la biblioteca, o añadir la
carpeta actual a la biblioteca para que aparezca en la lista.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List

__all__ = ["Entry", "list_directory", "parent_directory", "is_audio", "join_path"]


@dataclass
class Entry:
    """Una fila del explorador: una carpeta o un archivo."""

    path: str
    name: str
    is_dir: bool
    is_audio: bool
    size: int = 0

    @property
    def label(self) -> str:
        if self.name == "..":
            return ".."
        return self.name + "/" if self.is_dir else self.name


def is_audio(name: str, extensions: Iterable[str]) -> bool:
    """¿El nombre corresponde a una extensión de audio?"""
    ext = os.path.splitext(name)[1].lower()
    return ext in {e.lower() for e in extensions}


def join_path(directory: str, name: str) -> str:
    return os.path.join(directory, name)


def parent_directory(path: str) -> str:
    """Carpeta padre de ``path`` (``/`` si ya estamos en la raíz)."""
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    return parent if parent else "/"


def list_directory(
    path: str,
    extensions: Iterable[str],
    show_hidden: bool = False,
    show_all: bool = False,
    max_entries: int = 2000,
) -> List[Entry]:
    """Lista el contenido de ``path``: primero las carpetas, luego los archivos.

    Con ``show_all`` se muestran también los archivos que no son de audio; con
    ``show_hidden`` se incluyen los nombres que empiezan por punto.
    """
    entries: List[Entry] = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return entries

    for name in names:
        if not show_hidden and name.startswith("."):
            continue
        full = os.path.join(path, name)
        try:
            is_dir = os.path.isdir(full)
        except OSError:
            is_dir = False
        if is_dir:
            entries.append(Entry(full, name, True, False))
            continue
        audio = is_audio(name, extensions)
        if not audio and not show_all:
            continue
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        entries.append(Entry(full, name, False, audio, size))

    entries.sort(key=lambda e: (0 if e.is_dir else 1, e.name.lower()))
    return entries[:max_entries]
