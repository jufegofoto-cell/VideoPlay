# -*- coding: utf-8 -*-
"""Ventana "Ajustes": pestañas de imagen y de ecualizador. No es modal: los
cambios se aplican en vivo mientras el video se reproduce."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QCheckBox, QPushButton, QComboBox,
)

from . import effects as fx

SLIDER_STEPS = 1000


def _fmt_freq(hz: int) -> str:
    return f"{hz // 1000} k" if hz >= 1000 else str(hz)


class EffectsDialog(QDialog):
    adjustChanged = pyqtSignal()
    equalizerChanged = pyqtSignal()

    def __init__(self, parent, vlc_module, adjust: fx.ImageAdjust, eq: fx.Equalizer):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de imagen y audio")
        self.vlc = vlc_module
        self.adjust = adjust
        self.eq = eq
        self._updating = False

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_image_tab(), "🎨 Imagen")
        self.tabs.addTab(self._build_eq_tab(), "🎚 Ecualizador")
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addLayout(bottom)
        self.sync_from_state()

    # ----------------------------------------------------------- imagen --
    def _build_image_tab(self):
        w = QWidget()
        grid = QGridLayout(w)
        self.chk_adjust = QCheckBox("Activar ajustes de imagen")
        self.chk_adjust.toggled.connect(self._adjust_toggled)
        grid.addWidget(self.chk_adjust, 0, 0, 1, 3)
        self.adj_sliders, self.adj_labels = {}, {}
        for row, (name, (label, lo, hi, neutral, dec)) in enumerate(fx.ADJUST_PARAMS.items(), 1):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, SLIDER_STEPS)
            s.setMinimumWidth(320)
            s.valueChanged.connect(lambda v, n=name: self._adjust_slider(n, v))
            reset = QPushButton("↺")
            reset.setToolTip("Valor original")
            reset.setFixedWidth(34)
            reset.clicked.connect(lambda _=False, n=name: self._reset_one(n))
            val = QLabel()
            val.setMinimumWidth(48)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(s, row, 1)
            grid.addWidget(val, row, 2)
            grid.addWidget(reset, row, 3)
            self.adj_sliders[name], self.adj_labels[name] = s, val
        row = len(fx.ADJUST_PARAMS) + 1
        quick = QHBoxLayout()
        for text, values in (("Blanco y negro", {"saturation": 0.0}),
                             ("Más contraste", {"contrast": 1.5}),
                             ("Más brillo", {"brightness": 1.3})):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=values: self._quick(v))
            quick.addWidget(b)
        quick.addStretch(1)
        b_reset = QPushButton("Restablecer todo")
        b_reset.clicked.connect(self._reset_adjust)
        quick.addWidget(b_reset)
        grid.addLayout(quick, row, 0, 1, 4)
        note = QLabel("Los ajustes se ven en pantalla y también en las capturas.")
        note.setStyleSheet("color:#9aa3ad;")
        grid.addWidget(note, row + 1, 0, 1, 4)
        grid.setRowStretch(row + 2, 1)
        return w

    @staticmethod
    def _to_slider(name, value):
        _, lo, hi, _, _ = fx.ADJUST_PARAMS[name]
        return int(round((value - lo) / (hi - lo) * SLIDER_STEPS))

    @staticmethod
    def _from_slider(name, pos):
        _, lo, hi, _, dec = fx.ADJUST_PARAMS[name]
        return round(lo + (hi - lo) * pos / SLIDER_STEPS, dec)

    def _adjust_slider(self, name, pos):
        value = self._from_slider(name, pos)
        self.adj_labels[name].setText(self._fmt_adjust(name, value))
        if self._updating:
            return
        self.adjust.set(name, value)
        if not self.adjust.enabled:          # mover un control lo activa
            self.adjust.enabled = True
            self._set_checked(self.chk_adjust, True)
        self.adjustChanged.emit()

    @staticmethod
    def _fmt_adjust(name, value):
        dec = fx.ADJUST_PARAMS[name][4]
        return f"{value:+.0f}°" if name == "hue" else f"{value:.{dec}f}"

    def _adjust_toggled(self, on):
        if self._updating:
            return
        self.adjust.enabled = on
        self.adjustChanged.emit()

    def _reset_one(self, name):
        self.adjust.set(name, fx.ADJUST_PARAMS[name][3])
        self.sync_from_state()
        self.adjustChanged.emit()

    def _quick(self, values):
        for k, v in values.items():
            self.adjust.set(k, v)
        self.adjust.enabled = True
        self.sync_from_state()
        self.adjustChanged.emit()

    def _reset_adjust(self):
        self.adjust.reset()
        self.sync_from_state()
        self.adjustChanged.emit()

    # ------------------------------------------------------- ecualizador --
    def _build_eq_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.chk_eq = QCheckBox("Activar ecualizador")
        self.chk_eq.toggled.connect(self._eq_toggled)
        self.cb_preset = QComboBox()
        for i, name in enumerate(fx.preset_names(self.vlc)):
            self.cb_preset.addItem(name, i)
        self.cb_preset.addItem("Personalizado", fx.CUSTOM_PRESET)
        self.cb_preset.activated.connect(self._preset_chosen)
        b_flat = QPushButton("Restablecer")
        b_flat.clicked.connect(self._reset_eq)
        top.addWidget(self.chk_eq)
        top.addStretch(1)
        top.addWidget(QLabel("Preset"))
        top.addWidget(self.cb_preset)
        top.addWidget(b_flat)
        lay.addLayout(top)

        grid = QGridLayout()
        self.eq_sliders, self.eq_labels = [], []
        columns = [("Preamp", None)] + [(_fmt_freq(hz), i) for i, hz in enumerate(fx.EQ_BANDS_HZ)]
        for col, (title, idx) in enumerate(columns):
            s = QSlider(Qt.Vertical)
            s.setRange(int(fx.EQ_MIN_DB * 10), int(fx.EQ_MAX_DB * 10))
            s.setMinimumHeight(190)
            s.setTickPosition(QSlider.TicksBothSides)
            s.setTickInterval(50)
            val = QLabel("0.0")
            val.setAlignment(Qt.AlignCenter)
            lab = QLabel(title)
            lab.setAlignment(Qt.AlignCenter)
            if idx is None:
                lab.setStyleSheet("color:#7fd4ff;")
                s.valueChanged.connect(self._preamp_changed)
                self.preamp_slider, self.preamp_label = s, val
            else:
                s.valueChanged.connect(lambda v, i=idx: self._band_changed(i, v))
                self.eq_sliders.append(s)
                self.eq_labels.append(val)
            grid.addWidget(val, 0, col)
            grid.addWidget(s, 1, col, Qt.AlignHCenter)
            grid.addWidget(lab, 2, col)
            if idx is None:
                grid.setColumnMinimumWidth(col, 60)
        lay.addLayout(grid)
        hint = QLabel("Ganancia en dB (−20 a +20) por banda de frecuencia (Hz). "
                      "Afecta solo a la reproducción, no al audio exportado.")
        hint.setStyleSheet("color:#9aa3ad;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _band_changed(self, i, v):
        self.eq_labels[i].setText(f"{v / 10:+.1f}")
        if self._updating:
            return
        self.eq.set_band(i, v / 10)
        self._after_eq_edit()

    def _preamp_changed(self, v):
        self.preamp_label.setText(f"{v / 10:+.1f}")
        if self._updating:
            return
        self.eq.set_preamp(v / 10)
        self._after_eq_edit()

    def _after_eq_edit(self):
        if not self.eq.enabled:
            self.eq.enabled = True
            self._set_checked(self.chk_eq, True)
        self._select_preset_item()
        self.equalizerChanged.emit()

    def _eq_toggled(self, on):
        if self._updating:
            return
        self.eq.enabled = on
        self.equalizerChanged.emit()

    def _preset_chosen(self, index):
        preset = self.cb_preset.itemData(index)
        if preset == fx.CUSTOM_PRESET:
            return
        fx.load_preset(self.vlc, self.eq, preset)
        self.eq.enabled = True
        self.sync_from_state()
        self.equalizerChanged.emit()

    def _reset_eq(self):
        self.eq.reset()
        self.sync_from_state()
        self.equalizerChanged.emit()

    # ------------------------------------------------------------ comunes --
    def _set_checked(self, chk, on):
        self._updating = True
        chk.setChecked(on)
        self._updating = False

    def _select_preset_item(self):
        i = self.cb_preset.findData(self.eq.preset)
        self.cb_preset.setCurrentIndex(i if i >= 0 else self.cb_preset.count() - 1)

    def sync_from_state(self):
        """Refleja en los controles el estado actual (sin emitir señales)."""
        self._updating = True
        try:
            self.chk_adjust.setChecked(self.adjust.enabled)
            for name, s in self.adj_sliders.items():
                s.setValue(self._to_slider(name, self.adjust.values[name]))
                self.adj_labels[name].setText(self._fmt_adjust(name, self.adjust.values[name]))
            self.chk_eq.setChecked(self.eq.enabled)
            self.preamp_slider.setValue(int(round(self.eq.preamp * 10)))
            self.preamp_label.setText(f"{self.eq.preamp:+.1f}")
            for i, s in enumerate(self.eq_sliders):
                s.setValue(int(round(self.eq.bands[i] * 10)))
                self.eq_labels[i].setText(f"{self.eq.bands[i]:+.1f}")
            self._select_preset_item()
        finally:
            self._updating = False

    def show_tab(self, index: int):
        self.tabs.setCurrentIndex(index)
        self.show()
        self.raise_()
        self.activateWindow()
