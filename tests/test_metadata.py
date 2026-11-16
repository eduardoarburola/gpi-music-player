"""Tests de los parsers de metadatos."""

import os
import struct
import tempfile
import unittest

from gpi_music.metadata import (
    Tags,
    _id3_tags,
    _mp3_duration,
    guess_from_filename,
    read_metadata,
)


def make_id3v23(title: str, artist: str, album: str) -> bytes:
    """Construye un tag ID3v2.3 con los frames de texto indicados."""

    def frame(name: bytes, value: str) -> bytes:
        payload = b"\x00" + value.encode("latin-1")
        return name + struct.pack(">I", len(payload)) + b"\x00\x00" + payload

    body = b"".join([
        frame(b"TIT2", title),
        frame(b"TPE1", artist),
        frame(b"TALB", album),
    ])
    size = len(body)
    header = b"ID3" + b"\x03\x00" + b"\x00" + bytes(
        [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
    )
    return header + body


def make_cbr_mp3(frames: int = 100) -> bytes:
    """MP3 CBR de 128 kbps / 44.1 kHz con un número de frames dado."""
    frame_len = int(1152 / 8 * 128000 / 44100)  # 417 bytes
    header = bytes([0xFF, 0xFB, 0x90, 0x00])  # MPEG1 Layer3 128kbps 44.1kHz
    return (header + b"\x00" * (frame_len - 4)) * frames


def make_wav(seconds: float = 2.0, rate: int = 44100) -> bytes:
    channels, bits = 2, 16
    byte_rate = rate * channels * bits // 8
    data_size = int(byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, channels, rate, byte_rate, channels * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", data_size) + b"\x00" * data_size
    return b"RIFF" + struct.pack("<I", len(body)) + body


class TestId3(unittest.TestCase):
    def test_parse_tags(self):
        raw = make_id3v23("Nightcall", "Kavinsky", "OutRun")
        tags, offset = _id3_tags(raw)
        self.assertEqual(tags["title"], "Nightcall")
        self.assertEqual(tags["artist"], "Kavinsky")
        self.assertEqual(tags["album"], "OutRun")
        self.assertEqual(offset, len(raw))

    def test_no_id3(self):
        tags, offset = _id3_tags(b"\xff\xfb\x90\x00" + b"\x00" * 100)
        self.assertEqual(tags, {})
        self.assertEqual(offset, 0)


class TestMp3Duration(unittest.TestCase):
    def test_cbr_duration_from_size(self):
        audio = make_cbr_mp3(100)
        duration = _mp3_duration(audio, len(audio))
        self.assertIsNotNone(duration)
        # 100 frames * 1152 muestras / 44100 Hz = 2.612 s
        self.assertAlmostEqual(duration, 2.61, delta=0.05)

    def test_garbage_returns_none(self):
        self.assertIsNone(_mp3_duration(b"not audio at all", 12))


class TestWav(unittest.TestCase):
    def test_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tono.wav")
            with open(path, "wb") as fh:
                fh.write(make_wav(2.0))
            tags = read_metadata(path)
            self.assertAlmostEqual(tags.duration or 0, 2.0, delta=0.05)


class TestFilename(unittest.TestCase):
    def test_artist_title(self):
        artist, title = guess_from_filename("/música/Daft Punk - Around The World.mp3")
        self.assertEqual(artist, "Daft Punk")
        self.assertEqual(title, "Around The World")

    def test_only_title(self):
        artist, title = guess_from_filename("/m/intro.flac")
        self.assertEqual(artist, "")
        self.assertEqual(title, "intro")

    def test_fallback_when_no_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Bon Jovi - Livin On A Prayer.mp3")
            with open(path, "wb") as fh:
                fh.write(b"\x00" * 100)
            tags = read_metadata(path)
            self.assertEqual(tags.title, "Livin On A Prayer")
            self.assertEqual(tags.artist, "Bon Jovi")


class TestRobustness(unittest.TestCase):
    def test_missing_file(self):
        tags = read_metadata("/no/existe.mp3")
        self.assertIsInstance(tags, Tags)

    def test_truncated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "corta.flac")
            with open(path, "wb") as fh:
                fh.write(b"fLaC\x00\x00\x00\x22")
            tags = read_metadata(path)
            self.assertIsInstance(tags, Tags)


if __name__ == "__main__":
    unittest.main()
