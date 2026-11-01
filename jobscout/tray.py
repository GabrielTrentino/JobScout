"""Ícone do JobScout nos ícones ocultos da barra de tarefas (Win32 puro, sem dependência nova).

Roda numa thread com o próprio laço de mensagens. Clique abre o JobScout; o botão direito mostra o menu.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import threading
import zlib
from ctypes import wintypes
from pathlib import Path
from typing import Callable

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_APP = 0x8000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
TRAY_MESSAGE = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 16
NIIF_INFO = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
TPM_RIGHTBUTTON = 2
MF_STRING, MF_SEPARATOR = 0, 0x800
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _Guid(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


class _Notify(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("hwnd", wintypes.HWND), ("id", wintypes.UINT), ("flags", wintypes.UINT),
        ("callback", wintypes.UINT), ("icon", wintypes.HANDLE), ("tip", wintypes.WCHAR * 128), ("state", wintypes.DWORD),
        ("state_mask", wintypes.DWORD), ("info", wintypes.WCHAR * 256), ("version", wintypes.UINT),
        ("info_title", wintypes.WCHAR * 64), ("info_flags", wintypes.DWORD), ("guid", _Guid), ("balloon_icon", wintypes.HANDLE),
    ]


class _WindowClass(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("proc", WNDPROC), ("extra_class", ctypes.c_int), ("extra_window", ctypes.c_int),
        ("instance", wintypes.HINSTANCE), ("icon", wintypes.HANDLE), ("cursor", wintypes.HANDLE), ("background", wintypes.HANDLE),
        ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR),
    ]


def icon_bytes(size: int = 32) -> bytes:
    """Ícone .ico (PNG por dentro): círculo azul com o boneco, desenhado sem biblioteca de imagem."""
    def inside(x: float, y: float) -> tuple[int, int, int, int]:
        cx, cy = x - 15.5, y - 15.5
        if cx * cx + cy * cy > 15.5 ** 2:
            return (0, 0, 0, 0)
        head = (cx ** 2 + (cy + 7) ** 2) < 16
        body = abs(cx) < 1.3 and -4 < cy < 5
        arms = abs(cy + 1 + abs(cx) * 0.5) < 1.3 and abs(cx) < 7
        legs = abs(abs(cx) - (cy - 4) * 0.7) < 1.4 and 4 < cy < 12
        return (255, 255, 255, 255) if head or body or arms or legs else (47, 111, 209, 255)

    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            rows.extend(inside(x * 32 / size, y * 32 / size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), 22) + png


class Tray:
    def __init__(self, title: str, icon_path: Path, on_open: Callable[[], None], on_panel: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.title = title
        self.icon_path = icon_path
        self.on_open = on_open
        self.on_panel = on_panel
        self.on_quit = on_quit
        self.hwnd = None
        self.icon = None
        self.ready = threading.Event()
        self.ok = False
        self._proc = WNDPROC(self._handle)  # precisa viver enquanto a janela existir

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        threading.Thread(target=self._loop, daemon=True).start()
        self.ready.wait(3)
        return self.ok

    def _data(self, flags: int) -> _Notify:
        data = _Notify()
        data.size = ctypes.sizeof(_Notify)
        data.hwnd = self.hwnd
        data.id = 1
        data.flags = flags
        return data

    def _add(self) -> bool:
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        data.callback = TRAY_MESSAGE
        data.icon = self.icon
        data.tip = self.title[:127]
        return bool(ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))

    def set_tip(self, text: str) -> None:
        if self.hwnd:
            data = self._data(NIF_TIP)
            data.tip = text[:127]
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def notify(self, title: str, text: str) -> None:
        if self.hwnd:
            data = self._data(NIF_INFO)
            data.info = text[:255]
            data.info_title = title[:63]
            data.info_flags = NIIF_INFO
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def stop(self) -> None:
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _menu(self) -> None:
        user32 = ctypes.windll.user32
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, 1, f"Abrir {self.title}")
        user32.AppendMenuW(menu, MF_STRING, 2, "Abrir painel no navegador")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, 3, "Sair")
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # Sem isto o menu não fecha ao clicar fora.
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)

    def _handle(self, hwnd, message, wparam, lparam):
        user32 = ctypes.windll.user32
        if message == TRAY_MESSAGE:
            if lparam == WM_LBUTTONUP:
                self.on_open()
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if message == WM_COMMAND:
            action = {1: self.on_open, 2: self.on_panel, 3: self.on_quit}.get(wparam & 0xFFFF)
            if action:
                action()
            return 0
        if message == self._restart:
            # O Windows Explorer reiniciou e a bandeja voltou vazia.
            self._add()
            return 0
        if message == WM_CLOSE:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _loop(self) -> None:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        ctypes.windll.shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
        instance = kernel32.GetModuleHandleW(None)
        self._restart = user32.RegisterWindowMessageW("TaskbarCreated")
        window_class = _WindowClass(proc=self._proc, instance=instance, name="JobScoutTray")
        user32.RegisterClassW(ctypes.byref(window_class))
        self.hwnd = user32.CreateWindowExW(0, "JobScoutTray", self.title, 0, 0, 0, 0, 0, None, None, instance, None)
        self.icon_path.write_bytes(icon_bytes())
        self.icon = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        self.ok = bool(self.hwnd and self.icon and self._add())
        self.ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


def hide_console() -> None:
    """Aberto com dois cliques, o console não precisa ficar na tela. Num terminal já aberto, ele fica."""
    if sys.platform != "win32":
        return
    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    console = kernel32.GetConsoleWindow()
    owners = (ctypes.c_ulong * 8)()
    if console and kernel32.GetConsoleProcessList(owners, 8) <= 2:
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow(console, 0)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "JobScout"


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    """Liga ou desliga o início com o Windows, só para este usuário."""
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            runner = Path(sys.executable).with_name("pythonw.exe")
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, f'"{runner}" -m jobscout')
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except OSError:
                pass
