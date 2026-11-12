# -*- coding: utf-8 -*-
"""Diálogo "Exportar audio"."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PyQt5.QtCore import QTime
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton,
    QComboBox, QRadioButton, QTimeEdit, QDialogButtonBox, QFileDialog,
    QMessageBox, QLabel, QWidget, QButtonGroup,
)

from .audio_export import FORMATS, FORMATS_BY_KEY, ExportJob, unique_path

SAMPLERATES = [(0, "Original"), (44100, "44 100 Hz"), (48000, "48 000 Hz")]


def ms_to_qtime(ms: int) -> QTime:
    return QTime(0, 0).addMSecs(max(0, int(ms)))


def qtime_to_ms(t: QTime) -> int:
    return QTime(0, 0).msecsTo(t)


class ExportAudioDialog(QDialog):
    def __init__(self, parent, settings, source: Optional[str], media_filter: str,
                 tracks: List[Tuple[int, str]], current_track: Optional[int],
                 current_ms: int, duration_ms: int):
        super().__init__(parent)
        self.setWindowTitle("Exportar audio")
        self.setMinimumWidth(560)
        self.settings = settings
        self.media_filter = media_filter
        self._source_is_current = True
        self.current_ms = max(0, current_ms)
        self.duration_ms = max(0, duration_ms)

        # --- origen ---------------------------------------------------------
        self.ed_source = QLineEdit(source or "")
        self.ed_source.setReadOnly(True)
        btn_src = QPushButton("Elegir…")
        btn_src.clicked.connect(self._choose_source)
        row_src = self._row(self.ed_source, btn_src)

        self.cb_track = QComboBox()
        self._set_tracks(tracks, current_track)

        # --- formato --------------------------------------------------------
        self.cb_format = QComboBox()
        for f in FORMATS:
            self.cb_format.addItem(f.label, f.key)
        self.cb_quality = QComboBox()
        self.cb_channels = QComboBox()
        self.cb_channels.addItem("Estéreo", 2)
        self.cb_channels.addItem("Mono", 1)
        self.cb_rate = QComboBox()
        for rate, label in SAMPLERATES:
            self.cb_rate.addItem(label, rate)

        # --- rango ----------------------------------------------------------
        self.rb_all = QRadioButton("Todo el archivo")
        self.rb_part = QRadioButton("Fragmento")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_all)
        grp.addButton(self.rb_part)
        self.rb_all.setChecked(True)
        self.te_start = QTimeEdit()
        self.te_stop = QTimeEdit()
        for te in (self.te_start, self.te_stop):
            te.setDisplayFormat("HH:mm:ss.zzz")
        self.te_start.setTime(ms_to_qtime(self.current_ms))
        self.te_stop.setTime(ms_to_qtime(self.duration_ms or self.current_ms + 10000))
        b_start = QPushButton("Posición actual")
        b_stop = QPushButton("Posición actual")
        b_start.clicked.connect(lambda: self.te_start.setTime(ms_to_qtime(self.current_ms)))
        b_stop.clicked.connect(lambda: self.te_stop.setTime(ms_to_qtime(self.current_ms)))
        self._range_widgets = [self.te_start, self.te_stop, b_start, b_stop]
        range_box = QWidget()
        rl = QVBoxLayout(range_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.rb_all)
        rl.addWidget(self.rb_part)
        rl.addLayout(self._row(QLabel("Desde"), self.te_start, b_start))
        rl.addLayout(self._row(QLabel("Hasta"), self.te_stop, b_stop))
        self.rb_all.toggled.connect(self._update_range_enabled)

        # --- destino --------------------------------------------------------
        self.ed_dest = QLineEdit()
        btn_dest = QPushButton("…")
        btn_dest.clicked.connect(self._choose_dest)

        form = QFormLayout()
        form.addRow("Archivo de origen", row_src)
        form.addRow("Pista de audio", self.cb_track)
        form.addRow("Formato", self.cb_format)
        form.addRow("Calidad", self.cb_quality)
        form.addRow("Canales", self.cb_channels)
        form.addRow("Frecuencia", self.cb_rate)
        form.addRow("Rango", range_box)
        form.addRow("Guardar como", self._row(self.ed_dest, btn_dest))

        buttons = QDialogButtonBox()
        buttons.addButton("Exportar", QDialogButtonBox.AcceptRole)
        buttons.addButton("Cancelar", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

        # --- valores recordados --------------------------------------------
        fmt_key = self.settings.value("export/format", "mp3")
        idx = self.cb_format.findData(fmt_key)
        self.cb_format.setCurrentIndex(max(0, idx))
        self.cb_format.currentIndexChanged.connect(self._format_changed)
        self._format_changed()
        ch = self.cb_channels.findData(int(self.settings.value("export/channels", 2)))
        self.cb_channels.setCurrentIndex(max(0, ch))
        self._update_range_enabled()
        self._suggest_dest()

    # ------------------------------------------------------------ helpers --
    @staticmethod
    def _row(*widgets):
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        for i, w in enumerate(widgets):
            h.addWidget(w, 1 if i == 0 and isinstance(w, QLineEdit) else 0)
        return h

    def _set_tracks(self, tracks, current):
        self.cb_track.clear()
        if not tracks:
            self.cb_track.addItem("Predeterminada", None)
            return
        for tid, name in tracks:
            self.cb_track.addItem(name, tid)
        if current is not None:
            i = self.cb_track.findData(current)
            if i >= 0:
                self.cb_track.setCurrentIndex(i)

    def fmt(self):
        return FORMATS_BY_KEY[self.cb_format.currentData()]

    def _format_changed(self):
        f = self.fmt()
        self.cb_quality.clear()
        if f.bitrates:
            for b in f.bitrates:
                self.cb_quality.addItem(f"{b} kbps", b)
            saved = int(self.settings.value(f"export/bitrate_{f.key}", f.default_bitrate))
            i = self.cb_quality.findData(saved)
            self.cb_quality.setCurrentIndex(i if i >= 0 else self.cb_quality.findData(f.default_bitrate))
            self.cb_quality.setEnabled(True)
        else:
            self.cb_quality.addItem("Sin pérdida", 0)
            self.cb_quality.setEnabled(False)
        self.cb_rate.setEnabled(not f.fixed_samplerate)
        if f.fixed_samplerate:
            self.cb_rate.setCurrentIndex(self.cb_rate.findData(f.fixed_samplerate))
        dest = self.ed_dest.text()
        if dest:
            self.ed_dest.setText(os.path.splitext(dest)[0] + f.ext)

    def _update_range_enabled(self):
        for w in self._range_widgets:
            w.setEnabled(self.rb_part.isChecked())

    def _suggest_dest(self):
        src = self.ed_source.text()
        if not src:
            return
        folder = self.settings.value("export/dir", "") or os.path.dirname(src)
        base = os.path.splitext(os.path.basename(src))[0] or "audio"
        self.ed_dest.setText(unique_path(os.path.join(folder, base + self.fmt().ext)))

    def _choose_source(self):
        start = os.path.dirname(self.ed_source.text()) or self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Archivo de origen", start, self.media_filter)
        if path:
            self.ed_source.setText(path)
            self._source_is_current = False
            self.duration_ms = 0
            self.current_ms = 0
            self._set_tracks([], None)    # otra fuente: pista predeterminada
            self._suggest_dest()

    def _choose_dest(self):
        f = self.fmt()
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar audio como", self.ed_dest.text(), f"{f.label} (*{f.ext})")
        if path:
            if not path.lower().endswith(f.ext):
                path += f.ext
            self.ed_dest.setText(path)

    # -------------------------------------------------------------- aceptar --
    def _accept(self):
        src, dest = self.ed_source.text(), self.ed_dest.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Exportar audio", "Elige un archivo de origen válido.")
            return
        if not dest:
            QMessageBox.warning(self, "Exportar audio", "Indica dónde guardar el audio.")
            return
        if os.path.abspath(dest) == os.path.abspath(src):
            QMessageBox.warning(self, "Exportar audio", "El destino no puede ser el mismo archivo de origen.")
            return
        start = stop = 0
        if self.rb_part.isChecked():
            start, stop = qtime_to_ms(self.te_start.time()), qtime_to_ms(self.te_stop.time())
            if stop <= start:
                QMessageBox.warning(self, "Exportar audio", "El final del fragmento debe ser posterior al inicio.")
                return
            if self.duration_ms and start >= self.duration_ms:
                QMessageBox.warning(self, "Exportar audio", "El inicio está después del final del archivo.")
                return
            if self.duration_ms:
                stop = min(stop, self.duration_ms)
        if os.path.exists(dest):
            r = QMessageBox.question(self, "Exportar audio",
                                     f"Ya existe:\n{dest}\n\n¿Reemplazarlo?")
            if r != QMessageBox.Yes:
                return
        f = self.fmt()
        self.settings.setValue("export/format", f.key)
        if f.bitrates:
            self.settings.setValue(f"export/bitrate_{f.key}", self.cb_quality.currentData())
        self.settings.setValue("export/channels", self.cb_channels.currentData())
        self.settings.setValue("export/dir", os.path.dirname(os.path.abspath(dest)))
        self.job = ExportJob(
            source=src, dest=dest, fmt=f, bitrate=self.cb_quality.currentData() or 0,
            channels=self.cb_channels.currentData(), samplerate=self.cb_rate.currentData() or 0,
            track_id=self.cb_track.currentData(), start_ms=start, stop_ms=stop,
            duration_ms=self.duration_ms)
        self.accept()
