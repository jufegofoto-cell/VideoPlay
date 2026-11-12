# -*- coding: utf-8 -*-
"""
Exportación del audio de cualquier archivo que VLC pueda abrir, usando el
transcodificador de libVLC (no requiere ffmpeg ni otras dependencias).

Notas de libVLC 3
-----------------
* Se usa una instancia independiente de la del reproductor, así que se puede
  exportar mientras se reproduce.
* Con ``sout`` VLC ignora ``:start-time`` en algunos contenedores (p. ej. MKV),
  aunque ``:stop-time`` sí funciona. Para que el fragmento sea exacto en
  cualquier formato, si el fragmento no empieza en 0 se exporta primero a un
  WAV temporal (hasta el final del fragmento), se recorta el inicio con el
  módulo ``wave`` y luego se codifica al formato final.
* FLAC se guarda dentro de Ogg (.oga): el FLAC "crudo" que genera VLC queda sin
  duración en la cabecera.
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


@dataclass(frozen=True)
class AudioFormat:
    key: str
    label: str
    ext: str
    acodec: str
    mux: str
    bitrates: Tuple[int, ...] = ()      # vacío = sin pérdida (sin calidad)
    default_bitrate: int = 0
    fixed_samplerate: int = 0           # p. ej. Opus solo admite 48 kHz


FORMATS: List[AudioFormat] = [
    AudioFormat("mp3", "MP3", ".mp3", "mp3", "raw", (128, 192, 256, 320), 192),
    AudioFormat("m4a", "AAC (M4A)", ".m4a", "mp4a", "mp4", (96, 128, 192, 256), 192),
    AudioFormat("ogg", "Ogg Vorbis", ".ogg", "vorb", "ogg", (128, 192, 256, 320), 192),
    AudioFormat("opus", "Opus", ".opus", "opus", "ogg", (64, 96, 128, 160), 128, 48000),
    AudioFormat("wav", "WAV (sin pérdida)", ".wav", "s16l", "wav"),
    AudioFormat("flac", "FLAC en Ogg (sin pérdida)", ".oga", "flac", "ogg"),
]
FORMATS_BY_KEY = {f.key: f for f in FORMATS}


def _chain_path(path: str) -> str:
    """Ruta segura dentro de la cadena sout de VLC (entre comillas)."""
    path = os.path.abspath(path)
    if sys.platform.startswith("win"):
        path = path.replace("\\", "/")      # Windows acepta '/'; evita escapes
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_sout(fmt: AudioFormat, dst: str, bitrate: int = 0,
               channels: int = 2, samplerate: int = 0) -> str:
    parts = ["vcodec=none", f"acodec={fmt.acodec}"]
    if fmt.bitrates:
        parts.append(f"ab={bitrate or fmt.default_bitrate}")
    parts.append(f"channels={channels}")
    rate = fmt.fixed_samplerate or samplerate
    if rate:
        parts.append(f"samplerate={rate}")
    return ("#transcode{" + ",".join(parts) + "}"
            f":std{{access=file,mux={fmt.mux},dst={_chain_path(dst)}}}")


def unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base}_{n}{ext}"
        n += 1
    return path


def trim_wav_start(src: str, dst: str, start_s: float) -> float:
    """Copia `src` a `dst` saltando los primeros `start_s` segundos.
    Devuelve la duración resultante en segundos."""
    with wave.open(src, "rb") as r:
        params = r.getparams()
        r.setpos(min(r.getnframes(), int(round(start_s * r.getframerate()))))
        with wave.open(dst, "wb") as w:
            w.setparams(params)
            chunk = r.getframerate() * 10
            while True:
                data = r.readframes(chunk)
                if not data:
                    break
                w.writeframes(data)
    with wave.open(dst, "rb") as chk:
        return chk.getnframes() / float(chk.getframerate() or 1)


@dataclass
class ExportJob:
    source: str
    dest: str
    fmt: AudioFormat
    bitrate: int = 0
    channels: int = 2
    samplerate: int = 0
    track_id: Optional[int] = None      # id de pista de VLC; None = predeterminada
    start_ms: int = 0
    stop_ms: int = 0                    # 0 = hasta el final
    duration_ms: int = 0                # duración total del origen (para progreso)


class AudioExporter(QObject):
    """Ejecuta un ExportJob en segundo plano (libVLC usa sus propios hilos;
    aquí solo se consulta el estado con un QTimer)."""

    progress = pyqtSignal(float)        # 0..1
    finished = pyqtSignal(str)          # ruta del archivo final
    failed = pyqtSignal(str)

    def __init__(self, vlc_module, job: ExportJob, parent=None):
        super().__init__(parent)
        self.vlc = vlc_module
        self.job = job
        self._instance = None
        self._player = None
        self._passes: List[dict] = []
        self._current = None
        self._tmp_files: List[str] = []
        self._cancelled = False
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------- plan --
    def start(self):
        job = self.job
        if job.stop_ms and job.stop_ms <= job.start_ms:
            self.failed.emit("El final del fragmento debe ser posterior al inicio.")
            return
        os.makedirs(os.path.dirname(os.path.abspath(job.dest)) or ".", exist_ok=True)
        if job.start_ms > 0:
            fd, raw = tempfile.mkstemp(suffix=".wav", prefix="vzp_")
            os.close(fd)
            self._tmp_files.append(raw)
            wav = FORMATS_BY_KEY["wav"]
            self._passes.append({
                "source": job.source, "dest": raw,
                "sout": build_sout(wav, raw, channels=job.channels,
                                   samplerate=job.samplerate or 48000),
                "track": job.track_id, "stop_ms": job.stop_ms,
                "span": (0, job.stop_ms or job.duration_ms), "weight": 0.7,
                "after": "trim",
            })
            if job.fmt.key != "wav":
                self._passes.append({
                    "source": None, "dest": job.dest,
                    "sout": build_sout(job.fmt, job.dest, job.bitrate, job.channels,
                                       job.samplerate),
                    "track": None, "stop_ms": 0, "span": None, "weight": 0.3,
                })
        else:
            self._passes.append({
                "source": job.source, "dest": job.dest,
                "sout": build_sout(job.fmt, job.dest, job.bitrate, job.channels,
                                   job.samplerate),
                "track": job.track_id, "stop_ms": job.stop_ms,
                "span": (0, job.stop_ms or job.duration_ms), "weight": 1.0,
            })
        self._done_weight = 0.0
        self._instance = self.vlc.Instance("--quiet", "--no-video", "--no-sout-video",
                                           "--no-snapshot-preview")
        if self._instance is None:
            self.failed.emit("libVLC no pudo inicializarse para exportar.")
            return
        self._next_pass()

    def cancel(self):
        self._cancelled = True
        self._timer.stop()
        self._stop_player()
        self._release_instance()
        self._cleanup(remove_dest=True)

    def _fail(self, msg: str):
        self._timer.stop()
        self._stop_player()
        self._release_instance()
        self._cleanup(remove_dest=True)
        self.failed.emit(msg)

    # ------------------------------------------------------------ passes --
    def _next_pass(self):
        if not self._passes:
            self._timer.stop()
            self._stop_player()
            self._finish()
            return
        p = self._passes.pop(0)
        self._current = p
        if p["source"] is None:                 # usa el WAV recortado
            p["source"] = self._trimmed
        if os.path.exists(p["dest"]):
            os.remove(p["dest"])
        # :no-sout-all = una sola pista de audio (si no, VLC mezcla todas las
        # pistas en el mismo archivo y la duración se multiplica)
        opts = [f":sout={p['sout']}", ":no-sout-video", ":no-sout-all", ":sout-keep"]
        if p["track"] is not None:
            opts.append(f":audio-track-id={p['track']}")
        if p["stop_ms"]:
            opts.append(f":stop-time={p['stop_ms'] / 1000.0:.3f}")
        self._stop_player()
        self._player = self._instance.media_player_new()
        self._player.set_media(self._instance.media_new(p["source"], *opts))
        self._player.play()
        self._timer.start()

    def _poll(self):
        if self._player is None or self._cancelled:
            return
        st = self._player.get_state()
        p = self._current
        if st == self.vlc.State.Error:
            self._fail("VLC no pudo leer o codificar el archivo.")
            return
        if st == self.vlc.State.Ended:
            self._timer.stop()
            self._stop_player()
            if not self._valid_output(p["dest"]):
                self._fail("No se generó audio: el archivo no tiene una pista de "
                           "audio utilizable (o la pista elegida no existe).")
                return
            if p.get("after") == "trim":
                fd, trimmed = tempfile.mkstemp(suffix=".wav", prefix="vzp_trim_")
                os.close(fd)
                target = self.job.dest if self.job.fmt.key == "wav" else trimmed
                if target == trimmed:
                    self._tmp_files.append(trimmed)
                else:
                    os.remove(trimmed)
                try:
                    dur = trim_wav_start(p["dest"], target, self.job.start_ms / 1000.0)
                except (wave.Error, OSError) as exc:
                    self._fail(f"No se pudo recortar el audio: {exc}")
                    return
                if dur <= 0:
                    self._fail("El fragmento quedó vacío: revisa el inicio y el final.")
                    return
                self._trimmed = target
                if self._passes:
                    self._passes[0]["span"] = (0, int(dur * 1000))
            self._done_weight += p["weight"]
            self.progress.emit(min(1.0, self._done_weight))
            self._next_pass()
            return
        span = p.get("span")
        t = self._player.get_time()
        if span and span[1] > span[0] and t >= 0:
            frac = (t - span[0]) / float(span[1] - span[0])
        else:
            frac = max(0.0, self._player.get_position())
        self.progress.emit(min(0.999, self._done_weight + p["weight"] * max(0.0, min(1.0, frac))))

    # ---------------------------------------------------------- helpers --
    @staticmethod
    def _valid_output(path: str) -> bool:
        if not os.path.exists(path):
            return False
        if path.lower().endswith(".wav"):
            try:
                with wave.open(path, "rb") as w:
                    return w.getnframes() > 0
            except (wave.Error, EOFError):
                return False
        return os.path.getsize(path) > 1024

    def _stop_player(self):
        if self._player is not None:
            self._player.stop()
            self._player.release()
            self._player = None

    def _release_instance(self):
        if self._instance is not None:
            self._instance.release()
            self._instance = None

    def _finish(self):
        self.progress.emit(1.0)
        self._release_instance()
        self._cleanup(remove_dest=False)
        self.finished.emit(self.job.dest)

    def _cleanup(self, remove_dest: bool):
        for f in self._tmp_files:
            try:
                os.remove(f)
            except OSError:
                pass
        self._tmp_files.clear()
        if remove_dest:
            try:
                os.remove(self.job.dest)
            except OSError:
                pass
