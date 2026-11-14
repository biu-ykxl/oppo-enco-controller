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

import sys
import threading
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget)

from oppo import audioinfo, btwin
from oppo.devices import GENERIC, looks_like_oppo, profile_by_product_id
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
            self._poll_once(full=True)
            caps = self.buds.notify_caps()
            events = [e for e in (1, 2, 3, 5, 0xF2) if not caps or e in caps]
            if events:
                self.buds.register_notify(events)
            while not self.stop_flag.is_set():
                for _ in range(50):
                    if self.stop_flag.is_set():
                        break
                    time.sleep(0.1)
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
                batt = b.battery()
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
                events = b.read_events(0.8, self.product_id)
            for ev in events:
                self._emit("event", ev)
        except TransportError as e:
            if e.code == "disconnected":
                raise
            self._emit("error", str(e))

    # ---- 命令 ---------------------------------------------------------------
    def anc_set(self, index: int):
        def _do(b):
            b.anc_set(index)
            time.sleep(0.35)
            got = b.anc_query()          # ack 不算数，回读为准
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

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(432)
        self.resize(432, 760)

        self.root = QWidget(self)
        self.root.setObjectName("root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.root)

        lay = QVBoxLayout(self.root)
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

        self.apply_theme()

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
            if looks_like_oppo(d["name"]):
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
            self.profile = profile_by_product_id(data or None)
            self.lbl_title.setText(self.profile.name)
            self.lbl_state.setText("已连接")
            self.lbl_pid.setText(f"产品 ID {data}" if data else "型号未知")
            self.btn_connect.setText("断开")
            self.btn_connect.setEnabled(True)
            self.build_anc()
            self.build_eq(self.eq_items_builtin())
            self.refresh_codec_info()
            self.adjust_height()
        elif topic == "disconnected":
            self.btn_connect.setText("连接")
            self.btn_connect.setEnabled(True)
            self.lbl_state.setText("已断开")
            self.lbl_title.setText(APP_NAME)
            self.clear_state()
            QMessageBox.information(self, "连接断开", str(data))
        elif topic == "battery":
            self.apply_battery(data)
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
        self._check(self.anc_buttons, index)
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
            self._check(self.anc_buttons, ev["index"])
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
    app = QApplication(sys.argv)
    win = App(demo="--demo" in sys.argv)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
