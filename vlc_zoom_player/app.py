# -*- coding: utf-8 -*-
"""
VLC Zoom Player — ventana principal.

Reproductor basado en libVLC (el motor de VLC) con zoom por recuadro,
espejo, rotación y captura de lo que se ve en pantalla.
"""

from __future__ import annotations

import os
import sys
import time

from PyQt5.QtCore import Qt, QTimer, QRect, QPoint, QSettings, QStandardPaths, QUrl, pyqtSignal
from PyQt5.QtGui import QKeySequence, QDesktopServices, QRegion
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QFileDialog, QShortcut,
    QMessageBox, QStyle, QSizePolicy, QProgressDialog,
)

from . import __version__
from . import geometry as geo
from .vlc_loader import load_vlc
from .audio_export import AudioExporter
from .export_dialog import ExportAudioDialog

vlc, VLC_ERROR = load_vlc()

APP_TITLE = "VLC Zoom Player"
MIN_SELECTION_PX = 12        # tamaño mínimo del recuadro en pantalla
MIN_ZOOM_SRC_PX = 16         # tamaño mínimo de la zona ampliada en el video

VLC_EXTENSIONS = (
    "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m2ts *.mts *.mpg *.mpeg "
    "*.3gp *.vob *.ogv *.rm *.rmvb *.divx *.asf *.m4v "
    "*.mp3 *.flac *.aac *.wav *.ogg *.oga *.wma *.m4a *.opus *.aiff *.aif "
    "*.ape *.mka *.ac3 *.dts *.m3u *.m3u8 *.pls"
)

SHORTCUTS_HELP = """\
<table cellspacing=4>
<tr><td><b>z</b></td><td>Zoom: dibujar recuadro / quitar zoom</td></tr>
<tr><td><b>Shift+Z</b></td><td>Deshacer último nivel de zoom</td></tr>
<tr><td><b>s</b></td><td>Captura de lo que se ve (PNG)</td></tr>
<tr><td><b>h</b> / <b>v</b></td><td>Espejo horizontal / vertical</td></tr>
<tr><td><b>r</b> / <b>Shift+R</b></td><td>Rotar 90° horario / antihorario</td></tr>
<tr><td><b>Ctrl+0</b></td><td>Restablecer orientación</td></tr>
<tr><td><b>Espacio</b></td><td>Play / Pausa</td></tr>
<tr><td><b>← / →</b></td><td>Retroceder / avanzar 5 s</td></tr>
<tr><td><b>f</b> o doble clic</td><td>Pantalla completa</td></tr>
<tr><td><b>Esc</b></td><td>Cancelar selección / salir de pantalla completa</td></tr>
<tr><td><b>Ctrl+O</b></td><td>Abrir archivo</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Exportar audio</td></tr>
</table>"""


def ms_to_str(ms) -> str:
    if ms is None or ms < 0:
        return "--:--"
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def default_captures_dir() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    base = pictures or os.path.expanduser("~")
    return os.path.join(base, "VLC Zoom Player")


# ---------------------------------------------------------------------------
# Marco de selección: ventana flotante con forma de contorno. El video de VLC
# es una ventana nativa que tapa a los widgets hijos, y sin compositor (X11)
# una ventana translúcida se vería opaca; la máscara funciona en todos lados.
# ---------------------------------------------------------------------------
class SelectionOutline(QWidget):
    BORDER = 2

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("background:#7fd4ff;")

    def set_rect(self, rect: QRect):
        self.setGeometry(rect)
        r = QRect(0, 0, rect.width(), rect.height())
        b = self.BORDER
        inner = r.adjusted(b, b, -b, -b)
        region = QRegion(r)
        if inner.isValid():
            region = region.subtracted(QRegion(inner))
        self.setMask(region)


