# -*- coding: utf-8 -*-
"""
Dibujo del video en Qt a partir de los fotogramas que entrega libVLC.

¿Por qué no la ventana nativa de VLC?
------------------------------------
Con la ventana nativa el zoom dependía del recorte de VLC
(``crop_geometry``), que falla según la salida de video: en Linux ubica mal
la zona y en Windows (Direct3D) deja la pantalla en negro. Aquí VLC solo
decodifica (callbacks "vmem", formato RV32) y la app dibuja cada fotograma:

* el zoom, el espejo y la rotación los hace Qt al dibujar: son instantáneos,
  funcionan igual en todos los sistemas y nunca deforman la imagen;
* el recuadro de selección es un widget normal sobre el video;
* la captura sale de los mismos píxeles que se ven.

Los filtros de VLC (ajustes de imagen) se aplican antes de entregar el
fotograma, así que también se ven y se capturan.
"""

from __future__ import annotations

import ctypes
import threading
from typing import Optional, Tuple

from PyQt5.QtCore import Qt, QObject, QPoint, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QTransform
from PyQt5.QtWidgets import QRubberBand, QSizePolicy, QWidget

from . import geometry as geo

MAX_FRAME_WIDTH = 3840          # se reduce lo que supere 4K para ahorrar CPU
N_BUFFERS = 4
MIN_SELECTION_PX = 12


class FrameSource(QObject):
    """Recibe los fotogramas de libVLC en memoria (hilos de VLC) y los
    entrega de forma segura al hilo de la interfaz."""

    frameReady = pyqtSignal()

    def __init__(self, vlc_module):
        super().__init__()
        self.vlc = vlc_module
        self._mutex = threading.Lock()
        self._bufs = []
        self._buf_size = (0, 0)       # ancho, alto del búfer (con relleno)
        self._visible = (0, 0)        # zona útil (sin las filas de relleno)
        self._front = None
        self._counter = 0
        self._player = None
        self._make_callbacks()

    # ------------------------------------------------------- callbacks C --
    def _make_callbacks(self):
        vlc = self.vlc
        # python-vlc declara "chroma" como c_char_p (una copia), y hay que
        # escribir en él para pedir RV32; por eso se define el prototipo aquí.
        FMT = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                               ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))
        CLEAN = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
        self._set_format_callbacks = ctypes.CFUNCTYPE(None, ctypes.c_void_p, FMT, CLEAN)(
            ("libvlc_video_set_format_callbacks", vlc.dll))

        @FMT
        def fmt(opaque, chroma, width, height, pitches, lines):
            try:
                return self._on_format(chroma, width, height, pitches, lines)
            except Exception:  # noqa: BLE001 — nunca propagar a C
                return 0

        @CLEAN
        def cleanup(opaque):
            with self._mutex:
                self._front = None

        @vlc.CallbackDecorators.VideoLockCb
        def lock(opaque, planes):
            with self._mutex:
                if not self._bufs:
                    return 0
                i = self._counter % len(self._bufs)
                if i == self._front:
                    i = (i + 1) % len(self._bufs)
                self._counter = i + 1
                planes[0] = ctypes.cast(self._bufs[i], ctypes.c_void_p)
            return i + 1

        @vlc.CallbackDecorators.VideoUnlockCb
        def unlock(opaque, picture, planes):
            pass

        @vlc.CallbackDecorators.VideoDisplayCb
        def display(opaque, picture):
            if not picture:
                return
            with self._mutex:
                self._front = int(picture) - 1
            self.frameReady.emit()

        # mantener referencias: si Python las libera, VLC llamaría a basura
        self._cb = (fmt, cleanup, lock, unlock, display)

    def _on_format(self, chroma, width, height, pitches, lines):
        w, h = width[0], height[0]
        vis = (0, 0)
        if self._player is not None:
            try:
                vis = self._player.video_get_size(0) or (0, 0)
            except Exception:  # noqa: BLE001
                vis = (0, 0)
        vw, vh = vis if vis[0] and vis[1] and vis[0] <= w and vis[1] <= h else (w, h)
        if w > MAX_FRAME_WIDTH:                   # pedir a VLC una versión reducida
            scale = MAX_FRAME_WIDTH / float(w)
            w, h = MAX_FRAME_WIDTH, int(h * scale) & ~1
            vw, vh = min(w, int(vw * scale)), min(h, int(vh * scale))
            width[0], height[0] = w, h
        ctypes.memmove(chroma, b"RV32", 4)
        pitches[0] = w * 4
        lines[0] = h
        bufs = [(ctypes.c_ubyte * (w * h * 4))() for _ in range(N_BUFFERS)]
        with self._mutex:
            self._bufs = bufs
            self._buf_size = (w, h)
            self._visible = (vw, vh)
            self._front = None
        return N_BUFFERS

    # -------------------------------------------------------------- API --
    def attach(self, player):
        self._player = player
        player.video_set_callbacks(*self._cb[2:], None)
        self._set_format_callbacks(player._as_parameter_, self._cb[0], self._cb[1])

    def detach(self):
        self._player = None

    def clear(self):
        with self._mutex:
            self._front = None
        self.frameReady.emit()

    def frame_size(self) -> Tuple[int, int]:
        with self._mutex:
            return self._visible if self._front is not None else (0, 0)

    def paint_with(self, fn):
        """Llama fn(frame) con el fotograma actual mientras se impide que VLC
        lo reemplace. `frame` es (QImage del búfer, ancho, alto visibles), sin
        copiar píxeles; None si todavía no hay imagen."""
        with self._mutex:
            if self._front is None or not self._bufs:
                return fn(None)
            w, h = self._buf_size
            img = QImage(self._bufs[self._front], w, h, w * 4, QImage.Format_RGB32)
            return fn((img, self._visible[0], self._visible[1]))


