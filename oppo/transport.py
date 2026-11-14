"""RFCOMM 传输层：Windows AF_BTH 实现（参考 melodyctl MIT, Linux BlueZ 版移植）。

职责：连接（含通道探测）、hello、请求-响应、通知注册与事件读取、断线感知。
"""

from __future__ import annotations

import socket
import time

from .protocol import (CMD_ANC_QUERY, CMD_ANC_SET, CMD_BATT_GET, CMD_CAPS,
                       CMD_EQ_ALL,
                       CMD_EQ_SET, CMD_FIND_SET, CMD_GESTURES_GET,
                       CMD_INFO, CMD_NOTIFY_PUSH, CMD_NOTIFY_REG,
                       CMD_NOTIFY_REG_MULTI, CMD_NOTIFY_SUB,
                       CMD_SWITCH_FEATURE, CMD_VERSION_GET,
                       RESP_FLAG, RESP_NOTIFY_REG_MULTI, RESP_NOTIFY_REGISTERED,
                       anc_bitmap, decode_anc_bitmap, decode_battery, decode_caps,
                       decode_notify_event, decode_product_id,
                       decode_version_records, frame, notify_register_payload,
                       parse_eq_entries,
                       parse_frames)

# Windows WinSock：AF_BTH 恒为 32（部分 Python 构建未导出该常量名）
AF_BTH = getattr(socket, "AF_BTH", 32)

# 常见通道：欢律系耳机实测分布在 12 / 15，其余做 1..30 扫描
CHANNEL_CANDIDATES = [15, 12]
PROBE_TIMEOUT = 1.5
# Windows WinSock 错误码中代表「链路已死」的（10054=连接被重置,
# 10053=本机中止, 10065=不可达）。timeout 单独处理。
DEAD_WINERRORS = (10054, 10053, 10065, 10060, 10061, 10064)


class TransportError(Exception):
    def __init__(self, msg: str, code: str = "error"):
        super().__init__(msg)
        self.code = code


