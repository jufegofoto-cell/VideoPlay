# -*- coding: utf-8 -*-
"""Localiza libVLC e importa python-vlc sin hacer caer la aplicación."""

import os
import sys

WINDOWS_VLC_DIRS = [
    r"C:\Program Files\VideoLAN\VLC",
    r"C:\Program Files (x86)\VideoLAN\VLC",
]

INSTALL_HELP = (
    "No se encontró VLC (libVLC).\n\n"
    "Instala VLC media player desde https://www.videolan.org/ con la MISMA "
    "arquitectura que Python (Python de 64 bits → VLC de 64 bits).\n"
    "Si VLC está en otra carpeta, define la variable de entorno "
    "VLC_DIR con esa ruta."
)


def _windows_vlc_dir():
    candidates = [os.environ.get("VLC_DIR", "")] + WINDOWS_VLC_DIRS
    try:  # ruta registrada por el instalador de VLC
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"Software\VideoLAN\VLC") as k:
                    candidates.append(winreg.QueryValueEx(k, "InstallDir")[0])
            except OSError:
                pass
    except ImportError:
        pass
    for d in candidates:
        if d and os.path.exists(os.path.join(d, "libvlc.dll")):
            return d
    return None


def load_vlc():
    """Devuelve (módulo vlc, None) o (None, mensaje de error)."""
    if sys.platform.startswith("win"):
        d = _windows_vlc_dir()
        if d:
            os.add_dll_directory(d)
            os.environ.setdefault("PYTHON_VLC_LIB_PATH", os.path.join(d, "libvlc.dll"))
            os.environ.setdefault("VLC_PLUGIN_PATH", os.path.join(d, "plugins"))
    elif os.environ.get("VLC_DIR"):
        os.environ.setdefault("VLC_PLUGIN_PATH", os.path.join(os.environ["VLC_DIR"], "plugins"))
    try:
        import vlc  # noqa: WPS433
        vlc.libvlc_get_version()
    except (ImportError, OSError, NameError, AttributeError) as exc:
        return None, f"{INSTALL_HELP}\n\nDetalle: {exc}"
    return vlc, None
