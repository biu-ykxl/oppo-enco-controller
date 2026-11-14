"""OPPO Enco Controller —— Windows 版 OPPO / OnePlus 耳机控制台。

界面为仿浮窗形态的圆角卡片（无边框、可拖动），自绘电量环 / 拨动开关 / 胶囊按钮。

用法：
    python app.py            # 正常使用
    python app.py --demo     # 无耳机看界面
    python app.py --probe    # 命令行抓包诊断

优先适配：OPPO Enco Free4 / Free4 丹拿版（产品 ID 068C10 / 06C010）。
协议：OPOv1 over RFCOMM（欢律 App 同款，社区逆向公开规范 + 本项目真机校验）。
"""

from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from oppo import audioinfo, btwin, logs
from oppo.devices import (GENERIC, looks_like_supported,
                          profile_by_product_id)
from oppo.protocol import (FEATURE_GAME_MODE, FEATURE_HIGH_QUALITY,
                           HQ_OFF, HQ_ON)
from oppo.transport import Buds, TransportError
from oppo.ui import BatteryRing, SectionTitle, Toggle, palette, stylesheet

APP_NAME = "OPPO Enco"
APP_VERSION = "v1.3.0"

# 设备返回的内置预设常常没有名字，按 EQ id 回退到欢律的预设名称
EQ_FALLBACK_NAMES = {0: "至臻原音", 1: "纯享人声", 2: "澎湃低音",
                     3: "丹拿特调", 4: "自定义", 6: "出厂预设", 7: "自定义",
                     8: "自定义"}


class BudsWorker(threading.Thread):
    """会话线程：连接、轮询、订阅推送、执行写命令。"""

    class _Bridge(QWidget):
        sig = Signal(str, object)

    def __init__(self, addr: str):
        super().__init__(daemon=True)
        self.addr = addr
        self.buds: Buds | None = None
        self.stop_flag = threading.Event()
        self.bridge = self._Bridge()
        self.bridge.hide()
        self.product_id: str | None = None
        self.fast_anc = False        # Air 系列等：跳过回读校验
        self._cmd_lock = threading.Lock()

    def post(self, fn):
        with self._cmd_lock:
            if self.buds is None:
                return
            try:
                fn(self.buds)
            except TransportError as e:
                self._emit("error", str(e))
            except OSError as e:
                self._emit("error", f"蓝牙错误：{e}")

    def _emit(self, topic: str, data):
        self.bridge.sig.emit(topic, data)

    # ---- 主循环 -------------------------------------------------------------
    def run(self):
        last_err: Exception | None = None
        for attempt in range(3):
            if self.stop_flag.is_set():
                return
            try:
                self.buds = Buds(self.addr)
                self.buds.connect()
                last_err = None
                break
            except (TransportError, OSError) as e:
                last_err = e
                # 耳机刚出盒时蓝牙分页常要几秒才通，重试两次
                time.sleep(1.5)
        if last_err is not None:
            self._emit("disconnected", f"连接失败：{last_err}")
            return
        try:
            self.product_id = self.buds.info().get("product_id")
            self._emit("connected", self.product_id or "")
            # 先问设备自己支不支持这些档位，白名单没收录的型号（realme 等）靠这个
            modes = self.buds.anc_modes()
            if modes:
                self._emit("anc_modes", modes)
            self._poll_once(full=True)
            caps = self.buds.notify_caps()
            events = [e for e in (1, 2, 3, 5, 0xF2) if not caps or e in caps]
            if events:
                self.buds.register_notify(events)
            while not self.stop_flag.is_set():
                # 4s 一轮；拆成 0.05s 步进，命令来了能立刻抢占
                for _ in range(80):
                    if self.stop_flag.is_set():
                        break
                    time.sleep(0.05)
                if self.stop_flag.is_set():
                    break
                self._poll_once()
        except (TransportError, OSError) as e:
            self._emit("disconnected", str(e))
        finally:
            try:
                self.buds.close()
            except Exception:
                pass

    def _poll_once(self, full: bool = False):
        b = self.buds
        try:
            with self._cmd_lock:
                batt = b.battery(wait=1.0)
                if batt:
                    self._emit("battery", batt)
                if full:
                    self._emit("event", {"event": "versions",
                                         "records": b.versions()})
                    anc = b.anc_query()
                    if anc is not None:
                        self._emit("event", {"event": "noise_mode", "index": anc})
                    eq = b.eq_query()
                    if eq is not None:
                        self._emit("event", {"event": "eq_set", "index": eq})
                    self._emit("eq_catalog", b.eq_catalog())
                events = b.read_events(0.35, self.product_id)
            for ev in events:
                self._emit("event", ev)
        except TransportError as e:
            if e.code == "disconnected":
                raise
            self._emit("error", str(e))

    # ---- 命令 ---------------------------------------------------------------
    def anc_set(self, index: int):
        """切换降噪。

        快路径（Air 系列 / 未知型号）：发完即认为成功，不等待回读 ——
        这些固件回读要 1~3 秒，等待会让切换手感明显发滞。
        慢路径（Free4 等）：短等待回读确认，读不到就保留乐观状态。
        """
        def _do(b):
            b.anc_set(index)
            if self.fast_anc:
                self._emit("event", {"event": "noise_mode", "index": index})
                return
            got = b.anc_query(wait=0.7)   # ack 不算数，回读为准（但别等太久）
            self._emit("event", {"event": "noise_mode",
                                 "index": got if got is not None else index})
        self.post(_do)

    def eq_set(self, eq_id: int):
        def _do(b):
            b.set_eq(eq_id)
            time.sleep(0.25)
            got = b.eq_query()
            self._emit("event", {"event": "eq_set",
                                 "index": got if got is not None else eq_id})
        self.post(_do)

    def eq_refresh(self):
        self.post(lambda b: self._emit("eq_catalog", b.eq_catalog()))

    def feature_set(self, fid: int, value: int, on: bool, topic: str):
        def _do(b):
            fs = b.set_feature(fid, value)
            ok = (not fs) or (fs[0]["payload"][:1] == b"\x00")
            self._emit("feature_ack", {"topic": topic, "on": on, "ok": ok})
        self.post(_do)

    def find_ring(self, on: bool):
        self.post(lambda b: b.find(on))


