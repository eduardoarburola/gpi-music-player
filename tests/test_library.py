"""Tests del escaneo de la biblioteca."""

import os
import tempfile
import unittest

from gpi_music.library import discover_mounts, scan_directory
from gpi_music.config import Config


class TestScanDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "Rock"))
        os.makedirs(os.path.join(root, ".oculto"))
        for name in ("a.mp3", "b.ogg", "c.flac", "notas.txt", ".oculto.mp3"):
            with open(os.path.join(root, name), "wb") as fh:
                fh.write(b"\x00" * 32)
        with open(os.path.join(root, "Rock", "d.mp3"), "wb") as fh:
            fh.write(b"\x00" * 32)
        with open(os.path.join(root, ".oculto", "e.mp3"), "wb") as fh:
            fh.write(b"\x00" * 32)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_audio_recursively(self):
        tracks = scan_directory(self.root, [".mp3", ".ogg", ".flac"], "src", "label")
        names = sorted(os.path.basename(t.uri) for t in tracks)
        self.assertEqual(names, ["a.mp3", "b.ogg", "c.flac", "d.mp3"])

    def test_skips_hidden(self):
        tracks = scan_directory(self.root, [".mp3"], "src", "label")
        names = sorted(os.path.basename(t.uri) for t in tracks)
        self.assertNotIn(".oculto.mp3", names)
        self.assertNotIn("e.mp3", names)

    def test_non_recursive(self):
        tracks = scan_directory(self.root, [".mp3"], "src", "label", recursive=False)
        names = sorted(os.path.basename(t.uri) for t in tracks)
        self.assertEqual(names, ["a.mp3"])

    def test_missing_directory(self):
        self.assertEqual(scan_directory("/no/existe", [".mp3"], "s", "l"), [])

    def test_source_labels(self):
        tracks = scan_directory(self.root, [".mp3"], "src", "etiqueta")
        self.assertTrue(all(t.source_id == "src" for t in tracks))
        self.assertTrue(all(t.source_label == "etiqueta" for t in tracks))


class TestDiscoverMounts(unittest.TestCase):
    def test_finds_shares(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = os.path.join(tmp, "nas")
            os.makedirs(os.path.join(share, "Music"))
            os.makedirs(os.path.join(tmp, ".oculto"))
            found = discover_mounts([tmp])
            labels = [label for _path, label in found]
            self.assertIn("nas", labels)
            self.assertIn("nas/Music", labels)
            self.assertNotIn(".oculto", labels)


class TestConfigIntegration(unittest.TestCase):
    def test_defaults(self):
        from gpi_music.config import default_local_paths, detect_platform

        config = Config.default()
        paths = default_local_paths()
        self.assertTrue(paths)
        platform = detect_platform()
        if platform == "retropie":
            self.assertIn("~/RetroPie/roms/music", paths)
        elif platform == "recalbox":
            self.assertIn("/recalbox/share/roms/music", paths)
        self.assertEqual(config.library.local_paths, paths)
        self.assertEqual(config.mpd_targets(), [])

    def test_mpd_targets(self):
        config = Config.default()
        config.library.mpd_hosts = [["192.168.1.10", 6600], ["host2"]]
        self.assertEqual(config.mpd_targets(), [("192.168.1.10", 6600), ("host2", 6600)])

    def test_merge_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            config = Config.default()
            config.player.volume = 0.42
            config.save(path)
            loaded = Config.load(path)
            self.assertAlmostEqual(loaded.player.volume, 0.42, places=3)
            self.assertEqual(loaded.library.local_paths, config.library.local_paths)

    def test_merge_ignores_unknown_keys(self):
        config = Config.default()
        merged = config.merge({"player": {"volume": 0.2, "inventado": 1}})
        self.assertAlmostEqual(merged.player.volume, 0.2)
        self.assertFalse(hasattr(merged.player, "inventado"))


if __name__ == "__main__":
    unittest.main()
