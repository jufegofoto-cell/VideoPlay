# -*- coding: utf-8 -*-
"""Lista de reproducción: panel lateral con agregar, quitar, reordenar,
repetir y guardar/abrir listas .m3u."""

from __future__ import annotations

import os
from typing import Iterable, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

PATH_ROLE = Qt.UserRole


def read_m3u(path: str) -> List[str]:
    """Rutas de una lista .m3u/.m3u8 (relativas a la carpeta de la lista)."""
    base = os.path.dirname(os.path.abspath(path))
    out = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "://" not in line and not os.path.isabs(line):
                line = os.path.normpath(os.path.join(base, line))
            out.append(line)
    return out


def write_m3u(path: str, items: Iterable[str]):
    with open(path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for p in items:
            f.write(f"#EXTINF:-1,{os.path.basename(p)}\n{p}\n")


class PlaylistPanel(QWidget):
    playRequested = pyqtSignal(int)          # índice a reproducir
    changed = pyqtSignal()

    def __init__(self, media_filter: str, parent=None):
        super().__init__(parent)
        self.media_filter = media_filter
        self._current: Optional[int] = None

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(lambda it: self.playRequested.emit(self.list.row(it)))
        self.list.model().rowsMoved.connect(self._rows_moved)

        def button(text, tip, slot):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            return b

        row1 = QHBoxLayout()
        row1.addWidget(button("＋", "Agregar archivos", self.add_dialog))
        row1.addWidget(button("－", "Quitar seleccionados (Supr)", self.remove_selected))
        row1.addWidget(button("↑", "Subir", lambda: self._move(-1)))
        row1.addWidget(button("↓", "Bajar", lambda: self._move(1)))
        row1.addWidget(button("Vaciar", "Quitar todos", self.clear_all))
        row2 = QHBoxLayout()
        row2.addWidget(button("Abrir lista…", "Abrir una lista .m3u", self.load_dialog))
        row2.addWidget(button("Guardar lista…", "Guardar como .m3u", self.save_dialog))
        self.chk_repeat = QCheckBox("Repetir")
        self.chk_repeat.setToolTip("Al terminar el último, volver al primero")
        row2.addWidget(self.chk_repeat)
        row2.addStretch(1)

        self.setStyleSheet("QPushButton { padding:4px 6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list, 1)
        lay.addLayout(row1)
        lay.addLayout(row2)

    # ------------------------------------------------------------ datos --
    def paths(self) -> List[str]:
        return [self.list.item(i).data(PATH_ROLE) for i in range(self.list.count())]

    def count(self) -> int:
        return self.list.count()

    def path_at(self, i: int) -> Optional[str]:
        return self.list.item(i).data(PATH_ROLE) if 0 <= i < self.list.count() else None

    def add_paths(self, paths: Iterable[str]) -> Optional[int]:
        """Agrega rutas al final. Devuelve el índice de la primera agregada."""
        first = None
        for p in paths:
            if not p:
                continue
            it = QListWidgetItem(os.path.basename(p.rstrip("/\\")) or p)
            it.setData(PATH_ROLE, p)
            it.setToolTip(p)
            self.list.addItem(it)
            if first is None:
                first = self.list.count() - 1
        if first is not None:
            self.changed.emit()
        return first

    def current_index(self) -> Optional[int]:
        return self._current

    def set_current(self, index: Optional[int]):
        self._current = index if index is not None and 0 <= index < self.count() else None
        for i in range(self.count()):
            it = self.list.item(i)
            mark = i == self._current
            f = it.font()
            f.setBold(mark)
            it.setFont(f)
            name = os.path.basename(it.data(PATH_ROLE).rstrip("/\\")) or it.data(PATH_ROLE)
            it.setText(("▶ " if mark else "") + name)
        if self._current is not None:
            self.list.scrollToItem(self.list.item(self._current))
        self.changed.emit()

    def next_index(self) -> Optional[int]:
        if not self.count():
            return None
        if self._current is None:
            return 0
        if self._current + 1 < self.count():
            return self._current + 1
        return 0 if self.chk_repeat.isChecked() else None

    def prev_index(self) -> Optional[int]:
        if not self.count():
            return None
        if self._current is None:
            return 0
        if self._current > 0:
            return self._current - 1
        return self.count() - 1 if self.chk_repeat.isChecked() else 0

    # ---------------------------------------------------------- acciones --
    def add_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Agregar a la lista", "", self.media_filter)
        self.add_paths(paths)

    def remove_selected(self):
        rows = sorted((self.list.row(it) for it in self.list.selectedItems()), reverse=True)
        cur = self._current
        for r in rows:
            self.list.takeItem(r)
            if cur is not None:
                if r == cur:
                    cur = None
                elif r < cur:
                    cur -= 1
        self.set_current(cur)

    def clear_all(self):
        self.list.clear()
        self.set_current(None)

    def _move(self, delta: int):
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.count():
            return
        cur_path = self.path_at(self._current) if self._current is not None else None
        it = self.list.takeItem(row)
        self.list.insertItem(new, it)
        self.list.setCurrentRow(new)
        self._restore_current(cur_path, row, new)

    def _rows_moved(self, *args):
        # tras arrastrar, recuperar cuál es el elemento en reproducción
        for i in range(self.count()):
            if self.list.item(i).text().startswith("▶ "):
                self.set_current(i)
                return

    def _restore_current(self, cur_path, old_row, new_row):
        if self._current is None:
            return
        if self._current == old_row:
            self.set_current(new_row)
        elif old_row < self._current <= new_row:
            self.set_current(self._current - 1)
        elif new_row <= self._current < old_row:
            self.set_current(self._current + 1)
        else:
            self.set_current(self._current)

    def load_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir lista", "", "Listas (*.m3u *.m3u8)")
        if not path:
            return
        try:
            items = read_m3u(path)
        except OSError as exc:
            QMessageBox.warning(self, "Lista", f"No se pudo leer la lista:\n{exc}")
            return
        first = self.add_paths(items)
        if first is not None and self._current is None:
            self.playRequested.emit(first)

    def save_dialog(self):
        if not self.count():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar lista", "lista.m3u", "Lista (*.m3u)")
        if not path:
            return
        if not path.lower().endswith((".m3u", ".m3u8")):
            path += ".m3u"
        try:
            write_m3u(path, self.paths())
        except OSError as exc:
            QMessageBox.warning(self, "Lista", f"No se pudo guardar la lista:\n{exc}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.remove_selected()
        else:
            super().keyPressEvent(e)

