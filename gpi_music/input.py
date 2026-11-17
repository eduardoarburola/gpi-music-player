"""Entrada por botones y teclado usando evdev (sin dependencias).

En el GPi Case los botones pueden llegar de dos maneras:

* como **teclado** del driver ``gpio-keys`` (flechas, Intro, Retroceso, Tab…);
* como **mando** (el Retroflag usa ``xboxdrv``, así que la consola ve un
  «Microsoft X-Box 360 pad»).

La cruceta del GPi Case, tal y como la emula ``xboxdrv``, llega como un **hat**
(``ABS_HAT0X`` / ``ABS_HAT0Y`` con valores -1/0/+1), no como ejes. Por eso el
lector entiende varias formas de la misma dirección:

* ejes con rango real (``ABS_X`` / ``ABS_Y``), leyendo el rango del dispositivo
  con ``ioctl(EVIOCGABS)`` para saber dónde está el centro;
* hat (``ABS_HAT0X`` / ``ABS_HAT0Y``);
* botones de cruceta (``BTN_DPAD_*``);
* teclas de flecha del teclado.

Los eventos se traducen a *acciones* abstractas:

``up`` ``down`` ``left`` ``right`` ``confirm`` ``back`` ``next`` ``prev``
``volume_up`` ``volume_down`` ``toggle`` ``menu`` ``mute`` ``browse``

El mapa es configurable desde el archivo de configuración (sección ``input``).
"""

from __future__ import annotations

import glob
import os
import struct
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "InputReader",
    "ACTIONS",
    "parse_event",
    "default_keymap",
    "describe_event",
    "REPEATABLE_ACTIONS",
]

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
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_LEFTALT = 56
KEY_RIGHTALT = 100
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
BTN_DPAD_UP = 0x220
BTN_DPAD_DOWN = 0x221
BTN_DPAD_LEFT = 0x222
BTN_DPAD_RIGHT = 0x223

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

ABS_X = 0x00
ABS_Y = 0x01
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11

# _IOR('E', 0x40 + abs, struct input_absinfo) -> el número depende del código.
EVIOCGABS = 0x80184500
_ABS_INFO = struct.Struct("iiiiii")

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
ACTION_BROWSE = "browse"

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
    ACTION_BROWSE,
]

# Acciones que tienen sentido repetidas mientras se mantienen pulsadas.
REPEATABLE_ACTIONS = (ACTION_UP, ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT)

# Mapa por defecto: cubre el GPi Case (teclado gpio-keys), el mando emulado por
# xboxdrv (cruceta como hat) y un mando USB cualquiera.
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
    str(KEY_S): ACTION_BROWSE,       # «Y» del GPi Case en gpio-keys
    str(KEY_LEFTCTRL): ACTION_BROWSE,  # «Select» del GPi Case en gpio-keys
    str(KEY_Y): ACTION_NEXT,
    str(KEY_N): ACTION_NEXT,
    str(KEY_PAGEUP): ACTION_PREV,
    str(KEY_PAGEDOWN): ACTION_NEXT,
    str(KEY_F1): ACTION_PREV,
    str(KEY_F2): ACTION_NEXT,
    str(KEY_LEFTBRACE): ACTION_PREV,
    str(KEY_RIGHTBRACE): ACTION_NEXT,
    str(KEY_LEFTSHIFT): ACTION_PREV,
    str(KEY_RIGHTSHIFT): ACTION_NEXT,
    str(KEY_LEFTALT): ACTION_PREV,
    str(KEY_RIGHTALT): ACTION_NEXT,
    str(KEY_VOLUMEUP): ACTION_VOLUME_UP,
    str(KEY_VOLUMEDOWN): ACTION_VOLUME_DOWN,
    str(KEY_MUTE): ACTION_MUTE,
    str(KEY_D): ACTION_MUTE,
    # Cruceta como botones
    str(BTN_DPAD_UP): ACTION_UP,
    str(BTN_DPAD_DOWN): ACTION_DOWN,
    str(BTN_DPAD_LEFT): ACTION_LEFT,
    str(BTN_DPAD_RIGHT): ACTION_RIGHT,
    # Mando
    str(BTN_SOUTH): ACTION_CONFIRM,   # A
    str(BTN_EAST): ACTION_BACK,      # B
    str(BTN_NORTH): ACTION_TOGGLE,   # Y (posición superior)
    str(BTN_WEST): ACTION_BROWSE,    # X (posición izquierda)
    str(BTN_TL): ACTION_PREV,        # L
    str(BTN_TR): ACTION_NEXT,        # R
    str(BTN_THUMBL): ACTION_PREV,
    str(BTN_THUMBR): ACTION_NEXT,
    str(BTN_SELECT): ACTION_BROWSE,
    str(BTN_START): ACTION_MENU,
    str(BTN_MODE): ACTION_MENU,
}

