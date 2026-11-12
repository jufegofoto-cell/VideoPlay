# -*- coding: utf-8 -*-
"""
Ajustes de imagen (filtro "adjust" de VLC) y ecualizador de audio de 10
bandas. El estado se guarda en dataclasses independientes de VLC para poder
persistirlo y probarlo; las funciones ``apply_*`` lo aplican a un reproductor.

Notas de libVLC 3
-----------------
* ``video_get_adjust_int(Enable)`` no refleja el estado real, así que la app
  lleva su propio estado y nunca lo consulta a VLC.
* Tras recrear el reproductor, ``Enable=1`` se ignora si VLC cree que ya
  estaba activo: hay que apagarlo y encenderlo (``force=True``).
* El filtro de ajuste se ve en pantalla y también en las capturas.
* El ecualizador solo actúa sobre la reproducción: el transcodificador de VLC
  ignora el filtro "equalizer", por lo que no afecta a "Exportar audio".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

# ------------------------------------------------------------------ imagen --
# nombre: (etiqueta, mínimo, máximo, valor neutro, decimales)
ADJUST_PARAMS = {
    "brightness": ("Brillo", 0.0, 2.0, 1.0, 2),
    "contrast": ("Contraste", 0.0, 2.0, 1.0, 2),
    "saturation": ("Saturación", 0.0, 3.0, 1.0, 2),
    "hue": ("Tono (°)", -180.0, 180.0, 0.0, 0),
    "gamma": ("Gamma", 0.1, 3.0, 1.0, 2),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


@dataclass
class ImageAdjust:
    enabled: bool = False
    values: Dict[str, float] = field(
        default_factory=lambda: {k: p[3] for k, p in ADJUST_PARAMS.items()})

    def set(self, name: str, value: float):
        _, lo, hi, _, _ = ADJUST_PARAMS[name]
        self.values[name] = _clamp(value, lo, hi)

    def reset(self):
        self.values = {k: p[3] for k, p in ADJUST_PARAMS.items()}

    def is_neutral(self) -> bool:
        return all(abs(self.values[k] - p[3]) < 1e-6 for k, p in ADJUST_PARAMS.items())

    @property
    def active(self) -> bool:
        return self.enabled and not self.is_neutral()

    def to_json(self) -> str:
        return json.dumps({"enabled": self.enabled, "values": self.values})

    @classmethod
    def from_json(cls, text) -> "ImageAdjust":
        obj = cls()
        try:
            data = json.loads(text) if text else {}
        except (TypeError, ValueError):
            return obj
        if not isinstance(data, dict):
            return obj
        obj.enabled = bool(data.get("enabled", False))
        values = data.get("values")
        for k, v in (values.items() if isinstance(values, dict) else ()):
            if k in ADJUST_PARAMS:
                try:
                    obj.set(k, float(v))
                except (TypeError, ValueError):
                    pass
        return obj


def apply_adjust(vlc, player, adj: ImageAdjust, force: bool = False):
    """Aplica los ajustes. `force` apaga y vuelve a encender el filtro: es
    necesario cuando VLC crea una salida de video nueva (al recrear el
    reproductor), porque ignora "Enable" si cree que ya estaba activo."""
    if player is None:
        return
    A = vlc.VideoAdjustOption
    if not adj.active:
        player.video_set_adjust_int(A.Enable, 0)
        return
    if force:
        player.video_set_adjust_int(A.Enable, 0)
    player.video_set_adjust_int(A.Enable, 1)
    player.video_set_adjust_float(A.Brightness, adj.values["brightness"])
    player.video_set_adjust_float(A.Contrast, adj.values["contrast"])
    player.video_set_adjust_float(A.Saturation, adj.values["saturation"])
    player.video_set_adjust_float(A.Hue, adj.values["hue"])
    player.video_set_adjust_float(A.Gamma, adj.values["gamma"])


# -------------------------------------------------------------- ecualizador --
EQ_BANDS_HZ = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
EQ_MIN_DB, EQ_MAX_DB = -20.0, 20.0

# Nombres de los 18 presets de VLC 3, en el mismo orden
PRESET_NAMES_ES = [
    "Plano", "Clásica", "Club", "Dance", "Graves", "Graves y agudos", "Agudos",
    "Audífonos", "Sala amplia", "En vivo", "Fiesta", "Pop", "Reggae", "Rock",
    "Ska", "Suave", "Soft rock", "Techno",
]
CUSTOM_PRESET = -1


@dataclass
class Equalizer:
    enabled: bool = False
    preset: int = 0                    # índice de preset de VLC o CUSTOM_PRESET
    preamp: float = 0.0
    bands: List[float] = field(default_factory=lambda: [0.0] * len(EQ_BANDS_HZ))

    def set_band(self, i: int, db: float):
        self.bands[i] = _clamp(db, EQ_MIN_DB, EQ_MAX_DB)
        self.preset = CUSTOM_PRESET

    def set_preamp(self, db: float):
        self.preamp = _clamp(db, EQ_MIN_DB, EQ_MAX_DB)
        self.preset = CUSTOM_PRESET

    def reset(self):
        self.preset, self.preamp = 0, 0.0
        self.bands = [0.0] * len(EQ_BANDS_HZ)

    def to_json(self) -> str:
        return json.dumps({"enabled": self.enabled, "preset": self.preset,
                           "preamp": self.preamp, "bands": self.bands})

    @classmethod
    def from_json(cls, text) -> "Equalizer":
        obj = cls()
        try:
            data = json.loads(text) if text else {}
            if not isinstance(data, dict):
                return cls()
            obj.enabled = bool(data.get("enabled", False))
            obj.preset = int(data.get("preset", 0))
            obj.preamp = _clamp(data.get("preamp", 0.0), EQ_MIN_DB, EQ_MAX_DB)
            bands = [float(b) for b in data.get("bands", [])]
            if len(bands) == len(EQ_BANDS_HZ):
                obj.bands = [_clamp(b, EQ_MIN_DB, EQ_MAX_DB) for b in bands]
        except (TypeError, ValueError, AttributeError):
            return cls()
        return obj


def preset_names(vlc) -> List[str]:
    n = vlc.libvlc_audio_equalizer_get_preset_count()
    names = []
    for i in range(n):
        if i < len(PRESET_NAMES_ES):
            names.append(PRESET_NAMES_ES[i])
        else:
            raw = vlc.libvlc_audio_equalizer_get_preset_name(i)
            names.append(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
    return names


def load_preset(vlc, eq: Equalizer, index: int):
    """Copia los valores de un preset de VLC al estado `eq`."""
    handle = vlc.libvlc_audio_equalizer_new_from_preset(index)
    if not handle:
        return
    try:
        eq.preamp = vlc.libvlc_audio_equalizer_get_preamp(handle)
        eq.bands = [vlc.libvlc_audio_equalizer_get_amp_at_index(handle, i)
                    for i in range(len(EQ_BANDS_HZ))]
        eq.preset = index
    finally:
        vlc.libvlc_audio_equalizer_release(handle)


def apply_equalizer(vlc, player, eq: Equalizer):
    if player is None:
        return
    if not eq.enabled:
        player.set_equalizer(None)
        return
    handle = vlc.libvlc_audio_equalizer_new()
    try:
        vlc.libvlc_audio_equalizer_set_preamp(handle, eq.preamp)
        for i, db in enumerate(eq.bands):
            vlc.libvlc_audio_equalizer_set_amp_at_index(handle, db, i)
        player.set_equalizer(handle)          # libVLC copia los valores
    finally:
        vlc.libvlc_audio_equalizer_release(handle)
