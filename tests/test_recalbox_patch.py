"""Tests del parcheador de Recalbox (systemlist.xml)."""

import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import patch_recalbox  # noqa: E402

# Formato real de Recalbox 9 (ver systembuilder.py del repo de Recalbox).
SAMPLE = """<?xml version="1.0" ?>
<systemList>
  <defaults command="python /usr/bin/emulatorlauncher.pyc %CONTROLLERSCONFIG%"/>
  <system uuid="62f2cbed-5bcb-46d8-bca9-daaa36613c7a" name="nes" fullname="Nintendo Entertainment System">
    <descriptor path="%ROOT%/nes" theme="nes" extensions=".nes .zip!" extension.types="*=cart" icon="$F25c" downloader="1"/>
    <scraper screenscraper="3"/>
    <properties type="console" pad="mandatory" keyboard="no" mouse="no" lightgun="optional" releasedate="1983-07" retroachievements="1"/>
    <emulatorList>
      <emulator name="libretro">
        <core name="nestopia" priority="1" extensions=".nes" netplay="0" compatibility="high" speed="high"/>
      </emulator>
    </emulatorList>
  </system>
  <system uuid="aaaa" name="gbc" fullname="Game Boy Color">
    <descriptor path="%ROOT%/gbc" theme="gbc" extensions=".gb .gbc"/>
    <scraper screenscraper="9"/>
    <properties type="console" pad="mandatory" keyboard="no" mouse="no"/>
    <emulatorList/>
  </system>
</systemList>
"""


class TestXmlRomPath(unittest.TestCase):
    def test_roms_under_share_become_root_relative(self):
        self.assertEqual(
            patch_recalbox.xml_rom_path("/recalbox/share/roms/music"),
            "%ROOT%/music",
        )

    def test_roms_outside_share_stay_absolute(self):
        self.assertEqual(
            patch_recalbox.xml_rom_path("/mnt/nas/music"),
            "/mnt/nas/music",
        )

    def test_trailing_slash_is_ignored(self):
        self.assertEqual(
            patch_recalbox.xml_rom_path("/recalbox/share/roms/music/"),
            "%ROOT%/music",
        )


class TestPatchRecalbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.init = os.path.join(self.tmp, "systemlist.xml")
        self.target = os.path.join(self.tmp, "share", "systemlist.xml")
        with open(self.init, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self):
        return patch_recalbox.patch_systemlist(
            self.target, self.init, "%ROOT%/music",
            "/recalbox/share/system/gpi-music/gpi-music %ROM%", "music")

    def test_creates_copy_and_adds_system(self):
        result = self._patch()
        self.assertIn("actualizado", result)
        self.assertTrue(os.path.isfile(self.target))
        root = ET.parse(self.target).getroot()
        names = [s.get("name") for s in root.findall("system")]
        self.assertIn("music", names)
        self.assertIn("nes", names)  # los sistemas originales se conservan

    def test_system_has_expected_fields(self):
        self._patch()
        root = ET.parse(self.target).getroot()
        music = [s for s in root.findall("system") if s.get("name") == "music"][0]
        self.assertEqual(music.get("fullname"), "Música")
        self.assertTrue(music.get("uuid"))
        descriptor = music.find("descriptor")
        self.assertEqual(descriptor.get("path"), "%ROOT%/music")
        self.assertEqual(descriptor.get("theme"), "music")
        self.assertIn(".mp3", descriptor.get("extensions"))
        self.assertEqual(descriptor.get("extension.types"), "*=file")
        self.assertEqual(descriptor.get("downloader"), "0")
        self.assertIn("%ROM%", descriptor.get("command"))
        # Un sistema normal no es un puerto: no debe llevar port/readonly.
        self.assertIsNone(descriptor.get("port"))

    def test_properties_use_xml_attribute_names(self):
        self._patch()
        root = ET.parse(self.target).getroot()
        music = [s for s in root.findall("system") if s.get("name") == "music"][0]
        properties = music.find("properties")
        # En el XML los atributos no llevan el prefijo "device." del system.ini.
        self.assertEqual(properties.get("pad"), "mandatory")
        self.assertEqual(properties.get("keyboard"), "no")
        self.assertEqual(properties.get("mouse"), "no")
        self.assertIsNone(properties.get("device.pad"))
        self.assertEqual(properties.get("type"), "console")

    def test_emulator_list_has_a_core(self):
        self._patch()
        root = ET.parse(self.target).getroot()
        music = [s for s in root.findall("system") if s.get("name") == "music"][0]
        emulator_list = music.find("emulatorList")
        self.assertIsNotNone(emulator_list)
        self.assertTrue(emulator_list.findall("emulator"))
        self.assertTrue(emulator_list.findall("emulator/core"))

    def test_scraper_is_disabled(self):
        self._patch()
        root = ET.parse(self.target).getroot()
        music = [s for s in root.findall("system") if s.get("name") == "music"][0]
        self.assertEqual(music.find("scraper").get("screenscraper"), "0")

    def test_is_idempotent(self):
        self._patch()
        first = len(ET.parse(self.target).getroot().findall("system"))
        self._patch()
        root = ET.parse(self.target).getroot()
        music = [s for s in root.findall("system") if s.get("name") == "music"]
        self.assertEqual(len(music), 1)
        self.assertEqual(len(root.findall("system")), first)

    def test_backup_is_created(self):
        self._patch()
        backups = [f for f in os.listdir(os.path.dirname(self.target)) if ".bak-" in f]
        self.assertTrue(backups)

    def test_remove_drops_the_system(self):
        self._patch()
        code = patch_recalbox.main([
            "--target", self.target, "--init", self.init, "--remove",
        ])
        self.assertEqual(code, 0)
        root = ET.parse(self.target).getroot()
        names = [s.get("name") for s in root.findall("system")]
        self.assertNotIn("music", names)
        self.assertIn("nes", names)

    def test_es_systems_cfg(self):
        cfg = os.path.join(self.tmp, "es_systems.cfg")
        result = patch_recalbox.patch_es_systems(cfg, "/recalbox/share/roms/music", "/cmd %ROM%")
        self.assertEqual(result, "creado")
        with open(cfg, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("<name>music</name>", content)
        # Segunda vez no debe duplicar.
        result = patch_recalbox.patch_es_systems(cfg, "/recalbox/share/roms/music", "/cmd %ROM%")
        self.assertEqual(result, "ya-existe")
        with open(cfg, encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("<name>music</name>"), 1)

    def test_remove_es_systems_cfg(self):
        cfg = os.path.join(self.tmp, "es_systems.cfg")
        patch_recalbox.patch_es_systems(cfg, "/recalbox/share/roms/music", "/cmd %ROM%")
        # Se añade otro sistema para comprobar que no se toca.
        with open(cfg, encoding="utf-8") as fh:
            content = fh.read()
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content.replace(
                "</systemList>",
                "<system><name>nes</name></system>\n</systemList>"))

        result = patch_recalbox.remove_es_systems(cfg)
        self.assertIn("eliminado", result)
        with open(cfg, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn("<name>music</name>", content)
        self.assertIn("<name>nes</name>", content)


if __name__ == "__main__":
    unittest.main()
