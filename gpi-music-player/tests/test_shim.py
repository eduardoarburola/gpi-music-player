"""Tests del shim de dibujo y de la fábrica de pantallas."""

import os
import tempfile
import unittest

from gpi_music import shim
from gpi_music.display import DisplayError, available_backends, create_display


class TestShim(unittest.TestCase):
    def test_exposes_api(self):
        self.assertTrue(hasattr(shim, "Image"))
        self.assertTrue(hasattr(shim, "ImageDraw"))
        self.assertTrue(hasattr(shim, "ImageFont"))
        self.assertIn(shim.BACKEND, ("pil", "pygame"))

    def test_image_new_and_draw(self):
        image = shim.Image.new("RGB", (64, 32), (10, 20, 30))
        self.assertEqual(image.size, (64, 32))
        draw = shim.ImageDraw.Draw(image)
        draw.rectangle((2, 2, 20, 20), fill=(200, 100, 50))
        draw.text((4, 4), "Hola", font=None, fill=(255, 255, 255))

    def test_textbbox(self):
        image = shim.Image.new("RGB", (64, 32), (0, 0, 0))
        draw = shim.ImageDraw.Draw(image)
        font = shim.ImageFont.load_default()
        box = draw.textbbox((0, 0), "Hola", font=font)
        self.assertGreater(box[2] - box[0], 0)
        self.assertGreater(box[3] - box[1], 0)

    def test_tobytes(self):
        image = shim.Image.new("RGB", (4, 4), (1, 2, 3))
        self.assertEqual(len(image.tobytes("raw", "RGB")), 4 * 4 * 3)


class TestDisplay(unittest.TestCase):
    def test_available_backends(self):
        backends = available_backends()
        self.assertIn("pil", backends)
        self.assertIn("pygame", backends)
        self.assertIn("framebuffer", backends)

    def test_memory_display(self):
        display = create_display("", width=320, height=240)
        try:
            self.assertEqual(display.size, (320, 240))
            display.clear((0, 0, 0))
            display.present()
            self.assertEqual(display.image.size, (320, 240))
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "ux.png")
                display.save_png(path)
                self.assertTrue(os.path.getsize(path) > 0)
        finally:
            display.close()

    def test_ui_renders_on_display(self):
        from gpi_music.ui import UI

        display = create_display("", width=320, height=240)
        try:
            ui = UI(display)
            ui.draw_scanning("Escaneando")
            ui.draw_message("Hola", "sub")
            ui.draw_options(["Uno", "Dos"], 0)
        finally:
            display.close()


if __name__ == "__main__":
    unittest.main()