_EVENT_NAMES: Dict[int, str] = {
    KEY_ESC: "KEY_ESC",
    KEY_BACKSPACE: "KEY_BACKSPACE",
    KEY_TAB: "KEY_TAB",
    KEY_ENTER: "KEY_ENTER",
    KEY_LEFTCTRL: "KEY_LEFTCTRL",
    KEY_A: "KEY_A",
    KEY_S: "KEY_S",
    KEY_B: "KEY_B",
    KEY_C: "KEY_C",
    KEY_X: "KEY_X",
    KEY_Y: "KEY_Y",
    KEY_Z: "KEY_Z",
    KEY_SPACE: "KEY_SPACE",
    KEY_UP: "KEY_UP",
    KEY_DOWN: "KEY_DOWN",
    KEY_LEFT: "KEY_LEFT",
    KEY_RIGHT: "KEY_RIGHT",
    KEY_VOLUMEUP: "KEY_VOLUMEUP",
    KEY_VOLUMEDOWN: "KEY_VOLUMEDOWN",
    KEY_MUTE: "KEY_MUTE",
    BTN_SOUTH: "BTN_SOUTH(A)",
    BTN_EAST: "BTN_EAST(B)",
    BTN_NORTH: "BTN_X/NORTH",
    BTN_WEST: "BTN_Y/WEST",
    BTN_TL: "BTN_TL(L)",
    BTN_TR: "BTN_TR(R)",
    BTN_SELECT: "BTN_SELECT",
    BTN_START: "BTN_START",
    BTN_MODE: "BTN_MODE",
    BTN_THUMBL: "BTN_THUMBL",
    BTN_THUMBR: "BTN_THUMBR",
    BTN_DPAD_UP: "BTN_DPAD_UP",
    BTN_DPAD_DOWN: "BTN_DPAD_DOWN",
    BTN_DPAD_LEFT: "BTN_DPAD_LEFT",
    BTN_DPAD_RIGHT: "BTN_DPAD_RIGHT",
    ABS_X: "ABS_X",
    ABS_Y: "ABS_Y",
    ABS_HAT0X: "ABS_HAT0X",
    ABS_HAT0Y: "ABS_HAT0Y",
}