class Buds:
    """一条到耳机的 RFCOMM 会话。线程不安全：由调用方的工作线程持有。"""

    def __init__(self, addr: str, timeout: float = 6.0,
                 channel: int | None = None):
        self.addr = addr
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.seq = 0x20
        self.channel = channel
        self.channel_discovered = False
        self.lost: str | None = None
        self._pending_events: list[dict] = []
        self._buffer = bytearray()

    # ---- 连接 --------------------------------------------------------------
    def _connect_channel(self, channel: int,
                         timeout: float) -> socket.socket:
        s = socket.socket(AF_BTH, socket.SOCK_STREAM,
                          socket.BTPROTO_RFCOMM)
        s.settimeout(timeout)
        try:
            s.connect((self.addr, channel))
        except OSError:
            s.close()
            raise
        return s

    def connect(self) -> None:
        if self.channel is not None:
            self.sock = self._connect_channel(self.channel, self.timeout)
            self.lost = None
            self._hello()
            return
        order = CHANNEL_CANDIDATES + [
            c for c in range(1, 31) if c not in CHANNEL_CANDIDATES]
        last: OSError | str | None = None
        for ch in order:
            sock = None
            try:
                sock = self._connect_channel(ch, PROBE_TIMEOUT)
            except OSError as exc:
                last = exc
                continue
            # 能连上不等于对：RFCOMM 上还有 HFP/AVRCP 等服务，必须用
            # 一次电量查询验证这条链路真的是控制通道。
            if self._validate(sock):
                self.sock = sock
                self.channel = ch
                self.channel_discovered = True
                self.lost = None
                self._hello()
                return
            last = f"通道 {ch} 无应答"
            try:
                sock.close()
            except OSError:
                pass
        hint = ""
        win = getattr(last, "winerror", None)
        if win in (10064, 10065, 10060):
            hint = ("耳机在盒内休眠或已关机（Windows 仍显示已连接是残留状态）："
                    "请取出耳机、保持开机并与电脑连接后重试。")
        elif win == 10061:
            hint = "耳机拒绝连接：可能未配对，或正在被手机端欢律占用。"
        raise TransportError(
            f"{self.addr} 上没有可用的控制通道（最后尝试：{last}）。"
            + (hint or "请确认耳机已开机、已与 Windows 连接，且手机端欢律已断开。"),
            code="no_channel")

    def _validate(self, sock: socket.socket) -> bool:
        """连上后发一次电量查询，收到 0x8106 才认定是控制通道。"""
        try:
            sock.settimeout(1.2)
            sock.sendall(frame(CMD_BATT_GET, b"", 0x30))
            deadline = time.time() + 1.6
            buf = bytearray()
            while time.time() < deadline:
                try:
                    chunk = sock.recv(256)
                except socket.timeout:
                    continue
                if not chunk:
                    return False
                buf += chunk
                if any(f["cmd"] == (CMD_BATT_GET | RESP_FLAG)
                       for f in parse_frames(bytes(buf))):
                    return True
        except OSError:
            return False
        return False

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def reconnect(self) -> None:
        self.close()
        self.connect()

    def _hello(self) -> None:
        self.sock.sendall(frame(CMD_CAPS, b"", 0x23))
        self._drain(1.5)

    # ---- 收发 --------------------------------------------------------------
    def _drain(self, wait: float) -> bytes:
        assert self.sock is not None
        end = time.time() + wait
        buf = bytearray()
        self.sock.settimeout(0.3)
        while time.time() < end:
            try:
                chunk = self.sock.recv(512)
            except socket.timeout:
                continue
            except OSError as exc:
                if getattr(exc, "winerror", None) in DEAD_WINERRORS:
                    self.lost = exc.strerror or "连接中断"
                break
            if not chunk:
                self.lost = "耳机关闭了连接"
                break
            buf += chunk
            end = time.time() + 0.5
        return bytes(buf)

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    def send_frames(self, cmd: int, payload: bytes = b"",
                    wait: float = 2.5) -> list[dict]:
        assert self.sock is not None, "未连接"
        seq = self._next_seq()
        self.sock.sendall(frame(cmd, payload, seq))
        return parse_frames(self._drain(wait))

    def send(self, cmd: int, payload: bytes = b"",
             wait: float = 2.5) -> list[dict]:
        want = cmd | RESP_FLAG
        return [f for f in self.send_frames(cmd, payload, wait)
                if f["cmd"] == want]

    # ---- 高层 API -----------------------------------------------------------
    def caps(self) -> set[int]:
        """设备声明的命令 id 集合（0x0100 能力位图）。"""
        for f in self.send(CMD_CAPS):
            return decode_caps(f["payload"])
        return set()

    def info(self) -> dict:
        """产品 ID + 白名单匹配（product_id 可能未知）。"""
        frames = self.send(CMD_INFO)
        pid = None
        for f in frames:
            pid = decode_product_id(f["payload"])
            if pid:
                break
        return {"product_id": pid}

    def battery(self) -> dict[str, dict]:
        for f in self.send(CMD_BATT_GET):
            out = decode_battery(f["payload"])
            if out:
                return out
        raise TransportError("没有收到电量回复", code="no_response")

    def versions(self) -> list[dict]:
        for f in self.send(CMD_VERSION_GET):
            return decode_version_records(f["payload"])
        return []

    def set_eq(self, index: int) -> list[dict]:
        return self.send(CMD_EQ_SET, bytes([index & 0xFF]))

    def set_feature(self, feature_id: int, value: int | bool) -> list[dict]:
        """通用功能开关（0x0403）。

        payload 是 [featureId, value]，value 不一定是布尔：
        实测 Free4 上 feature 0x06（游戏模式）用 1/0，
        而 feature 0x18（高清音频/码率）用 2=开、0=关，发 1 会被拒（ack 02）。
        """
        v = int(value)
        return self.send(CMD_SWITCH_FEATURE, bytes([feature_id & 0xFF, v & 0xFF]))

    def eq_catalog(self) -> list[dict]:
        """读取设备侧全部 EQ 条目（含自定义预设）。

        0x0122 的请求载荷随固件而异：先用官方 App 的 `01 05`，无回包再退化
        为 `01 00` 与空包，尽量把耳机里已有的自定义预设读出来。
        """
        for payload in (b"\x01\x05", b"\x01\x00", b""):
            for f in self.send(CMD_EQ_ALL, payload, wait=2.0):
                entries = parse_eq_entries(f["payload"])
                if entries:
                    return entries
        return []

    def find(self, ring: bool) -> list[dict]:
        """查找耳机（响铃）。Free4 支持 heyFindDevice；部分型号无响应。"""
        return self.send(CMD_FIND_SET, bytes([1 if ring else 0]))

    def anc_query(self) -> int | None:
        """查询当前 ANC 状态 -> 叶子档位 ID（真机实测 Free4：3/4/5/6/7/8/11）。

        回复 payload 布局：status(1) + 请求回显(2) + 状态位图(2+)。
        位索引即叶子档位 ID，而不是白名单里的 group protocolIndex。
        """
        for f in self.send(CMD_ANC_QUERY, b"\x01\x01"):
            p = f["payload"]
            if len(p) < 4:
                continue
            # 跳过 status + 2 字节请求回显
            for off in (3, 2):
                idx = decode_anc_bitmap(p[off:])
                if idx is not None:
                    return idx
        return None

    def anc_set(self, leaf_index: int) -> list[dict]:
        return self.send(CMD_ANC_SET, b"\x01\x01" + anc_bitmap(leaf_index))

    def eq_query(self) -> int | None:
        """读当前 EQ 预设（0x010F）：[status][index]。"""
        for f in self.send(0x010F):
            p = f["payload"]
            if len(p) >= 2:
                return p[1]
        return None

    # ---- 通知 ---------------------------------------------------------------
    def notify_caps(self) -> list[int]:
        for f in self.send(CMD_NOTIFY_SUB, wait=2.0):
            p = f["payload"]
            if len(p) >= 2:
                return list(p[2:2 + p[1]])
        return []

    def register_notify(self, events: list[int]) -> dict:
        events = [e & 0xFF for e in events]
        self._pending_events = []
        if len(events) > 1:
            frames = self.send_frames(
                CMD_NOTIFY_REG_MULTI, notify_register_payload(events), 2.0)
            self._pending_events += [
                f for f in frames if f["cmd"] == RESP_NOTIFY_REGISTERED]
            ack = next((f for f in frames
                        if f["cmd"] == RESP_NOTIFY_REG_MULTI), None)
            if ack is not None and (not ack["payload"]
                                    or ack["payload"][0] == 0):
                return {"style": "bulk", "events": events}
        for e in events:
            frames = self.send_frames(CMD_NOTIFY_REG, bytes([e]), 1.5)
            self._pending_events += [
                f for f in frames if f["cmd"] == RESP_NOTIFY_REGISTERED]
        return {"style": "per-event", "events": events}

    def read_events(self, wait: float = 1.0,
                    product_id: str | None = None) -> list[dict]:
        """读 wait 秒并返回解码后的推送事件列表。断线抛 TransportError。"""
        out: list[dict] = []
        pending, self._pending_events = self._pending_events, []
        for f in pending:
            d = self._decode_push(f, product_id)
            if d:
                out.append(d)
        for f in parse_frames(self._drain(wait)):
            d = self._decode_push(f, product_id)
            if d:
                out.append(d)
        if self.lost and not out:
            raise TransportError(f"耳机断开了连接（{self.lost}）",
                                 code="disconnected")
        return out

    @staticmethod
    def _decode_push(f: dict, product_id: str | None) -> dict | None:
        if f["cmd"] == CMD_NOTIFY_PUSH:
            return decode_notify_event(f["payload"], product_id)
        if f["cmd"] == RESP_NOTIFY_REGISTERED and len(f["payload"]) >= 2:
            return decode_notify_event(f["payload"][1:], product_id)
        return None
