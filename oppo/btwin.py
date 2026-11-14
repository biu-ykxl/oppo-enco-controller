"""Windows 蓝牙支持：已配对设备枚举（bluetoothapis / bthprops.cpl）。

仅 Windows 可用；其他平台 import 不报错但函数返回空。
"""

from __future__ import annotations

import ctypes
import sys
import time
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


# ---------------------------------------------------------------------------
# 连接 / 断开（真实链路层，保留配对）
#
# Windows 没有公开的「断开蓝牙设备」API，可用两条底层路径：
#   1) BluetoothSetServiceState：逐个停用该设备的服务；当最后一个服务被停用，
#      系统才会真正断开链路。重新「连接」= 把 A2DP 服务关掉再打开。
#   2) IOCTL_BTH_DISCONNECT_DEVICE：部分驱动支持，作为补充尝试。
# 两条都保留配对信息，不会丢失设备。
# ---------------------------------------------------------------------------

KSPROP_DISCONNECT_IOCTL = (0x0041 << 16) | (0x1B << 2)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s: str) -> GUID:
    import uuid
    g = GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
    return g


GUID_A2DP = "{0000110B-0000-1000-8000-00805F9B34FB}"
GUID_HFP = "{0000111E-0000-1000-8000-00805F9B34FB}"
GUID_AVRCP = "{0000110E-0000-1000-8000-00805F9B34FB}"
GUID_SPP = "{00001101-0000-1000-8000-00805F9B34FB}"

SERVICE_DISABLE = 0
SERVICE_ENABLE = 1


def _addr_to_int(addr: str) -> int:
    return int(addr.replace(":", "").replace("-", ""), 16)


def _with_radio(fn):
    lib = _BT_INSTANCE.lib
    if lib is None:
        return False, "蓝牙不可用"
    lib.BluetoothFindFirstRadio.restype = ctypes.c_void_p
    lib.BluetoothFindFirstRadio.argtypes = [
        ctypes.POINTER(BLUETOOTH_FIND_RADIO_PARAMS),
        ctypes.POINTER(wintypes.HANDLE)]
    frp = BLUETOOTH_FIND_RADIO_PARAMS()
    frp.dwSize = ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS)
    hradio = wintypes.HANDLE()
    hfind = lib.BluetoothFindFirstRadio(ctypes.byref(frp), ctypes.byref(hradio))
    if not hfind:
        return False, "没有可用的蓝牙适配器"
    try:
        return fn(lib, hradio)
    finally:
        try:
            lib.BluetoothFindRadioClose(ctypes.c_void_p(hfind))
        except Exception:
            pass
        try:
            ctypes.windll.kernel32.CloseHandle(hradio)
        except Exception:
            pass


def _device_info(lib, hradio, addr: str):
    lib.BluetoothGetDeviceInfo.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
    info = BLUETOOTH_DEVICE_INFO()
    info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
    info.Address.ullLong = _addr_to_int(addr)
    if lib.BluetoothGetDeviceInfo(hradio, ctypes.byref(info)) != 0:
        return None
    return info


def _installed_services(lib, hradio, info) -> list[GUID]:
    """枚举该设备已安装（已记录）的服务 GUID 列表。"""
    lib.BluetoothEnumerateInstalledServices.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(GUID)]
    count = wintypes.DWORD(0)
    lib.BluetoothEnumerateInstalledServices(
        hradio, ctypes.byref(info), ctypes.byref(count), None)
    if count.value == 0:
        return []
    buf = (GUID * count.value)()
    if lib.BluetoothEnumerateInstalledServices(
            hradio, ctypes.byref(info), ctypes.byref(count), buf) != 0:
        return []
    return [buf[i] for i in range(count.value)]


def _set_service(lib, hradio, info, guid_s: str, state: int) -> int:
    lib.BluetoothSetServiceState.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO),
        ctypes.POINTER(GUID), wintypes.DWORD]
    g = _guid(guid_s)
    return lib.BluetoothSetServiceState(hradio, ctypes.byref(info),
                                        ctypes.byref(g), state)


def _still_connected(lib, hradio, addr: str) -> bool:
    info = _device_info(lib, hradio, addr)
    return bool(info is not None and info.fConnected)


def disconnect_device(addr: str) -> tuple[bool, str]:
    """真正断开该设备的链路（保留配对）。"""
    if not IS_WINDOWS:
        return False, "仅 Windows 支持"

    def run(lib, hradio):
        if not _still_connected(lib, hradio, addr):
            return True, "本就未连接"
        info = _device_info(lib, hradio, addr)
        if info is None:
            return False, "读不到设备信息（可能未配对）"
        services = _installed_services(lib, hradio, info)
        disabled = 0
        for g in services:
            like = GUID.from_buffer_copy(g)
            res = _set_service(
                lib, hradio, info,
                "{:08X}-{:04X}-{:04X}-{}".format(
                    like.Data1, like.Data2, like.Data3,
                    "-".join(f"{b:02X}" for b in like.Data4)), SERVICE_DISABLE)
            if res == 0:
                disabled += 1
        # 兜底：部分驱动接受强制断开 IOCTL
        try:
            addr_val = ctypes.c_ulonglong(_addr_to_int(addr))
            returned = wintypes.DWORD(0)
            k32 = ctypes.windll.kernel32
            k32.DeviceIoControl.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            k32.DeviceIoControl(hradio, KSPROP_DISCONNECT_IOCTL,
                                ctypes.byref(addr_val), 8, None, 0,
                                ctypes.byref(returned), None)
        except Exception:
            pass
        # 等链路真正释放（最多 2 秒）
        for _ in range(10):
            if not _still_connected(lib, hradio, addr):
                return True, f"已断开（停用 {disabled} 项服务）"
            time.sleep(0.2)
        return False, "停用了服务但链路仍未断开"

    return _with_radio(run)


def connect_device(addr: str) -> tuple[bool, str]:
    """触发回连：A2DP 服务先关再开，Windows 会重新建立音频链路。"""
    if not IS_WINDOWS:
        return False, "仅 Windows 支持"

    def run(lib, hradio):
        info = _device_info(lib, hradio, addr)
        if info is None:
            return False, "读不到设备信息（可能未配对）"
        ok = False
        for guid_s in (GUID_A2DP, GUID_HFP, GUID_AVRCP):
            _set_service(lib, hradio, info, guid_s, SERVICE_DISABLE)
            if _set_service(lib, hradio, info, guid_s, SERVICE_ENABLE) == 0:
                ok = True
        if ok:
            return True, "已发起连接"
        return False, "连接失败（服务状态未改变）"

    return _with_radio(run)


def is_connected(addr: str) -> bool:
    target = addr.upper()
    for d in list_bt_devices():
        if d["address"].upper() == target:
            return bool(d["connected"])
    return False
