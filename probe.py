"""命令行抓包 / 诊断工具（无需 GUI）。

用法：
    python probe.py                 # 枚举蓝牙设备
    python probe.py <BT地址>        # 连接耳机并 dump 全部交互帧
    python probe.py <BT地址> anc 1  # 设置 ANC protocolIndex=1（深度降噪）
    python probe.py <BT地址> eq 3   # EQ index=3（丹拿特调）
    python probe.py <BT地址> game on|off
    python probe.py <BT地址> find on|off
    python probe.py <BT地址> watch  # 持续监听推送
"""

from __future__ import annotations

import sys
import json

from oppo import btwin
from oppo.devices import profile_by_product_id
from oppo.protocol import (CMD_ANC_QUERY, CMD_ANC_SET, CMD_BATT_GET,
                           CMD_EQ_SET, CMD_FIND_SET, CMD_INFO,
                           CMD_NOTIFY_REG_MULTI, CMD_NOTIFY_SUB,
                           CMD_SWITCH_FEATURE, CMD_VERSION_GET, parse_eq_entries,
                           parse_frames)
from oppo.transport import Buds, TransportError


def hexs(b: bytes) -> str:
    return b.hex(" ").upper()


def dump(addr: str, args: list[str]) -> int:
    buds = Buds(addr)
    print(f"[*] 连接 {addr} …（自动探测 RFCOMM 通道）")
    buds.connect()
    print(f"[+] 已连接（通道 {buds.channel}）")

    def frames(cmd, payload=b"", wait=2.5):
        fs = buds.send_frames(cmd, payload, wait)
        for f in fs:
            print(f"    <- cmd=0x{f['cmd']:04X} seq=0x{f['seq']:02X} "
                  f"payload[{len(f['payload'])}]= {hexs(f['payload'])[:80]}")
        return fs

    print("[*] HELLO / 能力位图 0x0100")
    frames(0x0100, b"", )
    print("[*] 产品 ID 0x0103")
    pid = None
    for f in frames(CMD_INFO):
        if len(f["payload"]) >= 4:
            pid = f["payload"][1:4][::-1].hex().upper()
    prof = profile_by_product_id(pid)
    print(f"[+] 产品 ID: {pid} -> {prof.name}")

    print("[*] 固件版本 0x0105")
    frames(CMD_VERSION_GET)
    print("[*] 电量 0x0106")
    for f in frames(CMD_BATT_GET):
        p = f["payload"]
        if len(p) >= 2:
            for k in range(p[1]):
                i = 2 + k * 2
                if i + 1 < len(p):
                    who = {1: "左耳", 2: "右耳", 3: "充电盒"}.get(p[i], p[i])
                    v = p[i + 1]
                    print(f"    {who}: {v & 0x7F}%{' (充电中)' if v & 0x80 else ''}")
    print("[*] ANC 查询 0x010C")
    frames(CMD_ANC_QUERY, b"\x01\x01")
    print("[*] 可推送事件 0x0200")
    frames(CMD_NOTIFY_SUB, wait=2.0)

    if not args:
        print("[+] 抓包完成。加 `watch` 参数可持续监听推送："
              f"python probe.py {addr} watch")
        buds.close()
        return 0

    cmd = args[0]
    if cmd == "anc":
        idx = int(args[1]) if len(args) > 1 else 1
        print(f"[*] ANC 设置 -> protocolIndex={idx}")
        frames(CMD_ANC_SET, b"\x01\x01" + bytes(
            [1 << (idx % 8)] if idx < 8 else [0, 1 << (idx % 8)]))
    elif cmd == "eqall":
        print("[*] EQ 目录 0x0122 (01 05)")
        for f in frames(0x0122, b"\x01\x05", 3.0):
            for e in parse_eq_entries(f["payload"]):
                bands = " ".join(f"{b['freq']}Hz{b['gain']:+d}" for b in e["bands"])
                print(f"    id={e['id']:2d} {'自定义' if e['custom'] else '内置  '} "
                      f"{e['name']}  {bands}")
    elif cmd in ("ancmodes", "modes"):
        print("[*] 查询设备支持的降噪档位 0x010C (03 01)")
        for f in frames(0x010C, b"\x03\x01", 1.5):
            p = f["payload"]
            idx = [i * 8 + bit for i, byte in enumerate(p[2:])
                   for bit in range(8) if byte >> bit & 1]
            names = {3: "关闭", 4: "深度", 5: "中度", 6: "轻度", 7: "智能",
                     8: "通透", 9: "自适应通透", 11: "智能自适应"}
            print("    档位:", ", ".join(f"{i}({names.get(i, '?')})" for i in idx) or "无")
    elif cmd == "feat":
        fid = int(args[1], 0) if len(args) > 1 else 0x18
        on = args[2].lower() != "off" if len(args) > 2 else True
        print(f"[*] 功能开关 0x0403 feature=0x{fid:02X} -> {'开' if on else '关'}")
        frames(0x0403, bytes([fid, 1 if on else 0]))
    elif cmd == "eq":
        idx = int(args[1]) if len(args) > 1 else 0
        print(f"[*] EQ 设置 -> index={idx}")
        frames(CMD_EQ_SET, bytes([idx]))
    elif cmd == "game":
        on = args[1].lower() != "off" if len(args) > 1 else True
        print(f"[*] 游戏模式 -> {'开' if on else '关'}")
        frames(CMD_SWITCH_FEATURE, bytes([6, 1 if on else 0]))
    elif cmd == "find":
        on = args[1].lower() != "off" if len(args) > 1 else True
        print(f"[*] 查找耳机响铃 -> {'开' if on else '关'}")
        frames(CMD_FIND_SET, bytes([1 if on else 0]))
    else:
        print("[*] 注册推送 (1,2,5,0xF2) 并持续监听 … Ctrl+C 退出")
        try:
            buds.register_notify([1, 2, 5, 0xF2])
        except Exception as e:
            print(f"    (注册失败: {e})")
        try:
            while True:
                import time
                data = buds._drain(1.0)
                for f in parse_frames(data):
                    print(f"    <- cmd=0x{f['cmd']:04X} "
                          f"payload= {hexs(f['payload'])[:100]}")
        except KeyboardInterrupt:
            pass
    buds.close()
    print("[+] 完成")
    return 0


def run_probe() -> int:
    args = [a for a in sys.argv[2:]] if __name__ != "__main__" else sys.argv[1:]
    args = args or sys.argv[1:]
    positional = [a for a in sys.argv[1:] if a != "--probe"]
    if not positional:
        print("== 本机蓝牙设备 ==")
        devices = btwin.list_bt_devices()
        if not devices:
            print("（没有枚举到设备——需要 Windows / 已开启蓝牙 / 已配对）")
            return 0
        for d in devices:
            print(f"  {d['address']}  {'[连接]' if d['connected'] else '      '}"
                  f"  {d['name']}")
        return 0
    addr = positional[0]
    rest = positional[1:]
    try:
        return dump(addr, rest)
    except (TransportError, OSError) as e:
        print(f"[!] 失败：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_probe())