# ---------------------------------------------------------------------------
# Área de video: recibe la ventana de libVLC y gestiona la selección del zoom
# ---------------------------------------------------------------------------
class VideoFrame(QFrame):
    zoomRectSelected = pyqtSignal(QRect)     # en coordenadas del widget
    zoomSelectionCancelled = pyqtSignal()
    doubleClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: black;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._armed = False
        self._selecting = False
        self._origin = QPoint()
        self._rubber = SelectionOutline()

    @property
    def armed(self) -> bool:
        return self._armed

    def arm_selection(self, armed: bool):
        self._armed = armed
        self._selecting = False
        self._rubber.hide()
        self.setCursor(Qt.CrossCursor if armed else Qt.ArrowCursor)

    def cancel_selection(self):
        if self._armed or self._selecting:
            self.arm_selection(False)
            self.zoomSelectionCancelled.emit()

    def _clamped(self, pos: QPoint) -> QPoint:
        return QPoint(max(0, min(self.width() - 1, pos.x())),
                      max(0, min(self.height() - 1, pos.y())))

    def _update_rubber(self, pos: QPoint):
        local = QRect(self._origin, self._clamped(pos)).normalized()
        self._rubber.set_rect(QRect(self.mapToGlobal(local.topLeft()), local.size()))

    def mousePressEvent(self, e):
        if self._armed and e.button() == Qt.LeftButton:
            self._selecting = True
            self._origin = self._clamped(e.pos())
            self._update_rubber(e.pos())
            self._rubber.show()
            self._rubber.raise_()
        elif self._armed and e.button() == Qt.RightButton:
            self.cancel_selection()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._selecting:
            self._update_rubber(e.pos())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._selecting and e.button() == Qt.LeftButton:
            rect = QRect(self._origin, self._clamped(e.pos())).normalized()
            self.arm_selection(False)
            if rect.width() >= MIN_SELECTION_PX and rect.height() >= MIN_SELECTION_PX:
                self.zoomRectSelected.emit(rect)
            else:
                self.zoomSelectionCancelled.emit()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if not self._armed:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)

    def hideEvent(self, e):
        try:
            self._rubber.hide()
        except RuntimeError:   # ya destruido al cerrar la aplicación
            pass
        super().hideEvent(e)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 720)
        self.setAcceptDrops(True)
        self.settings = QSettings("VLCZoomPlayer", "VLCZoomPlayer")

        # --- estado ---------------------------------------------------------
        self.media_path = None
        self.transform = geo.IDENTITY     # espejo/rotación actual (matriz D4)
        self.zoom_stack = []              # zonas ampliadas, en orientación original
        self.instance = None
        self.player = None
        self._restore = None              # restauración tras recrear el reproductor
        self._slider_pressed = False
        self._crop_pending = False        # reaplicar zoom cuando haya video

        # --- widgets ---------------------------------------------------------
        self.video_frame = VideoFrame()
        self.video_frame.zoomRectSelected.connect(self._on_zoom_rect)
        self.video_frame.zoomSelectionCancelled.connect(self._on_zoom_cancelled)
        self.video_frame.doubleClicked.connect(self.toggle_fullscreen)

        def button(text, tip, checkable=False):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.NoFocus)   # Espacio no debe "pulsar" el botón
            return b

        self.btn_open = button("Abrir", "Abrir archivo (Ctrl+O)")
        self.btn_play = button("", "Play / Pausa (Espacio)")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_stop = button("", "Detener")
        self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_zoom = button("🔍 Zoom", "Dibujar recuadro para ampliar / quitar zoom (z)", True)
        self.btn_hflip = button("⇋", "Espejo horizontal (h)")
        self.btn_vflip = button("⇵", "Espejo vertical (v)")
        self.btn_rot_ccw = button("⟲", "Rotar 90° antihorario (Shift+R)")
        self.btn_rot_cw = button("⟳", "Rotar 90° horario (r)")
        self.btn_snap = button("📷 Captura", "Guardar lo que se ve como PNG (s)")
        self.btn_audio = button("🎵 Audio", "Exportar el audio a MP3, AAC, Ogg, Opus, WAV o FLAC (Ctrl+E)")

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.lbl_time = QLabel("00:00 / 00:00")
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(self.settings.value("volume", 80)))
        self.vol.setMaximumWidth(110)
        self.vol.setToolTip("Volumen")

        self.lbl_state = QLabel("")
        self.lbl_state.setStyleSheet("color:#7fd4ff; font-weight:bold;")

        controls = QHBoxLayout()
        controls.setSpacing(4)
        for w in (self.btn_open, self.btn_play, self.btn_stop, self.btn_zoom,
                  self.btn_hflip, self.btn_vflip, self.btn_rot_ccw,
                  self.btn_rot_cw, self.btn_snap, self.btn_audio):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.lbl_time)
        controls.addWidget(QLabel("🔊"))
        controls.addWidget(self.vol)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.video_frame, 1)
        lay.addLayout(controls)
        self.setCentralWidget(root)
        self.statusBar().addPermanentWidget(self.lbl_state)
        self.statusBar().showMessage("Listo — Ctrl+O o arrastra un archivo para reproducir")

        self._build_menu()

        # --- conexiones ------------------------------------------------------
        self.btn_open.clicked.connect(self.open_file)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_zoom.clicked.connect(self.toggle_zoom)
        self.btn_hflip.clicked.connect(lambda: self.apply_transform(geo.HFLIP))
        self.btn_vflip.clicked.connect(lambda: self.apply_transform(geo.VFLIP))
        self.btn_rot_cw.clicked.connect(lambda: self.apply_transform(geo.ROT_CW))
        self.btn_rot_ccw.clicked.connect(lambda: self.apply_transform(geo.ROT_CCW))
        self.btn_snap.clicked.connect(self.snapshot)
        self.btn_audio.clicked.connect(self.export_audio)
        self.slider.sliderPressed.connect(self._slider_press)
        self.slider.sliderReleased.connect(self._slider_release)
        self.slider.sliderMoved.connect(self._seek_slider)
        self.vol.valueChanged.connect(self._set_volume)

        shortcuts = {
            "z": self.toggle_zoom,
            "Shift+Z": self.zoom_out_one,
            "s": self.snapshot,
            "h": lambda: self.apply_transform(geo.HFLIP),
            "v": lambda: self.apply_transform(geo.VFLIP),
            "r": lambda: self.apply_transform(geo.ROT_CW),
            "Shift+R": lambda: self.apply_transform(geo.ROT_CCW),
            "Ctrl+0": self.reset_transform,
            "f": self.toggle_fullscreen,
            "Ctrl+O": self.open_file,
            "Ctrl+E": self.export_audio,
        }
        for seq, fn in shortcuts.items():
            QShortcut(QKeySequence(seq), self, activated=fn)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.seek_rel(-5000))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.seek_rel(5000))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape)

        self._build_player()

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

        self._apply_style()
        self._update_state_label()

    # ------------------------------------------------------------------ UI --
    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&Archivo")
        m_file.addAction("Abrir…\tCtrl+O", self.open_file)
        m_file.addAction("Exportar audio…\tCtrl+E", self.export_audio)
        m_file.addSeparator()
        m_file.addAction("Elegir carpeta de capturas…", self.choose_captures_dir)
        m_file.addAction("Abrir carpeta de capturas", self.open_captures_dir)
        m_file.addSeparator()
        m_file.addAction("Salir", self.close)

        m_video = mb.addMenu("&Video")
        m_video.addAction("Zoom por recuadro\tz", self.toggle_zoom)
        m_video.addAction("Deshacer nivel de zoom\tShift+Z", self.zoom_out_one)
        m_video.addSeparator()
        m_video.addAction("Espejo horizontal\th", lambda: self.apply_transform(geo.HFLIP))
        m_video.addAction("Espejo vertical\tv", lambda: self.apply_transform(geo.VFLIP))
        m_video.addAction("Rotar 90° horario\tr", lambda: self.apply_transform(geo.ROT_CW))
        m_video.addAction("Rotar 90° antihorario\tShift+R", lambda: self.apply_transform(geo.ROT_CCW))
        m_video.addAction("Restablecer orientación\tCtrl+0", self.reset_transform)
        m_video.addSeparator()
        m_video.addAction("Captura de lo que se ve\ts", self.snapshot)

        m_help = mb.addMenu("A&yuda")
        m_help.addAction("Atajos de teclado", lambda: QMessageBox.information(
            self, "Atajos de teclado", SHORTCUTS_HELP))
        m_help.addAction("Acerca de", lambda: QMessageBox.about(
            self, APP_TITLE,
            f"<b>{APP_TITLE}</b> {__version__}<br>"
            f"libVLC {vlc.libvlc_get_version().decode(errors='replace')}<br><br>"
            "Reproductor con zoom por recuadro, espejo, rotación y captura."))

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#1b1e23; color:#e8e8e8; }
            QMenuBar { background:#14161a; }
            QMenuBar::item:selected, QMenu::item:selected { background:#0b6fa4; }
            QMenu { background:#22262c; border:1px solid #3c414a; }
            QPushButton { background:#2b2f36; border:1px solid #3c414a;
                          border-radius:6px; padding:6px 10px; min-width:18px; }
            QPushButton:hover { background:#363b44; }
            QPushButton:checked { background:#0b6fa4; border-color:#0b6fa4; }
            QSlider::groove:horizontal { height:6px; background:#3c414a; border-radius:3px; }
            QSlider::handle:horizontal { width:14px; margin:-5px 0; border-radius:7px;
                                         background:#7fd4ff; }
            QSlider::sub-page:horizontal { background:#0b6fa4; border-radius:3px; }
            QLabel { padding:0 4px; }
            QStatusBar { background:#14161a; }
            QToolTip { background:#22262c; color:#e8e8e8; border:1px solid #3c414a; }
        """)

    def _update_state_label(self):
        parts = []
        if self.transform != geo.IDENTITY:
            parts.append(geo.describe(self.transform))
        if self.zoom_stack:
            parts.append(f"ZOOM ×{self._zoom_factor():.1f}")
        self.lbl_state.setText("  ·  ".join(parts))
        self.btn_zoom.setChecked(bool(self.zoom_stack) or self.video_frame.armed)

    # ------------------------------------------------------------ libVLC --
    def _build_player(self):
        """Crea instancia y reproductor. El filtro de espejo/rotación de VLC
        solo funciona como opción de instancia, así que cambiar la
        orientación implica recrearlos."""
        args = ["--no-video-title-show", "--no-snapshot-preview", "--quiet"]
        ttype = geo.vlc_transform_type(self.transform)
        if ttype:
            args += ["--video-filter=transform", f"--transform-type={ttype}"]
        self.instance = vlc.Instance(*args)
        if self.instance is None:
            raise RuntimeError("libVLC no pudo inicializarse")
        self.player = self.instance.media_player_new()
        # Sin esto, en Windows la ventana de VLC se queda con el mouse y el
        # teclado, y el recuadro de zoom / doble clic no llegan a Qt.
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        wid = int(self.video_frame.winId())
        if sys.platform.startswith("win"):
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)
        else:
            self.player.set_xwindow(wid)
        self.player.audio_set_volume(self.vol.value())

    def _release_player(self):
        if self.player is not None:
            self.player.stop()
            self.player.release()
        if self.instance is not None:
            self.instance.release()
        self.player = None
        self.instance = None

    def _has_video(self) -> bool:
        if self.player is None or self.media_path is None:
            return False
        if self.player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
            return False
        w, h = self._source_size()
        return bool(w and h)

    def _source_size(self):
        try:
            size = self.player.video_get_size(0)
        except Exception:  # noqa: BLE001 — sin pista de video
            return 0, 0
        return size if size else (0, 0)

    # --------------------------------------------------------------- media --
    def open_file(self):
        start = self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir archivo multimedia", start,
            f"Formatos VLC ({VLC_EXTENSIONS});;Todos los archivos (*.*)")
        if path:
            self.settings.setValue("last_dir", os.path.dirname(path))
            self.load(path)

    def load(self, path: str):
        if not path:
            return
        if not os.path.exists(path) and "://" not in path:
            self.statusBar().showMessage(f"No existe: {path}", 5000)
            return
        self.media_path = path
        self.zoom_stack.clear()
        self.video_frame.arm_selection(False)
        self._restore = None
        self.player.set_media(self.instance.media_new(path))
        self.player.play()
        self._crop_pending = True
        self.setWindowTitle(f"{APP_TITLE} — {os.path.basename(path)}")
        self.statusBar().showMessage(f"Reproduciendo: {path}", 5000)
        self._update_state_label()

    def toggle_play(self):
        if self.media_path is None:
            self.open_file()
            return
        st = self.player.get_state()
        if st == vlc.State.Playing:
            self.player.pause()
        elif st in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
            self.player.stop()
            self.player.play()
            self._crop_pending = True
        else:
            self.player.play()

    def stop(self):
        self.player.stop()

    def seek_rel(self, delta_ms: int):
        t, length = self.player.get_time(), self.player.get_length()
        if t >= 0 and length > 0:
            self.player.set_time(max(0, min(length - 100, t + delta_ms)))

    def _seek_slider(self, value):
        length = self.player.get_length()
        if length > 0:
            self.player.set_time(int(length * value / 1000))

    def _slider_press(self):
        self._slider_pressed = True

    def _slider_release(self):
        self._slider_pressed = False
        self._seek_slider(self.slider.value())

    def _set_volume(self, v):
        self.player.audio_set_volume(v)
        self.settings.setValue("volume", v)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
        else:
            self.menuBar().hide()
            self.showFullScreen()

    def _escape(self):
        if self.video_frame.armed:
            self.video_frame.cancel_selection()
        elif self.isFullScreen():
            self.toggle_fullscreen()

    # ---------------------------------------------------------------- poll --
    def _poll(self):
        if self.player is None:
            return
        st = self.player.get_state()
        playing = st in (vlc.State.Playing, vlc.State.Buffering, vlc.State.Opening)
        self.btn_play.setIcon(self.style().standardIcon(
            QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay))
        length, t = self.player.get_length(), self.player.get_time()
        self.lbl_time.setText(f"{ms_to_str(t)} / {ms_to_str(length)}")
        if length > 0 and not self._slider_pressed:
            self.slider.blockSignals(True)
            self.slider.setValue(1000 if st == vlc.State.Ended
                                 else int(1000 * max(0, t) / length))
            self.slider.blockSignals(False)
        # Al reiniciar la reproducción VLC crea una salida de video nueva y
        # olvida el recorte: lo reaplicamos en cuanto hay dimensiones.
        if self.zoom_stack:
            self._update_state_label()       # el aumento cambia al redimensionar
        if self._crop_pending and self._has_video():
            self._crop_pending = False
            self._schedule_crop()

    # ---------------------------------------------------------------- zoom --
    def _disp_size(self):
        """Tamaño de la imagen ya transformada (rotada/reflejada)."""
        w, h = self._source_size()
        return geo.transformed_size(w, h, self.transform)

    def _current_view(self) -> geo.Rect:
        """Zona visible, como fracción de la imagen transformada."""
        if not self.zoom_stack:
            return geo.FULL_VIEW
        return geo.map_rect(self.zoom_stack[-1], self.transform)

    def _zoom_factor(self) -> float:
        """Aumento real en pantalla respecto a la imagen completa."""
        dw, dh = self._disp_size()
        if not self.zoom_stack or not dw or not dh:
            return 1.0
        vw, vh = geo.view_pixel_size(self._current_view(), dw, dh)
        fw, fh = max(1, self.video_frame.width()), max(1, self.video_frame.height())
        return geo.fit(fw, fh, vw, vh)[2] / geo.fit(fw, fh, dw, dh)[2]

    def _apply_crop(self):
        if self.player is None:
            return
        src_w, src_h = self._source_size()
        geometry = None
        if self.zoom_stack and src_w and src_h:
            geometry = geo.crop_borders(self._current_view(), src_w, src_h)
        vlc.libvlc_video_set_crop_geometry(
            self.player, geometry.encode("ascii") if geometry else None)

    def _schedule_crop(self):
        """Aplica el recorte ahora y lo reafirma unos instantes después: tras
        un seek o al recrear el reproductor, VLC puede crear una salida de
        video nueva que ignora el recorte fijado antes."""
        self._apply_crop()
        for delay in (300, 800, 1600):
            QTimer.singleShot(delay, self._apply_crop)

    def toggle_zoom(self):
        if self.video_frame.armed:
            self.video_frame.cancel_selection()
        elif self.zoom_stack:
            self.reset_zoom()
            self.statusBar().showMessage("Zoom desactivado", 3000)
        elif not self._has_video():
            self.statusBar().showMessage("Primero reproduce un video para usar el zoom", 4000)
        else:
            self.video_frame.arm_selection(True)
            self.statusBar().showMessage(
                "Modo zoom: arrastra con el mouse el recuadro a ampliar "
                "(Esc, clic derecho o 'z' para cancelar)")
        self._update_state_label()

    def zoom_out_one(self):
        if self.zoom_stack:
            self.zoom_stack.pop()
            self._apply_crop()
            self._update_state_label()
            self.statusBar().showMessage("Nivel de zoom anterior", 3000)

    def reset_zoom(self):
        self.zoom_stack.clear()
        self.video_frame.arm_selection(False)
        self._apply_crop()
        self._update_state_label()

    def _on_zoom_cancelled(self):
        self._update_state_label()
        self.statusBar().showMessage("Selección de zoom cancelada", 3000)

    def _on_zoom_rect(self, rect: QRect):
        ok, msg = self.zoom_to_widget_rect(rect)
        self._update_state_label()
        if ok:
            self.statusBar().showMessage(
                f"Zoom ×{self._zoom_factor():.1f} — 'z' para quitarlo, "
                "Shift+Z para volver un nivel, o 'z' de nuevo tras quitarlo para otra zona", 6000)
        else:
            self.statusBar().showMessage(f"No se pudo aplicar el zoom: {msg}", 5000)

    def zoom_to_widget_rect(self, rect: QRect):
        """Amplía la zona `rect` (píxeles del área de video). Funciona también
        sobre una zona ya ampliada (zoom anidado)."""
        if not self._has_video():
            return False, "no hay video en reproducción"
        disp_w, disp_h = self._disp_size()
        view = self._current_view()
        vis_w, vis_h = geo.view_pixel_size(view, disp_w, disp_h)
        sub = geo.widget_rect_to_fraction(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            self.video_frame.width(), self.video_frame.height(), vis_w, vis_h)
        if sub is None:
            return False, "el recuadro está fuera de la imagen"
        new_view = geo.compose_view(view, sub)
        if new_view[2] * disp_w < MIN_ZOOM_SRC_PX or new_view[3] * disp_h < MIN_ZOOM_SRC_PX:
            return False, "zona demasiado pequeña"
        self.zoom_stack.append(geo.map_rect(new_view, geo.inverse(self.transform)))
        self._apply_crop()
        return True, ""

    # ---------------------------------------------------- espejo / rotación --
    def apply_transform(self, op: geo.Matrix):
        self.set_transform(geo.mul(op, self.transform))

    def reset_transform(self):
        self.set_transform(geo.IDENTITY)

    def set_transform(self, matrix: geo.Matrix):
        if matrix == self.transform:
            return
        self.video_frame.arm_selection(False)
        state = self.player.get_state() if self.player else None
        resume = None
        if self.media_path and state in (vlc.State.Playing, vlc.State.Paused,
                                         vlc.State.Buffering, vlc.State.Opening):
            resume = {"time": max(0, self.player.get_time()),
                      "paused": state == vlc.State.Paused, "tries": 100}
        self.transform = matrix
        self._release_player()
        self._build_player()
        if self.media_path:
            self.player.set_media(self.instance.media_new(self.media_path))
            self._crop_pending = True
        if resume:
            self.player.audio_set_mute(True)
            self.player.play()
            self._restore = resume
            QTimer.singleShot(40, self._restore_step)
        self._update_state_label()
        self.statusBar().showMessage(f"Orientación: {geo.describe(matrix)}", 3000)

    def _restore_step(self):
        r = self._restore
        if r is None or self.player is None:
            return
        if self._has_video() and self.player.get_length() > 0:
            self._restore = None
            self.player.set_time(r["time"])
            self._crop_pending = False
            self._schedule_crop()
            if r["paused"]:
                QTimer.singleShot(180, lambda: self._ensure_paused(10))
            QTimer.singleShot(200, lambda: self.player.audio_set_mute(False))
            return
        r["tries"] -= 1
        if r["tries"] > 0:
            QTimer.singleShot(40, self._restore_step)
        else:
            self._restore = None
            self.player.audio_set_mute(False)

    def _ensure_paused(self, tries):
        """Vuelve a pausar tras recrear el reproductor (VLC a veces ignora la
        primera pausa mientras termina el salto de posición)."""
        if self.player is None or self._restore is not None:
            return
        if self.player.get_state() != vlc.State.Paused:
            self.player.set_pause(1)
            if tries > 0:
                QTimer.singleShot(150, lambda: self._ensure_paused(tries - 1))

    # ------------------------------------------------------------ captura --
    def captures_dir(self) -> str:
        return self.settings.value("captures_dir", default_captures_dir())

    def choose_captures_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de capturas", self.captures_dir())
        if d:
            self.settings.setValue("captures_dir", d)
            self.statusBar().showMessage(f"Las capturas se guardarán en: {d}", 5000)

    def open_captures_dir(self):
        d = self.captures_dir()
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def snapshot(self):
        """Guarda un PNG de exactamente lo que se ve: zona ampliada, espejo y
        rotación incluidos, a la resolución real de esa zona del video."""
        if not self._has_video():
            self.statusBar().showMessage("No hay video en reproducción para capturar", 4000)
            return None
        folder = self.captures_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self.statusBar().showMessage(f"No se pudo crear la carpeta de capturas: {exc}", 6000)
            return None
        base = os.path.splitext(os.path.basename(self.media_path))[0][:60] or "captura"
        t = self.player.get_time()
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        path = os.path.join(folder, f"{base}_{ms_to_str(t).replace(':', '-')}_{stamp}.png")
        disp_w, disp_h = self._disp_size()
        # Hay que pasar el tamaño explícito: con 0×0 VLC usa las medidas del
        # video original y la imagen sale deformada al rotar o ampliar.
        w, h = geo.view_pixel_size(self._current_view(), disp_w, disp_h)
        ret = vlc.libvlc_video_take_snapshot(self.player, 0, path.encode("utf-8"), w, h)
        if ret != 0:
            self.statusBar().showMessage("Error al guardar la captura", 5000)
            return None
        self._confirm_snapshot(path, 25)
        return path

    def _confirm_snapshot(self, path, tries):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            self.statusBar().showMessage(f"📷 Captura guardada: {path}", 6000)
        elif tries > 0:
            QTimer.singleShot(120, lambda: self._confirm_snapshot(path, tries - 1))
        else:
            self.statusBar().showMessage("La captura tardó demasiado; inténtalo de nuevo", 5000)

    # ----------------------------------------------------------- drag&drop --
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile() or url.toString()
            if path:
                self.load(path)
                break

    # ------------------------------------------------------ exportar audio --
    def _audio_tracks(self):
        """Pistas de audio del medio actual: [(id, nombre)], id actual."""
        if self.player is None or self.media_path is None:
            return [], None
        try:
            desc = self.player.audio_get_track_description() or []
        except Exception:  # noqa: BLE001
            return [], None
        tracks = []
        for tid, name in desc:
            if tid < 0:
                continue                           # "Disable"
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            tracks.append((tid, name or f"Pista {tid}"))
        current = self.player.audio_get_track()
        return tracks, (current if current >= 0 else None)

    def export_audio(self):
        if getattr(self, "_exporter", None) is not None:
            self.statusBar().showMessage("Ya hay una exportación en curso", 4000)
            return
        tracks, current = self._audio_tracks()
        t = self.player.get_time() if self.player else 0
        length = self.player.get_length() if self.player and self.media_path else 0
        dlg = ExportAudioDialog(
            self, self.settings, self.media_path,
            f"Formatos VLC ({VLC_EXTENSIONS});;Todos los archivos (*.*)",
            tracks, current, max(0, t), max(0, length))
        if dlg.exec_() != dlg.Accepted:
            return
        job = dlg.job
        progress = QProgressDialog(f"Exportando audio de:\n{os.path.basename(job.source)}",
                                   "Cancelar", 0, 1000, self)
        progress.setWindowTitle("Exportar audio")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        exporter = AudioExporter(vlc, job, self)
        self._exporter = exporter

        def done():
            # QProgressDialog emite "canceled" al cerrarse: desconectar antes,
            # o se borraría el archivo recién exportado.
            try:
                progress.canceled.disconnect()
            except TypeError:
                pass
            progress.close()
            self._exporter = None
            exporter.deleteLater()

        def ok(path):
            done()
            self.statusBar().showMessage(f"🎵 Audio exportado: {path}", 8000)
            box = QMessageBox(QMessageBox.Information, "Exportar audio",
                              f"Audio exportado:\n{path}", parent=self)
            open_btn = box.addButton("Abrir carpeta", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Ok)
            box.exec_()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

        def fail(msg):
            done()
            QMessageBox.warning(self, "Exportar audio", msg)

        def cancel():
            exporter.cancel()
            done()
            self.statusBar().showMessage("Exportación cancelada", 4000)

        exporter.progress.connect(lambda f: progress.setValue(int(f * 1000)))
        exporter.finished.connect(ok)
        exporter.failed.connect(fail)
        progress.canceled.connect(cancel)
        exporter.start()

    def closeEvent(self, e):
        if getattr(self, "_exporter", None) is not None:
            self._exporter.cancel()
            self._exporter = None
        self.timer.stop()
        self._release_player()
        super().closeEvent(e)


# ---------------------------------------------------------------------------
def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    if vlc is None:
        QMessageBox.critical(None, APP_TITLE, VLC_ERROR)
        return 1
    try:
        win = MainWindow()
    except RuntimeError as exc:
        QMessageBox.critical(None, APP_TITLE, f"{exc}\n\n{VLC_ERROR or ''}")
        return 1
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        QTimer.singleShot(0, lambda: win.load(files[0]))
    return app.exec_()
