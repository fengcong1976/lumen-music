"""10 段均衡器面板：预设、逐段微调、自动记忆。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.player import Player

from .theme import MUTED, SUB

CUSTOM_LABEL = "自定义"


def _band_text(freq: int) -> str:
    if freq >= 1000:
        return f"{freq / 1000:g}K"
    return str(freq)


class EqualizerDialog(QDialog):
    RANGE = 12          # 每段增益范围 ±12 dB

    def __init__(self, player: Player, settings: QSettings, parent=None):
        super().__init__(parent)
        self.player = player
        self.settings = settings
        self._loading = True

        self.setObjectName("EqualizerDialog")
        self.setWindowTitle("音效 · 均衡器")
        self.setModal(False)
        self.setMinimumWidth(560)
        self._build()
        self._restore()
        self._loading = False

    # ---------------------------------------------------------------- 界面
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("音效")
        title.setObjectName("EqTitle")
        sub = QLabel("10 段均衡器 · 调整后立即生效")
        sub.setObjectName("EqSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        head.addLayout(title_box)
        head.addStretch(1)

        self.chk_enable = QCheckBox("启用均衡器")
        self.chk_enable.setCursor(Qt.CursorShape.PointingHandCursor)
        head.addWidget(self.chk_enable)
        root.addLayout(head)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.preset = QComboBox()
        self.preset.setMinimumWidth(170)
        self.preset.addItem(CUSTOM_LABEL)
        for index in range(self.player.eq_preset_count()):
            self.preset.addItem(self.player.eq_preset_label(index))
        self.btn_reset = QPushButton("重置")
        self.btn_reset.setObjectName("GhostButton")
        self.btn_reset.setFixedHeight(30)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        controls.addWidget(QLabel("预设"))
        controls.addWidget(self.preset, 1)
        controls.addWidget(self.btn_reset)
        root.addLayout(controls)

        bands = QHBoxLayout()
        bands.setSpacing(6)
        self.sliders: list[QSlider] = []
        self.value_labels: list[QLabel] = []
        for freq in self.player.eq_band_frequencies():
            column = QVBoxLayout()
            column.setSpacing(5)
            column.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            value = QLabel("0")
            value.setObjectName("EqValue")
            value.setFixedWidth(34)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)

            slider = QSlider(Qt.Orientation.Vertical)
            slider.setObjectName("EqSlider")
            slider.setRange(-self.RANGE, self.RANGE)
            slider.setValue(0)
            slider.setFixedSize(28, 132)
            slider.setCursor(Qt.CursorShape.PointingHandCursor)
            slider.setToolTip(f"{_band_text(freq)} Hz")

            name = QLabel(_band_text(freq))
            name.setObjectName("EqBand")
            name.setFixedWidth(34)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)

            column.addWidget(value, 0, Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(slider, 0, Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)

            self.sliders.append(slider)
            self.value_labels.append(value)
            bands.addLayout(column)
        root.addLayout(bands)

        footer = QHBoxLayout()
        hint = QLabel("预设立即应用；拖动任一滑块会自动切到「自定义」")
        hint.setObjectName("EqSub")
        hint.setStyleSheet(f"color: {MUTED};")
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("GhostButton")
        close_btn.setFixedSize(72, 30)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        footer.addWidget(hint)
        footer.addStretch(1)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        for index, slider in enumerate(self.sliders):
            slider.valueChanged.connect(
                lambda value, i=index: self._on_band_changed(i, value)
            )
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        self.chk_enable.toggled.connect(self._on_enabled_changed)
        self.btn_reset.clicked.connect(self._reset)

    # ---------------------------------------------------------------- 状态
    def _restore(self) -> None:
        enabled = self._as_bool(self.settings.value("equalizer/enabled", False), False)
        try:
            preset = int(self.settings.value("equalizer/preset", -1))
        except (TypeError, ValueError):
            preset = -1
        preset = preset if 0 <= preset < self.player.eq_preset_count() else -1

        bands = self._read_bands()
        self._loading = True
        for slider, gain in zip(self.sliders, bands):
            slider.setValue(max(-self.RANGE, min(self.RANGE, int(round(gain)))))
        self.preset.setCurrentIndex(preset + 1)
        self.chk_enable.setChecked(enabled)
        self._loading = False

        self._set_enabled(enabled)
        self._apply()
        self._update_labels()

    def _read_bands(self) -> list[float]:
        raw = self.settings.value("equalizer/bands", [])
        if isinstance(raw, str):
            raw = [part for part in raw.split(",") if part.strip()]
        if not isinstance(raw, (list, tuple)):
            raw = []
        gains: list[float] = []
        for value in raw:
            try:
                gains.append(float(value))
            except (TypeError, ValueError):
                gains.append(0.0)
        count = len(self.sliders)
        gains = gains[:count]
        gains.extend([0.0] * (count - len(gains)))
        return gains

    def _persist(self) -> None:
        self.settings.setValue("equalizer/enabled", self.chk_enable.isChecked())
        self.settings.setValue("equalizer/preset", self.preset.currentIndex() - 1)
        self.settings.setValue("equalizer/bands", [s.value() for s in self.sliders])

    def _apply(self) -> None:
        if not self.chk_enable.isChecked():
            self.player.disable_eq()
            return
        index = self.preset.currentIndex() - 1
        if index >= 0:
            self.player.apply_eq_preset(index)
        else:
            self.player.apply_eq_custom([float(s.value()) for s in self.sliders])

    # ---------------------------------------------------------------- 交互
    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.preset, self.btn_reset, *self.sliders):
            widget.setEnabled(enabled)
        for label in self.value_labels:
            label.setStyleSheet(f"color: {SUB if enabled else '#C3C8D6'};")

    def _on_enabled_changed(self, enabled: bool) -> None:
        self._set_enabled(enabled)
        if self._loading:
            return
        self._apply()
        self._persist()

    def _on_preset_changed(self, index: int) -> None:
        if self._loading:
            return
        if index > 0:
            gains = self.player.eq_preset_gains(index - 1)
            self._loading = True
            for slider, gain in zip(self.sliders, gains):
                slider.setValue(max(-self.RANGE, min(self.RANGE, int(round(gain)))))
            self._loading = False
        if not self.chk_enable.isChecked():
            # 选了预设还关着开关，用户显然是想听效果：顺手打开
            self.chk_enable.setChecked(True)
        self._apply()
        self._update_labels()
        self._persist()

    def _on_band_changed(self, _index: int, value: int) -> None:
        self.value_labels[_index].setText(f"{value:+d}" if value else "0")
        if self._loading:
            return
        if self.preset.currentIndex() != 0:
            self._loading = True
            self.preset.setCurrentIndex(0)
            self._loading = False
        if not self.chk_enable.isChecked():
            self.chk_enable.setChecked(True)
        self._apply()
        self._persist()

    def _reset(self) -> None:
        flat = -1
        for index in range(self.player.eq_preset_count()):
            if self.player.eq_preset_name(index).strip().lower() == "flat":
                flat = index
                break
        self._loading = True
        self.preset.setCurrentIndex(flat + 1 if flat >= 0 else 0)
        for slider in self.sliders:
            slider.setValue(0)
        self._loading = False
        self._apply()
        self._update_labels()
        self._persist()

    def _update_labels(self) -> None:
        for label, slider in zip(self.value_labels, self.sliders):
            value = slider.value()
            label.setText(f"{value:+d}" if value else "0")

    @staticmethod
    def _as_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
