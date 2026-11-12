import pytest

from vlc_zoom_player import effects as fx


def test_adjust_defaults_are_neutral():
    a = fx.ImageAdjust()
    assert a.is_neutral() and not a.active
    a.enabled = True
    assert not a.active            # activado pero neutro: no aplica filtro


def test_adjust_clamp_and_active():
    a = fx.ImageAdjust(enabled=True)
    a.set("contrast", 5)
    a.set("hue", -500)
    assert a.values["contrast"] == 2.0 and a.values["hue"] == -180.0
    assert a.active


def test_adjust_json_roundtrip():
    a = fx.ImageAdjust(enabled=True)
    a.set("saturation", 0.0)
    b = fx.ImageAdjust.from_json(a.to_json())
    assert b == a


@pytest.mark.parametrize("bad", [None, "", "no-json", "[1,2]", "5", '{"values": {"gamma": "x"}}', '{"values": [1]}'])
def test_adjust_bad_json(bad):
    a = fx.ImageAdjust.from_json(bad)
    assert a.values["gamma"] == 1.0


def test_equalizer_band_edit_makes_custom():
    e = fx.Equalizer(enabled=True, preset=3)
    e.set_band(0, 30)
    assert e.bands[0] == fx.EQ_MAX_DB and e.preset == fx.CUSTOM_PRESET


def test_equalizer_json_roundtrip_and_bad():
    e = fx.Equalizer(enabled=True)
    e.set_preamp(-4.5)
    e.set_band(9, 7.5)
    assert fx.Equalizer.from_json(e.to_json()) == e
    assert fx.Equalizer.from_json('{"bands": [1, 2]}').bands == [0.0] * 10
    assert fx.Equalizer.from_json("{roto").enabled is False


def test_preset_names_match_vlc_count():
    assert len(fx.PRESET_NAMES_ES) == 18
    assert len(fx.EQ_BANDS_HZ) == 10
