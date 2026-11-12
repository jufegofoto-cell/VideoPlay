"""Punto de entrada para PyInstaller (el paquete usa imports relativos)."""
import sys

from vlc_zoom_player.app import main

if __name__ == "__main__":
    sys.exit(main())
