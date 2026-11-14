"""设备型号档案：来自欢律 App compatWhiteList 的能力矩阵子集。

每个档案给出：产品 ID、名称、ANC 档位（protocolIndex -> 语义）、
EQ 预设（protocolIndex -> 名称）等。未知产品 ID 回退到通用档案。
"""

from __future__ import annotations

# ANC 档位定义（真机实测 Enco Free4 丹拿版 2026-11-13）。
# 注意：写命令要用「叶子档位 ID」，不能用白名单里的 group protocolIndex
# （0/1/2 这类 group 会被设备映射到随机叶子，实测 1->轻度、2->通透）。
# 实测有效集合 {3,4,5,6,7,8,9,11}；9 语义未标注，默认不显示。
ANC_FREE4 = [
    {"index": 3, "group": "off", "label": "关闭"},
    {"index": 4, "group": "nc", "label": "深度降噪"},
    {"index": 5, "group": "nc", "label": "中度降噪"},
    {"index": 6, "group": "nc", "label": "轻度降噪"},
    {"index": 7, "group": "nc", "label": "智能降噪"},
    {"index": 8, "group": "transparency", "label": "通透"},
    {"index": 11, "group": "adaptive", "label": "智能自适应"},
]

# 其它 Enco 型号的常见档位（真机未验证，按同一套叶子 ID 约定）
ANC_GENERIC = [
    {"index": 3, "group": "off", "label": "关闭"},
    {"index": 4, "group": "nc", "label": "降噪"},
    {"index": 8, "group": "transparency", "label": "通透"},
]

# EQ 预设：Free4 丹拿版 equalizerMode 0/1/2 + 3(丹拿特调, tag=3)
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


class DeviceProfile:
    def __init__(self, product_id: str, name: str, anc: list, eq: list,
                 game_mode: bool = True, find: bool = True,
                 wear_detect: bool = True, multi_connect: bool = True):
        self.product_id = product_id
        self.name = name
        self.anc = anc
        self.anc_by_index = {a["index"]: a for a in anc}
        self.eq = eq
        self.game_mode = game_mode
        self.find = find
        self.wear_detect = wear_detect
        self.multi_connect = multi_connect

    def anc_label(self, index: int) -> str:
        a = self.anc_by_index.get(index)
        return a["label"] if a else f"档位 {index}"


GENERIC = DeviceProfile("000000", "OPPO / OnePlus 耳机", ANC_GENERIC, EQ_GENERIC)

PROFILES: dict[str, DeviceProfile] = {}
for _pid, _name, _anc, _eq, _find in [
    ("068C10", "OPPO Enco Free4", ANC_FREE4, EQ_FREE4, True),
    ("06C010", "OPPO Enco Free4（丹拿版）", ANC_FREE4, EQ_FREE4_DYNAUDIO, True),
    ("063810", "OPPO Enco Free3", ANC_FREE4, EQ_GENERIC, True),
    ("067810", "OPPO Enco Air4", ANC_GENERIC, EQ_GENERIC, True),
    ("064810", "OPPO Enco Air3", ANC_GENERIC, EQ_GENERIC, False),
    ("064820", "OPPO Enco Air3 Pro", ANC_GENERIC, EQ_GENERIC, True),
]:
    PROFILES[_pid] = DeviceProfile(_pid, _name, _anc, _eq, _find)

# 蓝牙名称模糊匹配（在枚举已配对设备时识别候选）
NAME_HINTS = ["OPPO Enco", "Enco Free", "Enco Air", "Enco Buds", "Enco X",
              "OnePlus Buds", "OPPO Buds"]


def profile_by_product_id(pid: str | None) -> DeviceProfile:
    if pid:
        return PROFILES.get(pid.upper(), GENERIC)
    return GENERIC


def looks_like_oppo(bt_name: str) -> bool:
    n = (bt_name or "").lower()
    return any(h.lower() in n for h in NAME_HINTS)
