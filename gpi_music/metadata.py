"""Lectura de metadatos y duración sin dependencias externas.

Soporta MP3 (ID3v2), FLAC (Vorbis comments), OGG/Opus (Vorbis comments),
WAV (RIFF) y M4A/MP4 (atoms ilst). Si mutagen está instalado en el sistema se
usa como fuente prioritaria, pero el reproductor nunca lo necesita.

Si no se puede determinar la duración se devuelve ``None`` y la interfaz
muestra el tiempo transcurrido en lugar del total.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

__all__ = ["Tags", "read_metadata", "guess_from_filename"]


@dataclass
class Tags:
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: Optional[float] = None

    def any(self) -> bool:
        return bool(self.title or self.artist or self.album)


# --------------------------------------------------------------------------
# utilidades


HEAD_BYTES = 64 * 1024
TAIL_BYTES = 64 * 1024


def _read(path: str, size: int = HEAD_BYTES) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


def _read_tail(path: str, size: int = TAIL_BYTES) -> bytes:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            total = fh.tell()
            fh.seek(max(0, total - size))
            return fh.read()
    except OSError:
        return b""


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _decode(raw: bytes, encoding: int = 0) -> str:
    if not raw:
        return ""
    if encoding == 0:
        return raw.decode("latin-1", "replace").rstrip("\x00").strip()
    if encoding == 1:
        # UTF-16 con BOM
        try:
            return raw.decode("utf-16", "replace").rstrip("\x00").strip()
        except UnicodeDecodeError:
            return ""
    if encoding == 2:
        return raw.decode("utf-16-be", "replace").rstrip("\x00").strip()
    if encoding == 3:
        return raw.decode("utf-8", "replace").rstrip("\x00").strip()
    return ""


def guess_from_filename(path: str) -> Tuple[str, str]:
    """Saca ``artista - título`` del nombre del archivo."""
    name = os.path.splitext(os.path.basename(path))[0]
    name = name.replace("_", " ").strip()
    for sep in (" - ", " – ", " — ", "-"):
        if sep in name:
            left, right = name.split(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return "", name


# --------------------------------------------------------------------------
# MP3 / ID3v2


# Tablas de bitrate en kbps, indexadas por (versión, capa).
# La capa se codifica como 4 - layer_bits: 3 = Layer III, 2 = Layer II, 1 = Layer I.
_BITRATES = {
    # MPEG 1
    (3, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],  # Layer III
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],  # Layer II
    (3, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],  # Layer I
    # MPEG 2
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # Layer III
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # Layer II
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],  # Layer I
    # MPEG 2.5
    (0, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # Layer III
    (0, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # Layer II
    (0, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],  # Layer I
}
_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
_SAMPLES_PER_FRAME = {
    (3, 3): 1152,
    (3, 2): 1152,
    (3, 1): 384,
    (2, 3): 576,
    (2, 2): 1152,
    (2, 1): 384,
    (0, 3): 576,
    (0, 2): 1152,
    (0, 1): 384,
}

_ID3_FIELDS = {"TIT2": "title", "TT2": "title", "TPE1": "artist", "TP1": "artist",
               "TALB": "album", "TAL": "album"}


def _id3_tags(data: bytes) -> Tuple[Dict[str, str], int]:
    """Devuelve (tags, tamaño del tag ID3v2 en bytes)."""
    tags: Dict[str, str] = {}
    if len(data) < 10 or data[:3] != b"ID3":
        return tags, 0
    major = data[3]
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | (byte & 0x7F)
    total = size + 10
    if major >= 4:
        _parse_id3v24(data[10:total], tags)
    else:
        _parse_id3v23(data[10:total], tags)
    return tags, total


def _parse_id3v23(body: bytes, tags: Dict[str, str]) -> None:
    pos = 0
    while pos + 10 <= len(body):
        frame_id = body[pos:pos + 4]
        if not frame_id.strip(b"\x00"):
            break
        size = struct.unpack(">I", body[pos + 4:pos + 8])[0]
        data = body[pos + 10:pos + 10 + size]
        pos += 10 + size
        name = _ID3_FIELDS.get(frame_id.decode("latin-1", "replace"))
        if name and data:
            tags[name] = _decode(data[1:], data[0])


def _parse_id3v24(body: bytes, tags: Dict[str, str]) -> None:
    pos = 0
    while pos + 10 <= len(body):
        frame_id = body[pos:pos + 4]
        if not frame_id.strip(b"\x00"):
            break
        size = struct.unpack(">I", body[pos + 4:pos + 8])[0] & 0x0FFFFFFF
        data = body[pos + 10:pos + 10 + size]
        pos += 10 + size
        name = _ID3_FIELDS.get(frame_id.decode("latin-1", "replace"))
        if name and data:
            tags[name] = _decode(data[1:], data[0])


def _parse_mpeg_frame(header: bytes):
    """Devuelve (bitrate_bps, sample_rate, samples_per_frame, frame_length) o None."""
    if len(header) < 4 or header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
        return None
    version_id = (header[1] >> 3) & 0x03
    layer = (header[1] >> 1) & 0x03
    bitrate_index = (header[2] >> 4) & 0x0F
    sr_index = (header[2] >> 2) & 0x03
    padding = (header[2] >> 1) & 0x01
    if version_id == 1 or layer == 0 or bitrate_index in (0, 15) or sr_index == 3:
        return None
    rates = _SAMPLE_RATES.get(version_id)
    table = _BITRATES.get((version_id, 4 - layer))
    if not rates or not table:
        return None
    frame_rate = rates[sr_index]
    bitrate = table[bitrate_index] * 1000
    samples = _SAMPLES_PER_FRAME.get((version_id, 4 - layer), 1152)
    frame_len = int(samples / 8 * bitrate / frame_rate) + padding
    if frame_len <= 4:
        return None
    return bitrate, frame_rate, samples, frame_len


def _mp3_duration(body: bytes, audio_bytes: int = 0) -> Optional[float]:
    """Duración de un stream MPEG.

    Prioridad: cabecera Xing/VBRI (exacto) > CBR (tamaño del archivo) >
    extrapolación a partir de los frames leídos.
    """
    if len(body) < 4:
        return None
    pos = 0
    total_samples = 0
    sample_rate = 0
    bitrate = 0
    frames = 0
    bytes_walked = 0
    xing_frames: Optional[int] = None
    bitrates = set()

    while pos + 4 <= len(body) and frames < 200000:
        if body[pos] != 0xFF or (body[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        parsed = _parse_mpeg_frame(body[pos:pos + 4])
        if parsed is None:
            pos += 1
            continue
        frame_bitrate, frame_rate, samples, frame_len = parsed

        if frames == 0:
            window = body[pos + 4:pos + 4 + 32]
            for marker in (b"Xing", b"Info", b"VBRI"):
                idx = window.find(marker)
                if idx == -1:
                    continue
                if marker == b"VBRI":
                    if idx + 14 <= len(window):
                        xing_frames = struct.unpack(">I", window[idx + 10:idx + 14])[0]
                else:
                    flags = struct.unpack(">I", window[idx + 4:idx + 8])[0]
                    if flags & 0x0001 and idx + 12 <= len(window):
                        xing_frames = struct.unpack(">I", window[idx + 8:idx + 12])[0]
                if xing_frames:
                    break

        if frames == 0:
            sample_rate = frame_rate
        bitrate = frame_bitrate
        bitrates.add(frame_bitrate)
        total_samples += samples
        bytes_walked += frame_len
        frames += 1
        pos += frame_len

    if not frames or not sample_rate:
        return None
    if xing_frames:
        samples_per_frame = total_samples // frames
        return xing_frames * samples_per_frame / sample_rate
    if len(bitrates) == 1 and audio_bytes > 0:
        # CBR: el tamaño del archivo da la duración exacta.
        return audio_bytes * 8 / float(bitrate)
    if bytes_walked > 0 and audio_bytes > bytes_walked:
        # VBR sin Xing: extrapolamos con lo leído.
        return (total_samples / sample_rate) * (audio_bytes / float(bytes_walked))
    return total_samples / sample_rate


def _read_mp3(path: str, data: bytes, tail: bytes, size: int) -> Tags:
    tags_raw, offset = _id3_tags(data)
    duration = _mp3_duration(data[offset:], max(0, size - offset))
    return Tags(
        title=tags_raw.get("title", ""),
        artist=tags_raw.get("artist", ""),
        album=tags_raw.get("album", ""),
        duration=duration,
    )


# --------------------------------------------------------------------------
# FLAC


def _read_flac(path: str, data: bytes, tail: bytes = b"", size: int = 0) -> Tags:
    tags = Tags()
    if data[:4] != b"fLaC":
        return tags
    pos = 4
    while pos + 4 <= len(data):
        header = data[pos]
        block_type = header & 0x7F
        size = int.from_bytes(data[pos + 1:pos + 4], "big")
        body = data[pos + 4:pos + 4 + size]
        pos += 4 + size
        if block_type == 0 and len(body) >= 18:
            # STREAMINFO: sample rate 20 bits, total samples 36 bits
            packed = int.from_bytes(body[10:18], "big")
            sample_rate = (packed >> 44) & 0xFFFFF
            total_samples = packed & 0xFFFFFFFFF
            if sample_rate and total_samples:
                tags.duration = total_samples / sample_rate
        elif block_type == 4:
            for key, value in _parse_vorbis_comment(body).items():
                key = key.upper()
                if key == "TITLE":
                    tags.title = value
                elif key == "ARTIST":
                    tags.artist = value
                elif key == "ALBUM":
                    tags.album = value
        if header & 0x80:
            break
    return tags


# --------------------------------------------------------------------------
# Vorbis comments (usados por FLAC, OGG y Opus)


def _parse_vorbis_comment(body: bytes) -> Dict[str, str]:
    """Parsea un bloque Vorbis comment (little endian)."""
    out: Dict[str, str] = {}
    if len(body) < 8:
        return out
    try:
        vendor_len = struct.unpack("<I", body[0:4])[0]
        pos = 4 + vendor_len
        if pos + 4 > len(body):
            return out
        count = struct.unpack("<I", body[pos:pos + 4])[0]
        pos += 4
        for _ in range(min(count, 512)):
            if pos + 4 > len(body):
                break
            length = struct.unpack("<I", body[pos:pos + 4])[0]
            pos += 4
            item = body[pos:pos + length]
            pos += length
            text = item.decode("utf-8", "replace")
            if "=" in text:
                key, value = text.split("=", 1)
                out.setdefault(key, value)
    except struct.error:
        pass
    return out


# --------------------------------------------------------------------------
# OGG / Opus


def _read_ogg(path: str, data: bytes, tail: bytes = b"", size: int = 0) -> Tags:
    tags = Tags()
    sample_rate = 0
    comment_body = b""
    last_granule = 0
    # La cabecera va al principio; el último granule está al final del archivo.
    for chunk in (data, tail):
        pos = 0
        while pos + 27 <= len(chunk):
            if chunk[pos:pos + 4] != b"OggS":
                pos += 1
                continue
            granule = struct.unpack("<q", chunk[pos + 6:pos + 14])[0]
            if granule > 0:
                last_granule = max(last_granule, granule)
            seg_table = chunk[pos + 26]
            header_len = 27 + seg_table
            body_start = pos + header_len
            segs = chunk[pos + 27:pos + 27 + seg_table]
            body_len = sum(segs)
            body = chunk[body_start:body_start + body_len]
            if body[:7] == b"\x01vorbis" and len(body) >= 16:
                sample_rate = struct.unpack("<I", body[12:16])[0]
            elif body[:8] == b"OpusHead" and len(body) >= 12:
                sample_rate = 48000
            elif body[:7] == b"\x03vorbis":
                comment_body = body[7:]
            elif body[:8] == b"OpusTags":
                comment_body = body[8:]
            pos = body_start + body_len
    if sample_rate and last_granule > 0:
        tags.duration = last_granule / sample_rate
    if comment_body:
        for key, value in _parse_vorbis_comment(comment_body).items():
            key = key.upper()
            if key == "TITLE":
                tags.title = value
            elif key == "ARTIST":
                tags.artist = value
            elif key == "ALBUM":
                tags.album = value
    return tags


# --------------------------------------------------------------------------
# WAV


def _read_wav(path: str, data: bytes, tail: bytes = b"", size: int = 0) -> Tags:
    tags = Tags()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return tags
    pos = 12
    byte_rate = 0
    data_size = 0
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + chunk_size]
        if chunk_id == b"fmt " and len(body) >= 16:
            byte_rate = struct.unpack("<I", body[8:12])[0]
        elif chunk_id == b"data":
            # El tamaño real es el declarado en la cabecera: el archivo puede
            # ser más grande que el búfer que hemos leído.
            data_size = chunk_size or len(tail)
            break
        pos += 8 + chunk_size + (chunk_size & 1)
    if byte_rate and data_size:
        tags.duration = data_size / byte_rate
    return tags


# --------------------------------------------------------------------------
# M4A / MP4


_M4A_TAGS = {b"\xa9nam": "title", b"\xa9ART": "artist", b"\xa9alb": "album"}


def _read_m4a(path: str, data: bytes, tail: bytes = b"", size: int = 0) -> Tags:
    tags = Tags()
    # El átomo moov puede estar al principio o al final del archivo.
    for blob in (data, tail):
        if b"moov" not in blob[:4096] and b"moov" not in blob[-4096:]:
            continue
        for atom, size_range in _iter_atoms(blob, 0, len(blob)):
            if atom != b"moov":
                continue
            moov_body = blob[size_range[0]:size_range[1]]
            for sub, ssize in _iter_atoms(moov_body, 0, len(moov_body)):
                if sub == b"mvhd":
                    mvhd = moov_body[ssize[0]:ssize[1]]
                    if len(mvhd) >= 20:
                        version = mvhd[0]
                        if version == 1 and len(mvhd) >= 32:
                            timescale = struct.unpack(">I", mvhd[20:24])[0]
                            duration = struct.unpack(">Q", mvhd[24:32])[0]
                        else:
                            timescale = struct.unpack(">I", mvhd[12:16])[0]
                            duration = struct.unpack(">I", mvhd[16:20])[0]
                        if timescale:
                            tags.duration = duration / timescale
                elif sub == b"udta":
                    _parse_m4a_tags(moov_body[ssize[0]:ssize[1]], tags)
        if tags.duration:
            break
    return tags


def _parse_m4a_tags(body: bytes, tags: Tags) -> None:
    for atom, size in _iter_atoms(body, 0, len(body)):
        if atom == b"ilst":
            ilst = body[size[0]:size[1]]
            for sub, ssize in _iter_atoms(ilst, 0, len(ilst)):
                name = _M4A_TAGS.get(sub)
                if not name:
                    continue
                payload = ilst[ssize[0]:ssize[1]]
                for inner, isize in _iter_atoms(payload, 0, len(payload)):
                    if inner == b"data" and len(payload[isize[0]:isize[1]]) >= 8:
                        raw = payload[isize[0] + 8:isize[1]]
                        setattr(tags, name, raw.decode("utf-8", "replace").strip())
            return


def _iter_atoms(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        atom = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield atom, (pos + header, min(pos + size, end))
        pos += size


# --------------------------------------------------------------------------
# API


_READERS = {
    ".mp3": _read_mp3,
    ".flac": _read_flac,
    ".ogg": _read_ogg,
    ".oga": _read_ogg,
    ".opus": _read_ogg,
    ".wav": _read_wav,
    ".m4a": _read_m4a,
    ".mp4": _read_m4a,
}


def read_metadata(path: str) -> Tags:
    """Lee tags y duración de un archivo de audio.

    Nunca lanza excepciones: si algo falla devuelve los tags vacíos y, como
    mínimo, el título deducido del nombre del archivo.
    """
    ext = os.path.splitext(path)[1].lower()
    reader = _READERS.get(ext)
    tags = Tags()
    if reader:
        head = _read(path)
        if head:
            try:
                tags = reader(path, head, _read_tail(path), _file_size(path))
            except Exception:  # noqa: BLE001 - nunca romper la reproducción
                tags = Tags()
    if not tags.title and not tags.artist:
        artist, title = guess_from_filename(path)
        tags.title = tags.title or title
        tags.artist = tags.artist or artist
    return tags
