# -*- coding: utf-8 -*-
"""
VLC Zoom Player — ventana principal.

Reproductor basado en libVLC (el motor de VLC) con zoom por recuadro,
espejo, rotación, captura de lo que se ve, lista de reproducción, ajustes
de imagen, ecualizador y exportación de audio.

VLC decodifica el audio y el video; la imagen la dibuja la app
(ver ``video_view.py``), así el zoom no depende del recorte de VLC.
"""

from __future__ import annotations

import os
import sys
import time

from PyQt5.QtCore import Qt, QTimer, QRect, QRectF, QSettings, QStandardPaths, QUrl
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QKeySequence, QDesktopServices, QIcon, QPixmap, QPainter, QColor, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QShortcut, QMessageBox, QStyle,
    QProgressDialog, QDockWidget, QFrame,
)

from . import __version__
from . import geometry as geo
from . import effects as fx
from .vlc_loader import load_vlc
from .audio_export import AudioExporter
from .export_dialog import ExportAudioDialog
from .effects_dialog import EffectsDialog
from .playlist import PlaylistPanel, read_m3u
from .video_view import FrameSource, VideoView

vlc, VLC_ERROR = load_vlc()

APP_TITLE = "VLC Zoom Player"
MIN_ZOOM_SRC_PX = 16         # tamaño mínimo de la zona ampliada en el video
SEEK_STEP_MS = 10000         # botones ⏪ / ⏩

VLC_EXTENSIONS = (
    "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m2ts *.mts *.mpg *.mpeg "
    "*.3gp *.vob *.ogv *.rm *.rmvb *.divx *.asf *.m4v "
    "*.mp3 *.flac *.aac *.wav *.ogg *.oga *.wma *.m4a *.opus *.aiff *.aif "
    "*.ape *.mka *.ac3 *.dts"
)
MEDIA_FILTER = f"Formatos VLC ({VLC_EXTENSIONS});;Todos los archivos (*.*)"
PLAYLIST_EXT = (".m3u", ".m3u8")

