"""Tests de la entrada (evdev) y del renderizado."""

import struct
import unittest

from gpi_music.fb import Surface
from gpi_music.input import (
    ACTION_BACK,
    ACTION_CONFIRM,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_MENU,
    ACTION_NEXT,
    ACTION_RIGHT,
    ACTION_TOGGLE,
    ACTION_UP,
    InputReader,
    parse_event,
)
from gpi_music.ui import UI


def make_event(etype: int, code: int, value: int) -> bytes:
    return struct.pack("llHHi", 0, 0, etype, code, value)


class TestParseEvent(unittest.TestCase):
    def test_parses(self):
        data = make_event(1, 103, 1)  # EV_KEY KEY_UP value 1
        self.assertEqual(parse_event(data), (1, 103, 1))

    def test_incomplete(self):
        self.assertIsNone(parse_event(b"\x00\x01"))


class TestKeymap(unittest.TestCase):
    def setUp(self):
        self.reader = InputReader(devices=[])

    def test_arrows(self):
        self.assertEqual(self.reader._translate(1, 103, 1, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(1, 108, 1, 0), ACTION_DOWN)
        self.assertEqual(self.reader._translate(1, 105, 1, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(1, 106, 1, 0), ACTION_RIGHT)

    def test_confirm_and_back(self):
        self.assertEqual(self.reader._translate(1, 28, 1, 0), ACTION_CONFIRM)
        self.assertEqual(self.reader._translate(1, 1, 1, 0), ACTION_BACK)
        self.assertEqual(self.reader._translate(1, 14, 1, 0), ACTION_BACK)

    def test_menu_and_toggle(self):
        self.assertEqual(self.reader._translate(1, 15, 1, 0), ACTION_MENU)
        self.assertEqual(self.reader._translate(1, 45, 1, 0), ACTION_TOGGLE)

    def test_release_is_ignored(self):
        self.assertIsNone(self.reader._translate(1, 103, 0, 0))

    def test_gamepad_buttons(self):
        self.assertEqual(self.reader._translate(1, 0x130, 1, 0), ACTION_CONFIRM)
        self.assertEqual(self.reader._translate(1, 0x137, 1, 0), ACTION_NEXT)

    def test_joystick_axes(self):
        self.assertEqual(self.reader._translate(3, 0, 0, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(3, 0, 65535, 0), ACTION_RIGHT)
        self.assertEqual(self.reader._translate(3, 1, 0, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(3, 1, 65535, 0), ACTION_DOWN)

    def test_custom_keymap_overrides(self):
        reader = InputReader(devices=[], keymap={"103": "toggle"})
        self.assertEqual(reader._translate(1, 103, 1, 0), ACTION_TOGGLE)


class TestRendering(unittest.TestCase):
    def test_library_view_renders(self):
        from gpi_music.library import Track

        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        tracks = [
            Track(uri="a.mp3", source_id="l", source_label="music (microSD)", title="Uno", artist="A"),
            Track(uri="b.mp3", source_id="l", source_label="music (microSD)", title="Dos", artist="B"),
        ]
        ui.draw_library(tracks, 1, "music (microSD)", len(tracks))
        self.assertEqual(surface.image.size, (320, 240))

    def test_empty_library_renders(self):
        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        ui.draw_library([], 0, "", 0)

    def test_now_playing_renders(self):
        from gpi_music.library import Track

        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        track = Track(uri="a.mp3", source_id="l", source_label="music (microSD)",
                      title="Título largo que no cabe en la pantalla de la consola",
                      artist="Artista", album="Álbum", duration=200)
        ui.draw_now_playing(track, 65.0, 200.0, False, 0.7, "ALEATORIO")
        self.assertEqual(surface.image.size, (320, 240))

    def test_options_view_renders(self):
        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        ui.draw_options(["Uno", "Dos"], 1)

    def test_scale_for_big_screen(self):
        surface = Surface(device="", width=640, height=480)
        ui = UI(surface)
        self.assertEqual(ui.scale, 2)


class TestFrameBufferPacking(unittest.TestCase):
    def test_padding_to_stride(self):
        surface = Surface(device="", width=4, height=2)
        surface.stride = 16  # 4 px * 3 bytes = 12 -> 16
        data = surface._pad_rows(b"\x00" * 24, 12)
        self.assertEqual(len(data), 32)

    def test_565_packing_length(self):
        surface = Surface(device="", width=8, height=4)
        surface.bpp = 16
        packed = surface._pack(surface.image)
        self.assertEqual(len(packed), 8 * 4 * 2)


if __name__ == "__main__":
    unittest.main()