class App(QWidget):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.dark = True
        self.p = palette(self.dark)
        self.worker: BudsWorker | None = None
        self.profile = GENERIC
        self.demo = demo
        self.ring_on = False
        self.feature_state = {"game": False, "hq": False}
        self._drag: QPoint | None = None
        self.compact = False
        self.verbose = False
        self._cur_mode = None
        self.settings = QSettings("OppoEncoCC", "controller")
        # 条状形态里显示哪些东西（可自定义）
        self.bar_items = {"anc": True, "battery": True,
                          "game": False, "find": False}

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(432)
        self.resize(432, 760)

        self.root = QWidget(self)
        self.root.setObjectName("root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.root)

        root_lay = QVBoxLayout(self.root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.panel = QWidget()
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(12)
        lay.addLayout(self._build_header())
        lay.addWidget(self._sep())
        lay.addWidget(self._build_device_row())
        lay.addLayout(self._build_battery())
        lay.addWidget(self._sep())
        lay.addWidget(self._build_anc())
        lay.addWidget(self._build_eq())
        lay.addWidget(self._sep())
        lay.addWidget(self._build_audio())
        lay.addWidget(self._build_features())
        lay.addStretch(1)
        lay.addWidget(self._build_footer())

        self.bar = self._build_bar()
        self.bar.setVisible(False)
        root_lay.addWidget(self.panel)
        root_lay.addWidget(self.bar)

        self._load_settings()
        self.apply_theme()
        if self.settings.value("compact", False, type=bool):
            self.toggle_compact()       # 恢复上次的条状形态

        if demo:
            QTimer.singleShot(150, self._load_demo)
        else:
            QTimer.singleShot(0, self.refresh_devices)

    # ---- 构建 ---------------------------------------------------------------
    def _sep(self) -> QFrame:
        f = QFrame()
        f.setObjectName("sep")
        f.setFixedHeight(1)
        return f

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_title = QLabel(APP_NAME)
        self.lbl_title.setObjectName("title")
        self.lbl_state = QLabel("未连接")
        self.lbl_state.setObjectName("sub")
        row.addWidget(self.lbl_title)
        row.addWidget(self.lbl_state)
        row.addStretch(1)

        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setObjectName("icon")
        self.btn_settings.setToolTip("设置 / 日志")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_min = QPushButton("▾")
        self.btn_min.setObjectName("icon")
        self.btn_min.setToolTip("最小化为条状")
        self.btn_min.setCursor(Qt.PointingHandCursor)
        self.btn_min.clicked.connect(self.toggle_compact)
        self.btn_theme = QPushButton("☀")
        self.btn_theme.setObjectName("icon")
        self.btn_theme.setToolTip("切换深浅色")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("icon")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("窗口置顶")
        self.btn_pin.setCursor(Qt.PointingHandCursor)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("icon")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_settings)
        row.addWidget(self.btn_min)
        row.addWidget(self.btn_theme)
        row.addWidget(self.btn_pin)
        row.addWidget(self.btn_close)
        return row

    def _build_device_row(self):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.combo_dev = QComboBox()
        self.combo_dev.addItem("点击 ⟳ 搜索耳机", "")
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setObjectName("icon")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("刷新设备列表")
        self.btn_refresh.clicked.connect(self.refresh_devices)
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.setCursor(Qt.PointingHandCursor)
        self.btn_connect.clicked.connect(self.toggle_connect)
        self.btn_connect.setEnabled(False)
        row.addWidget(self.combo_dev, 1)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_connect)
        return w

    def _build_battery(self):
        row = QHBoxLayout()
        row.setSpacing(4)
        self.ring_l = BatteryRing("左耳", self.p)
        self.ring_r = BatteryRing("右耳", self.p)
        self.ring_c = BatteryRing("充电盒", self.p)
        for r in (self.ring_l, self.ring_r, self.ring_c):
            row.addWidget(r)
        row.addStretch(1)
        return row

    def _build_anc(self):
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(SectionTitle("降噪", self.p))
        self.anc_grid = QGridLayout()
        self.anc_grid.setSpacing(6)
        box.addLayout(self.anc_grid)
        return w

    def _build_eq(self):
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.eq_title = SectionTitle("音效", self.p, action="⟳")
        self.eq_title.clicked.connect(self.refresh_eq)
        box.addWidget(self.eq_title)
        self.eq_hint = QLabel("连接后自动读取耳机内置与自定义预设")
        self.eq_hint.setObjectName("sub")
        box.addWidget(self.eq_hint)
        self.eq_grid = QGridLayout()
        self.eq_grid.setSpacing(6)
        box.addLayout(self.eq_grid)
        return w

    def _build_audio(self):
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(SectionTitle("音频 · Hi-Res", self.p))

        # 设备侧只有两档：标准(0x18=0) / Hi-Res(0x18=2)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.tier_buttons: dict[int, QPushButton] = {}
        for label, val in (("标准码率", HQ_OFF), ("Hi-Res 高清", HQ_ON)):
            btn = QPushButton(label)
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=val: self.on_tier(v))
            self.tier_buttons[val] = btn
            row.addWidget(btn)
        row.addStretch(1)
        box.addLayout(row)

        self.lbl_codec = QLabel("当前链路 —")
        self.lbl_codec.setObjectName("chip")
        self.lbl_codec.setWordWrap(True)
        box.addWidget(self.lbl_codec)
        note = QLabel("设备只有这两档且不支持回读（显示为上次设置）；"
                      "LHDC 具体码率由手机端协商，Windows 不提供读取接口")
        note.setObjectName("sub")
        note.setWordWrap(True)
        box.addWidget(note)
        return w

    def _build_features(self):
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        box.addWidget(SectionTitle("功能", self.p))

        self.sw_game, row_game = self._switch_row(
            "低延迟游戏模式", "手势切换后耳机会推送状态", "game")
        box.addWidget(row_game)

        self.btn_find = QPushButton("🔊   查找耳机响铃")
        self.btn_find.setObjectName("ghost")
        self.btn_find.setCursor(Qt.PointingHandCursor)
        self.btn_find.clicked.connect(self.on_find)
        box.addWidget(self.btn_find)
        return w

    def _switch_row(self, title: str, hint: str, key: str):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        lab = QLabel(title)
        lab.setObjectName("chipTitle")
        sub = QLabel(hint)
        sub.setObjectName("sub")
        col.addWidget(lab)
        col.addWidget(sub)
        sw = Toggle(self.p)
        sw.toggled.connect(lambda on, k=key: self.on_feature(k, on))
        row.addLayout(col, 1)
        row.addWidget(sw)
        return sw, w

    def _build_footer(self):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.lbl_fw = QLabel("固件 —")
        self.lbl_fw.setObjectName("sub")
        self.lbl_pid = QLabel(f"Controller {APP_VERSION}")
        self.lbl_pid.setObjectName("sub")
        col.addWidget(self.lbl_fw)
        col.addWidget(self.lbl_pid)
        return w

    # ---- 条状形态 -----------------------------------------------------------
    def _build_bar(self):
        w = QWidget()
        w.setObjectName("bar")
        row = QHBoxLayout(w)
        row.setContentsMargins(14, 9, 10, 9)
        row.setSpacing(8)

        self.bar_dot = QLabel("●")
        self.bar_dot.setObjectName("dot")
        self.bar_name = QLabel("未连接")
        self.bar_name.setObjectName("barname")
        self.bar_name.setFixedWidth(108)

        self.btn_bar_anc = QPushButton("降噪 —")
        self.btn_bar_anc.setObjectName("pillMini")
        self.btn_bar_anc.setCursor(Qt.PointingHandCursor)
        self.btn_bar_anc.setToolTip("点击循环切换降噪模式")
        self.btn_bar_anc.clicked.connect(self.cycle_anc)

        self.bar_batt = QLabel("")
        self.bar_batt.setObjectName("battmini")

        self.btn_bar_game = QPushButton("🎮")
        self.btn_bar_game.setObjectName("icon")
        self.btn_bar_game.setCheckable(True)
        self.btn_bar_game.setToolTip("游戏模式")
        self.btn_bar_game.setCursor(Qt.PointingHandCursor)
        self.btn_bar_game.toggled.connect(self.on_bar_game)

        self.btn_bar_find = QPushButton("🔊")
        self.btn_bar_find.setObjectName("icon")
        self.btn_bar_find.setToolTip("查找耳机")
        self.btn_bar_find.setCursor(Qt.PointingHandCursor)
        self.btn_bar_find.clicked.connect(self.on_find)

        self.btn_expand = QPushButton("▴")
        self.btn_expand.setObjectName("icon")
        self.btn_expand.setToolTip("展开完整面板")
        self.btn_expand.setCursor(Qt.PointingHandCursor)
        self.btn_expand.clicked.connect(self.toggle_compact)

        self.btn_bar_close = QPushButton("✕")
        self.btn_bar_close.setObjectName("icon")
        self.btn_bar_close.setCursor(Qt.PointingHandCursor)
        self.btn_bar_close.clicked.connect(self.close)

        row.addWidget(self.bar_dot)
        row.addWidget(self.bar_name)
        row.addWidget(self.btn_bar_anc, 1)
        row.addWidget(self.bar_batt)
        row.addWidget(self.btn_bar_game)
        row.addWidget(self.btn_bar_find)
        row.addWidget(self.btn_expand)
        row.addWidget(self.btn_bar_close)
        return w

    def toggle_compact(self):
        self.compact = not self.compact
        self.panel.setVisible(not self.compact)
        self.bar.setVisible(self.compact)
        if self.compact:
            self.setFixedWidth(470)     # 条状比面板稍宽，够放降噪+电量
            self.resize(470, 58)
            self._sync_bar()
        else:
            self.setFixedWidth(432)
            self._fit_panel()
        self._save_settings()

    def _fit_panel(self):
        self.panel.adjustSize()
        self.resize(self.width(), max(660, self.panel.sizeHint().height()))

    def cycle_anc(self):
        """条状形态：一个按钮轮流切换降噪档位。"""
        modes = [m["index"] for m in self.profile.anc]
        if not modes:
            return
        try:
            i = modes.index(self._cur_mode)
        except ValueError:
            i = -1
        nxt = modes[(i + 1) % len(modes)]
        self.on_anc(nxt)

    def _sync_bar(self):
        """把连接状态与当前档位同步到条状形态。"""
        if not hasattr(self, "btn_bar_anc"):
            return
        name = self.lbl_title.text() if self.lbl_state.text().startswith("已连接") else "未连接"
        # 右侧图标越少，名字留的空间越大
        extra_icons = int(self.bar_items["game"]) + int(self.bar_items["find"])
        avail = 150 - extra_icons * 28
        self.bar_name.setFixedWidth(avail)
        from PySide6.QtGui import QFontMetrics
        self.bar_name.setText(QFontMetrics(self.bar_name.font()).elidedText(
            name, Qt.ElideRight, avail - 4))
        self.bar_name.setToolTip(name)
        self.bar_dot.setProperty("on", name != "未连接")
        self.bar_dot.style().unpolish(self.bar_dot)
        self.bar_dot.style().polish(self.bar_dot)
        if self._cur_mode is not None:
            label = self.profile.anc_label(self._cur_mode)
            self.btn_bar_anc.setText(label)
            self.btn_bar_anc.setToolTip(f"降噪：{label}（点击切换下一档）")
        else:
            self.btn_bar_anc.setText("降噪 —")
            self.btn_bar_anc.setToolTip("点击切换降噪模式")
        self.btn_bar_anc.setVisible(self.bar_items["anc"])
        self.bar_batt.setVisible(self.bar_items["battery"])
        self.btn_bar_game.setVisible(self.bar_items["game"])
        self.btn_bar_find.setVisible(self.bar_items["find"] and self.profile.find)

    def on_bar_game(self, on: bool):
        if self.sw_game.isChecked() != on:
            self.sw_game.setChecked(on)

    # ---- 设置菜单 -----------------------------------------------------------
    def open_settings(self):
        m = QMenu(self)
        sub = m.addMenu("条状形态显示")
        for key, label in (("anc", "降噪切换"), ("battery", "电量"),
                           ("game", "游戏模式"), ("find", "查找耳机")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.bar_items[key])
            act.toggled.connect(lambda on, k=key: self.set_bar_item(k, on))
            sub.addAction(act)
        m.addSeparator()
        act_log = QAction("详细协议日志", self)
        act_log.setCheckable(True)
        act_log.setChecked(self.verbose)
        act_log.toggled.connect(self.set_verbose)
        m.addAction(act_log)
        m.addAction("打开日志文件夹", self.open_log_folder)
        act_dark = QAction("深色模式", self)
        act_dark.setCheckable(True)
        act_dark.setChecked(self.dark)
        act_dark.toggled.connect(lambda on: self.set_dark(on))
        m.addAction(act_dark)
        m.exec(self.btn_settings.mapToGlobal(
            self.btn_settings.rect().bottomLeft()))

    def set_bar_item(self, key: str, on: bool):
        self.bar_items[key] = on
        self._sync_bar()
        self._save_settings()

    def set_verbose(self, on: bool):
        self.verbose = on
        logs.set_verbose(on)
        logs.get("app").info("详细协议日志 %s", "开启" if on else "关闭")
        self._save_settings()

    def open_log_folder(self):
        path = logs.log_dir()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)          # noqa: S606 - Windows 打开资源管理器
        except OSError:
            QMessageBox.information(self, "日志目录", str(path))

    def set_dark(self, on: bool):
        if self.dark != on:
            self.dark = on
            self.apply_theme()
            self._save_settings()

    # ---- 持久化 -------------------------------------------------------------
    def _load_settings(self):
        st = self.settings
        self.dark = st.value("dark", True, type=bool)
        self.verbose = st.value("verbose", False, type=bool)
        for key in self.bar_items:
            self.bar_items[key] = st.value(f"bar/{key}",
                                           self.bar_items[key], type=bool)
        logs.setup(self.verbose)

    def _save_settings(self):
        st = self.settings
        st.setValue("dark", self.dark)
        st.setValue("verbose", self.verbose)
        st.setValue("compact", self.compact)
        for key, val in self.bar_items.items():
            st.setValue(f"bar/{key}", val)

    # ---- 主题 ---------------------------------------------------------------
    def apply_theme(self):
        self.p = palette(self.dark)
        self.setStyleSheet(stylesheet(self.p))
        self.root.setStyleSheet(f"QWidget#root {{ background: {self.p['card']};"
                                f" border: 1px solid {self.p['line']};"
                                f" border-radius: 18px; }}")
        for r in (self.ring_l, self.ring_r, self.ring_c):
            r.p = self.p
            r.update()
        for sw in (self.sw_game,):
            sw.p = self.p
            sw.update()
        self.btn_theme.setText("☀" if self.dark else "🌙")
        if hasattr(self, "bar_dot"):
            self.bar_dot.style().unpolish(self.bar_dot)
            self.bar_dot.style().polish(self.bar_dot)

    def toggle_pin(self):
        on = self.btn_pin.isChecked()
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()          # 改窗口标志后必须重新 show 才会生效
        self.setGeometry(geo)
        self.btn_pin.setText("📍" if on else "📌")

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()

    # ---- 无边框拖动 ----------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 64:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    # ---- 设备 ---------------------------------------------------------------
    def refresh_devices(self):
        self.combo_dev.clear()
        devices = btwin.list_bt_devices()
        self.combo_dev.addItem("选择耳机…", "")
        found = 0
        for d in devices:
            if looks_like_supported(d["name"]):
                tag = "  ·  已连接" if d["connected"] else ""
                self.combo_dev.addItem(f"{d['name']}{tag}", d["address"])
                found += 1
        if not found:
            self.combo_dev.addItem("未找到 OPPO 耳机，请先在系统蓝牙中配对", "")
        self.combo_dev.currentIndexChanged.connect(self._dev_changed)
        for i in range(self.combo_dev.count()):
            if "已连接" in self.combo_dev.itemText(i):
                self.combo_dev.setCurrentIndex(i)
                break
        self.btn_connect.setEnabled(bool(self.combo_dev.currentData()))

    def _dev_changed(self, *_):
        self.btn_connect.setEnabled(bool(self.combo_dev.currentData()))

    def toggle_connect(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop_flag.set()
            self.worker = None
            self.btn_connect.setText("连接")
            self.lbl_state.setText("未连接")
            return
        addr = self.combo_dev.currentData()
        if not addr:
            return
        self.btn_connect.setText("连接中…")
        self.btn_connect.setEnabled(False)
        self.lbl_state.setText("正在连接…")
        self._start_worker(addr)

    def _start_worker(self, addr):
        w = BudsWorker(addr)
        w.bridge.sig.connect(self.on_worker_event)
        self.worker = w
        w.start()

    # ---- 事件 ---------------------------------------------------------------
    def on_worker_event(self, topic: str, data):
        if topic == "connected":
            bt_name = self.combo_dev.currentText().split("  ·")[0]
            self.profile = profile_by_product_id(data or None, bt_name)
            if self.worker:
                self.worker.fast_anc = self.profile.fast_anc
            self.lbl_title.setText(self.profile.name)
            self.lbl_state.setText("已连接")
            self.lbl_pid.setText(f"产品 ID {data}" if data else "型号未知")
            self.btn_connect.setText("断开")
            self.btn_connect.setEnabled(True)
            self.build_anc()
            self.build_eq(self.eq_items_builtin())
            self.refresh_codec_info()
            self._sync_bar()
            self.adjust_height()
        elif topic == "disconnected":
            self.btn_connect.setText("连接")
            self.btn_connect.setEnabled(True)
            self.lbl_state.setText("已断开")
            self.lbl_title.setText(APP_NAME)
            self.clear_state()
            self._cur_mode = None
            self._sync_bar()
            QMessageBox.information(self, "连接断开", str(data))
        elif topic == "battery":
            self.apply_battery(data)
        elif topic == "anc_modes":
            if data:
                self.profile = self.profile.with_modes(data)
                self.build_anc()
                self._sync_bar()
        elif topic == "eq_catalog":
            if data:
                items = self.eq_items_merged(data)
                n_dev = sum(1 for i in items if i[2])
                self.build_eq(items, f"已读取 {n_dev} 个耳机内预设，内置预设同步可用")
            else:
                self.eq_hint.setText("设备未返回 EQ 目录，显示内置预设")
        elif topic == "feature_ack":
            if not data.get("ok"):
                if data["topic"] == "hq":
                    self._check(self.tier_buttons,
                                HQ_OFF if data["on"] else HQ_ON)
                else:
                    self.set_switch_silent(data["topic"], not data["on"])
                hint = ("高清音频被耳机拒绝：当前蓝牙链路不支持高清编码"
                        "（Windows 一般只协商 SBC/AAC，需 LHDC/LDAC 设备才能开）。"
                        if data["topic"] == "hq" else "耳机未接受该设置。")
                QMessageBox.warning(self, "设备拒绝", hint)
        elif topic == "event":
            self.apply_event(data)
        elif topic == "error":
            self.lbl_state.setText(str(data))

    def clear_state(self):
        for r in (self.ring_l, self.ring_r, self.ring_c):
            r.set_state(None)
        self.lbl_fw.setText("固件 —")

    # ---- 控件重建 -----------------------------------------------------------
    def build_anc(self):
        while self.anc_grid.count():
            it = self.anc_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.anc_buttons: dict[int, QPushButton] = {}
        for i, a in enumerate(self.profile.anc):
            btn = QPushButton(a["label"])
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=a["index"]: self.on_anc(idx))
            self.anc_buttons[a["index"]] = btn
            self.anc_grid.addWidget(btn, i // 4, i % 4)
        for c in range(4):
            self.anc_grid.setColumnStretch(c, 1)
        if self._cur_mode is not None:
            self._check(self.anc_buttons, self._cur_mode)
        self._sync_bar()

    def build_eq(self, items: list[tuple[int, str, bool]], hint: str = ""):
        """items = [(eqId, 名称, 是否来自耳机目录)]，按 id 升序铺成芯片。"""
        while self.eq_grid.count():
            it = self.eq_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.eq_buttons: dict[int, QPushButton] = {}
        seen: set[int] = set()
        for i, (eq_id, name, from_dev) in enumerate(sorted(items, key=lambda x: x[0])):
            if eq_id in seen:
                continue
            seen.add(eq_id)
            btn = QPushButton(("✎ " if from_dev else "") + name[:14])
            btn.setObjectName("pill")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("耳机内预设（含自定义）" if from_dev else "内置预设")
            btn.clicked.connect(lambda _=False, k=eq_id: self.on_eq(k))
            self.eq_buttons[eq_id] = btn
            self.eq_grid.addWidget(btn, i // 3, i % 3)
            for c in range(3):
                self.eq_grid.setColumnStretch(c, 1)
        if hint:
            self.eq_hint.setText(hint)

    def eq_items_builtin(self) -> list[tuple[int, str, bool]]:
        return [(e["index"], e["label"], False) for e in self.profile.eq]

    def eq_items_merged(self, catalog: list) -> list[tuple[int, str, bool]]:
        """内置预设 + 耳机目录合并；同一 id 以耳机目录为准。"""
        items: dict[int, tuple[int, str, bool]] = {}
        for e in self.profile.eq:
            items[e["index"]] = (e["index"], e["label"], False)
        for e in catalog:
            name = e["name"]
            if name.startswith("预设 "):
                name = EQ_FALLBACK_NAMES.get(e["id"], name)
            items[e["id"]] = (e["id"], name, True)
        return list(items.values())

    # ---- 交互 ---------------------------------------------------------------
    def on_anc(self, index: int):
        # 先乐观更新：点下去立刻有反馈，回读结果稍后覆盖
        self._cur_mode = index
        self._check(self.anc_buttons, index)
        self._sync_bar()
        if self.worker:
            self.worker.anc_set(index)

    def on_eq(self, eq_id: int):
        self._check(self.eq_buttons, eq_id)
        if self.worker:
            self.worker.eq_set(eq_id)

    def refresh_eq(self):
        if self.worker:
            self.worker.eq_refresh()

    @staticmethod
    def _check(buttons: dict, key: int):
        for k, b in buttons.items():
            b.setChecked(k == key)

    def on_tier(self, value: int):
        self._check(self.tier_buttons, value)
        self.feature_state["hq"] = value == HQ_ON
        if self.worker:
            self.worker.feature_set(FEATURE_HIGH_QUALITY, value,
                                    value == HQ_ON, "hq")

    def refresh_codec_info(self):
        fmt = audioinfo.read_output_format()
        self.lbl_codec.setText("当前链路  " + audioinfo.describe(fmt))

    def on_feature(self, key: str, on: bool):
        self.feature_state[key] = on
        if not self.worker:
            return
        if key == "game":
            self.worker.feature_set(FEATURE_GAME_MODE, 1 if on else 0, on, "game")
        elif key == "hq":
            # 高清音频/码率：设备用 2 表示开、0 表示关（发 1 会被拒）
            self.worker.feature_set(FEATURE_HIGH_QUALITY,
                                    HQ_ON if on else HQ_OFF, on, "hq")

    def set_switch_silent(self, key: str, on: bool):
        if key == "hq":
            # 码率档位是二选一按钮组：拒绝时回到相反档
            return
        sw = {"game": self.sw_game}.get(key)
        if sw:
            sw.blockSignals(True)
            sw.setChecked(on)
            sw.blockSignals(False)

    def on_find(self):
        if not self.worker:
            return
        self.ring_on = not self.ring_on
        self.worker.find_ring(self.ring_on)
        self.btn_find.setText("🔕   停止响铃" if self.ring_on else "🔊   查找耳机响铃")

    # ---- 状态渲染 -----------------------------------------------------------
    def apply_battery(self, batt: dict):
        for ring, key in ((self.ring_l, "left"), (self.ring_r, "right"),
                          (self.ring_c, "case")):
            v = batt.get(key)
            ring.set_state(v["level"] if v else None,
                           bool(v and v["charging"]))
        seq = []
        for key in ("left", "right", "case"):
            v = batt.get(key)
            if v:
                seq.append(f"{v['level']}%" + ("⚡" if v["charging"] else ""))
        self.bar_batt.setText("/".join(seq))
        self.bar_batt.setToolTip("左 · 右 · 充电盒")

    def apply_event(self, ev: dict):
        name = ev.get("event")
        if name == "battery" and ev.get("battery"):
            self.apply_battery(ev["battery"])
        elif name == "bud_status" and ev.get("status"):
            st = ev["status"]
            parts = []
            for side, cn in (("left", "左"), ("right", "右")):
                s = st.get(side)
                if not s:
                    continue
                parts.append(f"{cn}耳" + ("佩戴" if s.get("in_ear")
                                          else ("在盒" if s.get("in_case") else "在外")))
            if parts:
                self.lbl_state.setText("已连接 · " + "，".join(parts))
        elif name == "game_mode" and ev.get("game") is not None:
            self.feature_state["game"] = bool(ev["game"].get("on"))
            self.set_switch_silent("game", self.feature_state["game"])
        elif name == "noise_mode" and ev.get("index") is not None:
            self._cur_mode = ev["index"]
            self._check(self.anc_buttons, ev["index"])
            self._sync_bar()
        elif name == "eq_set" and ev.get("index") is not None:
            self._check(self.eq_buttons, ev["index"])
        elif name == "versions":
            recs = ev.get("records") or []
            by = {(r["component"], r["kind"]): r["value"] for r in recs}
            parts = [f"{cn} {by[(c, 2)]}" for c, cn in
                     ((1, "左"), (2, "右"), (3, "盒")) if (c, 2) in by]
            self.lbl_fw.setText("固件  " + " · ".join(parts) if parts else "固件 —")
        elif name == "connected_devices":
            devs = ev.get("devices") or []
            if devs:
                self.lbl_state.setText(
                    "已连接 · 双连 " + "、".join(d["name"] or d["address"]
                                                 for d in devs))

    # ---- 演示 ---------------------------------------------------------------
    def adjust_height(self):
        self.resize(self.width(), max(660, self.sizeHint().height()))

    def _load_demo(self):
        self.on_worker_event("connected", "06C010")
        self.btn_connect.setText("断开")
        self.btn_connect.setEnabled(True)
        self.apply_battery({"left": {"level": 88, "charging": False},
                            "right": {"level": 76, "charging": True},
                            "case": {"level": 42, "charging": False}})
        self._check(self.anc_buttons, 4)
        self._check(self.eq_buttons, 3)
        self.lbl_fw.setText("固件  左 118 · 右 118 · 盒 105")
        self.lbl_state.setText("已连接 · 演示数据")
        self._cur_mode = 4
        self._sync_bar()
        self.sw_game.blockSignals(True)
        self.sw_game.setChecked(True)
        self.sw_game.blockSignals(False)

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop_flag.set()
        super().closeEvent(e)


def main() -> int:
    if "--probe" in sys.argv:
        from probe import run_probe
        return run_probe()
    logs.setup("--verbose" in sys.argv)
    app = QApplication(sys.argv)
    win = App(demo="--demo" in sys.argv)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
