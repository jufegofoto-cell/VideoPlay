# -*- coding: utf-8 -*-
"""
Geometría pura (sin Qt ni VLC) para zoom, espejo y rotación.

Convenciones
------------
* Las transformaciones de imagen (espejo / rotación) forman el grupo diédrico
  D4: 8 combinaciones posibles. Se representan como matrices enteras 2x2
  ``(a, b, c, d)`` que actúan sobre coordenadas centradas de la imagen
  (x hacia la derecha, y hacia abajo)::

        x' = a·x + b·y
        y' = c·x + d·y

  Cada una de las 8 matrices corresponde exactamente a un valor del filtro
  ``transform`` de VLC (``--transform-type``).

* Los rectángulos se expresan *normalizados* ``(x, y, w, h)`` en [0, 1],
  relativos a la imagen completa. El zoom se guarda en la orientación
  ORIGINAL del video, de modo que se conserva al rotar o reflejar.

* El dibujo (``video_view.py``) usa estas funciones para encajar la zona
  visible con su proporción (franjas negras si hace falta): la imagen nunca
  se deforma.
"""

from __future__ import annotations

from typing import Optional, Tuple

Matrix = Tuple[int, int, int, int]
Rect = Tuple[float, float, float, float]   # x, y, w, h normalizados

IDENTITY: Matrix = (1, 0, 0, 1)
HFLIP: Matrix = (-1, 0, 0, 1)        # espejo horizontal
VFLIP: Matrix = (1, 0, 0, -1)        # espejo vertical
ROT_CW: Matrix = (0, -1, 1, 0)       # 90° en sentido horario
ROT_CCW: Matrix = (0, 1, -1, 0)      # 90° en sentido antihorario
FULL_VIEW: Rect = (0.0, 0.0, 1.0, 1.0)

# Matriz -> valor de --transform-type de VLC (None = sin filtro)
VLC_TRANSFORM_TYPES = {
    (1, 0, 0, 1): None,
    (0, -1, 1, 0): "90",
    (-1, 0, 0, -1): "180",
    (0, 1, -1, 0): "270",
    (-1, 0, 0, 1): "hflip",
    (1, 0, 0, -1): "vflip",
    (0, 1, 1, 0): "transpose",
    (0, -1, -1, 0): "antitranspose",
}

DESCRIPTIONS = {
    None: "Original",
    "90": "Rotado 90°",
    "180": "Rotado 180°",
    "270": "Rotado 270°",
    "hflip": "Espejo horizontal",
    "vflip": "Espejo vertical",
    "transpose": "Espejo + rotado 270°",
    "antitranspose": "Espejo + rotado 90°",
}


# ----------------------------------------------------------- transformaciones --
def mul(m1: Matrix, m2: Matrix) -> Matrix:
    """Producto m1·m2 (aplica primero m2 y luego m1)."""
    a, b, c, d = m1
    e, f, g, h = m2
    return (a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h)


def inverse(m: Matrix) -> Matrix:
    """Las matrices de D4 son ortogonales: la inversa es la traspuesta."""
    a, b, c, d = m
    return (a, c, b, d)


def vlc_transform_type(m: Matrix) -> Optional[str]:
    return VLC_TRANSFORM_TYPES[m]


def describe(m: Matrix) -> str:
    return DESCRIPTIONS[VLC_TRANSFORM_TYPES[m]]


def swaps_axes(m: Matrix) -> bool:
    """True si la transformación intercambia ancho y alto (rotación 90/270)."""
    return m[0] == 0


def transformed_size(w: int, h: int, m: Matrix) -> Tuple[int, int]:
    return (h, w) if swaps_axes(m) else (w, h)


def _map_point(u: float, v: float, m: Matrix) -> Tuple[float, float]:
    """Mapea un punto normalizado [0,1]² a través de la matriz m."""
    x, y = 2 * u - 1, 2 * v - 1
    a, b, c, d = m
    return ((a * x + b * y + 1) / 2, (c * x + d * y + 1) / 2)


def map_rect(rect: Rect, m: Matrix) -> Rect:
    """Transforma un rectángulo normalizado con la matriz m."""
    x, y, w, h = rect
    pts = [_map_point(px, py, m)
           for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


# -------------------------------------------------------------------- encaje --
def fit(container_w: float, container_h: float,
        content_w: float, content_h: float) -> Tuple[float, float, float]:
    """Encaje con letterbox: devuelve (offset_x, offset_y, escala)."""
    scale = min(container_w / content_w, container_h / content_h)
    return ((container_w - content_w * scale) / 2.0,
            (container_h - content_h * scale) / 2.0,
            scale)


def widget_rect_to_fraction(rect: Tuple[float, float, float, float],
                            widget_w: float, widget_h: float,
                            content_w: float, content_h: float) -> Optional[Rect]:
    """Convierte un rectángulo en píxeles del widget a fracción de la imagen
    mostrada (descontando las franjas negras). None si cae fuera."""
    off_x, off_y, scale = fit(widget_w, widget_h, content_w, content_h)
    disp_w, disp_h = content_w * scale, content_h * scale
    rx, ry, rw, rh = rect
    x0 = max(0.0, min(1.0, (rx - off_x) / disp_w))
    y0 = max(0.0, min(1.0, (ry - off_y) / disp_h))
    x1 = max(0.0, min(1.0, (rx + rw - off_x) / disp_w))
    y1 = max(0.0, min(1.0, (ry + rh - off_y) / disp_h))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def compose_view(view: Rect, sub: Rect) -> Rect:
    """Sub-rectángulo `sub` (fracción de la vista actual) -> fracción de la
    imagen completa. Permite hacer zoom sobre una zona ya ampliada."""
    vx, vy, vw, vh = view
    sx, sy, sw, sh = sub
    return (vx + sx * vw, vy + sy * vh, sw * vw, sh * vh)


# ------------------------------------------------------------------ captura --
def view_pixel_size(view: Rect, disp_w: int, disp_h: int) -> Tuple[int, int]:
    """Tamaño en píxeles reales de la zona visible (para la captura)."""
    return (max(1, int(round(view[2] * disp_w))),
            max(1, int(round(view[3] * disp_h))))