_DIRECTION_ACTIONS: Dict[int, Tuple[str, str]] = {
    ABS_X: (ACTION_LEFT, ACTION_RIGHT),
    ABS_Y: (ACTION_UP, ACTION_DOWN),
    ABS_HAT0X: (ACTION_LEFT, ACTION_RIGHT),
    ABS_HAT0Y: (ACTION_UP, ACTION_DOWN),
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


def describe_event(etype: int, code: int, value: int) -> str:
    """Texto legible de un evento, para la pantalla de diagnóstico."""
    name = _EVENT_NAMES.get(code, "code 0x%X" % code)
    if etype == EV_KEY:
        state = {0: "suelto", 1: "pulsado", 2: "repetido"}.get(value, str(value))
        return "KEY  %-16s %s" % (name, state)
    if etype == EV_ABS:
        return "ABS  %-16s %d" % (name, value)
    return "EV%d  %-16s %d" % (etype, name, value)


class InputReader:
    """Lee los dispositivos de entrada y devuelve acciones.

    ``devices`` permite forzar una lista concreta de ficheros (útil en tests).
    ``keymap`` sobrescribe el mapa por defecto con entradas del tipo
    ``{"315": "browse"}`` (código de Linux como texto).
    ``events_log`` recibe una función a la que se envía cada evento en texto,
    para dejar un registro en disco y poder diagnosticar a distancia.
    """

    def __init__(
        self,
        devices: Optional[Iterable[str]] = None,
        keymap: Optional[Dict[str, str]] = None,
        repeat_delay: float = 0.45,
        repeat_rate: float = 0.12,
        events_log: Optional[Callable[[str], None]] = None,
        history: int = 12,
    ) -> None:
        self.keymap = dict(default_keymap)
        if keymap:
            self.keymap.update({str(k): v for k, v in keymap.items()})
        self.devices: List[str] = []
        self._fds: Dict[int, int] = {}
        self._pressed: Dict[int, set] = {}
        self._axis_state: Dict[int, Dict[int, int]] = {}
        self._dir_state: Dict[int, Dict[int, int]] = {}
        self._abs_range: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {}
        self._neutral_seen = set()
        self._held: Dict[str, Tuple[float, bool]] = {}
        self._held_src: Dict[str, Tuple[int, int]] = {}
        self._repeat_emit: Dict[str, float] = {}
        self.repeat_delay = max(0.05, float(repeat_delay))
        self.repeat_rate = max(0.03, float(repeat_rate))
        self.events_log = events_log
        self.events: List[str] = []
        self._history = max(1, int(history))
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

    def _note(self, etype: int, code: int, value: int) -> None:
        """Guarda el evento en el historial de diagnóstico."""
        line = describe_event(etype, code, value)
        self.events.append(line)
        del self.events[:-self._history]
        if self.events_log is not None:
            try:
                self.events_log(line)
            except Exception:  # noqa: BLE001 - el log nunca debe romper la app
                pass

    def _press(self, action: str, fd: int, code: int, repeatable: bool = True) -> bool:
        """Marca una acción como pulsada.

        Para las direcciones (arriba/abajo/izquierda/derecha) solo cuenta la
        primera: la cruceta puede llegar como hat y como eje a la vez y no
        debe mover dos pasos. El resto de botones se delivers siempre.
        """
        if action in REPEATABLE_ACTIONS:
            source = self._held_src.get(action)
            if source is not None and source != (fd, code):
                return False
        now = time.monotonic()
        self._held[action] = (now, repeatable)
        self._held_src[action] = (fd, code)
        self._repeat_emit[action] = now
        return True

    def _release(self, action: str, fd: int, code: int) -> None:
        if action in REPEATABLE_ACTIONS:
            source = self._held_src.get(action)
            if source is not None and source != (fd, code):
                # La acción la tiene otro botón: no se suelta aquí.
                return
        self._held.pop(action, None)
        self._held_src.pop(action, None)
        self._repeat_emit.pop(action, None)

    def _abs_limits(self, fd: int, code: int) -> Optional[Tuple[int, int]]:
        """Rango real del eje (mínimo, máximo) leído del dispositivo."""
        key = (fd, code)
        if key in self._abs_range:
            return self._abs_range[key]
        limits: Optional[Tuple[int, int]] = None
        try:
            import fcntl

            raw = fcntl.ioctl(fd, EVIOCGABS | (0x40 + code), bytes(_ABS_INFO.size))
            _value, vmin, vmax = struct.unpack("iii", raw[:12])
            if vmax > vmin:
                limits = (vmin, vmax)
        except Exception:  # noqa: BLE001 - si falla, usamos el valor por defecto
            limits = None
        self._abs_range[key] = limits
        return limits

    def _direction(self, fd: int, code: int, value: int) -> int:
        """Convierte un valor de eje/hat en -1, 0 o +1."""
        if code in (ABS_HAT0X, ABS_HAT0Y):
            return value if value in (-1, 0, 1) else 0
        limits = self._abs_limits(fd, code)
        if limits is None:
            # Sin ioctl: asumimos el rango habitual de 16 bits con signo.
            vmin, vmax = -32768, 32767
        else:
            vmin, vmax = limits
        center = (vmin + vmax) / 2.0
        threshold = max(1.0, (vmax - vmin) * 0.25)
        if value < center - threshold:
            return -1
        if value > center + threshold:
            return 1
        return 0

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
        for action in self._repeats():
            if action not in actions:
                actions.append(action)
        return actions

    def _repeats(self) -> List[str]:
        """Auto-repetición de las direcciones que se mantienen pulsadas."""
        if not self._held:
            return []
        now = time.monotonic()
        out: List[str] = []
        for action in list(self._held):
            pressed_at, repeatable = self._held[action]
            if not repeatable or action not in REPEATABLE_ACTIONS:
                continue
            if now - pressed_at < self.repeat_delay:
                continue
            if now - self._repeat_emit.get(action, 0.0) < self.repeat_rate:
                continue
            self._repeat_emit[action] = now
            out.append(action)
        return out

    def _translate(self, etype: int, code: int, value: int, fd: int) -> Optional[str]:
        if etype == EV_KEY:
            self._note(etype, code, value)
            action = self.keymap.get(str(code))
            if value == 0:  # soltar
                pressed = self._pressed.get(fd)
                if pressed is not None:
                    pressed.discard(code)
                if action:
                    self._release(action, fd, code)
                return None
            if value not in (1, 2):  # 1 = pulsado, 2 = repetición del teclado
                return None
            pressed = self._pressed.setdefault(fd, set())
            pressed.add(code)
            if action:
                # El teclado ya repite solo; los botones de mando no.
                repeatable = code >= 0x100
                if not self._press(action, fd, code, repeatable):
                    return None
                return action
            return None
        if etype == EV_ABS:
            self._note(etype, code, value)
            return self._translate_abs(code, value, fd)
        return None

    def _translate_abs(self, code: int, value: int, fd: int) -> Optional[str]:
        actions = _DIRECTION_ACTIONS.get(code)
        if actions is None:
            return None
        state = self._axis_state.setdefault(fd, {})
        state[code] = value
        direction = self._direction(fd, code, value)
        if code in (ABS_X, ABS_Y) and direction == 0:
            # Hemos visto el centro del eje: a partir de aquí se puede repetir.
            self._neutral_seen.add((fd, code))
        previous = self._dir_state.setdefault(fd, {}).get(code, 0)
        if direction == previous:
            return None
        self._dir_state[fd][code] = direction
        if direction == 0:
            # Al volver al centro se suelta la dirección.
            self._release(actions[0], fd, code)
            self._release(actions[1], fd, code)
            return None
        action = actions[0] if direction < 0 else actions[1]
        # Solo repetimos un eje si ya hemos visto el centro: así un mando mal
        # reportado (siempre en 0) no genera un scroll infinito.
        repeatable = code in (ABS_HAT0X, ABS_HAT0Y) or (fd, code) in self._neutral_seen
        if not self._press(action, fd, code, repeatable):
            return None
        return action

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
