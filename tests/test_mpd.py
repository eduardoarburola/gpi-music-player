"""Tests del cliente MPD (con un servidor falso en un hilo)."""

import socket
import threading
import unittest

from gpi_music.mpd import MPDClient, MPDError


class FakeMPDServer(threading.Thread):
    """Servidor MPD mínimo que responde con líneas predefinidas."""

    def __init__(self, responses):
        super().__init__(daemon=True)
        self.responses = {k.decode() if isinstance(k, bytes) else k: v for k, v in responses.items()}
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.received = []

    def run(self):
        conn, _addr = self.server.accept()
        conn.sendall(b"OK MPD 0.23.5\n")
        buffer = b""
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                command = line.decode("utf-8", "replace").strip()
                self.received.append(command)
                reply = self.responses.get(command.split(" ")[0], b"OK\n")
                conn.sendall(reply)
        conn.close()


class TestMPDClient(unittest.TestCase):
    def setUp(self):
        self.server = FakeMPDServer({
            b"listallinfo": (
                b"file: Rock/01.mp3\n"
                b"Title: Nightcall\n"
                b"Artist: Kavinsky\n"
                b"Album: OutRun\n"
                b"Time: 258\n"
                b"file: Rock/02.mp3\n"
                b"Title: Sandstorm\n"
                b"Artist: Darude\n"
                b"OK\n"
            ),
            b"status": (
                b"volume: 70\n"
                b"state: play\n"
                b"time: 12:258\n"
                b"repeat: 0\n"
                b"random: 0\n"
                b"OK\n"
            ),
            b"play": b"OK\n",
        })
        self.server.start()
        self.client = MPDClient("127.0.0.1", self.server.port, timeout=3)

    def tearDown(self):
        self.client.close()
        self.server.server.close()

    def test_greeting_and_list(self):
        tracks = self.client.list_tracks()
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0].title, "Nightcall")
        self.assertEqual(tracks[0].artist, "Kavinsky")
        self.assertEqual(tracks[0].duration, 258.0)
        self.assertEqual(tracks[1].title, "Sandstorm")
        self.assertTrue(tracks[0].remote)

    def test_status(self):
        status = self.client.status()
        self.assertEqual(status.get("state"), "play")
        self.assertEqual(status.get("volume"), "70")

    def test_command_error(self):
        self.server.responses["play"] = b"ACK [5@0] {} unknown command\n"
        with self.assertRaises(MPDError):
            self.client.play()


class TestStatusHelpers(unittest.TestCase):
    def test_elapsed_and_duration(self):
        from gpi_music.app import _status_duration, _status_elapsed

        status = {"time": "12:258"}
        self.assertEqual(_status_elapsed(status), 12.0)
        self.assertEqual(_status_duration(status), 258.0)

    def test_elapsed_field(self):
        from gpi_music.app import _status_duration, _status_elapsed

        status = {"elapsed": "9.5", "duration": "100.0"}
        self.assertAlmostEqual(_status_elapsed(status), 9.5)
        self.assertAlmostEqual(_status_duration(status), 100.0)

    def test_missing(self):
        from gpi_music.app import _status_duration, _status_elapsed

        self.assertEqual(_status_elapsed({}), 0.0)
        self.assertIsNone(_status_duration({}))


if __name__ == "__main__":
    unittest.main()
