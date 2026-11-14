"""读取 Windows 默认输出设备的音频格式（采样率 / 位深 / 声道）。

蓝牙链路的编码与码率由 Windows 的 A2DP 栈协商，没有公开 API 直接给出
codec / bitrate；但可以经 Core Audio 的 GetMixFormat 拿到主机侧渲染格式，
用于在界面上说明当前链路的音频参数。

全程 ctypes 直调 COM，任何一步失败都返回 None，不影响主功能。
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import POINTER, byref, c_void_p, c_uint32, c_ulong

IS_WINDOWS = sys.platform == "win32"

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioClient = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"
CLSCTX_ALL = 23


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str | None = None):
        super().__init__()
        if s:
            raw = uuid.UUID(s).bytes_le
            ctypes.memmove(byref(self), raw, 16)


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", ctypes.c_ushort),
                ("nChannels", ctypes.c_ushort),
                ("nSamplesPerSec", ctypes.c_uint32),
                ("nAvgBytesPerSec", ctypes.c_uint32),
                ("nBlockAlign", ctypes.c_ushort),
                ("wBitsPerSample", ctypes.c_ushort),
                ("cbSize", ctypes.c_ushort)]


def _method(ptr, index: int, restype, *argtypes):
    """按虚表下标取 COM 方法并绑定（第一个参数固定为接口指针）。"""
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(vtbl[index])


def read_output_format() -> dict | None:
    """返回 {rate, bits, channels, pcm_kbps}，失败返回 None。"""
    if not IS_WINDOWS:
        return None
    try:
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitialize(None)
    except OSError:
        return None

    enum = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(GUID(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
        byref(GUID(IID_IMMDeviceEnumerator)), byref(enum))
    if hr != 0 or not enum:
        return None

    dev = c_void_p()
    client = c_void_p()
    try:
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eConsole=0)
        get_default = _method(enum, 4, ctypes.c_long, ctypes.c_int,
                              ctypes.c_int, POINTER(c_void_p))
        if get_default(enum, 0, 0, byref(dev)) != 0 or not dev:
            return None

        # IMMDevice::Activate(IID_IAudioClient, CLSCTX_ALL, NULL, &client)
        activate = _method(dev, 3, ctypes.c_long, POINTER(GUID), c_uint32,
                           c_void_p, POINTER(c_void_p))
        if activate(dev, byref(GUID(IID_IAudioClient)), CLSCTX_ALL, None,
                    byref(client)) != 0 or not client:
            return None

        pwfx = POINTER(WAVEFORMATEX)()
        # IAudioClient::GetMixFormat(&fmt)
        get_mix = _method(client, 8, ctypes.c_long,
                          POINTER(POINTER(WAVEFORMATEX)))
        if get_mix(client, byref(pwfx)) != 0 or not pwfx:
            return None

        fmt = pwfx.contents
        rate, bits, ch = fmt.nSamplesPerSec, fmt.wBitsPerSample, fmt.nChannels
        if not rate or not ch:
            return None
        return {"rate": rate, "bits": bits, "channels": ch,
                "pcm_kbps": round(rate * bits * ch / 1000)}
    finally:
        try:
            if client:
                _method(client, 2, ctypes.c_ulong)(client)
            if dev:
                _method(dev, 2, ctypes.c_ulong)(dev)
            _method(enum, 2, ctypes.c_ulong)(enum)
        except Exception:
            pass


def describe(fmt: dict | None) -> str:
    """渲染成一句可读的参数说明。"""
    if not fmt:
        return "系统音频参数不可读"
    ch = "立体声" if fmt["channels"] == 2 else f"{fmt['channels']} 声道"
    depth = ("32-bit float" if fmt["bits"] == 32 else f"{fmt['bits']}-bit")
    return (f"{fmt['rate'] / 1000:.1f} kHz · {ch} · 系统混音 {depth}"
            f"；蓝牙编码由 Windows 协商（AAC/SBC）")
