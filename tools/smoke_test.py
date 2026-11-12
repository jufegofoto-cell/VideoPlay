# -*- coding: utf-8 -*-
"""
Prueba de humo de extremo a extremo con la app real y libVLC.

    python tools/smoke_test.py VIDEO VIDEO_CORTO [CARPETA_SALIDA]

Reproduce el video y prueba: zoom (con el mouse, manteniendo la proporción),
zoom anidado, Zoom All, adelantar/atrasar, rotación y espejo (también en
pausa), ajustes de imagen, ecualizador y lista de reproducción (paso
automático al siguiente). Guarda capturas y pantallazos en la carpeta de
salida. Devuelve código 0 si todo pasa.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QGuiApplication, QImage, QMouseEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402

from vlc_zoom_player import app as appmod  # noqa: E402
from vlc_zoom_player import effects as fx  # noqa: E402
from vlc_zoom_player import geometry as geo  # noqa: E402


def run(video, short_video, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    qapp = appmod.QApplication(sys.argv[:1])
    win = appmod.MainWindow()
    win.settings.setValue("captures_dir", out_dir)
    win.playlist.clear_all()
    win.adjust.reset()                 # empezar sin efectos guardados
    win.adjust.enabled = False
    win.eq.reset()
    win.eq.enabled = False
    win._on_adjust_changed()
    win._on_eq_changed()
    win.dock.show()
    win.move(0, 0)
    win.resize(1240, 760)
    win.show()
    results, failures = [], []

    def check(name, cond, detail=""):
        results.append(f"[{'OK ' if cond else 'FALLA'}] {name} {detail}")
        if not cond:
            failures.append(name)

    def screen(name, widget=None):
        widget = widget or win
        QGuiApplication.primaryScreen().grabWindow(0).copy(widget.frameGeometry()).save(
            os.path.join(out_dir, f"screen_{name}.png"))

    def snap(name, expect_size=None):
        path = win.snapshot()
        img = QImage(path or "")
        size = (img.width(), img.height())
        if expect_size is not None:
            check(f"captura {name}", not img.isNull() and size == tuple(expect_size),
                  f"esperado={tuple(expect_size)} obtenido={size}")
        if path and os.path.exists(path):
            os.replace(path, os.path.join(out_dir, f"snap_{name}.png"))
        return img

    def colorfulness(img):
        """Diferencia media entre canales (0 = gris)."""
        total, n = 0, 0
        for y in range(0, img.height(), max(1, img.height() // 40)):
            for x in range(0, img.width(), max(1, img.width() // 40)):
                c = img.pixelColor(x, y)
                total += max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
                n += 1
        return total / max(1, n)

    def aspect_ok(tag):
        """La imagen en pantalla tiene la proporción de la zona visible."""
        vw, vh = win.video.visible_pixel_size()
        pic = win.video.picture_rect()
        ok = vw and vh and abs(pic.width() / pic.height() - vw / vh) < 0.01
        check(f"proporción sin deformar ({tag})", bool(ok),
              f"zona={vw}x{vh} ({vw / max(1, vh):.3f}) pantalla={pic.width():.0f}x{pic.height():.0f}"
              f" ({pic.width() / max(1, pic.height()):.3f})")

    steps = []

    def step(delay):
        def deco(fn):
            steps.append((delay, fn))
            return fn
        return deco

    @step(2500)
    def _1():
        check("video cargado", win._has_video(), str(win.frames.frame_size()))
        check("lista con el archivo", win.playlist.count() == 1 and win.playlist.current_index() == 0)
        screen("1_original")
        snap("1_original", win.frames.frame_size())
        aspect_ok("original")

    @step(800)
    def _2():
        # selección con el mouse (eventos Qt): ancho grande y alto pequeño;
        # el recuadro debe ajustarse a la proporción de la imagen
        win.toggle_zoom()
        pic = win.video.picture_rect()
        a = QPoint(int(pic.left() + 40), int(pic.top() + 30))
        b = QPoint(int(pic.left() + pic.width() * 0.55), int(pic.top() + 60))
        QTest.mousePress(win.video, Qt.LeftButton, Qt.NoModifier, a)
        move = QMouseEvent(QEvent.MouseMove, QPointF(b), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(win.video, move)          # arrastre con el botón apretado
        r = win.video._rubber.geometry()
        win._rubber_seen = (r.width(), r.height(), win.video._rubber.isVisible())
        screen("2_seleccion")
        QTest.mouseRelease(win.video, Qt.LeftButton, Qt.NoModifier, b)

    @step(800)
    def _3():
        rw, rh, visible = win._rubber_seen
        pic = win.video.picture_rect()
        check("recuadro visible al arrastrar", visible)
        check("recuadro con la proporción del video",
              abs(rw / max(1, rh) - pic.width() / pic.height()) < 0.03,
              f"recuadro={rw}x{rh}")
        check("zoom con el mouse", len(win.zoom_stack) == 1, win.lbl_state.text())
        aspect_ok("zoom")
        dw, dh = win._disp_size()
        snap("2_zoom", geo.view_pixel_size(win._current_view(), dw, dh))
        screen("3_zoom")

    @step(800)
    def _4():
        fw, fh = win.video.width(), win.video.height()
        ok, msg = win.zoom_to_widget_rect(QRect(fw // 2, fh // 2, fw // 4, fh // 4))
        check("zoom anidado", ok and len(win.zoom_stack) == 2, msg)
        win.zoom_out_one()
        check("deshacer nivel", len(win.zoom_stack) == 1)
        win.zoom_all()
        check("Zoom All", not win.zoom_stack and win.video.view == geo.FULL_VIEW)
        win._t0 = win.player.get_time()
        win.seek_rel(appmod.SEEK_STEP_MS)

    @step(1200)
    def _5():
        t = win.player.get_time()
        check("adelantar 10 s", t - win._t0 > 8000, f"antes={win._t0} después={t}")
        win._t0 = t
        win.seek_rel(-appmod.SEEK_STEP_MS)

    @step(1200)
    def _6():
        t = win.player.get_time()
        check("atrasar 10 s", win._t0 - t > 7000, f"antes={win._t0} después={t}")
        win.apply_transform(geo.ROT_CW)
        fw, fh = win.frames.frame_size()
        check("rotación instantánea", win._disp_size() == (fh, fw))

    @step(800)
    def _7():
        snap("4_rotado", win._disp_size())
        aspect_ok("rotado")
        screen("4_rotado")
        fw, fh = win.video.width(), win.video.height()
        ok, msg = win.zoom_to_widget_rect(QRect(fw // 4, 0, fw // 2, fh // 3))
        check("zoom sobre video rotado", ok, msg)
        aspect_ok("rotado con zoom")
        win.player.set_pause(1)

    @step(900)
    def _8():
        if win.player.get_state() != appmod.vlc.State.Paused:
            win.player.set_pause(1)        # VLC a veces ignora la primera pausa

    @step(700)
    def _9():
        check("pausado", win.player.get_state() == appmod.vlc.State.Paused)
        win.apply_transform(geo.HFLIP)
        check("zoom conservado tras espejo", len(win.zoom_stack) == 1)
        check("pausa conservada", win.player.get_state() == appmod.vlc.State.Paused)
        dw, dh = win._disp_size()
        snap("5_espejo_zoom", geo.view_pixel_size(win._current_view(), dw, dh))
        screen("5_espejo_zoom")
        win.reset_transform()
        win.zoom_all()
        win.player.set_pause(0)

    @step(1200)
    def _10():
        win.adjust.enabled = True
        win.adjust.set("saturation", 0.0)
        win._on_adjust_changed()
        fx.load_preset(appmod.vlc, win.eq, 13)          # Rock
        win.eq.enabled = True
        win._on_eq_changed()
        check("estado de ajustes", win.adjust.active and win.eq.enabled
              and "Imagen ajustada" in win.lbl_state.text(), win.lbl_state.text())

    @step(1500)
    def _11():
        img = snap("6_blanco_y_negro")
        check("ajuste visible en la captura (gris)", colorfulness(img) < 12,
              f"color={colorfulness(img):.1f}")
        win.apply_transform(geo.ROT_CW)

    @step(700)
    def _12():
        img = snap("7_bn_rotado")
        check("ajuste se conserva al girar", colorfulness(img) < 12,
              f"color={colorfulness(img):.1f}")
        win.open_effects(1)

    @step(1000)
    def _13():
        screen("8_ecualizador", win._fx_dialog)
        win._fx_dialog.show_tab(0)

    @step(700)
    def _14():
        screen("9_imagen", win._fx_dialog)
        win._fx_dialog.close()
        win.adjust.enabled = False
        win._on_adjust_changed()
        win.reset_transform()
        win.eq.enabled = False
        win._on_eq_changed()

    @step(1500)
    def _15():
        img = snap("10_sin_ajustes")
        check("ajuste desactivado (color)", colorfulness(img) > 60, f"color={colorfulness(img):.1f}")
        win.playlist.add_paths([short_video])
        check("lista con 2 elementos", win.playlist.count() == 2)
        win.play_index(1)

    @step(1500)
    def _16():
        check("reproduce el elegido en la lista", win.media_path == short_video
              and win.playlist.current_index() == 1)
        screen("11_lista")
        win.playlist.chk_repeat.setChecked(True)   # tras el último vuelve al primero

    @step(6500)
    def _17():
        check("paso automático al siguiente (repetir)", win.media_path == video
              and win.playlist.current_index() == 0,
              f"actual={os.path.basename(win.media_path or '')}")

    @step(1000)
    def _end():
        print("\n".join(results))
        print("RESULTADO:", "FALLA" if failures else "OK")
        win.close()
        qapp.exit(1 if failures else 0)

    win.add_and_play([video])
    acc = 0
    for delay, fn in steps:
        acc += delay
        QTimer.singleShot(acc, fn)
    return qapp.exec_()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "smoke_out"))
