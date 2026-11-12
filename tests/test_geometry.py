import pytest

from vlc_zoom_player import geometry as geo

ALL = list(geo.VLC_TRANSFORM_TYPES)


def test_group_is_closed_and_complete():
    # Cualquier combinación de espejos y giros cae en uno de los 8 tipos de VLC
    gens = [geo.HFLIP, geo.VFLIP, geo.ROT_CW, geo.ROT_CCW]
    seen = {geo.IDENTITY}
    frontier = [geo.IDENTITY]
    while frontier:
        m = frontier.pop()
        for g in gens:
            n = geo.mul(g, m)
            assert n in geo.VLC_TRANSFORM_TYPES
            if n not in seen:
                seen.add(n)
                frontier.append(n)
    assert seen == set(ALL)


@pytest.mark.parametrize("m", ALL)
def test_inverse(m):
    assert geo.mul(m, geo.inverse(m)) == geo.IDENTITY


def test_known_compositions():
    assert geo.mul(geo.ROT_CW, geo.ROT_CW) == (-1, 0, 0, -1)
    assert geo.vlc_transform_type(geo.mul(geo.HFLIP, geo.VFLIP)) == "180"
    four = geo.IDENTITY
    for _ in range(4):
        four = geo.mul(geo.ROT_CW, four)
    assert four == geo.IDENTITY


def test_rot_cw_moves_top_left_to_top_right():
    # Igual que el filtro "90" de VLC: la esquina sup. izq. pasa a la sup. der.
    x, y, w, h = geo.map_rect((0, 0, 0.1, 0.1), geo.ROT_CW)
    assert x == pytest.approx(0.9) and y == pytest.approx(0)


@pytest.mark.parametrize("m", ALL)
def test_map_rect_roundtrip(m):
    r = (0.1, 0.2, 0.3, 0.25)
    back = geo.map_rect(geo.map_rect(r, m), geo.inverse(m))
    assert back == pytest.approx(r)


def test_swaps_axes():
    assert geo.transformed_size(1280, 720, geo.ROT_CW) == (720, 1280)
    assert geo.transformed_size(1280, 720, geo.HFLIP) == (1280, 720)


def test_letterbox_fraction():
    # Widget 1000x1000 con video 16:9 -> franjas de 218.75 px arriba/abajo
    frac = geo.widget_rect_to_fraction((0, 218.75, 500, 281.25), 1000, 1000, 1600, 900)
    assert frac == pytest.approx((0, 0, 0.5, 0.5))
    assert geo.widget_rect_to_fraction((0, 0, 100, 100), 1000, 1000, 1600, 900) is None


def test_compose_view_nested():
    assert geo.compose_view((0.5, 0.5, 0.5, 0.5), (0.5, 0, 0.5, 1)) == (0.75, 0.5, 0.25, 0.5)


def test_crop_borders():
    assert geo.crop_borders(geo.FULL_VIEW, 1280, 720) is None
    assert geo.crop_borders((0.25, 0.25, 0.5, 0.5), 1280, 720) == "320+180+320+180"
    # siempre valores pares
    for v in geo.crop_borders((0.1234, 0.333, 0.5, 0.4), 1279, 721).split("+"):
        assert int(v) % 2 == 0


def test_view_pixel_size():
    assert geo.view_pixel_size((0, 0, 0.5, 0.25), 720, 1280) == (360, 320)
