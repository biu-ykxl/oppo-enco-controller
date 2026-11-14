"""Windows 蓝牙支持：已配对设备枚举（bluetoothapis / bthprops.cpl）。

仅 Windows 可用；其他平台 import 不报错但函数返回空。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"


class _BT:
    def __init__(self):
        self.lib = None
        if not IS_WINDOWS:
            return
        for name in ("bthprops.cpl", "bluetoothapis.dll"):
            try:
                self.lib = ctypes.WinDLL(name)
                break
            except OSError:
                continue

    def available(self) -> bool:
        return self.lib is not None


_BT_INSTANCE = _BT()


class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong),
                ("rgBytes", ctypes.c_ubyte * 6)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay",
                 "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Address", BLUETOOTH_ADDRESS),
        ("ulClassofDevice", wintypes.ULONG),
        ("fConnected", wintypes.BOOL),
        ("fRemembered", wintypes.BOOL),
        ("fAuthenticated", wintypes.BOOL),
        ("stLastSeen", SYSTEMTIME),
        ("stLastUsed", SYSTEMTIME),
        ("szName", ctypes.c_wchar * 248),
    ]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("fReturnAuthenticated", wintypes.BOOL),
        ("fReturnRemembered", wintypes.BOOL),
        ("fReturnUnknown", wintypes.BOOL),
        ("fReturnUnauthenticated", wintypes.BOOL),
        ("fIssueInquiry", wintypes.BOOL),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", wintypes.HANDLE),
    ]


class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


def list_bt_devices() -> list[dict]:
    """枚举本机蓝牙已配对/已连接设备。

    返回 [{name, address, connected, remembered, authenticated}]；
    失败或非 Windows 返回空列表。
    """
    lib = _BT_INSTANCE.lib
    if lib is None:
        return []

    lib.BluetoothFindFirstRadio.restype = ctypes.c_void_p
    lib.BluetoothFindFirstRadio.argtypes = [
        ctypes.POINTER(BLUETOOTH_FIND_RADIO_PARAMS),
        ctypes.POINTER(wintypes.HANDLE)]
    lib.BluetoothFindFirstDevice.restype = ctypes.c_void_p
    lib.BluetoothFindFirstDevice.argtypes = [
        ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS),
        ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
    lib.BluetoothFindNextDevice.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
    lib.BluetoothFindNextDevice.restype = wintypes.BOOL
    lib.BluetoothFindDeviceClose.argtypes = [ctypes.c_void_p]
    _close_handle = ctypes.windll.kernel32.CloseHandle
    _close_handle.argtypes = [wintypes.HANDLE]

    frp = BLUETOOTH_FIND_RADIO_PARAMS()
    frp.dwSize = ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS)
    hradio = wintypes.HANDLE()
    hfind_radio = lib.BluetoothFindFirstRadio(
        ctypes.byref(frp), ctypes.byref(hradio))
    if not hfind_radio:
        return []
    try:
        params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
        params.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS)
        params.fReturnAuthenticated = True
        params.fReturnRemembered = True
        params.fReturnUnknown = False
        params.fReturnUnauthenticated = False
        params.fIssueInquiry = False
        params.cTimeoutMultiplier = 1
        params.hRadio = hradio

        info = BLUETOOTH_DEVICE_INFO()
        info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)

        out: list[dict] = []
        hfind = lib.BluetoothFindFirstDevice(ctypes.byref(params),
                                             ctypes.byref(info))
        if hfind:
            try:
                while True:
                    addr = ":".join(f"{b:02X}" for b in
                                    reversed(info.Address.rgBytes))
                    name = info.szName or ""
                    if name or info.fRemembered:
                        out.append({
                            "name": name,
                            "address": addr,
                            "connected": bool(info.fConnected),
                            "remembered": bool(info.fRemembered),
                            "authenticated": bool(info.fAuthenticated),
                        })
                    info2 = BLUETOOTH_DEVICE_INFO()
                    info2.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
                    if not lib.BluetoothFindNextDevice(hfind,
                                                       ctypes.byref(info2)):
                        break
                    info = info2
            finally:
                lib.BluetoothFindDeviceClose(hfind)
        return out
    finally:
        _close_handle(hradio)
