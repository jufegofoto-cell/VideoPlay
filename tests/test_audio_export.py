import os
import sys
import wave

import pytest

pytest.importorskip("PyQt5")

from vlc_zoom_player import audio_export as ae  # noqa: E402


def _expected_dst(path):
    # En Windows la ruta se vuelve absoluta (C:\\...) y se escribe con "/"
    p = os.path.abspath(path)
    if sys.platform.startswith("win"):
        p = p.replace("\\", "/")
    return p


def test_build_sout_mp3(tmp_path):
    dst = str(tmp_path / "x y.mp3")
    s = ae.build_sout(ae.FORMATS_BY_KEY["mp3"], dst, 256, 1, 44100)
    assert s.startswith("#transcode{vcodec=none,acodec=mp3,ab=256,channels=1,samplerate=44100}")
    assert f':std{{access=file,mux=raw,dst="{_expected_dst(dst)}"}}' in s
    assert "\\" not in s.split("dst=")[1] or not sys.platform.startswith("win")


def test_build_sout_lossless_has_no_bitrate():
    s = ae.build_sout(ae.FORMATS_BY_KEY["flac"], "/tmp/a.oga")
    assert "ab=" not in s and "mux=ogg" in s


def test_opus_forces_48k():
    s = ae.build_sout(ae.FORMATS_BY_KEY["opus"], "/tmp/a.opus", samplerate=44100)
    assert "samplerate=48000" in s


def test_quotes_escaped_in_path():
    s = ae.build_sout(ae.FORMATS_BY_KEY["wav"], os.path.join("carpeta", 'di"jo.wav'))
    assert 'dst="' in s and '\\"' in s


def test_unique_path(tmp_path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"x")
    assert ae.unique_path(str(p)) == str(tmp_path / "a_1.mp3")


def test_trim_wav_start(tmp_path):
    src, dst = tmp_path / "s.wav", tmp_path / "d.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(1000)
        w.writeframes(b"\x00\x00" * 5000)        # 5 s
    dur = ae.trim_wav_start(str(src), str(dst), 2.0)
    assert dur == pytest.approx(3.0)
    assert os.path.getsize(dst) < os.path.getsize(src)
