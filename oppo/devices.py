"""设备型号档案与名称识别。

白名单（欢律 compatWhiteList）只覆盖 OPPO / OnePlus；realme 与新型号走
「通用档位 + 运行时发现」：由设备用 0x010C(03 01) 自报支持的降噪档位。
"""

from __future__ import annotations

from .protocol import MODE_LABELS

# 通用档位（白名单未收录时使用；实际会先尝试设备自报）
ANC_GENERIC = [
    {"index": 3, "group": "off", "label": "关闭"},
    {"index": 1, "group": "nc", "label": "降噪"},
    {"index": 2, "group": "transparency", "label": "通透"},
]

# Free4 世代：叶子档位（真机实测）
ANC_FREE4 = [
    {"index": 3, "group": "off", "label": "关闭"},
    {"index": 4, "group": "nc", "label": "深度降噪"},
    {"index": 5, "group": "nc", "label": "中度降噪"},
    {"index": 6, "group": "nc", "label": "轻度降噪"},
    {"index": 7, "group": "nc", "label": "智能降噪"},
    {"index": 8, "group": "transparency", "label": "通透"},
    {"index": 11, "group": "adaptive", "label": "智能自适应"},
]

EQ_FREE4_DYNAUDIO = [
    {"index": 0, "label": "至臻原音"},
    {"index": 1, "label": "纯享人声"},
    {"index": 2, "label": "澎湃低音"},
    {"index": 3, "label": "丹拿特调"},
    {"index": 6, "label": "出厂/自定义"},
]
EQ_FREE4 = [
    {"index": 0, "label": "至臻原音"},
    {"index": 1, "label": "纯享人声"},
    {"index": 2, "label": "澎湃低音"},
]
EQ_GENERIC = [
    {"index": 0, "label": "原音"},
    {"index": 1, "label": "低音"},
    {"index": 2, "label": "人声"},
]

_GROUP_ORDER = {"off": 0, "nc": 1, "adaptive": 2, "transparency": 3}


def modes_from_indices(indices: list[int]) -> list[dict]:
    """把设备自报的档位 ID 列表转成 UI 档位（按语义分组排序）。"""
    out: list[dict] = []
    for i in sorted(set(indices)):
        if i == 3:
            group = "off"
        elif i in (8, 9):
            group = "transparency"
        elif i == 11:
            group = "adaptive"
        else:
            group = "nc"
        out.append({"index": i, "group": group,
                    "label": MODE_LABELS.get(i, f"模式 {i}")})
    out.sort(key=lambda m: (_GROUP_ORDER.get(m["group"], 4), m["index"]))
    return out


class DeviceProfile:
    def __init__(self, product_id: str, name: str, anc: list, eq: list,
                 game_mode: bool = True, find: bool = True,
                 wear_detect: bool = True, multi_connect: bool = True,
                 fast_anc: bool = False):
        self.product_id = product_id
        self.name = name
        self.anc = anc
        self.anc_by_index = {a["index"]: a for a in anc}
        self.eq = eq
        self.game_mode = game_mode
        self.find = find
        self.wear_detect = wear_detect
        self.multi_connect = multi_connect
        # Air 系列等固件对降噪写命令响应慢：跳过回读校验，乐观更新
        self.fast_anc = fast_anc

    def anc_label(self, index: int) -> str:
        a = self.anc_by_index.get(index)
        return a["label"] if a else MODE_LABELS.get(index, f"档位 {index}")

    def with_modes(self, indices: list[int]) -> "DeviceProfile":
        """用设备自报的档位替换档案里的档位表（保留其它能力）。"""
        if not indices:
            return self
        clone = DeviceProfile(
            self.product_id, self.name, modes_from_indices(indices), self.eq,
            self.game_mode, self.find, self.wear_detect, self.multi_connect,
            self.fast_anc)
        return clone


GENERIC = DeviceProfile("000000", "OPPO / OnePlus / realme 耳机",
                        ANC_GENERIC, EQ_GENERIC, fast_anc=True)
REALME = DeviceProfile("000001", "realme 耳机", ANC_GENERIC, EQ_GENERIC,
                       fast_anc=True)

PROFILES: dict[str, DeviceProfile] = {}
for _pid, _name, _anc, _eq, _find, _fast in [
    ("068C10", "OPPO Enco Free4", ANC_FREE4, EQ_FREE4, True, False),
    ("06C010", "OPPO Enco Free4（丹拿版）", ANC_FREE4, EQ_FREE4_DYNAUDIO, True, False),
    ("063810", "OPPO Enco Free3", ANC_FREE4, EQ_GENERIC, True, False),
    ("067810", "OPPO Enco Air4", ANC_GENERIC, EQ_GENERIC, True, True),
    ("064810", "OPPO Enco Air3", ANC_GENERIC, EQ_GENERIC, False, True),
    ("064820", "OPPO Enco Air3 Pro", ANC_GENERIC, EQ_GENERIC, True, True),
]:
    PROFILES[_pid] = DeviceProfile(_pid, _name, _anc, _eq, _find,
                                   fast_anc=_fast)

# 蓝牙名称关键字：命中即认为是同一协议族的耳机
NAME_HINTS = ["OPPO Enco", "Enco Free", "Enco Air", "Enco Buds", "Enco X",
              "OnePlus Buds", "OPPO Buds", "realme", "Buds Air", "Buds T",
              "Buds Pro", "Buds Z", "HeyMelody"]


def profile_by_product_id(pid: str | None,
                          bt_name: str = "") -> DeviceProfile:
    """产品 ID 优先；未收录时按蓝牙名称猜品牌，最后回退通用档案。"""
    if pid:
        hit = PROFILES.get(pid.upper())
        if hit:
            return hit
    if "realme" in (bt_name or "").lower():
        return REALME
    return GENERIC


def looks_like_supported(bt_name: str) -> bool:
    n = (bt_name or "").lower()
    return any(h.lower() in n for h in NAME_HINTS)


# 兼容旧调用
looks_like_oppo = looks_like_supported
