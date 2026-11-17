#!/usr/bin/env python3
"""Registra el sistema «Música» en Recalbox 9.

Recalbox 9 describe sus sistemas en ``systemlist.xml``. Para añadir uno propio
se copia el original de ``share_init`` a la carpeta de usuario (el original es
de solo lectura y nunca se toca) y se le añade un bloque ``<system>``.

Formato verificado contra el generador de Recalbox
(``package/recalbox-romfs2/scripts/systembuilder.py``) y contra la wiki:

    <system uuid="..." name="music" fullname="Música">
      <descriptor path="%ROOT%/music" theme="music" extensions=".mp3 ..."
                  extension.types="*=file" icon="$F25c" downloader="0"
                  command="/ruta/gpi-music %ROM%"/>
      <scraper screenscraper="0"/>
      <properties type="console" pad="mandatory" keyboard="no" mouse="no"
                  lightgun="no" releasedate="2024" manufacturer="gpi-music-player"
                  retroachievements="0" crt.multiresolution="0" crt.multiregion="0"
                  ignoredfiles=""/>
      <emulatorList>
        <emulator name="bash">
          <core name="bash" priority="1" extensions=".mp3 ..." netplay="0"
                softpatching="0" compatibility="high" speed="high" crt.available="1"/>
        </emulator>
      </emulatorList>
    </system>

Ojo: en el XML los atributos se llaman ``pad``/``keyboard``/``mouse`` (sin el
prefijo ``device.`` que usa el ``system.ini`` original) y la ruta de las roms
se escribe como ``%ROOT%/music``.

También escribe un ``es_systems.cfg`` clásico por si el EmulationStation de la
versión instalada lo lee en lugar del ``systemlist.xml``.

Es idempotente: si el sistema ya existe lo reemplaza.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
import uuid
import xml.etree.ElementTree as ET

SYSTEM_NAME = "music"
FULL_NAME = "Música"
EXTENSIONS = ".mp3 .ogg .oga .opus .wav .flac .m4a .mp4 .aac .wma"
ROM_ROOT = "/recalbox/share/roms"
THEME = "music"
ICON = "$F25c"

ES_SYSTEMS_TEMPLATE = """<system>
\t<name>music</name>
\t<fullname>{fullname}</fullname>
\t<path>{path}</path>
\t<extension>{extensions}</extension>
\t<command>{command}</command>
\t<platform>music</platform>
\t<theme>music</theme>
</system>
"""


def log(message: str) -> None:
    print("  %s" % message)


def xml_rom_path(roms_dir: str) -> str:
    """Convierte la ruta de roms al formato del XML (``%ROOT%/<carpeta>``)."""
    roms_dir = roms_dir.rstrip("/")
    if roms_dir == ROM_ROOT:
        return "%ROOT%"
    prefix = ROM_ROOT + "/"
    if roms_dir.startswith(prefix):
        return "%ROOT%/" + roms_dir[len(prefix):]
    return roms_dir


def build_system(path: str, command: str, theme: str) -> ET.Element:
    """Construye el bloque <system> del sistema de música."""
    system = ET.Element("system", attrib={
        "uuid": str(uuid.uuid4()),
        "name": SYSTEM_NAME,
        "fullname": FULL_NAME,
    })

    descriptor = ET.SubElement(system, "descriptor", attrib={
        "path": path,
        "theme": theme,
        "extensions": EXTENSIONS,
        "extension.types": "*=file",
        "icon": ICON,
        "downloader": "0",
        "command": command,
    })

    ET.SubElement(system, "scraper", attrib={"screenscraper": "0"})

    ET.SubElement(system, "properties", attrib={
        "type": "console",
        "pad": "mandatory",
        "keyboard": "no",
        "mouse": "no",
        "lightgun": "no",
        "releasedate": "2024",
        "manufacturer": "gpi-music-player",
        "retroachievements": "0",
        "crt.multiresolution": "0",
        "crt.multiregion": "0",
        "ignoredfiles": "",
    })

    # EmulationStation espera al menos un emulador/core en la lista. El comando
    # real lo pone el descriptor, así que este core nunca llega a ejecutarse.
    emulator_list = ET.SubElement(system, "emulatorList")
    emulator = ET.SubElement(emulator_list, "emulator", attrib={"name": "bash"})
    ET.SubElement(emulator, "core", attrib={
        "name": "bash",
        "priority": "1",
        "extensions": EXTENSIONS,
        "netplay": "0",
        "softpatching": "0",
        "compatibility": "high",
        "speed": "high",
        "crt.available": "1",
    })

    assert descriptor is not None  # silence linters
    return system


def patch_systemlist(target: str, init: str, path: str, command: str, theme: str) -> str:
    if not os.path.isfile(target):
        if not os.path.isfile(init):
            return "no-encontrado (%s)" % init
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(init, target)
        except OSError as exc:
            return "error-copiando (%s)" % exc
        log("copiado el systemlist.xml original a %s" % target)

    try:
        tree = ET.parse(target)
    except (ET.ParseError, OSError) as exc:
        return "xml-invalido (%s)" % exc
    root = tree.getroot()

    for system in root.findall("system"):
        if system.get("name") == SYSTEM_NAME:
            root.remove(system)

    root.append(build_system(path, command, theme))

    try:
        backup = "%s.bak-%s" % (target, time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(target, backup)
        tree.write(target, encoding="utf-8", xml_declaration=True)
    except OSError as exc:
        return "error-escribiendo (%s)" % exc
    return "actualizado (copia: %s)" % os.path.basename(backup)


def patch_es_systems(target: str, path: str, command: str) -> str:
    """Añade el sistema a un es_systems.cfg clásico (idempotente)."""
    block = ES_SYSTEMS_TEMPLATE.format(
        fullname=FULL_NAME, path=path, extensions=EXTENSIONS, command=command
    )
    try:
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
    except OSError as exc:
        return "error (%s)" % exc
    return "actualizado (copia: %s)" % os.path.basename(backup)


def remove_es_systems(target: str) -> str:
    """Quita el bloque <system> de música de un es_systems.cfg."""
    if not os.path.isfile(target):
        return "no-existe"
    try:
        with open(target, "r", encoding="utf-8") as fh:
            content = fh.read()

        pattern = re.compile(
            r"[ \t]*<system>.*?<name>\s*%s\s*</name>.*?</system>\s*?" % SYSTEM_NAME,
            re.DOTALL,
        )
        new_content, count = pattern.subn("", content)
        if not count:
            return "sin cambios"

        backup = "%s.bak-%s" % (target, time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(target, backup)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(new_content)
    except OSError as exc:
        return "error (%s)" % exc
    return "eliminado (copia: %s)" % os.path.basename(backup)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Registra el sistema Música en Recalbox")
    parser.add_argument("--init", default="/recalbox/share_init/system/.emulationstation/systemlist.xml")
    parser.add_argument("--target", default="/recalbox/share/system/.emulationstation/systemlist.xml")
    parser.add_argument("--es-systems", default="/recalbox/share/system/.emulationstation/es_systems.cfg")
    parser.add_argument("--roms", default="/recalbox/share/roms/music")
    parser.add_argument("--command", default="/recalbox/share/system/gpi-music/gpi-music %ROM%")
    parser.add_argument("--theme", default=THEME)
    parser.add_argument("--remove", action="store_true", help="elimina el sistema en lugar de añadirlo")
    args = parser.parse_args(argv)

    if args.remove:
        if os.path.isfile(args.target):
            try:
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
            except (ET.ParseError, OSError) as exc:
                log("systemlist.xml: error (%s)" % exc)
        log("es_systems.cfg: %s" % remove_es_systems(args.es_systems))
        return 0

    log("systemlist.xml: %s" % patch_systemlist(
        args.target, args.init, xml_rom_path(args.roms), args.command, args.theme))
    log("es_systems.cfg: %s" % patch_es_systems(args.es_systems, args.roms, args.command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
