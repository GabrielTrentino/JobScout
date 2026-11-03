"""Janela suspensa no canto direito, sempre por cima, como um overlay de jogo."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from jobscout import tray

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
SW_HIDE = 0
SW_SHOW = 5


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
VK_LBUTTON = 0x01
RGN_OR = 2


MODES = {
    # nome: (largura lógica padrão, altura cheia?, raio dos cantos)
    "bolha": (300, False, 16),
    "menu": (300, False, 16),
    "painel": (WIDTH, True, 0),
    "amplo": (880, True, 0),
}
MARGIN = 14
# Bolha sozinha: janela quadrada, boneco num círculo embaixo à esquerda, contador no canto de cima.
BUBBLE = 72
ORB = 64
BADGE = (30, 22)
# Ao soltar a bolha: perto do canto volta para o lugar padrão; perto da borda direita gruda nela.
SNAP_CORNER = 140
SNAP_EDGE = 48


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", ctypes.c_ulong)]


def _monitor_work(hwnd: int) -> Area:
    """Área útil, em pixels físicos, do monitor onde a janela está."""
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if monitor and user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
        work = info.rcWork
    else:
        work = _Rect()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
    return Area(work.left, work.top, work.right, work.bottom)


def snap(area: Area, window: Area, scale: float) -> tuple[int, int] | None:
    """Onde a bolha fica depois de solta: None = canto padrão; senão o canto inferior direito da janela."""
    to_right = abs(area.right - window.right)
    to_bottom = abs(area.bottom - window.bottom)
    if to_right < SNAP_CORNER * scale and to_bottom < SNAP_CORNER * scale:
        return None
    if to_right < SNAP_EDGE * scale:
        return (area.right - round(MARGIN * scale), window.bottom)
    return (window.right, window.bottom)


def _region(width: int, tall: int, shape: str, radius: int, scale: float) -> int:
    gdi32 = ctypes.windll.gdi32
    for name in ("CreateRoundRectRgn", "CreateEllipticRgn"):
        getattr(gdi32, name).restype = ctypes.c_void_p
    if shape not in ("orb", "orb-badge"):
        r = round(radius * 2 * scale)
        return gdi32.CreateRoundRectRgn(0, 0, width + 1, tall + 1, r, r)
    orb = round(ORB * scale)
    region = gdi32.CreateEllipticRgn(0, tall - orb, orb + 1, tall + 1)
    if shape == "orb-badge":
        badge_w, badge_h = round(BADGE[0] * scale), round(BADGE[1] * scale)
        badge = gdi32.CreateRoundRectRgn(width - badge_w, 0, width + 1, badge_h + 1, badge_h, badge_h)
        gdi32.CombineRgn(ctypes.c_void_p(region), ctypes.c_void_p(region), ctypes.c_void_p(badge), RGN_OR)
        gdi32.DeleteObject(ctypes.c_void_p(badge))
    return region


def place(hwnd: int, mode: str, height: int = 0, width: int = 0, shape: str = "", anchor: tuple[int, int] | None = None) -> None:
    """Posiciona a janela em pixels físicos: bolha e menu no canto (ou onde foram soltos), painéis na borda direita.

    O resize/move do pywebview desconta uma borda que a janela sem moldura não tem
    e deixa uma fresta à direita; aqui o cálculo é feito direto no Win32.
    shape "orb"/"orb-badge" recorta a janela no círculo do boneco (e no contador).
    anchor é o canto inferior direito da janela; None = canto padrão da tela.
    """
    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    default_width, full, radius = MODES.get(mode, MODES["painel"])
    previous = user32.SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2)
    try:
        area = _monitor_work(hwnd)
        scale = (user32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96) / 96
        area_w, area_h = area.right - area.left, area.bottom - area.top
        # Painel na borda direita pode crescer até 90% da tela (Currículo com os pontos de melhoria ao lado).
        size = min(round((width or default_width) * scale), round(area_w * (0.9 if full else 0.7)))
        if full:
            left, top, tall = area.right - size, area.top, area_h
        else:
            margin = round(MARGIN * scale)
            tall = min(max(round(max(height, 60) * scale), round(60 * scale)), area_h - 2 * margin)
            right, bottom = anchor or (area.right - margin, area.bottom - margin)
            left = max(area.left, min(right - size, area.right - size))
            top = max(area.top, min(bottom - tall, area.bottom - tall))
        user32.SetWindowPos(ctypes.c_void_p(hwnd), None, left, top, size, tall, SWP_NOZORDER | SWP_NOACTIVATE)
        if radius or shape:
            user32.SetWindowRgn(ctypes.c_void_p(hwnd), ctypes.c_void_p(_region(size, tall, shape, radius, scale)), True)
        else:
            user32.SetWindowRgn(ctypes.c_void_p(hwnd), None, True)
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))


def drag(hwnd: int, grab: tuple[float, float]) -> tuple[int, int] | None:
    """Leva a janela com o mouse enquanto o botão esquerdo estiver apertado; devolve onde ela deve ficar.

    grab é o ponto da janela onde o clique pegou, em pixels lógicos: a chamada chega depois que o mouse
    já andou alguns pixels, e medir a distância só agora deixaria a janela atrás do cursor.
    """
    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user32.SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2)
    try:
        cursor, rect = _Point(), _Rect()
        scale = (user32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96) / 96
        dx, dy = round(grab[0] * scale), round(grab[1] * scale)
        while user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
            user32.GetCursorPos(ctypes.byref(cursor))
            user32.SetWindowPos(ctypes.c_void_p(hwnd), None, cursor.x - dx, cursor.y - dy, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            time.sleep(0.01)
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        return snap(_monitor_work(hwnd), Area(rect.left, rect.top, rect.right, rect.bottom), scale)
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
        self._height = BUBBLE
        self._width = BUBBLE
        self._shape = "orb"
        self._anchor: tuple[int, int] | None = None
        self._handle = 0
        self._hidden = False
        self._tray = None
        # O pywebview chama cada função numa thread: os pedidos de tamanho entram um por vez e em ordem.
        self._shape_lock = threading.Lock()
        self._last_request = 0
        self._diagnostics: Path | None = None

    def _hwnd(self) -> int:
        # Janela escondida some da lista do Windows: guarda o HWND da primeira vez.
        self._handle = self._handle or own_window(self._window.title)
        return self._handle

    def encaixar(self) -> bool:
        """Reaplica o formato atual (também usado ao abrir)."""
        hwnd = self._hwnd()
        if not hwnd:
            return False
        place(hwnd, self._mode, self._height, self._width, self._shape, self._anchor)
        return True

    def formato(self, mode: str, height: int = 0, width: int = 0, shape: str = "", pedido: int = 0) -> bool:
        """bolha e menu: tamanho e recorte pedidos pela página; painel e amplo: altura da tela."""
        if mode not in MODES:
            return False
        with self._shape_lock:
            # Pedido antigo que chegou atrasado não desfaz o mais novo.
            if pedido and pedido < self._last_request:
                return False
            self._last_request = pedido or self._last_request
            self._mode = mode
            self._height = int(height or 0)
            self._width = int(width or 0)
            self._shape = shape if shape in ("orb", "orb-badge") else ""
            return self.encaixar()

    def medir(self) -> list[int]:
        """Tamanho da janela em pixels lógicos, para a página conferir se acompanhou."""
        hwnd = self._hwnd()
        if not hwnd:
            return []
        rect = _Rect()
        user32 = ctypes.windll.user32
        user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        scale = (user32.GetDpiForWindow(ctypes.c_void_p(hwnd)) or 96) / 96
        return [round(rect.right / scale), round(rect.bottom / scale)]

    def ajustar(self, detalhe: str = "") -> bool:
        """A página ficou com tamanho diferente da janela: um pixel a mais e de volta refaz o layout."""
        hwnd = self._hwnd()
        if not hwnd or self._hidden:
            return False
        if self._diagnostics:
            try:
                with self._diagnostics.open("a", encoding="utf-8") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} modo={self._mode} {detalhe}\n")
            except OSError:
                pass
        with self._shape_lock:
            rect = _Rect()
            ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(hwnd), None, rect.left, rect.top, rect.right - rect.left + 1, rect.bottom - rect.top, SWP_NOZORDER | SWP_NOACTIVATE,
            )
            return self.encaixar()

    def arrastar(self, x: float = 0, y: float = 0) -> bool:
        """A página chama ao perceber um arraste na bolha, com o ponto onde o clique pegou; volta ao soltar.

        Devolve True se a bolha foi presa no canto padrão.
        """
        hwnd = self._hwnd()
        if not hwnd or self._mode not in ("bolha", "menu"):
            return False
        self._anchor = drag(hwnd, (float(x), float(y)))
        self.encaixar()
        return self._anchor is None

    def abrir_painel(self, view: str = "rascunhos") -> None:
        webbrowser.open(f"{self._panel_url}#{view}")

    def escolher_pasta(self, inicial: str = "") -> str:
        """Caixa do Windows para escolher a pasta do JobScout; "" se a pessoa cancelar."""
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=inicial or "")
        return str(chosen[0]) if chosen else ""

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

    def ocultar(self) -> bool:
        """Vai para os ícones ocultos; o JobScout segue rodando. False se não há ícone na bandeja."""
        hwnd = self._hwnd()
        if not hwnd or not self._tray or not self._tray.ok:
            return False
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), SW_HIDE)
        self._hidden = True
        return True

    def mostrar(self) -> bool:
        hwnd = self._hwnd()
        if not hwnd:
            return False
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOW)
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        self._hidden = False
        return self.encaixar()

    def alternar(self) -> None:
        if self._hidden:
            self.mostrar()
        else:
            self.ocultar()

    def avisar(self, texto: str = "") -> None:
        """Aviso do Windows, só com a janela escondida (com ela aberta, o aviso aparece na bolha)."""
        if self._hidden and self._tray and texto:
            self._tray.notify(self._window.title, str(texto))

    def dica(self, texto: str = "") -> None:
        if self._tray and texto:
            self._tray.set_tip(str(texto))


def available() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def run(panel_url: str, on_closed, *, icon: Path | None = None, hidden: bool = False, name: str = "JobScout", on_bridge=None) -> None:
    """Abre o overlay e o ícone nos ícones ocultos. Bloqueia a thread principal até sair pelo menu."""
    import webview

    area = work_area()
    bridge = Bridge(panel_url)
    if icon:
        bridge._diagnostics = icon.with_name("janela.log")
    window = webview.create_window(
        "JobScout",
        panel_url + "?overlay=1#agora",
        js_api=bridge,
        width=BUBBLE,
        height=BUBBLE,
        x=area.right - BUBBLE - MARGIN,
        y=area.bottom - BUBBLE - MARGIN,
        frameless=True,
        easy_drag=False,
        on_top=True,
        resizable=False,
        min_size=(ORB, ORB),
        background_color="#0d1117",
    )
    bridge._window = window

    if icon:
        bridge._tray = tray.Tray(name, icon, bridge.alternar, lambda: bridge.abrir_painel("agora"), window.destroy)
        bridge._tray.start()
    if on_bridge:
        on_bridge(bridge)

    def on_shown() -> None:
        # A janela nativa pode levar um instante para aparecer na lista do Windows.
        for _ in range(20):
            if bridge.encaixar():
                if hidden:
                    bridge.ocultar()
                return
            time.sleep(0.1)

    window.events.shown += on_shown
    window.events.closed += on_closed
    webview.start(private_mode=False)
    if bridge._tray:
        bridge._tray.stop()
