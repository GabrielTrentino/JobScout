"""Janela suspensa no canto direito, sempre por cima, como um overlay de jogo."""

from __future__ import annotations

import ctypes
import sys
import time
import webbrowser
from dataclasses import dataclass

WIDTH = 400


@dataclass(frozen=True)
class Area:
    left: int
    top: int
    right: int
    bottom: int


def work_area() -> Area:
    """Área útil do monitor principal (sem a barra de tarefas), em pixels lógicos."""
    if sys.platform != "win32":
        return Area(0, 0, 1440, 900)

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = Rect()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    try:
        scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    except (AttributeError, OSError):
        scale = 1.0
    # Sem DPI awareness o Windows já devolve lógico; com ela, converte.
    aware = _dpi_aware()
    factor = scale if aware else 1.0
    return Area(*(round(value / factor) for value in (rect.left, rect.top, rect.right, rect.bottom)))


HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


def own_window(title: str) -> int:
    """HWND da janela deste processo com esse título (o navegador também pode ter um 'JobScout')."""
    if sys.platform != "win32":
        return 0
    user32 = ctypes.windll.user32
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    found = ctypes.c_void_p(0)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def check(hwnd, _param):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, 256)
        if buffer.value == title:
            found.value = hwnd
            return False
        return True

    user32.EnumWindows(callback_type(check), None)
    return int(found.value or 0)


def set_topmost(hwnd: int, on: bool) -> None:
    ctypes.windll.user32.SetWindowPos(
        ctypes.c_void_p(hwnd),
        ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST),
        0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


SWP_NOZORDER = 0x0004
PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


MODES = {
    # nome: (largura lógica, altura cheia?, raio dos cantos)
    "bolha": (300, False, 16),
    "menu": (300, False, 16),
    "painel": (WIDTH, True, 0),
    "amplo": (880, True, 0),
}
MARGIN = 14


def place(hwnd: int, mode: str, height: int = 0) -> None:
    """Posiciona a janela em pixels físicos: bolha e menu no canto inferior direito, painéis na borda direita.

    O resize/move do pywebview desconta uma borda que a janela sem moldura não tem
    e deixa uma fresta à direita; aqui o cálculo é feito direto no Win32.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    width_logical, full, radius = MODES.get(mode, MODES["painel"])
    previous = user32.SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2)
    try:
        rect = Rect()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA, já físico
        scale = (user32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96) / 96
        area_w, area_h = rect.right - rect.left, rect.bottom - rect.top
        width = min(round(width_logical * scale), round(area_w * 0.7))
        if full:
            left, top, tall = rect.right - width, rect.top, area_h
        else:
            margin = round(MARGIN * scale)
            tall = min(max(round(max(height, 60) * scale), round(60 * scale)), area_h - 2 * margin)
            left, top = rect.right - width - margin, rect.bottom - tall - margin
        user32.SetWindowPos(ctypes.c_void_p(hwnd), None, left, top, width, tall, SWP_NOZORDER | SWP_NOACTIVATE)
        if radius:
            r = round(radius * 2 * scale)
            region = gdi32.CreateRoundRectRgn(0, 0, width + 1, tall + 1, r, r)
            user32.SetWindowRgn(ctypes.c_void_p(hwnd), ctypes.c_void_p(region), True)
        else:
            user32.SetWindowRgn(ctypes.c_void_p(hwnd), None, True)
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))


def _dpi_aware() -> bool:
    try:
        return bool(ctypes.windll.user32.IsProcessDPIAware())
    except (AttributeError, OSError):
        return False


class Bridge:
    """Funções que a página do overlay chama via window.pywebview.api.

    Atributos com _ ficam fora do alcance do JS; sem isso o pywebview varre a janela nativa.
    """

    def __init__(self, panel_url: str) -> None:
        self._panel_url = panel_url
        self._window = None
        self._mode = "bolha"
        self._height = 76

    def _hwnd(self) -> int:
        return own_window(self._window.title)

    def encaixar(self) -> bool:
        """Reaplica o formato atual (também usado ao abrir)."""
        hwnd = self._hwnd()
        if not hwnd:
            return False
        place(hwnd, self._mode, self._height)
        return True

    def formato(self, mode: str, height: int = 0) -> bool:
        """bolha e menu: altura pedida pela página; painel e amplo: altura da tela."""
        if mode not in MODES:
            return False
        self._mode = mode
        self._height = int(height or 0)
        return self.encaixar()

    def abrir_painel(self, view: str = "rascunhos") -> None:
        webbrowser.open(f"{self._panel_url}#{view}")

    def abrir_link(self, url: str) -> None:
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)

    def fixar(self, on: bool) -> bool:
        # window.on_top do pywebview muda TopMost do WinForms fora da thread da interface
        # e derruba o processo. SetWindowPos só mexe na ordem e vale de qualquer thread.
        hwnd = self._hwnd()
        if not hwnd:
            return False
        set_topmost(hwnd, bool(on))
        return True

    def fechar(self) -> None:
        self._window.destroy()


def available() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def run(panel_url: str, on_closed) -> None:
    """Abre o overlay. Bloqueia a thread principal até a janela fechar."""
    import webview

    area = work_area()
    bridge = Bridge(panel_url)
    width = MODES["bolha"][0]
    window = webview.create_window(
        "JobScout",
        panel_url + "?overlay=1#agora",
        js_api=bridge,
        width=width,
        height=76,
        x=area.right - width - MARGIN,
        y=area.bottom - 76 - MARGIN,
        frameless=True,
        easy_drag=False,
        on_top=True,
        resizable=False,
        min_size=(200, 60),
        background_color="#0d1117",
    )
    bridge._window = window

    def on_shown() -> None:
        # A janela nativa pode levar um instante para aparecer na lista do Windows.
        for _ in range(20):
            if bridge.encaixar():
                return
            time.sleep(0.1)

    window.events.shown += on_shown
    window.events.closed += on_closed
    webview.start(private_mode=False)