SHORTCUTS_HELP = """\
<table cellspacing=4>
<tr><td><b>z</b></td><td>Zoom: dibujar recuadro (o quitar el zoom)</td></tr>
<tr><td><b>a</b></td><td>Zoom All: volver al video completo</td></tr>
<tr><td><b>Shift+Z</b></td><td>Deshacer último nivel de zoom</td></tr>
<tr><td><b>s</b></td><td>Captura de lo que se ve (PNG)</td></tr>
<tr><td><b>h</b> / <b>v</b></td><td>Espejo horizontal / vertical</td></tr>
<tr><td><b>r</b> / <b>Shift+R</b></td><td>Rotar 90° horario / antihorario</td></tr>
<tr><td><b>Ctrl+0</b></td><td>Restablecer orientación</td></tr>
<tr><td><b>Espacio</b></td><td>Play / Pausa</td></tr>
<tr><td><b>← / →</b></td><td>Retroceder / avanzar 5 s</td></tr>
<tr><td><b>Shift+← / Shift+→</b></td><td>Retroceder / avanzar 10 s</td></tr>
<tr><td><b>p</b> / <b>n</b></td><td>Anterior / siguiente de la lista</td></tr>
<tr><td><b>Ctrl+L</b></td><td>Mostrar / ocultar la lista de reproducción</td></tr>
<tr><td><b>f</b> o doble clic</td><td>Pantalla completa</td></tr>
<tr><td><b>Esc</b></td><td>Cancelar selección / salir de pantalla completa</td></tr>
<tr><td><b>Ctrl+O</b></td><td>Abrir archivos</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Exportar audio</td></tr>
<tr><td><b>Ctrl+I</b></td><td>Ajustes de imagen (brillo, contraste, color…)</td></tr>
<tr><td><b>Ctrl+Shift+E</b></td><td>Ecualizador de audio</td></tr>
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


def expand_paths(paths):
    """Archivos sueltos y listas .m3u -> lista de rutas a reproducir."""
    out = []
    for p in paths:
        if p.lower().endswith(PLAYLIST_EXT) and os.path.isfile(p):
            try:
                out.extend(read_m3u(p))
            except OSError:
                pass
        elif p:
            out.append(p)
    return out


def media_icon(kind: str, color: str = "#e8e8e8", size: int = 20) -> QIcon:
    """Íconos de reproducción dibujados en color claro (los del sistema son
    oscuros y casi no se ven sobre botones oscuros)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    s = float(size)

    def tri(x0, x1, y0=0.2, y1=0.8):         # triángulo hacia la derecha si x1 > x0
        p.drawPolygon(QPolygonF([QPointF(x0 * s, y0 * s), QPointF(x1 * s, 0.5 * s),
                                 QPointF(x0 * s, y1 * s)]))

    def bar(x, w=0.12, y0=0.2, y1=0.8):
        p.drawRect(QRectF(x * s, y0 * s, w * s, (y1 - y0) * s))

    if kind == "play":
        tri(0.28, 0.82)
    elif kind == "pause":
        bar(0.28, 0.16)
        bar(0.56, 0.16)
    elif kind == "stop":
        p.drawRect(QRectF(0.25 * s, 0.25 * s, 0.5 * s, 0.5 * s))
    elif kind == "fwd":
        tri(0.12, 0.5)
        tri(0.5, 0.88)
    elif kind == "back":
        tri(0.5, 0.12)
        tri(0.88, 0.5)
    elif kind == "next":
        tri(0.2, 0.68)
        bar(0.68)
    elif kind == "prev":
        tri(0.8, 0.32)
        bar(0.2)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1240, 760)
        self.setAcceptDrops(True)
        self.settings = QSettings("VLCZoomPlayer", "VLCZoomPlayer")

        # --- estado ---------------------------------------------------------
        self.media_path = None
        self.transform = geo.IDENTITY     # espejo/rotación actual (matriz D4)
        self.zoom_stack = []              # zonas ampliadas, en orientación original
        self._slider_pressed = False
        self._vout_pending = False        # aplicar ajustes cuando llegue el video
        self._last_state = None
        self.adjust = fx.ImageAdjust.from_json(self.settings.value("fx/adjust", ""))
        self.eq = fx.Equalizer.from_json(self.settings.value("fx/equalizer", ""))
        self._adjust_was_active = False
        self._fx_dialog = None
        self._exporter = None

        # --- libVLC ----------------------------------------------------------
        self.instance = vlc.Instance("--no-video-title-show", "--no-snapshot-preview",
                                     "--no-osd", "--quiet")
        if self.instance is None:
            raise RuntimeError("libVLC no pudo inicializarse")
        self.player = self.instance.media_player_new()
        self.frames = FrameSource(vlc)
        self.frames.attach(self.player)

        # --- área de video ---------------------------------------------------
        self.video = VideoView(self.frames)
        self.video.zoomRectSelected.connect(self._on_zoom_rect)
        self.video.zoomSelectionCancelled.connect(self._on_zoom_cancelled)
        self.video.doubleClicked.connect(self.toggle_fullscreen)

        # --- lista de reproducción --------------------------------------------
        self.playlist = PlaylistPanel(MEDIA_FILTER)
        self.playlist.playRequested.connect(self.play_index)
        self.playlist.changed.connect(self._save_playlist)
        self.dock = QDockWidget("Lista de reproducción", self)
        self.dock.setObjectName("playlist")
        self.dock.setWidget(self.playlist)
        self.dock.setMinimumWidth(240)
        self.dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(lambda v: self.btn_list.setChecked(v))

        # --- controles -------------------------------------------------------
        def button(text, tip, checkable=False, icon=None):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.NoFocus)   # Espacio no debe "pulsar" el botón
            if isinstance(icon, str):
                b.setIcon(media_icon(icon))
            elif icon is not None:
                b.setIcon(self.style().standardIcon(icon))
            return b



        self.btn_open = button("", "Abrir archivos (Ctrl+O)", icon=QStyle.SP_DialogOpenButton)
        self.btn_prev = button("", "Anterior de la lista (p)", icon="prev")
        self.btn_back = button("", "Retroceder 10 s (Shift+←)", icon="back")
        self.btn_play = button("", "Play / Pausa (Espacio)", icon="play")
        self.btn_fwd = button("", "Adelantar 10 s (Shift+→)", icon="fwd")
        self.btn_next = button("", "Siguiente de la lista (n)", icon="next")
        self.btn_stop = button("", "Detener", icon="stop")
        self.btn_zoom = button("🔍 Zoom", "Dibujar recuadro para ampliar (z)", True)
        self.btn_zoom_all = button("⤢ Zoom All", "Volver al video completo (a)")
        self.btn_hflip = button("⇋", "Espejo horizontal (h)")
        self.btn_vflip = button("⇵", "Espejo vertical (v)")
        self.btn_rot_ccw = button("⟲", "Rotar 90° antihorario (Shift+R)")
        self.btn_rot_cw = button("⟳", "Rotar 90° horario (r)")
        self.btn_snap = button("📷", "Captura: guardar lo que se ve como PNG (s)")
        self.btn_audio = button("🎵", "Exportar audio a MP3, AAC, Ogg, Opus, WAV o FLAC (Ctrl+E)")
        self.btn_fx = button("🎛", "Ajustes de imagen (brillo, contraste, color…) y ecualizador (Ctrl+I)")
        self.btn_list = button("☰ Lista", "Mostrar / ocultar la lista de reproducción (Ctrl+L)", True)

        self._fixed_buttons = (
            self.btn_open, self.btn_prev, self.btn_back, self.btn_play, self.btn_fwd,
            self.btn_next, self.btn_stop, self.btn_zoom, self.btn_zoom_all, self.btn_hflip,
            self.btn_vflip, self.btn_rot_ccw, self.btn_rot_cw, self.btn_snap, self.btn_audio,
            self.btn_fx, self.btn_list)

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

        def sep():
            f = QFrame()
            f.setFrameShape(QFrame.VLine)
            f.setStyleSheet("color:#3c414a;")
            return f

        row_time = QHBoxLayout()
        row_time.addWidget(self.slider, 1)
        row_time.addWidget(self.lbl_time)

        row_btn = QHBoxLayout()
        row_btn.setSpacing(4)
        groups = [
            (self.btn_open,),
            (self.btn_prev, self.btn_back, self.btn_play, self.btn_fwd, self.btn_next, self.btn_stop),
            (self.btn_zoom, self.btn_zoom_all),
            (self.btn_hflip, self.btn_vflip, self.btn_rot_ccw, self.btn_rot_cw),
            (self.btn_snap, self.btn_audio, self.btn_fx, self.btn_list),
        ]
        for gi, group in enumerate(groups):
            if gi:
                row_btn.addWidget(sep())
            for w in group:
                row_btn.addWidget(w)
        row_btn.addStretch(1)
        row_btn.addWidget(QLabel("🔊"))
        row_btn.addWidget(self.vol)

        self.controls = QWidget()
        cl = QVBoxLayout(self.controls)
        cl.setContentsMargins(0, 4, 0, 0)
        cl.setSpacing(4)
        cl.addLayout(row_time)
        cl.addLayout(row_btn)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.video, 1)
        lay.addWidget(self.controls)
        self.setCentralWidget(root)
        self.statusBar().addPermanentWidget(self.lbl_state)
        self.statusBar().showMessage("Listo — Ctrl+O o arrastra archivos para reproducir")

        self._build_menu()

        # --- conexiones ------------------------------------------------------
        self.btn_open.clicked.connect(self.open_files)
        self.btn_prev.clicked.connect(self.play_prev)
        self.btn_back.clicked.connect(lambda: self.seek_rel(-SEEK_STEP_MS))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_fwd.clicked.connect(lambda: self.seek_rel(SEEK_STEP_MS))
        self.btn_next.clicked.connect(self.play_next)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_zoom.clicked.connect(self.toggle_zoom)
        self.btn_zoom_all.clicked.connect(self.zoom_all)
        self.btn_hflip.clicked.connect(lambda: self.apply_transform(geo.HFLIP))
        self.btn_vflip.clicked.connect(lambda: self.apply_transform(geo.VFLIP))
        self.btn_rot_cw.clicked.connect(lambda: self.apply_transform(geo.ROT_CW))
        self.btn_rot_ccw.clicked.connect(lambda: self.apply_transform(geo.ROT_CCW))
        self.btn_snap.clicked.connect(self.snapshot)
        self.btn_audio.clicked.connect(self.export_audio)
        self.btn_fx.clicked.connect(lambda: self.open_effects(0))
        self.btn_list.clicked.connect(self.toggle_playlist)
        self.slider.sliderPressed.connect(self._slider_press)
        self.slider.sliderReleased.connect(self._slider_release)
        self.slider.sliderMoved.connect(self._seek_slider)
        self.vol.valueChanged.connect(self._set_volume)

        shortcuts = {
            "z": self.toggle_zoom,
            "a": self.zoom_all,
            "Shift+Z": self.zoom_out_one,
            "s": self.snapshot,
            "h": lambda: self.apply_transform(geo.HFLIP),
            "v": lambda: self.apply_transform(geo.VFLIP),
            "r": lambda: self.apply_transform(geo.ROT_CW),
            "Shift+R": lambda: self.apply_transform(geo.ROT_CCW),
            "Ctrl+0": self.reset_transform,
            "f": self.toggle_fullscreen,
            "n": self.play_next,
            "p": self.play_prev,
            "Ctrl+L": self.toggle_playlist,
            "Ctrl+O": self.open_files,
            "Ctrl+E": self.export_audio,
            "Ctrl+I": lambda: self.open_effects(0),
            "Ctrl+Shift+E": lambda: self.open_effects(1),
            "Shift+Left": lambda: self.seek_rel(-SEEK_STEP_MS),
            "Shift+Right": lambda: self.seek_rel(SEEK_STEP_MS),
        }
        for seq, fn in shortcuts.items():
            QShortcut(QKeySequence(seq), self, activated=fn)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.seek_rel(-5000))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.seek_rel(5000))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape)

        self.player.audio_set_volume(self.vol.value())
        fx.apply_equalizer(vlc, self.player, self.eq)

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

        self._apply_style()
        # que los botones no se encojan (el texto se cortaría con la lista
        # abierta); se mide después de aplicar el estilo, que agrega relleno
        for b in self._fixed_buttons:
            b.ensurePolished()
            b.setMinimumWidth(b.sizeHint().width())
        self._restore_playlist()
        self.resizeDocks([self.dock], [270], Qt.Horizontal)
        self._update_state_label()

    # ------------------------------------------------------------------ UI --
    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&Archivo")
        m_file.addAction("Abrir…\tCtrl+O", self.open_files)
        m_file.addAction("Exportar audio…\tCtrl+E", self.export_audio)
        m_file.addSeparator()
        m_file.addAction("Elegir carpeta de capturas…", self.choose_captures_dir)
        m_file.addAction("Abrir carpeta de capturas", self.open_captures_dir)
        m_file.addSeparator()
        m_file.addAction("Salir", self.close)

        m_play = mb.addMenu("&Reproducción")
        m_play.addAction("Play / Pausa\tEspacio", self.toggle_play)
        m_play.addAction("Detener", self.stop)
        m_play.addAction("Retroceder 10 s\tShift+←", lambda: self.seek_rel(-SEEK_STEP_MS))
        m_play.addAction("Adelantar 10 s\tShift+→", lambda: self.seek_rel(SEEK_STEP_MS))
        m_play.addSeparator()
        m_play.addAction("Anterior\tp", self.play_prev)
        m_play.addAction("Siguiente\tn", self.play_next)
        m_play.addAction("Lista de reproducción\tCtrl+L", self.toggle_playlist)

        m_video = mb.addMenu("&Video")
        m_video.addAction("Zoom por recuadro\tz", self.toggle_zoom)
        m_video.addAction("Zoom All (video completo)\ta", self.zoom_all)
        m_video.addAction("Deshacer nivel de zoom\tShift+Z", self.zoom_out_one)
        m_video.addSeparator()
        m_video.addAction("Espejo horizontal\th", lambda: self.apply_transform(geo.HFLIP))
        m_video.addAction("Espejo vertical\tv", lambda: self.apply_transform(geo.VFLIP))
        m_video.addAction("Rotar 90° horario\tr", lambda: self.apply_transform(geo.ROT_CW))
        m_video.addAction("Rotar 90° antihorario\tShift+R", lambda: self.apply_transform(geo.ROT_CCW))
        m_video.addAction("Restablecer orientación\tCtrl+0", self.reset_transform)
        m_video.addSeparator()
        m_video.addAction("Captura de lo que se ve\ts", self.snapshot)
        m_video.addSeparator()
        m_video.addAction("Ajustes de imagen…\tCtrl+I", lambda: self.open_effects(0))

        m_audio = mb.addMenu("A&udio")
        m_audio.addAction("Ecualizador…\tCtrl+Shift+E", lambda: self.open_effects(1))
        m_audio.addAction("Exportar audio…\tCtrl+E", self.export_audio)

        m_help = mb.addMenu("A&yuda")
        m_help.addAction("Atajos de teclado", lambda: QMessageBox.information(
            self, "Atajos de teclado", SHORTCUTS_HELP))
        m_help.addAction("Acerca de", lambda: QMessageBox.about(
            self, APP_TITLE,
            f"<b>{APP_TITLE}</b> {__version__}<br>"
            f"libVLC {vlc.libvlc_get_version().decode(errors='replace')}<br><br>"
            "Reproductor con zoom por recuadro, espejo, rotación, captura, "
            "lista de reproducción, ajustes de imagen, ecualizador y "
            "exportación de audio."))

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
            QDockWidget::title { background:#14161a; padding:6px; }
            QListWidget { background:#15171b; alternate-background-color:#1b1e23;
                          border:1px solid #3c414a; }
            QListWidget::item:selected { background:#0b6fa4; }
            QRubberBand { border:2px solid #7fd4ff; background:rgba(127,212,255,40); }
        """)

    def _update_state_label(self):
        parts = []
        if self.transform != geo.IDENTITY:
            parts.append(geo.describe(self.transform))
        if self.zoom_stack:
            parts.append(f"ZOOM ×{self._zoom_factor():.1f}")
        if self.adjust.active:
            parts.append("Imagen ajustada")
        if self.eq.enabled:
            parts.append("EQ")
        self.lbl_state.setText("  ·  ".join(parts))
        self.btn_zoom.setChecked(self.video.armed)
        self.btn_zoom_all.setEnabled(bool(self.zoom_stack))

    # ---------------------------------------------------------- reproductor --
    def _has_video(self) -> bool:
        if self.media_path is None:
            return False
        if self.player.get_state() not in (vlc.State.Playing, vlc.State.Paused):
            return False
        w, h = self.frames.frame_size()
        return bool(w and h)

    # --------------------------------------------------------------- media --
    def open_files(self):
        start = self.settings.value("last_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir archivos (se agregan a la lista)", start,
            f"Formatos VLC ({VLC_EXTENSIONS} *.m3u *.m3u8);;Todos los archivos (*.*)")
        if paths:
            self.settings.setValue("last_dir", os.path.dirname(paths[0]))
            self.add_and_play(paths)

    def add_and_play(self, paths):
        first = self.playlist.add_paths(expand_paths(paths))
        if first is not None:
            self.play_index(first)

    def play_index(self, index: int):
        path = self.playlist.path_at(index)
        if path is None:
            return
        self.playlist.set_current(index)
        self.load(path)

    def play_next(self):
        i = self.playlist.next_index()
        if i is not None:
            self.play_index(i)
        else:
            self.statusBar().showMessage("No hay siguiente en la lista", 3000)

    def play_prev(self):
        # como en los reproductores habituales: si ya avanzó, vuelve al inicio
        if self.media_path and self.player.get_time() > 3000:
            self.player.set_time(0)
            return
        i = self.playlist.prev_index()
        if i is not None:
            self.play_index(i)

    def load(self, path: str):
        if not path:
            return
        if not os.path.exists(path) and "://" not in path:
            self.statusBar().showMessage(f"No existe: {path}", 5000)
            return
        self.media_path = path
        self.zoom_stack.clear()
        self.video.arm_selection(False)
        self.video.set_view(geo.FULL_VIEW)
        self.frames.clear()
        self.player.set_media(self.instance.media_new(path))
        self.player.play()
        self._vout_pending = True
        self.setWindowTitle(f"{APP_TITLE} — {os.path.basename(path)}")
        self.statusBar().showMessage(f"Reproduciendo: {path}", 5000)
        self._update_state_label()

    def toggle_play(self):
        if self.media_path is None:
            if self.playlist.count():
                self.play_index(self.playlist.current_index() or 0)
            else:
                self.open_files()
            return
        st = self.player.get_state()
        if st == vlc.State.Playing:
            self.player.pause()
        elif st in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
            self.player.stop()
            self.player.play()
            self._vout_pending = True
        else:
            self.player.play()

    def stop(self):
        self.player.stop()
        self.frames.clear()

    def seek_rel(self, delta_ms: int):
        t, length = self.player.get_time(), self.player.get_length()
        if t >= 0 and length > 0:
            self.player.set_time(max(0, min(length - 200, t + delta_ms)))

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
            self.statusBar().show()
            if self._dock_was_visible:
                self.dock.show()
        else:
            self._dock_was_visible = self.dock.isVisible()
            self.menuBar().hide()
            self.statusBar().hide()
            self.dock.hide()
            self.showFullScreen()

    def _escape(self):
        if self.video.armed:
            self.video.cancel_selection()
        elif self.isFullScreen():
            self.toggle_fullscreen()

    def toggle_playlist(self):
        self.dock.setVisible(not self.dock.isVisible())

    def _save_playlist(self):
        self.settings.setValue("playlist/paths", self.playlist.paths())
        cur = self.playlist.current_index()
        self.settings.setValue("playlist/current", -1 if cur is None else cur)

    def _restore_playlist(self):
        paths = self.settings.value("playlist/paths", []) or []
        if isinstance(paths, str):
            paths = [paths]
        self.playlist.add_paths(paths)
        self.dock.setVisible(self.settings.value("playlist/visible", "false") in ("true", True))
        self._dock_was_visible = self.dock.isVisible()

    # ---------------------------------------------------------------- poll --
    def _poll(self):
        st = self.player.get_state()
        playing = st in (vlc.State.Playing, vlc.State.Buffering, vlc.State.Opening)
        if playing != getattr(self, "_icon_playing", None):
            self._icon_playing = playing
            self.btn_play.setIcon(media_icon("pause" if playing else "play"))
        length, t = self.player.get_length(), self.player.get_time()
        self.lbl_time.setText(f"{ms_to_str(t)} / {ms_to_str(length)}")
        if length > 0 and not self._slider_pressed:
            self.slider.blockSignals(True)
            self.slider.setValue(1000 if st == vlc.State.Ended
                                 else int(1000 * max(0, t) / length))
            self.slider.blockSignals(False)
        if self.zoom_stack:
            self._update_state_label()       # el aumento cambia al redimensionar
        if self._vout_pending and self._has_video():
            self._vout_pending = False
            self._on_new_video()
        # al terminar un archivo, pasar al siguiente de la lista
        if st == vlc.State.Ended and self._last_state != vlc.State.Ended:
            nxt = self.playlist.next_index()
            if nxt is not None:
                QTimer.singleShot(0, lambda: self.play_index(nxt))
        self._last_state = st

    def _on_new_video(self):
        """Primera imagen de un archivo: aplicar los ajustes de imagen."""
        self._apply_video_effects(force=True)
        QTimer.singleShot(600, lambda: self._apply_video_effects(force=True))
        self._update_state_label()

    # ---------------------------------------------------------------- zoom --
    def _disp_size(self):
        """Tamaño de la imagen ya transformada (rotada/reflejada)."""
        return self.video.display_size()

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
        fw, fh = max(1, self.video.width()), max(1, self.video.height())
        return geo.fit(fw, fh, vw, vh)[2] / geo.fit(fw, fh, dw, dh)[2]

    def _apply_view(self):
        self.video.set_view(self._current_view())
        self._update_state_label()

    def toggle_zoom(self):
        if self.video.armed:
            self.video.cancel_selection()
        elif not self._has_video():
            self.statusBar().showMessage("Primero reproduce un video para usar el zoom", 4000)
        else:
            self.video.arm_selection(True)
            self.statusBar().showMessage(
                "Modo zoom: arrastra el recuadro a ampliar; mantiene la proporción del video "
                "(Esc o clic derecho para cancelar)")
        self._update_state_label()

    def zoom_all(self):
        """Zoom All: volver a ver el video completo."""
        self.video.arm_selection(False)
        if self.zoom_stack:
            self.zoom_stack.clear()
            self._apply_view()
            self.statusBar().showMessage("Zoom All: video completo", 3000)
        self._update_state_label()

    def reset_zoom(self):
        self.zoom_all()

    def zoom_out_one(self):
        if self.zoom_stack:
            self.zoom_stack.pop()
            self._apply_view()
            self.statusBar().showMessage("Nivel de zoom anterior", 3000)

    def _on_zoom_cancelled(self):
        self._update_state_label()
        self.statusBar().showMessage("Selección de zoom cancelada", 3000)

    def _on_zoom_rect(self, rect: QRect):
        ok, msg = self.zoom_to_widget_rect(rect)
        self._update_state_label()
        if ok:
            self.statusBar().showMessage(
                f"Zoom ×{self._zoom_factor():.1f} — 'z' para ampliar más, "
                "Shift+Z para volver un nivel, 'a' (Zoom All) para el video completo", 6000)
        else:
            self.statusBar().showMessage(f"No se pudo aplicar el zoom: {msg}", 5000)

    def zoom_to_widget_rect(self, rect: QRect):
        """Amplía la zona `rect` (píxeles del área de video). Funciona también
        sobre una zona ya ampliada (zoom anidado). La imagen se dibuja siempre
        con su proporción: nunca se deforma."""
        if not self._has_video():
            return False, "no hay video en reproducción"
        disp_w, disp_h = self._disp_size()
        view = self._current_view()
        vis_w, vis_h = geo.view_pixel_size(view, disp_w, disp_h)
        sub = geo.widget_rect_to_fraction(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            self.video.width(), self.video.height(), vis_w, vis_h)
        if sub is None:
            return False, "el recuadro está fuera de la imagen"
        new_view = geo.compose_view(view, sub)
        if new_view[2] * disp_w < MIN_ZOOM_SRC_PX or new_view[3] * disp_h < MIN_ZOOM_SRC_PX:
            return False, "zona demasiado pequeña"
        self.zoom_stack.append(geo.map_rect(new_view, geo.inverse(self.transform)))
        self._apply_view()
        return True, ""

    # ---------------------------------------------------- espejo / rotación --
    def apply_transform(self, op: geo.Matrix):
        self.set_transform(geo.mul(op, self.transform))

    def reset_transform(self):
        self.set_transform(geo.IDENTITY)

    def set_transform(self, matrix: geo.Matrix):
        """Instantáneo: lo hace Qt al dibujar (no se recrea el reproductor).
        El zoom se conserva porque se guarda en la orientación original."""
        if matrix == self.transform:
            return
        self.video.arm_selection(False)
        self.transform = matrix
        self.video.set_transform(matrix)
        self._apply_view()
        self.statusBar().showMessage(f"Orientación: {geo.describe(matrix)}", 3000)

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
        """Guarda un PNG de exactamente lo que se ve (zona ampliada, espejo,
        rotación y ajustes de imagen) a la resolución real de esa zona."""
        if not self._has_video():
            self.statusBar().showMessage("No hay video en reproducción para capturar", 4000)
            return None
        img = self.video.render_view()
        if img is None:
            self.statusBar().showMessage("Todavía no hay imagen para capturar", 4000)
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
        if not img.save(path, "PNG"):
            self.statusBar().showMessage("Error al guardar la captura", 5000)
            return None
        self.statusBar().showMessage(f"📷 Captura guardada: {path}", 6000)
        return path

    # ----------------------------------------------------------- drag&drop --
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() or u.toString() for u in e.mimeData().urls()]
        self.add_and_play([p for p in paths if p])

    # ------------------------------------------------------ exportar audio --
    def _audio_tracks(self):
        """Pistas de audio del medio actual: [(id, nombre)], id actual."""
        if self.media_path is None:
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
        if self._exporter is not None:
            self.statusBar().showMessage("Ya hay una exportación en curso", 4000)
            return
        tracks, current = self._audio_tracks()
        t = self.player.get_time()
        length = self.player.get_length() if self.media_path else 0
        dlg = ExportAudioDialog(self, self.settings, self.media_path, MEDIA_FILTER,
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

    # ------------------------------------------------- imagen / ecualizador --
    def open_effects(self, tab: int = 0):
        if self._fx_dialog is None:
            self._fx_dialog = EffectsDialog(self, vlc, self.adjust, self.eq)
            self._fx_dialog.adjustChanged.connect(self._on_adjust_changed)
            self._fx_dialog.equalizerChanged.connect(self._on_eq_changed)
        self._fx_dialog.sync_from_state()
        self._fx_dialog.show_tab(tab)

    def _apply_video_effects(self, force: bool = False):
        fx.apply_adjust(vlc, self.player, self.adjust, force)

    def _on_adjust_changed(self):
        # Al pasar de inactivo a activo se fuerza el encendido del filtro; al
        # mover un control con el filtro ya activo solo se cambian valores.
        turning_on = self.adjust.active and not self._adjust_was_active
        self._adjust_was_active = self.adjust.active
        self._apply_video_effects(force=turning_on)
        if turning_on:
            QTimer.singleShot(500, lambda: self._apply_video_effects(force=True))
        self.settings.setValue("fx/adjust", self.adjust.to_json())
        self._update_state_label()

    def _on_eq_changed(self):
        fx.apply_equalizer(vlc, self.player, self.eq)
        self.settings.setValue("fx/equalizer", self.eq.to_json())
        self._update_state_label()

    def closeEvent(self, e):
        if self._exporter is not None:
            self._exporter.cancel()
            self._exporter = None
        self.settings.setValue("playlist/visible", self.dock.isVisible())
        self._save_playlist()
        self.timer.stop()
        self.player.stop()
        self.frames.detach()
        self.player.release()
        self.instance.release()
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
        QTimer.singleShot(0, lambda: win.add_and_play(files))
    return app.exec_()
