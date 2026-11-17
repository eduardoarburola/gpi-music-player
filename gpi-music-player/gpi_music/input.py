"""Entrada por botones y teclado usando evdev (sin dependencias).

En el GPi Case los botones llegan como eventos de teclado del driver
``gpio-keys`` (flechas, Intro, Retroceso, Tab…), y en RetroPie también
funcionan como joystick. Este módulo lee ``/dev/input/event*`` directamente y
traduce los eventos a *acciones* abstractas:

``up`` ``down`` ``left`` ``right`` ``confirm`` ``back`` ``next`` ``prev``
``volume_up`` ``volume_down`` ``toggle`` ``menu`` ``mute``

El mapa es configurable desde el archivo de configuración.
"""

from __future__ import annotations

import glob
import os
import struct
from typing import Dict, Iterable, List, Optional

__all__ = ["InputReader", "ACTIONS", "parse_event", "default_keymap"]

# Códigos de tecla del kernel (linux/input-event-codes.h).
KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_Y = 21
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_SPACE = 57
KEY_F1 = 59
KEY_F2 = 60
KEY_LEFTALT = 56
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_UP = 103
KEY_DOWN = 108
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_HOME = 102
KEY_END = 107
KEY_PAGEUP = 104
KEY_PAGEDOWN = 109
KEY_POWER = 116
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_KPENTER = 96

# Botones de joystick (gamepad ABI).
BTN_SOUTH = 0x130
BTN_EAST = 0x131
BTN_NORTH = 0x133
BTN_WEST = 0x134
BTN_TL = 0x136
BTN_TR = 0x137
BTN_SELECT = 0x13A
BTN_START = 0x13B
BTN_MODE = 0x13C
BTN_THUMBL = 0x13D
BTN_THUMBR = 0x13E

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

ABS_X = 0x00
ABS_Y = 0x01

ACTION_UP = "up"
ACTION_DOWN = "down"
ACTION_LEFT = "left"
ACTION_RIGHT = "right"
ACTION_CONFIRM = "confirm"
ACTION_BACK = "back"
ACTION_NEXT = "next"
ACTION_PREV = "prev"
ACTION_VOLUME_UP = "volume_up"
ACTION_VOLUME_DOWN = "volume_down"
ACTION_TOGGLE = "toggle"
ACTION_MENU = "menu"
ACTION_MUTE = "mute"

ACTIONS = [
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_CONFIRM,
    ACTION_BACK,
    ACTION_NEXT,
    ACTION_PREV,
    ACTION_VOLUME_UP,
    ACTION_VOLUME_DOWN,
    ACTION_TOGGLE,
    ACTION_MENU,
    ACTION_MUTE,
]

# Mapa por defecto: cubre el GPi Case (teclado gpio-keys) y un mando USB.
default_keymap: Dict[str, str] = {
    # Teclado
    str(KEY_UP): ACTION_UP,
    str(KEY_DOWN): ACTION_DOWN,
    str(KEY_LEFT): ACTION_LEFT,
    str(KEY_RIGHT): ACTION_RIGHT,
    str(KEY_ENTER): ACTION_CONFIRM,
    str(KEY_KPENTER): ACTION_CONFIRM,
    str(KEY_SPACE): ACTION_CONFIRM,
    str(KEY_A): ACTION_CONFIRM,
    str(KEY_Z): ACTION_CONFIRM,
    str(KEY_ESC): ACTION_BACK,
    str(KEY_BACKSPACE): ACTION_BACK,
    str(KEY_B): ACTION_BACK,
    str(KEY_TAB): ACTION_MENU,
    str(KEY_C): ACTION_TOGGLE,
    str(KEY_X): ACTION_TOGGLE,
    str(KEY_Y): ACTION_NEXT,
    str(KEY_N): ACTION_NEXT,
    str(KEY_PAGEUP): ACTION_PREV,
    str(KEY_PAGEDOWN): ACTION_NEXT,
    str(KEY_F1): ACTION_PREV,
    str(KEY_F2): ACTION_NEXT,
    str(KEY_LEFTBRACE): ACTION_PREV,
    str(KEY_RIGHTBRACE): ACTION_NEXT,
    str(KEY_VOLUMEUP): ACTION_VOLUME_UP,
    str(KEY_VOLUMEDOWN): ACTION_VOLUME_DOWN,
    str(KEY_MUTE): ACTION_MUTE,
    str(KEY_D): ACTION_MUTE,
    # Mando
    str(BTN_SOUTH): ACTION_CONFIRM,
    str(BTN_EAST): ACTION_BACK,
    str(BTN_NORTH): ACTION_TOGGLE,
    str(BTN_WEST): ACTION_MENU,
    str(BTN_TL): ACTION_PREV,
    str(BTN_TR): ACTION_NEXT,
    str(BTN_THUMBL): ACTION_PREV,
    str(BTN_THUMBR): ACTION_NEXT,
    str(BTN_SELECT): ACTION_MENU,
    str(BTN_START): ACTION_MENU,
}

