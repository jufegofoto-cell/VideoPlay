# -*- coding: utf-8 -*-
"""
Prueba de humo de extremo a extremo con la app real y libVLC.

    python tools/smoke_test.py VIDEO [CARPETA_SALIDA]

Reproduce el video, aplica zoom (incluido zoom anidado), espejo y rotación,
guarda capturas en cada paso y comprueba sus dimensiones. También guarda
pantallazos de la ventana (screen_*.png). Devuelve código 0 si todo pasa.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QRect, QTimer  # noqa: E402
from PyQt5.QtGui import QImage, QGuiApplication  # noqa: E402

from vlc_zoom_player import app as appmod  # noqa: E402
from vlc_zoom_player import geometry as geo  # noqa: E402
from vlc_zoom_player import effects as fx  # noqa: E402


def run(video, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    qapp = appmod.QApplication(sys.argv[:1])
    win = appmod.MainWindow()
    win.settings.setValue("captures_dir", out_dir)
    win.adjust.reset()                 # empezar sin efectos guardados
    win.adjust.enabled = False
    win.eq.reset()
    win.eq.enabled = False
    win._on_adjust_changed()
    win._on_eq_changed()
    win.move(0, 0)
    win.show()
    results, failures = [], []

    def check(name, cond, detail=""):
        results.append(f"[{'OK ' if cond else 'FALLA'}] {name} {detail}")
        if not cond:
            failures.append(name)

    def screen(name):
        pix = QGuiApplication.primaryScreen().grabWindow(0)
        g = win.frameGeometry()
        pix.copy(g).save(os.path.join(out_dir, f"screen_{name}.png"))

    def snap(name, expect_size):
        path = win.snapshot()
        def verify():
            img = QImage(path or "")
            size = (img.width(), img.height())
            check(f"captura {name}", not img.isNull() and size == expect_size,
                  f"esperado={expect_size} obtenido={size}")
            if path and os.path.exists(path):
                os.replace(path, os.path.join(out_dir, f"snap_{name}.png"))
        QTimer.singleShot(900, verify)

    def colorfulness(img):
        """Diferencia media entre canales (0 = gris)."""
        total, n = 0, 0
        for y in range(0, img.height(), max(1, img.height() // 40)):
            for x in range(0, img.width(), max(1, img.width() // 40)):
                c = img.pixelColor(x, y)
                total += max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
                n += 1
        return total / max(1, n)

    def snap_color(name, want_gray):
        path = win.snapshot()
        def verify():
            img = QImage(path or "")
            col = colorfulness(img) if not img.isNull() else -1
            ok = (0 <= col < 12) if want_gray else col > 60
            check(f"captura {name} ({'gris' if want_gray else 'color'})", ok, f"color={col:.1f}")
            if path and os.path.exists(path):
                os.replace(path, os.path.join(out_dir, f"snap_{name}.png"))
        QTimer.singleShot(900, verify)

    steps = []

    def step(delay):
        def deco(fn):
            steps.append((delay, fn))
            return fn
        return deco

    @step(2500)
    def _1():
        check("video cargado", win._has_video(), str(win._source_size()))
        screen("1_original")
        snap("1_original", win._source_size())

    @step(1500)
    def _2():
        fw, fh = win.video_frame.width(), win.video_frame.height()
        # recuadro en el cuarto superior izquierdo del área de video
        ok, msg = win.zoom_to_widget_rect(QRect(0, 0, fw // 2, fh // 2))
        check("zoom por recuadro", ok, msg)
        w, h = win._source_size()
        snap("2_zoom", geo.view_pixel_size(win._current_view(), w, h))

    @step(1500)
    def _3():
        screen("2_zoom")
        fw, fh = win.video_frame.width(), win.video_frame.height()
        ok, msg = win.zoom_to_widget_rect(QRect(fw // 2, fh // 2, fw // 2, fh // 2))
        check("zoom anidado", ok and len(win.zoom_stack) == 2, msg)

    @step(1500)
    def _4():
        screen("3_zoom_anidado")
        win.zoom_out_one()
        check("deshacer nivel", len(win.zoom_stack) == 1)
        win.reset_zoom()
        win._t_before = win.player.get_time()
        win.apply_transform(geo.ROT_CW)

    @step(2500)
    def _5():
        t = win.player.get_time()
        check("rotación conserva posición", abs(t - win._t_before) < 3000,
              f"antes={win._t_before} después={t}")
        screen("4_rotado")
        snap("4_rotado", win._disp_size())

    @step(1500)
    def _6():
        fw, fh = win.video_frame.width(), win.video_frame.height()
        ok, msg = win.zoom_to_widget_rect(QRect(fw // 4, 0, fw // 2, fh // 3))
        check("zoom sobre video rotado", ok, msg)

    @step(1500)
    def _7():
        screen("5_rotado_zoom")
        dw, dh = win._disp_size()
        snap("5_rotado_zoom", geo.view_pixel_size(win._current_view(), dw, dh))

    @step(1500)
    def _8():
        win.player.set_pause(1)

    @step(400)
    def _8a():
        if win.player.get_state() != appmod.vlc.State.Paused:
            win.player.set_pause(1)       # VLC a veces ignora la primera pausa

    @step(700)
    def _8b():
        check("pausado antes del espejo", win.player.get_state() == appmod.vlc.State.Paused,
              str(win.player.get_state()))
        win.apply_transform(geo.HFLIP)

    @step(3000)
    def _9():
        check("zoom conservado tras espejo", len(win.zoom_stack) == 1)
        check("pausa conservada", win.player.get_state() == appmod.vlc.State.Paused,
              str(win.player.get_state()))
        screen("6_espejo_zoom")
        dw, dh = win._disp_size()
        snap("6_espejo_zoom", geo.view_pixel_size(win._current_view(), dw, dh))

    @step(1500)
    def _10():
        win.reset_transform()
        win.reset_zoom()

    @step(2000)
    def _11():
        win.adjust.enabled = True
        win.adjust.set("saturation", 0.0)
        win._on_adjust_changed()
        fx.load_preset(appmod.vlc, win.eq, 13)          # Rock
        win.eq.enabled = True
        win._on_eq_changed()
        check("estado de ajustes", win.adjust.active and win.eq.enabled
              and "Imagen ajustada" in win.lbl_state.text(), win.lbl_state.text())

    @step(1500)
    def _12():
        screen("7_blanco_y_negro")
        snap_color("7_blanco_y_negro", True)

    @step(1500)
    def _13():
        win.apply_transform(geo.ROT_CW)                  # recrea el reproductor

    @step(3000)
    def _14():
        snap_color("8_bn_rotado", True)
        win.open_effects(1)

    @step(1500)
    def _15():
        d = win._fx_dialog
        QGuiApplication.primaryScreen().grabWindow(0).copy(d.frameGeometry()).save(
            os.path.join(out_dir, "screen_9_ecualizador.png"))
        d.show_tab(0)

    @step(800)
    def _16():
        d = win._fx_dialog
        QGuiApplication.primaryScreen().grabWindow(0).copy(d.frameGeometry()).save(
            os.path.join(out_dir, "screen_10_imagen.png"))
        d.close()
        win.adjust.enabled = False
        win._on_adjust_changed()
        win.reset_transform()

    @step(3000)
    def _17():
        snap_color("11_sin_ajustes", False)
        win.eq.enabled = False
        win._on_eq_changed()

    @step(2000)
    def _end():
        check("orientación restablecida", win.transform == geo.IDENTITY)
        print("\n".join(results))
        print("RESULTADO:", "FALLA" if failures else "OK")
        win.close()
        qapp.exit(1 if failures else 0)

    win.load(video)
    acc = 0
    for delay, fn in steps:
        acc += delay
        QTimer.singleShot(acc, fn)
    return qapp.exec_()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "smoke_out"))
