"""OPOv1 协议层：帧封装、命令表、解码器。

移植自社区逆向成果（GPL/MIT 公开资料）：
- OPO v1 RFCOMM 规范（Swastik36/OPPO-Earbuds docs/PROTOCOL.md，公开参考规范）
- melodyctl（chiragverma11/melodyctl，MIT License, (c) 2026 Chirag Verma）
- 欢律 App 白名单（HeyMelody compatWhiteList，含 Enco Free4 / Free4 丹拿版能力表）

帧格式：
    AA [varint len] 00 00 [cmd LE16] [seq u8] [paylen LE16] [payload...]
"""

from __future__ import annotations

# ---- 命令字 ---------------------------------------------------------------
CMD_CAPS = 0x0100            # 能力位图（HELLO）
CMD_INFO = 0x0103            # 产品 ID（3 字节小端 -> 白名单 id）
CMD_VERSION_GET = 0x0105     # 固件版本（ASCII CSV 三元组）
CMD_BATT_GET = 0x0106        # 电量查询
CMD_GESTURES_GET = 0x0108    # 触控手势表
CMD_ANC_QUERY = 0x010C       # payload 01 01；回复为位图
CMD_EQ_SET = 0x0406          # payload: [protocol_index]
CMD_GESTURES_SET = 0x0401    # payload: [count, (ear,button,action,func)*count]
CMD_SWITCH_FEATURE = 0x0403  # payload: [featureId, enable]（feature 6 = 游戏模式）
CMD_ANC_SET = 0x0404         # payload: 01 01 <bitmap>
CMD_FIND_SET = 0x0400        # payload: [status]（01 响铃 / 00 停止）
CMD_GAMESOUND_SET = 0x0423   # payload: [type, enable]
CMD_EQ_CUSTOM_SET = 0x0418   # 自定义 EQ 写入（创建/更新/删除）
CMD_EQ_ALL = 0x0122          # EQ 目录（含自定义预设）读取，payload 01 05
CMD_SPATIAL_SET = 0x0422     # 空间音频：[00 关 / 01 固定 / 02 头动]
CMD_BATCH_STATUS = 0x010D    # 批量特性状态查询（部分型号不支持）

# 功能开关 id（0x0403 的 featureId，属设备数据）
FEATURE_HIGH_QUALITY = 0x18  # Hi-Res / 码率：值 2=高清、0=标准（发 1 或 3 会断链）
HQ_OFF, HQ_ON = 0x00, 0x02

# 通知子系统
CMD_NOTIFY_SUB = 0x0200      # 查询可推送的事件 id（回 0x8200）
CMD_NOTIFY_REG = 0x0201      # 注册单个事件: payload [eventId]
CMD_NOTIFY_PUSH = 0x0204     # 设备推送；payload[0] = eventId
CMD_NOTIFY_REG_MULTI = 0x0205
RESP_NOTIFY_REG_MULTI = 0x8205
RESP_NOTIFY_REGISTERED = 0x8202

FEATURE_GAME_MODE = 6
RESP_FLAG = 0x8000

NOTIFY_BATTERY = 1
NOTIFY_BUD_STATUS = 2
NOTIFY_GAME_MODE = 5
NOTIFY_USER_INTERACTION = 0xF1
NOTIFY_CONNECTED_DEVICES = 0xF2
NOTIFY_NAMES = {
    NOTIFY_BATTERY: "battery", NOTIFY_BUD_STATUS: "bud_status",
    3: "noise_mode", 4: "compactness", NOTIFY_GAME_MODE: "game_mode",
    6: "multi_connect", 17: "tone_change",
    NOTIFY_USER_INTERACTION: "user_interaction",
    NOTIFY_CONNECTED_DEVICES: "connected_devices",
}

STATUS_FLAG_OUT_OF_CASE = 0x01
STATUS_FLAG_IN_EAR = 0x02
STATUS_FLAG_COVER_OPEN = 0x04

COMPONENT = {1: "left", 2: "right", 3: "case"}
EAR = {1: "left", 2: "right", 4: "both"}

# ANC modeType 名称（欢律白名单语义）
# 降噪叶子档位 ID -> 显示名（设备实际使用这套编号，跨 OPPO/OnePlus/realme 通用）
MODE_LABELS = {
    3: "关闭", 4: "深度降噪", 5: "中度降噪", 6: "轻度降噪",
    7: "智能降噪", 8: "通透", 9: "自适应通透", 11: "智能自适应",
}
# 官方 App 用来查「支持哪些档位」的请求
ANC_MODES_PAYLOAD = b"\x03\x01"

