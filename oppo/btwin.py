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
    """尝试强制断开经典蓝牙链路（保留配对、不动服务）。

    重要：**不要**用 BluetoothSetServiceState 停 A2DP 来断开 —— 实测会让
    Windows 卸载该设备的音频端点（"耳机 (XXX)" 从设备管理器消失），之后即使
    重新连接也没有声音，必须移除设备重新配对才能恢复。所以这里只用
    IOCTL_BTH_DISCONNECT_DEVICE，驱动不支持时如实返回失败，由调用方决定是否
    仅关闭控制通道。
    """
    if not IS_WINDOWS:
        return False, "仅 Windows 支持"

    def run(lib, hradio):
        if not _still_connected(lib, hradio, addr):
            return True, "本就未连接"
        try:
            addr_val = ctypes.c_ulonglong(_addr_to_int(addr))
            returned = wintypes.DWORD(0)
            k32 = ctypes.windll.kernel32
            k32.DeviceIoControl.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            ok = k32.DeviceIoControl(hradio, KSPROP_DISCONNECT_IOCTL,
                                     ctypes.byref(addr_val), 8, None, 0,
                                     ctypes.byref(returned), None)
            if ok:
                return True, "已断开"
            err = k32.GetLastError()
        except Exception as exc:                     # noqa: BLE001
            return False, f"断开失败：{exc}"
        # 驱动不支持该 IOCTL（本机为 WinError 50）：保持链路不动，交给用户
        return False, f"此适配器不支持强制断开（WinError {err}），已仅关闭控制通道"

    return _with_radio(run)


def connect_device(addr: str) -> tuple[bool, str]:
    """仅查询链路状态。**不再通过服务开关触发回连**（会破坏音频端点）。"""
    if not IS_WINDOWS:
        return False, "仅 Windows 支持"
    if is_connected(addr):
        return True, "链路已在"
    return False, "链路未建立，请先在 Windows 蓝牙设置中连接"


def has_audio_endpoint(name_hint: str, timeout: float = 20.0) -> bool | None:
    """检查该设备在系统里是否还有音频端点（True/False/None=无法判断）。

    A2DP 服务被异常停用后端点会被卸载，表现就是「连上了但没声音」。
    """
    if not IS_WINDOWS or not name_hint:
        return None
    import subprocess
    hint = name_hint.replace("'", "")
    ps = ("Get-PnpDevice -Class AudioEndpoint | Where-Object "
          "{ $_.FriendlyName -like '*" + hint + "*' } | "
          "Select-Object -First 1 -ExpandProperty FriendlyName")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=timeout)
        raw = out.stdout or b""
        for enc in ("utf-8", "gbk", "mbcs"):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = raw.decode("utf-8", "replace")
        return bool(text.strip())
    except Exception:
        return None


def is_connected(addr: str) -> bool:
    """实时查询该设备是否已连接。

    注意：list_bt_devices() 来自设备搜索，fConnected 有明显滞后（断开后仍报
    True），判断链路状态必须用 BluetoothGetDeviceInfo 实时值。
    """
    if not IS_WINDOWS:
        return False

    def run(lib, hradio):
        info = _device_info(lib, hradio, addr)
        return (bool(info is not None and info.fConnected), "ok")

    ok, _ = _with_radio(run)
    return ok
