"""Tests del explorador de archivos y de su integración con la app."""

import os
import shutil
import tempfile
import unittest

from gpi_music.app import VIEW_FILES, VIEW_LIBRARY, VIEW_PLAYING, App
from gpi_music.browser import is_audio, list_directory, parent_directory
from gpi_music.config import Config
from gpi_music.fb import Surface


class FakeEngine:
    """Motor de reproducción falso: no toca el audio del sistema."""

    def __init__(self):
        self.played = []
        self.volume = 0.0
        self.duration = None
        self.stopped = False

    def play(self, uri, duration=None):
        self.played.append(uri)
        self.duration = duration

    def set_volume(self, value):
        self.volume = value

    def toggle_pause(self):
        pass

    def stop(self):
        self.stopped = True

    def seek(self, seconds):
        pass

    def position(self):
        return 0.0

    def is_finished(self):
        return False

    def close(self):
        pass


def make_app(root=None):
    config = Config.default()
    config.library.local_paths = [root] if root else []
    surface = Surface(device="", width=320, height=240)
    engine = FakeEngine()
    app = App(config, surface, input_reader=None, engine=engine)
    return app, engine


class TestBrowserModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "Rock"))
        os.makedirs(os.path.join(self.tmp, ".oculto"))
        for name in ("cancion.mp3", "otro.flac", "notas.txt"):
            with open(os.path.join(self.tmp, name), "wb") as fh:
                fh.write(b"x")
        self.extensions = [".mp3", ".flac"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lists_folders_first(self):
        entries = list_directory(self.tmp, self.extensions)
        self.assertEqual(entries[0].name, "Rock")
        self.assertTrue(entries[0].is_dir)
        self.assertEqual([e.name for e in entries[1:]], ["cancion.mp3", "otro.flac"])

    def test_skips_non_audio_and_hidden(self):
        names = [e.name for e in list_directory(self.tmp, self.extensions)]
        self.assertNotIn("notas.txt", names)
        self.assertNotIn(".oculto", names)

    def test_show_all_includes_other_files(self):
        names = [e.name for e in list_directory(self.tmp, self.extensions, show_all=True)]
        self.assertIn("notas.txt", names)

    def test_show_hidden_includes_dot_dirs(self):
        names = [e.name for e in list_directory(self.tmp, self.extensions, show_hidden=True)]
        self.assertIn(".oculto", names)

    def test_parent_directory(self):
        self.assertEqual(parent_directory("/media/Music"), "/media")
        self.assertEqual(parent_directory("/"), "/")

    def test_is_audio(self):
        self.assertTrue(is_audio("cancion.MP3", self.extensions))
        self.assertFalse(is_audio("notas.txt", self.extensions))

    def test_missing_directory_returns_empty(self):
        self.assertEqual(list_directory("/no/existe", self.extensions), [])


class TestAppBrowser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "Rock"))
        with open(os.path.join(self.tmp, "cancion.mp3"), "wb") as fh:
            fh.write(b"x")
        self.app, self.engine = make_app(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_browser_lists_parent_first(self):
        self.app.handle_action("browse")
        self.assertEqual(self.app.view, VIEW_FILES)
        self.assertEqual(self.app.browse_entries[0].name, "..")
        self.assertIn("Rock", [e.name for e in self.app.browse_entries])

    def test_move_selection(self):
        self.app.open_browser()
        self.app.handle_action("down")
        self.assertEqual(self.app.browse_index, 1)
        self.app.handle_action("up")
        self.assertEqual(self.app.browse_index, 0)

    def test_enter_folder_and_go_back(self):
        self.app.open_browser()
        self.app.browse_index = 1  # la carpeta Rock
        self.app.handle_action("confirm")
        self.assertTrue(self.app.browse_path.endswith("Rock"))
        self.app.handle_action("back")
        self.assertEqual(self.app.browse_path, os.path.abspath(self.tmp))

    def test_play_loose_file(self):
        self.app.open_browser()
        index = [i for i, e in enumerate(self.app.browse_entries) if e.name == "cancion.mp3"][0]
        self.app.browse_index = index
        self.app.handle_action("confirm")
        self.assertEqual(self.app.view, VIEW_PLAYING)
        self.assertEqual(self.engine.played[-1], os.path.join(self.tmp, "cancion.mp3"))

    def test_filter_toggle_shows_other_files(self):
        with open(os.path.join(self.tmp, "notas.txt"), "wb") as fh:
            fh.write(b"x")
        self.app.open_browser()
        names = [e.name for e in self.app.browse_entries]
        self.assertNotIn("notas.txt", names)
        self.app.handle_action("toggle")
        names = [e.name for e in self.app.browse_entries]
        self.assertIn("notas.txt", names)

    def test_add_folder_to_library_saves_config(self):
        config_path = os.path.join(self.tmp, "config.json")
        self.app.config.path = config_path
        self.app.open_browser()
        self.app.handle_action("menu")
        options = self.app._options()
        self.assertIn("Añadir carpeta a la biblioteca", options)
        self.app.options_index = options.index("Añadir carpeta a la biblioteca")
        self.app.handle_action("confirm")
        self.assertIn(os.path.abspath(self.tmp), self.app.config.library.local_paths)
        self.assertTrue(os.path.isfile(config_path))

    def test_browse_button_returns_to_library(self):
        self.app.open_browser()
        self.app.handle_action("browse")
        self.assertEqual(self.app.view, VIEW_LIBRARY)


if __name__ == "__main__":
    unittest.main()
