"""界面组件与主题：仿 vivo 浮窗形态的圆角卡片风格。

自绘组件：电量环、拨动开关、胶囊按钮。全部支持深浅两套配色。
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QRectF, Qt, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QWidget)

DARK = {
    "bg": "#14161B", "card": "#1B1E25", "card2": "#22262F",
    "text": "#EDEFF3", "sub": "#8C93A1", "line": "#2A2F3A",
    "accent": "#4C8DFF", "accent2": "#7CC4FF",
    "ok": "#3DD68C", "warn": "#F5A524", "bad": "#F5556B",
    "ring_track": "#262B35", "hover": "#252A33",
    "toggle_off": "#2E3440",
}
LIGHT = {
    "bg": "#F2F4F7", "card": "#FFFFFF", "card2": "#F6F7FA",
    "text": "#171A1F", "sub": "#6B7280", "line": "#E4E7EC",
    "accent": "#2F6FED", "accent2": "#5A9BFF",
    "ok": "#12B76A", "warn": "#E39A00", "bad": "#E5484D",
    "ring_track": "#EAEDF2", "hover": "#EEF1F6",
    "toggle_off": "#C7CDD8",
}


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def stylesheet(p: dict) -> str:
    return f"""
    * {{ font-family: "Microsoft YaHei UI", "Segoe UI"; }}
    QWidget#root {{
        background: {p['card']};
        border: 1px solid {p['line']};
        border-radius: 18px;
    }}
    QLabel {{ color: {p['text']}; background: transparent; }}
    QLabel#title {{ font-size: 15px; font-weight: 600; }}
    QLabel#sub {{ color: {p['sub']}; font-size: 11px; }}
    QLabel#section {{ color: {p['sub']}; font-size: 11px; font-weight: 600;
                      letter-spacing: 1px; }}
    QLabel#battnum {{ font-size: 19px; font-weight: 600; }}
    QLabel#battlabel {{ color: {p['sub']}; font-size: 11px; }}
    QLabel#chip {{ color: {p['sub']}; font-size: 11px; }}
    QLabel#chipTitle {{ color: {p['text']}; font-size: 12px; }}

    QPushButton#icon {{
        background: transparent; border: none; color: {p['sub']};
        font-size: 15px; padding: 4px; border-radius: 8px;
    }}
    QPushButton#icon:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#icon:checked {{ background: {p['accent']}; color: #FFFFFF; }}

    QPushButton#pill {{
        background: {p['card2']}; border: 1px solid {p['line']};
        color: {p['text']}; border-radius: 13px; padding: 6px 8px;
        font-size: 12px;
    }}
    QPushButton#pill:hover {{ border-color: {p['accent']}; }}
    QPushButton#pill:checked {{
        background: {p['accent']}; border-color: {p['accent']}; color: #FFFFFF;
        font-weight: 600;
    }}

    QPushButton#primary {{
        background: {p['accent']}; color: #FFFFFF; border: none;
        border-radius: 11px; padding: 9px 18px; font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {p['accent2']}; }}
    QPushButton#primary:disabled {{ background: {p['line']}; color: {p['sub']}; }}

    QPushButton#ghost {{
        background: transparent; border: 1px solid {p['line']};
        color: {p['text']}; border-radius: 11px; padding: 9px 14px;
        font-size: 12px;
    }}
    QPushButton#ghost:hover {{ border-color: {p['accent']};
                               color: {p['accent']}; }}

    QComboBox {{
        background: {p['card2']}; border: 1px solid {p['line']};
        border-radius: 10px; padding: 6px 10px; color: {p['text']};
        font-size: 12px;
    }}
    QComboBox:hover {{ border-color: {p['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {p['card']}; color: {p['text']};
        border: 1px solid {p['line']}; border-radius: 8px;
        selection-background-color: {p['accent']}; outline: none;
        padding: 4px;
    }}

    QWidget#bar {{ background: transparent; }}
    QLabel#dot {{ color: {p['sub']}; font-size: 11px; }}
    QLabel#dot[on="true"] {{ color: {p['ok']}; }}
    QLabel#barname {{ color: {p['text']}; font-size: 12px; font-weight: 600; }}
    QLabel#battmini {{ color: {p['sub']}; font-size: 11px; }}
    QPushButton#pillMini {{
        background: {p['card2']}; border: 1px solid {p['line']};
        color: {p['text']}; border-radius: 10px; padding: 5px 10px;
        font-size: 11px; text-align: left;
    }}
    QPushButton#pillMini:hover {{ border-color: {p['accent']};
                                  color: {p['accent']}; }}

    QFrame#sep {{ background: {p['line']}; max-height: 1px; border: none; }}
    QMenu {{
        background: {p['card']}; color: {p['text']};
        border: 1px solid {p['line']}; border-radius: 10px; padding: 6px;
        font-size: 12px;
    }}
    QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {p['hover']}; }}
    QMenu::item:checked {{ color: {p['accent']}; font-weight: 600; }}
    QMenu::separator {{ height: 1px; background: {p['line']}; margin: 5px 8px; }}

    QStatusBar {{ background: transparent; color: {p['sub']}; font-size: 11px; }}
    QStatusBar::item {{ border: none; }}
    """


class BatteryRing(QWidget):
    """电量环：270° 圆弧 + 中央百分比 + 充电闪电。"""

    def __init__(self, label: str, p: dict, parent=None):
        super().__init__(parent)
        self.p = p
        self.label = label
        self.level: int | None = None
        self.charging = False
        self.setFixedSize(96, 104)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_state(self, level: int | None, charging: bool = False):
        self.level, self.charging = level, charging
        self.update()

    def _color(self) -> str:
        if self.level is None:
            return self.p["sub"]
        if self.level <= 20:
            return self.p["bad"]
        if self.level <= 45:
            return self.p["warn"]
        return self.p["ok"]

    def paintEvent(self, _e):
        w = self.width()
        ring_size = 78
        rect = QRectF((w - ring_size) / 2, 2, ring_size, ring_size)
        pt = QPainter(self)
        pt.setRenderHint(QPainter.Antialiasing)

        # 轨道
        pen = QPen(QColor(self.p["ring_track"]), 7)
        pen.setCapStyle(Qt.RoundCap)
        pt.setPen(pen)
        pt.drawArc(rect, 225 * 16, -270 * 16)

        # 进度
        if self.level is not None:
            pen.setColor(QColor(self._color()))
            pt.setPen(pen)
            span = -270 * 16 * max(0.02, min(self.level, 100) / 100)
            pt.drawArc(rect, 225 * 16, int(span))

        # 中央数字 + 小号百分号（整体居中）
        f_big = QFont("Microsoft YaHei UI")
        f_big.setPixelSize(21)
        f_big.setBold(True)
        f_small = QFont("Microsoft YaHei UI")
        f_small.setPixelSize(10)
        big = "—" if self.level is None else f"{self.level}"
        from PySide6.QtGui import QFontMetrics
        w_big = QFontMetrics(f_big).horizontalAdvance(big)
        w_small = QFontMetrics(f_small).horizontalAdvance("%") if self.level is not None else 0
        start_x = rect.center().x() - (w_big + w_small) / 2
        base_y = rect.center().y() + QFontMetrics(f_big).ascent() / 2 - 2
        pt.setFont(f_big)
        pt.setPen(QColor(self.p["text"]))
        pt.drawText(int(start_x), int(base_y), big)
        if self.level is not None:
            pt.setFont(f_small)
            pt.setPen(QColor(self.p["sub"]))
            pt.drawText(int(start_x + w_big + 1), int(base_y), "%")

        # 充电闪电（环外右上）
        if self.charging:
            f3 = QFont("Segoe UI Symbol")
            f3.setPixelSize(13)
            pt.setFont(f3)
            pt.setPen(QColor(self.p["warn"]))
            pt.drawText(QRectF(rect.right() - 14, rect.top() - 4, 20, 16),
                        Qt.AlignCenter, "⚡")

        # 名称
        f4 = QFont("Microsoft YaHei UI")
        f4.setPixelSize(11)
        pt.setFont(f4)
        pt.setPen(QColor(self.p["sub"]))
        pt.drawText(QRectF(0, ring_size + 4, w, 18), Qt.AlignCenter, self.label)
        pt.end()


class Toggle(QAbstractButton):
    """拨动开关：40×18 轨道 + 14px 滑块，130ms 缓动。

    用 QVariantAnimation 驱动，而不是 QPropertyAnimation —— 后者要求属性
    出现在 Qt 元对象里，Python 的 property() 不可见，动画会静默失效。
    """

    def __init__(self, p: dict, parent=None):
        super().__init__(parent)
        self.p = p
        self.setCheckable(True)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._offset = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.toggled.connect(self._animate)

    def _on_value(self, v):
        self._offset = float(v)
        self.update()

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(float(self._offset))
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool):
        super().setChecked(on)
        # 程序化设置（未显示或已屏蔽信号，不会触发 toggled）时直接落位，
        # 否则滑块会停在关闭一侧，状态显示错误。
        if not self.isVisible() or self.signalsBlocked():
            self._offset = 1.0 if on else 0.0
            self.update()

    def sizeHint(self):
        return self.size()

    def paintEvent(self, _e):
        pt = QPainter(self)
        pt.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 3, 40, 18)
        off_rgb = QColor(self.p.get("toggle_off", self.p["line"]))
        on_rgb = QColor(self.p["accent"])
        c = QColor(
            int(off_rgb.red() + (on_rgb.red() - off_rgb.red()) * self._offset),
            int(off_rgb.green() + (on_rgb.green() - off_rgb.green()) * self._offset),
            int(off_rgb.blue() + (on_rgb.blue() - off_rgb.blue()) * self._offset))
        pt.setPen(Qt.NoPen)
        pt.setBrush(c)
        pt.drawRoundedRect(r, 9, 9)

        knob_x = 3 + self._offset * 20
        pt.setBrush(QColor("#FFFFFF"))
        pt.drawEllipse(QRectF(knob_x, 5, 14, 14))
        pt.end()


class SectionTitle(QWidget):
    """小节标题 + 右侧可选小按钮。"""

    clicked = Signal()

    def __init__(self, text: str, p: dict, action: str | None = None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lab = QLabel(text)
        lab.setObjectName("section")
        lay.addWidget(lab)
        lay.addStretch(1)
        if action:
            btn = QPushButton(action)
            btn.setObjectName("icon")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self.clicked.emit)
            lay.addWidget(btn)
