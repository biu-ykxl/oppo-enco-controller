"""界面组件与主题：仿 vivo 浮窗形态的圆角卡片风格。

自绘组件：电量环、拨动开关、胶囊按钮。全部支持深浅两套配色。
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QRect, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

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

    QPushButton#chevron {{
        background: transparent; border: none; color: {p['sub']};
        font-size: 11px; padding: 0;
    }}
    QPushButton#chevron:hover {{ color: {p['text']}; }}
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
    QScrollArea#scroll, QWidget#panelBody {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['line']}; border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['sub']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
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


class Collapsible(QWidget):
    """可收起分区：标题行（箭头 + 标题 + 可选右侧按钮）+ 内容体。"""

    toggled = Signal(bool)

    def __init__(self, title: str, p: dict, action: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.p = p
        self.collapsed = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.btn_toggle = QPushButton("▾")
        self.btn_toggle.setObjectName("chevron")
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setFixedWidth(18)
        self.btn_toggle.clicked.connect(self.toggle)
        self.lbl = QLabel(title)
        self.lbl.setObjectName("section")
        self.lbl.setCursor(Qt.PointingHandCursor)
        head.addWidget(self.btn_toggle)
        head.addWidget(self.lbl)
        head.addStretch(1)
        self.btn_action = None
        if action:
            self.btn_action = QPushButton(action)
            self.btn_action.setObjectName("icon")
            self.btn_action.setCursor(Qt.PointingHandCursor)
            head.addWidget(self.btn_action)
        box.addLayout(head)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(6)
        box.addWidget(self.body)

        # 点标题也能收起
        self.lbl.mousePressEvent = lambda _e: self.toggle()

    def add(self, w):
        self.body_lay.addWidget(w)

    def toggle(self):
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, on: bool, notify: bool = True):
        self.collapsed = on
        self.body.setVisible(not on)
        self.btn_toggle.setText("▸" if on else "▾")
        if notify:
            self.toggled.emit(on)


class MarqueeLabel(QWidget):
    """跑马灯文字：文字超出宽度时左右循环滚动，否则居中显示。"""

    def __init__(self, p: dict, parent=None):
        super().__init__(parent)
        self.p = p
        self._text = ""
        self._offset = 0.0
        self._gap = 28.0            # 循环时两段文字之间的空隙
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps
        self._timer.timeout.connect(self._step)
        self.setMinimumWidth(60)
        self.setFixedHeight(20)

    def setText(self, text: str):
        self._text = text or ""
        self._offset = 0.0
        self._restart()

    def text(self) -> str:
        return self._text

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._restart()

    def _restart(self):
        need = self._text_width() + self._gap > self.width() + 2
        if need and not self._timer.isActive():
            self._timer.start()
        elif not need and self._timer.isActive():
            self._timer.stop()
            self._offset = 0.0
        self.update()

    def _text_width(self) -> float:
        from PySide6.QtGui import QFontMetrics
        return QFontMetrics(self.font()).horizontalAdvance(self._text)

    def _step(self):
        tw = self._text_width()
        if tw <= 0:
            return
        self._offset += 0.9
        if self._offset > tw + self._gap:
            self._offset = 0.0
        self.update()

    def set_palette(self, p: dict):
        self.p = p
        self.update()

    def paintEvent(self, _e):
        pt = QPainter(self)
        pt.setRenderHint(QPainter.Antialiasing)
        pt.setClipRect(self.rect())      # 文字不能画到按钮上
        pt.setPen(QColor(self.p["text"]))
        f = self.font()
        f.setPixelSize(12)
        f.setBold(True)
        pt.setFont(f)
        fm = pt.fontMetrics()
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        tw = fm.horizontalAdvance(self._text)
        if tw + self._gap <= self.width() + 2:
            pt.drawText(QRectF(0, 0, self.width(), self.height()),
                        Qt.AlignLeft | Qt.AlignVCenter, self._text)
        else:
            x = -self._offset
            pt.drawText(QRectF(x, 0, tw + 4, self.height()),
                        Qt.AlignLeft | Qt.AlignVCenter, self._text)
            # 第二段，形成无缝循环
            pt.drawText(QRectF(x + tw + self._gap, 0, tw + 4, self.height()),
                        Qt.AlignLeft | Qt.AlignVCenter, self._text)
        pt.end()


class FlowLayout(QLayout):
    """流式布局：按可用宽度自动换行（参考 Qt 官方 FlowLayout 示例）。

    用于降噪胶囊与音效芯片，窗口变窄时自动折行，不会把窗口最小宽度撑大。
    """

    def __init__(self, parent=None, margin: int = 0,
                 hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def clear(self):
        while self._items:
            item = self._items.pop()
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            if x + w > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class ElidedLabel(QWidget):
    """单行文字，宽度不够时自动省略；min size 很小，不会撑大布局。"""

    def __init__(self, text: str, p: dict, *, pixel: int = 15,
                 bold: bool = True, max_width: int = 210, parent=None):
        super().__init__(parent)
        self.p = p
        self._text = text
        self._pixel = pixel
        self._bold = bold
        self._max = max_width
        self.setFixedHeight(pixel + 6)
        self.setMinimumWidth(56)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def setText(self, text: str):
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def set_palette(self, p: dict):
        self.p = p
        self.update()

    def _font(self):
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(self._pixel)
        f.setBold(self._bold)
        return f

    def sizeHint(self):
        from PySide6.QtGui import QFontMetrics
        w = QFontMetrics(self._font()).horizontalAdvance(self._text) + 4
        return QSize(min(w, self._max), self.height())

    def minimumSizeHint(self):
        return QSize(56, self.height())

    def paintEvent(self, _e):
        from PySide6.QtGui import QFontMetrics
        pt = QPainter(self)
        pt.setRenderHint(QPainter.Antialiasing)
        pt.setClipRect(self.rect())
        f = self._font()
        pt.setFont(f)
        pt.setPen(QColor(self.p["text"]))
        fm = QFontMetrics(f)
        txt = fm.elidedText(self._text, Qt.ElideRight, self.width() - 2)
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        pt.drawText(QRectF(0, 0, self.width(), self.height()),
                    Qt.AlignLeft | Qt.AlignVCenter, txt)
        pt.end()
