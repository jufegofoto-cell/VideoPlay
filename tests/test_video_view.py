import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import QPointF, QRectF  # noqa: E402

from vlc_zoom_player import geometry as geo  # noqa: E402
from vlc_zoom_player.video_view import picture_transform  # noqa: E402


def _map(t, x, y):
    p = t.map(QPointF(x, y))
    return round(p.x(), 6), round(p.y(), 6)


def test_identity_full_view_scales_uniformly():
    t = picture_transform(1280, 720, geo.IDENTITY, geo.FULL_VIEW, QRectF(10, 20, 640, 360))
    assert _map(t, 0, 0) == (10, 20)
    assert _map(t, 1280, 720) == (650, 380)


def test_zoom_keeps_aspect():
    # zona derecha-abajo de 1/4: debe llenar el destino con la misma escala en x e y
    view = (0.5, 0.5, 0.5, 0.5)
    t = picture_transform(1280, 720, geo.IDENTITY, view, QRectF(0, 0, 640, 360))
    assert _map(t, 640, 360) == (0, 0)
    assert _map(t, 1280, 720) == (640, 360)
    assert t.m11() == pytest.approx(t.m22())


def test_rotation_cw_maps_top_left_to_top_right():
    t = picture_transform(1280, 720, geo.ROT_CW, geo.FULL_VIEW, QRectF(0, 0, 720, 1280))
    assert _map(t, 0, 0) == (720, 0)
    assert _map(t, 1280, 720) == (0, 1280)


def test_hflip():
    t = picture_transform(100, 50, geo.HFLIP, geo.FULL_VIEW, QRectF(0, 0, 100, 50))
    assert _map(t, 0, 0) == (100, 0)
