"""Tests de la fábrica de pantallas."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpi_music import display, shim  # noqa: E402


class TestCreateDisplay(unittest.TestCase):
    def test_memory_mode_never_touches_the_screen(self):
        """Con fb_device vacío debe devolver una pantalla en memoria."""
        screen = display.create_display("", width=320, height=240)
        try:
            self.assertEqual(screen.size, (320, 240))
            self.assertTrue(hasattr(screen, "draw"))
            # present() no debe fallar aunque no haya vídeo inicializado.
            screen.present()
            screen.clear((10, 20, 30))
        finally:
            screen.close()

    def test_memory_mode_saves_a_png(self):
        import tempfile

        screen = display.create_display("", width=64, height=48)
        path = os.path.join(tempfile.mkdtemp(), "ux.png")
        try:
            screen.save_png(path)
            self.assertTrue(os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 0)
        finally:
            screen.close()

    def test_available_backends_reports_the_libraries(self):
        backends = display.available_backends()
        self.assertIn("pil", backends)
        self.assertIn("pygame", backends)
        self.assertIn("framebuffer", backends)
        self.assertEqual(backends["pil"], shim.HAVE_PIL)

    def test_framebuffer_size_falls_back_to_gpi_case(self):
        width, height = display._framebuffer_size()
        self.assertGreaterEqual(width, 1)
        self.assertGreaterEqual(height, 1)


class TestPygameMemoryDisplay(unittest.TestCase):
    def test_needs_pygame_without_pillow(self):
        if shim.HAVE_PIL:
            self.skipTest("esta prueba es para el entorno con pygame")
        screen = display.PygameMemoryDisplay(width=320, height=240)
        try:
            self.assertEqual(screen.size, (320, 240))
            screen.draw.rectangle((0, 0, 10, 10), (255, 0, 0))
            screen.present()
        finally:
            screen.close()


class TestFramebufferDisplay(unittest.TestCase):
    """El backend que escribe directamente en /dev/fb0 (sin driver de vídeo)."""

    def setUp(self):
        if shim.HAVE_PIL:
            self.skipTest("esta prueba es para el entorno con pygame")
        import tempfile

        from gpi_music import fb

        self.tmp = tempfile.mkdtemp()
        self.device = os.path.join(self.tmp, "fb0")
        with open(self.device, "wb") as fh:
            fh.write(b"\x00" * (8 * 4 * 2))
        self._orig = fb._detect_fb_info
        fb._detect_fb_info = lambda device: (8, 2, 32, 8 * 4)

    def tearDown(self):
        from gpi_music import fb

        fb._detect_fb_info = self._orig

    def test_writes_bgrx_pixels(self):
        screen = display.FramebufferDisplay(device=self.device)
        try:
            self.assertEqual(screen.size, (8, 2))
            screen.clear((255, 0, 0))
            screen.present()
            with open(self.device, "rb") as fh:
                data = fh.read()
            # BGRX: azul, verde, rojo, relleno
            self.assertEqual(data[0:4], bytes([0, 0, 255, 0]))
        finally:
            screen.close()

    def test_adds_stride_padding(self):
        from gpi_music import fb

        fb._detect_fb_info = lambda device: (8, 2, 32, 8 * 4 + 4)
        screen = display.FramebufferDisplay(device=self.device)
        try:
            screen.clear((0, 255, 0))
            screen.present()
            with open(self.device, "rb") as fh:
                data = fh.read()
            self.assertEqual(len(data), (8 * 4 + 4) * 2)
            self.assertEqual(data[0:4], bytes([0, 255, 0, 0]))
            # El relleno va al final de cada fila (32 bytes de píxeles + 4 de relleno).
            self.assertEqual(data[32:36], bytes([0, 0, 0, 0]))
            self.assertEqual(data[36:40], bytes([0, 255, 0, 0]))
        finally:
            screen.close()

    def test_does_not_initialise_the_sdl_video_driver(self):
        """El backend de framebuffer no debe abrir SDL/Dispmanx.

        Es lo que evita el cuelgue en ``flip()`` cuando EmulationStation
        todavía tiene la pantalla.
        """
        import pygame

        screen = display.FramebufferDisplay(device=self.device)
        try:
            self.assertFalse(pygame.display.get_init())
        finally:
            screen.close()


if __name__ == "__main__":
    unittest.main()
