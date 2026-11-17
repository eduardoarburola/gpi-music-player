#!/usr/bin/env python3
"""Registra el sistema «Música» en Recalbox 9.

Recalbox 9 describe sus sistemas en ``systemlist.xml``. Para añadir uno
propio se crea una copia en la carpeta de usuario (nunca se toca la original
de ``share_init``) y se le añade un bloque ``<system>`` clonando la estructura
de un sistema existente.

También escribe un ``es_systems.cfg`` clásico por si el EmulationStation de la
versión instalada lo lee en lugar del ``systemlist.xml``.

Es idempotente: si el sistema ya existe lo reemplaza.
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import time
import uuid
import xml.etree.ElementTree as ET

SYSTEM_NAME = "music"
FULL_NAME = "Música"
EXTENSIONS = ".mp3 .ogg .oga .opus .wav .flac .m4a .mp4 .aac .wma"

# Sistemas de los que se clona la estructura (los más sencillos primero).
TEMPLATES = ("gbc", "gb", "genesis", "nes", "snes", "megadrive", "ports")

ES_SYSTEMS_TEMPLATE = """<system>
	<name>music</name>
	<fullname>{fullname}</fullname>
	<path>{path}</path>
	<extension>{extensions}</extension>
	<command>{command}</command>
	<platform>music</platform>
	<theme>music</theme>
</system>
"""


def log(message: str) -> None:
    print("  %s" % message)


def find_template(root: ET.Element):
    systems = root.findall("system")
    by_name = {s.get("name"): s for s in systems}
    for name in TEMPLATES:
        if name in by_name:
            return by_name[name]
    for system in systems:
        if system.find("descriptor") is not None:
            return system
    return None


def build_system(template, path: str, command: str, theme: str) -> ET.Element:
    system = copy.deepcopy(template) if template is not None else ET.Element("system")

    system.set("uuid", str(uuid.uuid4()))
    system.set("name", SYSTEM_NAME)
    system.set("fullname", FULL_NAME)

    descriptor = system.find("descriptor")
    if descriptor is None:
        descriptor = ET.SubElement(system, "descriptor")
    descriptor.set("path", path)
    descriptor.set("theme", theme)
    descriptor.set("extensions", EXTENSIONS)
    descriptor.set("extension.types", "*=file")
    descriptor.set("icon", "$F25c")
    descriptor.set("downloader", "0")
    descriptor.set("command", command)
    descriptor.set("port", "0")
    descriptor.set("readonly", "0")

    scraper = system.find("scraper")
    if scraper is None:
        scraper = ET.SubElement(system, "scraper")
    scraper.set("screenscraper", "0")

    properties = system.find("properties")
    if properties is not None:
        # Necesitamos cruceta y botones: pads obligatorio, teclado opcional.
        properties.set("device.pad", "mandatory")
        properties.set("device.keyboard", "no")
        properties.set("device.mouse", "no")
        properties.set("type", "console")

    emulator_list = system.find("emulatorList")
    if emulator_list is not None:
        for child in list(emulator_list):
            emulator_list.remove(child)

    return system


def patch_systemlist(target: str, init: str, path: str, command: str, theme: str) -> str:
    if not os.path.isfile(target):
        if not os.path.isfile(init):
            return "no-encontrado (%s)" % init
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(init, target)
        log("copiado el systemlist.xml original a %s" % target)

    try:
        tree = ET.parse(target)
    except ET.ParseError as exc:
        return "xml-invalido (%s)" % exc
    root = tree.getroot()

    for system in root.findall("system"):
        if system.get("name") == SYSTEM_NAME:
            root.remove(system)

    template = find_template(root)
    root.append(build_system(template, path, command, theme))

    backup = "%s.bak-%s" % (target, time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(target, backup)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return "actualizado (copia: %s)" % os.path.basename(backup)


def patch_es_systems(target: str, path: str, command: str) -> str:
    """Añade el sistema a un es_systems.cfg clásico (idempotente)."""
    block = ES_SYSTEMS_TEMPLATE.format(
        fullname=FULL_NAME, path=path, extensions=EXTENSIONS, command=command
    )
    if not os.path.isfile(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("<systemList>\n%s</systemList>\n" % block)
        return "creado"

    with open(target, "r", encoding="utf-8") as fh:
        content = fh.read()
    if "<name>%s</name>" % SYSTEM_NAME in content:
        return "ya-existe"

    backup = "%s.bak-%s" % (target, time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(target, backup)
    if "</systemList>" in content:
        index = content.lower().rindex("</systemlist>")
        content = content[:index] + block + content[index:]
    else:
        content = content + "\n" + block
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    return "actualizado (copia: %s)" % os.path.basename(backup)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Registra el sistema Música en Recalbox")
    parser.add_argument("--init", default="/recalbox/share_init/system/.emulationstation/systemlist.xml")
    parser.add_argument("--target", default="/recalbox/share/system/.emulationstation/systemlist.xml")
    parser.add_argument("--es-systems", default="/recalbox/share/system/.emulationstation/es_systems.cfg")
    parser.add_argument("--roms", default="/recalbox/share/roms/music")
    parser.add_argument("--command", default="/recalbox/share/system/gpi-music/gpi-music %ROM%")
    parser.add_argument("--theme", default="music")
    parser.add_argument("--remove", action="store_true", help="elimina el sistema en lugar de añadirlo")
    args = parser.parse_args(argv)

    if args.remove:
        if os.path.isfile(args.target):
            tree = ET.parse(args.target)
            root = tree.getroot()
            removed = False
            for system in root.findall("system"):
                if system.get("name") == SYSTEM_NAME:
                    root.remove(system)
                    removed = True
            if removed:
                tree.write(args.target, encoding="utf-8", xml_declaration=True)
            log("systemlist.xml: %s" % ("eliminado" if removed else "sin cambios"))
        return 0

    log("systemlist.xml: %s" % patch_systemlist(
        args.target, args.init, args.roms, args.command, args.theme))
    log("es_systems.cfg: %s" % patch_es_systems(args.es_systems, args.roms, args.command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