MODE_NAMES = {1: "off", 2: "transparency", 3: "light", 4: "deep", 5: "nc",
              6: "adaptive", 7: "smart", 8: "medium", 10: "adaptive",
              26: "原音", 28: "人声", 29: "低音", 30: "丹拿特调", 34: "丹拿特调"}


def frame(cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    """构建单帧 OPOv1 包（payload <= 120 字节）。"""
    body = bytes([cmd & 0xFF, (cmd >> 8) & 0xFF, seq & 0xFF,
                  len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload
    length = len(body) + 2
    if length > 127:
        raise ValueError("payload too large for a single frame")
    return bytes([0xAA, length, 0x00, 0x00]) + body


def parse_frames(data: bytes) -> list[dict]:
    """把字节流解析为 OPOv1 帧字典列表。"""
    out: list[dict] = []
    i = 0
    n = len(data)
    while i < n:
        if data[i] != 0xAA:
            i += 1
            continue
        j = i + 1
        length = 0
        shift = 0
        while j < n:
            b = data[j]
            length |= (b & 0x7F) << shift
            j += 1
            shift += 7
            if not (b & 0x80):
                break
        if j + length > n:
            break
        body = data[j + 2:j + length]
        if len(body) >= 5:
            cmd = body[0] | (body[1] << 8)
            seq = body[2]
            plen = body[3] | (body[4] << 8)
            out.append({"cmd": cmd, "seq": seq,
                        "payload": body[5:5 + plen],
                        "raw": data[i:j + length]})
        i = j + length
    return out


# ---- 解码器 ---------------------------------------------------------------

def decode_product_id(payload: bytes) -> str | None:
    """0x0103 回复：[status][3 字节小端产品 ID]。"""
    if len(payload) < 4:
        return None
    return payload[1:4][::-1].hex().upper()


def decode_battery(payload: bytes) -> dict[str, dict]:
    """电量：[status][count][ (dev, charging<<7|level) * count ]。"""
    if len(payload) < 2:
        return {}
    count = payload[1]
    out: dict[str, dict] = {}
    for k in range(count):
        idx = 2 + k * 2
        if idx + 1 >= len(payload):
            break
        dev, val = payload[idx], payload[idx + 1]
        out[COMPONENT.get(dev, f"id{dev}")] = {
            "level": val & 0x7F, "charging": bool(val & 0x80)}
    return out


def decode_status_event(body: bytes) -> dict[str, dict]:
    """佩戴/在仓状态：[count][ (component, flags) * count ]。"""
    if not body:
        return {}
    count = body[0]
    out: dict[str, dict] = {}
    for k in range(count):
        off = 1 + k * 2
        if off + 2 > len(body):
            break
        dev, flags = body[off], body[off + 1]
        out[COMPONENT.get(dev, f"id{dev}")] = {
            "in_case": not flags & STATUS_FLAG_OUT_OF_CASE,
            "in_ear": bool(flags & STATUS_FLAG_IN_EAR),
            "cover_open": bool(flags & STATUS_FLAG_COVER_OPEN),
        }
    return out


def decode_connected_devices(body: bytes) -> list[dict]:
    """双连设备列表：[count][ (mac6 反序, u16, nameLen, name) * count ]。"""
    if not body:
        return []
    count = body[0]
    off = 1
    out: list[dict] = []
    for _ in range(count):
        if off + 9 > len(body):
            break
        addr = ":".join(f"{b:02X}" for b in reversed(body[off:off + 6]))
        nlen = body[off + 8]
        name = body[off + 9:off + 9 + nlen]
        if len(name) < nlen:
            break
        out.append({"address": addr,
                    "name": name.decode("utf-8", "replace")})
        off += 9 + nlen
    return out


def decode_version_records(payload: bytes) -> list[dict]:
    """固件版本：[status][count] + ASCII CSV (component, kind, value)。"""
    records: list[dict] = []
    if len(payload) < 2:
        return records
    count = payload[1]
    text = payload[2:].decode("ascii", "replace")
    nums: list[int] = []
    for tok in text.split(","):
        tok = tok.strip()
        if tok.lstrip("-").isdigit():
            nums.append(int(tok))
    for i in range(0, min(len(nums), count * 3) - 2, 3):
        records.append({"component": nums[i], "kind": nums[i + 1],
                        "value": nums[i + 2]})
    return records


# 能力位图 -> 解锁的命令 id 组（来自欢律 App 位索引表）
CAP_GROUPS = [
    [261], [262], [263], [264, 1025, 1046], [265], [1024], [1026], [1027],
    [268, 1028], [1029], [1030, 271], [1031], [], [1032], [1033], [], [],
    [276], [], [1038, 1037, 277, 278], [1039], [1040, 281], [517], [3840], [],
    [280, 1041], [282, 1042], [284, 1043], [], [274, 1035], [286, 287, 1045],
    [1037], [], [289, 1047], [290, 1048], [1049], [285, 1044], [291, 1050],
    [292, 1051], [293, 1052, 295, 1053, 1055], [1057, 35, 36, 34, 294, 297],
    [61185], [61186], [61187, 1054], [1056], [28], [], [1058, 298], [61188],
    [1059, 299], [], [1060], [61190], [], [], [1061, 302, 1062], [303],
    [1063, 304], [305, 1064], [1065, 306], [20], [1069, 307], [1070], [61191],
    [61192, 310, 1075], [61193], [1073, 308], [1074, 309, 1077], [279],
]


def decode_caps(payload: bytes) -> set[int]:
    """0x8100 回复：[status][bitmap...] -> 支持的命令 id 集合。"""
    if len(payload) < 2:
        return set()
    bmp = payload[1:]
    out: set[int] = set()
    for i, ids in enumerate(CAP_GROUPS):
        if i < len(bmp) * 8 and (bmp[i // 8] >> (i % 8)) & 1:
            out.update(ids)
    return out


def anc_bitmap(protocol_index: int) -> bytes:
    """ANC 设置位图：bit idx%8 of byte idx//8。"""
    n = protocol_index // 8 + 1
    b = bytearray(n)
    b[protocol_index // 8] |= 1 << (protocol_index % 8)
    return bytes(b)


def decode_anc_bitmap(bitmap: bytes) -> int | None:
    """位图最低置位位的 index，None 表示无。"""
    for i, byte in enumerate(bitmap):
        if byte:
            return i * 8 + ((byte & -byte).bit_length() - 1)
    return None


def decode_notify_event(payload: bytes, product_id: str | None = None) -> dict:
    """解码一条 0x0204 推送：[eventId][body...]。"""
    if not payload:
        return {}
    eid = payload[0]
    body = payload[1:]
    out: dict = {"event_id": eid,
                 "event": NOTIFY_NAMES.get(eid, f"event{eid}")}
    if eid == NOTIFY_BATTERY:
        out["battery"] = decode_battery(b"\x00" + body)
    elif eid == NOTIFY_BUD_STATUS:
        out["status"] = decode_status_event(body)
    elif eid == NOTIFY_CONNECTED_DEVICES:
        out["devices"] = decode_connected_devices(body)
    elif eid == NOTIFY_GAME_MODE:
        idx = 2 if product_id and product_id.upper() in {
            "062410", "062810", "063410", "063010"} else 1
        if len(body) > idx:
            out["game"] = {"on": bool(body[idx])}
    else:
        out["raw"] = body.hex(" ").upper()
    return out


def notify_register_payload(events: list[int]) -> bytes:
    return bytes([len(events)]) + bytes(e & 0xFF for e in events)


def parse_eq_entries(payload: bytes) -> list[dict]:
    """解析 0x8122 的 EQ 目录（内置 + 自定义预设）。

    布局：[status][count] 之后每条：
        [selected][minGain][maxGain][eqId][nameLen][name UTF-8]
        [bandCount][ (freq LE16, gain int8) * bandCount ]
    实测容错：不同固件可能省略 selected 或 band 段，逐字段做边界检查。
    """
    entries: list[dict] = []
    if len(payload) < 2:
        return entries
    count = payload[1]
    off = 2
    for _ in range(count):
        if off + 5 > len(payload):
            break
        selected = payload[off]
        min_gain = payload[off + 1]
        max_gain = payload[off + 2]
        eq_id = payload[off + 3]
        name_len = payload[off + 4]
        off += 5
        if off + name_len > len(payload):
            break
        name = payload[off:off + name_len].decode("utf-8", "replace")
        off += name_len
        bands: list[dict] = []
        if off < len(payload):
            band_count = payload[off]
            off += 1
            for _b in range(band_count):
                if off + 3 > len(payload):
                    break
                freq = payload[off] | (payload[off + 1] << 8)
                gain = payload[off + 2]
                if gain > 127:
                    gain -= 256
                bands.append({"freq": freq, "gain": gain})
                off += 3
        entries.append({
            "selected": bool(selected), "id": eq_id, "name": name or f"预设 {eq_id}",
            "min": min_gain, "max": max_gain, "bands": bands,
            "custom": bool(bands),
        })
    return entries
