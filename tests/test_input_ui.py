"""Tests de la entrada (evdev) y del renderizado."""

import struct
import time
import unittest

from gpi_music.fb import Surface
from gpi_music.input import (
    ACTION_BACK,
    ACTION_BROWSE,
    ACTION_CONFIRM,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_MENU,
    ACTION_NEXT,
    ACTION_PREV,
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
        # El centro se detecta solo (rango por defecto de 16 bits con signo).
        self.assertIsNone(self.reader._translate(3, 0, 0, 0))
        self.assertEqual(self.reader._translate(3, 0, -32768, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(3, 0, 32767, 0), ACTION_RIGHT)
        # Repetir el mismo valor no vuelve a disparar la acción.
        self.assertIsNone(self.reader._translate(3, 0, 32767, 0))
        self.assertEqual(self.reader._translate(3, 1, -32768, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(3, 1, 32767, 0), ACTION_DOWN)

    def test_hat_dpad(self):
        # La cruceta del GPi Case llega como hat (ABS_HAT0X/ABS_HAT0Y).
        self.assertIsNone(self.reader._translate(3, 0x10, 0, 0))
        self.assertEqual(self.reader._translate(3, 0x10, -1, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(3, 0x10, 1, 0), ACTION_RIGHT)
        self.assertIsNone(self.reader._translate(3, 0x10, 0, 0))
        self.assertEqual(self.reader._translate(3, 0x11, -1, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(3, 0x11, 1, 0), ACTION_DOWN)

    def test_dpad_buttons(self):
        self.assertEqual(self.reader._translate(1, 0x120, 1, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(1, 0x121, 1, 0), ACTION_DOWN)
        self.assertEqual(self.reader._translate(1, 0x122, 1, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(1, 0x123, 1, 0), ACTION_RIGHT)

    def test_gamepad_mapping(self):
        self.assertEqual(self.reader._translate(1, 0x130, 1, 0), ACTION_CONFIRM)   # A
        self.assertEqual(self.reader._translate(1, 0x131, 1, 0), ACTION_BACK)      # B
        self.assertEqual(self.reader._translate(1, 0x133, 1, 0), ACTION_TOGGLE)    # Y
        self.assertEqual(self.reader._translate(1, 0x134, 1, 0), ACTION_BROWSE)    # X
        self.assertEqual(self.reader._translate(1, 0x13A, 1, 0), ACTION_BROWSE)    # Select
        self.assertEqual(self.reader._translate(1, 0x13B, 1, 0), ACTION_MENU)      # Start

    def test_custom_keymap_overrides(self):
        reader = InputReader(devices=[], keymap={"103": "toggle"})
        self.assertEqual(reader._translate(1, 103, 1, 0), ACTION_TOGGLE)

    def test_gpio_keys_mapping(self):
        # Asignación típica del GPi Case con gpio-keys.
        self.assertEqual(self.reader._translate(1, 103, 1, 0), ACTION_UP)
        self.assertEqual(self.reader._translate(1, 108, 1, 0), ACTION_DOWN)
        self.assertEqual(self.reader._translate(1, 105, 1, 0), ACTION_LEFT)
        self.assertEqual(self.reader._translate(1, 106, 1, 0), ACTION_RIGHT)
        self.assertEqual(self.reader._translate(1, 30, 1, 0), ACTION_CONFIRM)   # A
        self.assertEqual(self.reader._translate(1, 14, 1, 0), ACTION_BACK)      # B
        self.assertEqual(self.reader._translate(1, 45, 1, 0), ACTION_TOGGLE)    # X
        self.assertEqual(self.reader._translate(1, 31, 1, 0), ACTION_BROWSE)    # Y
        self.assertEqual(self.reader._translate(1, 29, 1, 0), ACTION_BROWSE)    # Select
        self.assertEqual(self.reader._translate(1, 15, 1, 0), ACTION_MENU)      # Start
        self.assertEqual(self.reader._translate(1, 42, 1, 0), ACTION_PREV)      # L
        self.assertEqual(self.reader._translate(1, 54, 1, 0), ACTION_NEXT)      # R

    def test_duplicate_devices_do_not_double_step(self):
        # La misma dirección puede llegar como tecla y como hat.
        reader = InputReader(devices=[])
        self.assertEqual(reader._translate(1, 103, 1, 0), ACTION_UP)
        self.assertIsNone(reader._translate(3, 0x11, -1, 1))
        # Al soltar el hat, la tecla sigue manteniendo la acción.
        self.assertIsNone(reader._translate(3, 0x11, 0, 1))
        self.assertEqual(reader._translate(1, 103, 0, 0), None)

    def test_held_direction_repeats(self):
        reader = InputReader(devices=[], repeat_delay=0.05, repeat_rate=0.02)
        reader._translate(3, 0x10, -1, 0)
        time.sleep(0.09)
        self.assertEqual(reader._repeats(), [ACTION_LEFT])
        self.assertEqual(reader._repeats(), [])  # aún no ha pasado el ritmo
        time.sleep(0.03)
        self.assertEqual(reader._repeats(), [ACTION_LEFT])

    def test_axis_without_center_does_not_repeat(self):
        reader = InputReader(devices=[], repeat_delay=0.05, repeat_rate=0.02)
        reader._translate(3, 0, -32768, 0)
        time.sleep(0.09)
        self.assertEqual(reader._repeats(), [])

    def test_events_history(self):
        reader = InputReader(devices=[])
        reader._translate(1, 0x130, 1, 0)
        reader._translate(3, 0x10, -1, 0)
        self.assertTrue(reader.events)
        self.assertIn("BTN_SOUTH", reader.events[0])
        self.assertIn("ABS_HAT0X", reader.events[1])

    def test_event_log_callback(self):
        lines = []
        reader = InputReader(devices=[], events_log=lines.append)
        reader._translate(1, 0x131, 1, 0)
        self.assertEqual(len(lines), 1)
        self.assertIn("BTN_EAST", lines[0])


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

    def test_filebrowser_view_renders(self):
        from gpi_music.browser import Entry

        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        entries = [
            Entry("/media", "..", True, False),
            Entry("/media/Music", "Music", True, False),
            Entry("/media/cancion.mp3", "cancion.mp3", False, True),
        ]
        ui.draw_filebrowser("/media", entries, 2)
        self.assertEqual(surface.image.size, (320, 240))

    def test_filebrowser_empty_renders(self):
        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        ui.draw_filebrowser("/media", [], 0)

    def test_debug_view_renders(self):
        surface = Surface(device="", width=320, height=240)
        ui = UI(surface)
        ui.draw_debug(["dispositivos: event0", "KEY  BTN_SOUTH(A)  pulsado"])

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