def _draw(painter: QPainter, frame):
    """Dibuja solo la zona visible (VLC agrega filas de relleno abajo)."""
    img, w, h = frame
    painter.drawImage(QRectF(0, 0, w, h), img, QRectF(0, 0, w, h))


def picture_transform(src_w: int, src_h: int, m: geo.Matrix, view: geo.Rect,
                      target: QRectF) -> QTransform:
    """Transformación que lleva píxeles del fotograma original a la pantalla:
    primero espejo/rotación (matriz D4), luego la zona visible `view`
    (fracción de la imagen transformada) escalada dentro de `target`."""
    a, b, c, d = m
    dw, dh = geo.transformed_size(src_w, src_h, m)
    # Qt usa vectores fila: x' = m11·x + m21·y + dx ; y' = m12·x + m22·y + dy
    orient = QTransform(a, c, b, d,
                        dw / 2.0 - a * src_w / 2.0 - b * src_h / 2.0,
                        dh / 2.0 - c * src_w / 2.0 - d * src_h / 2.0)
    vx, vy, vw, vh = view
    scale = target.width() / (vw * dw)
    to_screen = QTransform(scale, 0, 0, scale,
                           target.x() - vx * dw * scale,
                           target.y() - vy * dh * scale)
    return orient * to_screen


class VideoView(QWidget):
    """Área de video: dibuja el fotograma con zoom/espejo/rotación y gestiona
    la selección del recuadro de zoom (con la proporción de la imagen)."""

    zoomRectSelected = pyqtSignal(QRect)     # en coordenadas del widget
    zoomSelectionCancelled = pyqtSignal()
    doubleClicked = pyqtSignal()

    def __init__(self, source: FrameSource, parent=None):
        super().__init__(parent)
        self.source = source
        self.transform = geo.IDENTITY
        self.view: geo.Rect = geo.FULL_VIEW
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._armed = False
        self._selecting = False
        self._origin = QPoint()
        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        source.frameReady.connect(self.update, Qt.QueuedConnection)

    # ------------------------------------------------------------ estado --
    def set_transform(self, m: geo.Matrix):
        self.transform = m
        self.update()

    def set_view(self, view: geo.Rect):
        self.view = view
        self.update()

    def display_size(self) -> Tuple[int, int]:
        w, h = self.source.frame_size()
        return geo.transformed_size(w, h, self.transform)

    def visible_pixel_size(self) -> Tuple[int, int]:
        dw, dh = self.display_size()
        return geo.view_pixel_size(self.view, dw, dh) if dw and dh else (0, 0)

    def picture_rect(self) -> QRectF:
        """Rectángulo del widget que ocupa la imagen (sin franjas negras)."""
        vw, vh = self.visible_pixel_size()
        if not vw or not vh:
            return QRectF()
        ox, oy, s = geo.fit(self.width(), self.height(), vw, vh)
        return QRectF(ox, oy, vw * s, vh * s)

    # ------------------------------------------------------------ dibujo --
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        target = self.picture_rect()
        if target.isEmpty():
            return

        def draw(frame):
            if frame is None:
                return
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setClipRect(target)
            p.setTransform(picture_transform(frame[1], frame[2],
                                             self.transform, self.view, target))
            _draw(p, frame)

        self.source.paint_with(draw)

    def render_view(self) -> Optional[QImage]:
        """Imagen de lo que se ve, a la resolución real de esa zona."""
        vw, vh = self.visible_pixel_size()
        if not vw or not vh:
            return None
        out = QImage(vw, vh, QImage.Format_RGB32)
        out.fill(QColor(0, 0, 0))

        def draw(frame):
            if frame is None:
                return False
            p = QPainter(out)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setTransform(picture_transform(frame[1], frame[2], self.transform,
                                             self.view, QRectF(0, 0, vw, vh)))
            _draw(p, frame)
            p.end()
            return True

        return out if self.source.paint_with(draw) else None

    # --------------------------------------------------------- selección --
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

    def _selection_rect(self, pos: QPoint) -> QRect:
        """Recuadro desde el origen hasta `pos` con la misma proporción que la
        imagen visible, para que la zona ampliada llene el reproductor sin
        deformarse; limitado al área de la imagen."""
        pic = self.picture_rect()
        if pic.isEmpty():
            return QRect()
        ar = pic.width() / pic.height()
        ox, oy = self._origin.x(), self._origin.y()
        dx, dy = pos.x() - ox, pos.y() - oy
        sx = 1 if dx >= 0 else -1
        sy = 1 if dy >= 0 else -1
        w = max(abs(dx), abs(dy) * ar)
        # no salirse de la imagen
        max_w = (pic.right() - ox) if sx > 0 else (ox - pic.left())
        max_h = (pic.bottom() - oy) if sy > 0 else (oy - pic.top())
        w = max(0.0, min(w, max_w, max_h * ar))
        h = w / ar
        x = ox if sx > 0 else ox - w
        y = oy if sy > 0 else oy - h
        return QRect(int(round(x)), int(round(y)), int(round(w)), int(round(h)))

    def mousePressEvent(self, e):
        if self._armed and e.button() == Qt.LeftButton:
            pic = self.picture_rect()
            o = e.pos()
            self._origin = QPoint(int(min(max(o.x(), pic.left()), pic.right())),
                                  int(min(max(o.y(), pic.top()), pic.bottom())))
            self._selecting = True
            self._rubber.setGeometry(QRect(self._origin, self._origin))
            self._rubber.show()
        elif self._armed and e.button() == Qt.RightButton:
            self.cancel_selection()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._selecting:
            self._rubber.setGeometry(self._selection_rect(e.pos()))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._selecting and e.button() == Qt.LeftButton:
            rect = self._selection_rect(e.pos())
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