_EVENT_STRUCT = struct.Struct("llHHi")


def parse_event(data: bytes):
    """Descompone un ``input_event`` de Linux.

    Devuelve ``(type, code, value)`` o ``None`` si el paquete está incompleto.
    """
    if len(data) < _EVENT_STRUCT.size:
        return None
    _sec, _usec, etype, code, value = _EVENT_STRUCT.unpack(data)
    return etype, code, value


class InputReader:
    """Lee los dispositivos de entrada y devuelve acciones.

    ``devices`` permite forzar una lista concreta de ficheros (útil en tests).
    """

    def __init__(self, devices: Optional[Iterable[str]] = None, keymap: Optional[Dict[str, str]] = None) -> None:
        self.keymap = dict(default_keymap)
        if keymap:
            self.keymap.update({str(k): v for k, v in keymap.items()})
        self.devices: List[str] = []
        self._fds: Dict[int, int] = {}
        self._pressed: Dict[int, set] = {}
        self._actions: List[str] = []
        self._axis_state: Dict[int, Dict[int, int]] = {}
        self._open(devices)

    # ------------------------------------------------------------ interno ---
    def _open(self, devices: Optional[Iterable[str]]) -> None:
        if devices is None:
            devices = sorted(glob.glob("/dev/input/event*"))
        for path in devices:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self.devices.append(path)
            self._fds[fd] = fd
            self._pressed[fd] = set()

    # ------------------------------------------------------------- público ---
    def poll(self) -> List[str]:
        """Devuelve las acciones detectadas desde la última llamada."""
        actions: List[str] = []
        for fd in list(self._fds):
            try:
                while True:
                    data = os.read(fd, _EVENT_STRUCT.size * 32)
                    if not data:
                        break
                    offset = 0
                    while offset + _EVENT_STRUCT.size <= len(data):
                        event = parse_event(data[offset:offset + _EVENT_STRUCT.size])
                        offset += _EVENT_STRUCT.size
                        if event is None:
                            continue
                        etype, code, value = event
                        action = self._translate(etype, code, value, fd)
                        if action and action not in actions:
                            actions.append(action)
            except BlockingIOError:
                continue
            except OSError:
                continue
        return actions

    def _translate(self, etype: int, code: int, value: int, fd: int) -> Optional[str]:
        if etype == EV_KEY:
            if value == 0:  # soltar
                pressed = self._pressed.get(fd)
                if pressed is not None:
                    pressed.discard(code)
                return None
            action = self.keymap.get(str(code))
            if action:
                return action
            return None
        if etype == EV_ABS:
            axis = self._axis_state.setdefault(fd, {})
            axis[code] = value
            if code == ABS_X:
                if value < 20000:
                    return ACTION_LEFT
                if value > 40000:
                    return ACTION_RIGHT
            elif code == ABS_Y:
                if value < 20000:
                    return ACTION_UP
                if value > 40000:
                    return ACTION_DOWN
            return None
        return None

    def close(self) -> None:
        for fd in list(self._fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
        self.devices = []

    def __enter__(self) -> "InputReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
