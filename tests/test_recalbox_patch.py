"""Tests del parcheador de Recalbox (systemlist.xml)."""

import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import patch_recalbox  # noqa: E402

SAMPLE = """<?xml version="1.0" ?>
<systemList>
  <defaults command="python /usr/bin/emulatorlauncher.pyc %CONTROLLERSCONFIG%"/>
  <system uuid="62f2cbed-5bcb-46d8-bca9-daaa36613c7a" name="nes" fullname="Nintendo Entertainment System">
    <descriptor path="/recalbox/share/roms/nes" theme="nes" extensions=".nes .zip!" extension.types="*=cart" icon="$F25c" downloader="1"/>
    <scraper screenscraper="3"/>
    <properties type="console" device.pad="mandatory" device.keyboard="no" device.mouse="no"/>
    <emulatorList>
      <emulator name="libretro">
        <core package="BR2_PACKAGE_LIBRETRO_NESTOPIA" priority="1" emulator="libretro" core="nestopia"/>
      </emulator>
    </emulatorList>
  </system>
  <system uuid="aaaa" name="gbc" fullname="Game Boy Color">
    <descriptor path="/recalbox/share/roms/gbc" theme="gbc" extensions=".gb .gbc"/>
    <scraper screenscraper="9"/>
    <properties type="console" device.pad="mandatory"/>
    <emulatorList/>
  </system>
</systemList>
"""


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
            self.target, self.init, "/recalbox/share/roms/music",
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
        descriptor = music.find("descriptor")
        self.assertEqual(descriptor.get("path"), "/recalbox/share/roms/music")
        self.assertIn(".mp3", descriptor.get("extensions"))
        self.assertIn("%ROM%", descriptor.get("command"))
        properties = music.find("properties")
        self.assertEqual(properties.get("device.pad"), "mandatory")

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


if __name__ == "__main__":
    unittest.main()
