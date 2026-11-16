#!/usr/bin/env python3
"""Añade (o actualiza) el sistema "Música" en el es_systems.cfg de EmulationStation.

Es idempotente: si el sistema ya existe lo reemplaza; nunca duplica entradas.
Siempre deja una copia de seguridad antes de tocar el archivo.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time

SYSTEM_NAME = "music"

TEMPLATE = """	<system>
		<name>{name}</name>
		<fullname>{fullname}</fullname>
		<path>%HOME%/RetroPie/roms/{romdir}</path>
		<extension>{extension}</extension>
		<command>{command}</command>
		<platform>{platform}</platform>
		<theme>{theme}</theme>
	</system>
"""

DEFAULT = {
    "name": SYSTEM_NAME,
    "fullname": "Música",
    "romdir": "music",
    "extension": ".mp3 .ogg .oga .opus .wav .flac .m4a .mp4 .aac .wma",
    "command": "/usr/local/bin/gpi-music %ROM%",
    "platform": "music",
    "theme": "music",
}


def build_block(values: dict) -> str:
    return TEMPLATE.format(**values)


def remove_system(text: str, name: str) -> str:
    """Quita el bloque <system> con ese <name> (si existe)."""
    pattern = re.compile(
        r"[ \t]*<system>.*?<name>\s*" + re.escape(name) + r"\s*</name>.*?</system>\s*",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("", text)


def patch_file(path: str, values: dict, backup: bool = True) -> str:
    if not os.path.isfile(path):
        return "missing"
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()

    cleaned = remove_system(original, values["name"])
    block = build_block(values)

    if "<systemList" in cleaned:
        index = cleaned.lower().rindex("</systemlist>")
        new_text = cleaned[:index] + block + cleaned[index:]
    else:
        new_text = "<systemList>\n" + block + "</systemList>\n"

    if new_text == original:
        return "unchanged"

    if backup:
        shutil.copy2(path, "%s.bak-%s" % (path, time.strftime("%Y%m%d%H%M%S")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return "updated"


def remove_only_patch(path: str, values: dict) -> str:
    """Quita el sistema del archivo sin añadir nada nuevo."""
    if not os.path.isfile(path):
        return "missing"
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    cleaned = remove_system(original, values["name"])
    if cleaned == original:
        return "unchanged"
    shutil.copy2(path, "%s.bak-%s" % (path, time.strftime("%Y%m%d%H%M%S")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(cleaned)
    return "removed"


def main(argv) -> int:
    values = dict(DEFAULT)
    argv = list(argv)
    paths = []
    remove_only = False
    while argv:
        arg = argv.pop(0)
        if arg == "--name" and argv:
            values["name"] = argv.pop(0)
        elif arg == "--fullname" and argv:
            values["fullname"] = argv.pop(0)
        elif arg == "--romdir" and argv:
            values["romdir"] = argv.pop(0)
        elif arg == "--command" and argv:
            values["command"] = argv.pop(0)
        elif arg == "--remove":
            remove_only = True
        elif arg == "--no-backup":
            pass
        else:
            paths.append(arg)

    for path in paths:
        if remove_only:
            result = remove_only_patch(path, values)
        else:
            result = patch_file(path, values)
        print("%-60s %s" % (path, result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
