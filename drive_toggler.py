import sys
import os
import time
import math
import ctypes
import ctypes.wintypes
import subprocess
import json
import re

from PyQt5.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QAction, QMessageBox
from PyQt5.QtCore import Qt, QPoint, QPointF, QTimer, QRectF
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QIcon, QPixmap
)

SETTINGS_FILE = 'settings.json'

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_mountvol_info():
    try:
        result = subprocess.run(['mountvol'], capture_output=True, encoding='mbcs', check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        output = result.stdout
    except subprocess.CalledProcessError as e:
        print("Error running mountvol:", e)
        return {}

    volumes = {}
    current_vol = None
    
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('\\\\?\\Volume{'):
            current_vol = line
            volumes[current_vol] = []
        elif current_vol:
            if re.match(r'^[A-Z]:\\$', line):
                volumes[current_vol].append(line[:2])
            elif line == "*** NO MOUNT POINTS ***":
                pass
                
    return volumes

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print("Error loading settings:", e)
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)
    except Exception as e:
        print("Error saving settings:", e)

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

if hasattr(user32, 'GetWindowLongPtrW'):
    user32.GetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    _GetWindowLong = user32.GetWindowLongPtrW
else:
    user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    _GetWindowLong = user32.GetWindowLongW

if hasattr(user32, 'SetWindowLongPtrW'):
    user32.SetWindowLongPtrW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    _SetWindowLong = user32.SetWindowLongPtrW
else:
    user32.SetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    _SetWindowLong = user32.SetWindowLongW


def lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    r = c1.red()   + (c2.red()   - c1.red())   * t
    g = c1.green() + (c2.green() - c1.green()) * t
    b = c1.blue()  + (c2.blue()  - c1.blue())  * t
    a = c1.alpha() + (c2.alpha() - c1.alpha()) * t
    return QColor(int(r), int(g), int(b), int(a))


class DriveTogglerButton(QWidget):
    OUTER_R     = 26
    INNER_R     = 11
    WIDGET_SIZE = 56

    def __init__(self, parent):
        super().__init__(parent)
        self._p = parent
        self.setFixedSize(self.WIDGET_SIZE, self.WIDGET_SIZE)

        self._drag_pos   = QPoint()
        self._is_drag    = False
        self._hover_zone = None
        self._press_zone = None

        self._hover_inner_val = 0.0
        self._hover_left_val  = 0.0
        self._hover_right_val = 0.0

        self._press_inner_val = 0.0
        self._press_left_val  = 0.0
        self._press_right_val = 0.0

        self._pt = 0.0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(28)

        self.setMouseTracking(True)

    def _tick(self):
        self._pt = (self._pt + 0.062) % (2 * math.pi)
        
        ti = 1.0 if self._hover_zone == 'inner' else 0.0
        tl = 1.0 if self._hover_zone == 'left' else 0.0
        tr = 1.0 if self._hover_zone == 'right' else 0.0

        self._hover_inner_val += (ti - self._hover_inner_val) * 0.15
        self._hover_left_val  += (tl - self._hover_left_val) * 0.15
        self._hover_right_val += (tr - self._hover_right_val) * 0.15

        for zone, attr in [('inner', '_press_inner_val'), ('left', '_press_left_val'), ('right', '_press_right_val')]:
            current = getattr(self, attr)
            if self._press_zone == zone:
                setattr(self, attr, 1.0)
            else:
                new_val = current - 0.07
                if new_val < 0.0: new_val = 0.0
                setattr(self, attr, new_val)

        self.update()

    def _zone(self, pos):
        cx = cy = self.WIDGET_SIZE / 2
        dx, dy = pos.x() - cx, pos.y() - cy
        r = math.hypot(dx, dy)
        if r <= self.INNER_R:
            return 'inner'
        if r <= self.OUTER_R:
            return 'left' if dx < 0 else 'right'
        return None

    def paintEvent(self, _ev):
        try:
            self._paint_impl()
        except Exception as e:
            print(f"paintEvent error: {e}")

    def _paint_impl(self):
        p   = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        S   = self.WIDGET_SIZE
        cx  = cy = S / 2.0

        state_hidden = self._p.is_any_drive_hidden()
        
        if state_hidden:
            c_base  = QColor(38, 20, 20, 191)    
            c_hover = QColor(58, 30, 30, 217)    
            c_press = QColor(180, 50, 0, 204)   
            
            b_base  = QColor(255, 200, 200, 38)
            b_hover = QColor(230, 80, 50, 128)
            b_press = QColor(230, 80, 50, 255)
        else:
            c_base  = QColor(20, 38, 32, 191)
            c_hover = QColor(30, 58, 48, 217)
            c_press = QColor(0, 180, 120, 204)
            
            b_base  = QColor(200, 255, 230, 38)
            b_hover = QColor(0, 230, 150, 128)
            b_press = QColor(0, 230, 150, 255)

        def get_zone_color(hover_val, press_val):
            c = lerp_color(c_base, c_hover, hover_val)
            c = lerp_color(c, c_press, press_val)
            return c

        p.setPen(Qt.NoPen)
        
        left_color = get_zone_color(self._hover_left_val, self._press_left_val)
        p.setBrush(QBrush(left_color))
        p.drawPie(QRectF(cx - self.OUTER_R, cy - self.OUTER_R, self.OUTER_R * 2, self.OUTER_R * 2), 90 * 16, 180 * 16)
        
        right_color = get_zone_color(self._hover_right_val, self._press_right_val)
        p.setBrush(QBrush(right_color))
        p.drawPie(QRectF(cx - self.OUTER_R, cy - self.OUTER_R, self.OUTER_R * 2, self.OUTER_R * 2), 270 * 16, 180 * 16)

        div = QPen(QColor(255, 255, 255, 12))
        div.setWidthF(1.0)
        div.setStyle(Qt.DashLine)
        p.setPen(div)
        ie = self.INNER_R + 2.5
        oe = self.OUTER_R - 1.0
        p.drawLine(QPointF(cx, cy - oe), QPointF(cx, cy - ie))
        p.drawLine(QPointF(cx, cy + ie), QPointF(cx, cy + oe))

        sp = QPen(QColor(255, 255, 255, 15))
        sp.setWidthF(1.0)
        p.setPen(sp)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), self.INNER_R + 2, self.INNER_R + 2)

        inner_color = get_zone_color(self._hover_inner_val, self._press_inner_val)
        p.setBrush(QBrush(inner_color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), self.INNER_R, self.INNER_R)

        sw = QPen(QColor(255, 255, 255, 180))
        sw.setWidthF(1.8)
        sw.setCapStyle(Qt.RoundCap)
        p.setPen(sw)
        sa = 4.0
        if state_hidden:
            p.drawLine(QPointF(cx - sa, cy), QPointF(cx + sa, cy))
        else:
            p.drawLine(QPointF(cx - sa, cy), QPointF(cx + sa, cy))
            p.drawLine(QPointF(cx, cy - sa), QPointF(cx, cy + sa))

        is_locked = self._p.is_locked
        overall_hover = max(self._hover_left_val, self._hover_right_val, self._hover_inner_val)
        overall_press = max(self._press_left_val, self._press_right_val, self._press_inner_val)
        
        if is_locked:
            b_base_lock  = QColor(255, 165, 0, 153)
            b_hover_lock = QColor(255, 165, 0, 217)
            border_color = lerp_color(b_base_lock, b_hover_lock, overall_hover)
        else:
            border_color = lerp_color(b_base, b_hover, overall_hover)
            border_color = lerp_color(border_color, b_press, overall_press)

        b_pen = QPen(border_color)
        b_pen.setWidthF(2.0)
        p.setPen(b_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), self.OUTER_R, self.OUTER_R)

        p.end()

    def mouseMoveEvent(self, event):
        z = self._zone(event.pos())
        if z != self._hover_zone:
            self._hover_zone = z
            self.update()

        if event.buttons() & Qt.LeftButton and not self._p.is_locked:
            diff = event.globalPos() - (self._p.frameGeometry().topLeft() + self._drag_pos)
            if diff.manhattanLength() > 5:
                self._is_drag = True
            if self._is_drag:
                self._p.move(event.globalPos() - self._drag_pos)
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            mods = event.modifiers()
            if mods & Qt.AltModifier:
                QApplication.quit(); return
            if mods & Qt.ShiftModifier:
                self._p.toggle_lock(); event.accept(); return
            self._drag_pos  = event.globalPos() - self._p.frameGeometry().topLeft()
            self._is_drag   = False
            self._press_zone = self._zone(event.pos())
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            pz = self._press_zone
            self._press_zone = None
            self.update()
            if not self._is_drag:
                z = self._zone(event.pos())
                if z == pz:
                    if z == 'inner' or z == 'left' or z == 'right':
                        self._p.toggle_all_drives()
            self._is_drag = False
        event.accept()

    def leaveEvent(self, _ev):
        self._hover_zone = None
        self.update()


class DriveTogglerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        S = DriveTogglerButton.WIDGET_SIZE
        self.setFixedSize(S, S)
        self.setWindowTitle("Drive Toggler")

        self._idle_op  = 0.50
        self._hover_op = 0.90
        self.setWindowOpacity(self._idle_op)

        self.is_locked = False
        
        global SETTINGS_FILE
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        SETTINGS_FILE = os.path.join(base_path, 'settings.json')
        
        self.settings = load_settings()
        self.volumes = get_mountvol_info()
        self.update_settings_with_current_drives()

        self._btn = DriveTogglerButton(self)
        self._btn.move(0, 0)

        self._fade_target = self._idle_op
        self._fade_timer  = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._fade_step)

        self.drag_pos = QPoint()
        self.setMouseTracking(True)

        hwnd  = int(self.winId())
        style = _GetWindowLong(hwnd, GWL_EXSTYLE)
        _SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

        self._setup_tray()
        
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.refresh_drives)
        self._poll.start(2000)

    def update_settings_with_current_drives(self):
        updated = False
        for vol_id, mount_points in self.volumes.items():
            current_letter = mount_points[0] if mount_points else None
            if current_letter == 'C:':
                continue
            if current_letter:
                if vol_id not in self.settings or self.settings[vol_id] != current_letter:
                    self.settings[vol_id] = current_letter
                    updated = True
        if updated:
            save_settings(self.settings)

    def refresh_drives(self):
        self.volumes = get_mountvol_info()
        self.update_settings_with_current_drives()
        self._btn.update()

    def is_any_drive_hidden(self):
        for vol_id, letter in self.settings.items():
            if letter == 'C:':
                continue
            mount_points = self.volumes.get(vol_id, [])
            if letter not in mount_points:
                return True
        return False

    def toggle_all_drives(self):
        hidden_any = self.is_any_drive_hidden()
        
        for vol_id, letter in self.settings.items():
            if letter == 'C:':
                continue
            mount_points = self.volumes.get(vol_id, [])
            is_hidden = letter not in mount_points
            
            if hidden_any and is_hidden:
                self.restore_drive(vol_id, letter)
            elif not hidden_any and not is_hidden:
                self.hide_drive(letter)
        
        self.refresh_drives()

    def hide_drive(self, letter):
        try:
            cmd = ['mountvol', f"{letter}\\", '/D']
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"Hidden drive {letter}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to hide drive {letter}:\n{e}")

    def restore_drive(self, vol_id, letter):
        try:
            cmd = ['mountvol', f"{letter}\\", vol_id]
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"Restored drive {letter}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to restore drive {letter}:\n{e}")

    def _fade_to(self, target: float):
        self._fade_target = target
        if not self._fade_timer.isActive():
            self._fade_timer.start()

    def _fade_step(self):
        cur = self.windowOpacity()
        diff = self._fade_target - cur
        if abs(diff) < 0.02:
            self.setWindowOpacity(self._fade_target)
            self._fade_timer.stop()
        else:
            self.setWindowOpacity(cur + diff * 0.15)

    def enterEvent(self, e):
        self._fade_to(self._hover_op); super().enterEvent(e)

    def leaveEvent(self, e):
        self._fade_to(self._idle_op); super().leaveEvent(e)

    def toggle_lock(self):
        self.is_locked = not self.is_locked
        s = "locked" if self.is_locked else "unlocked"
        print(f"Position {s}")
        if hasattr(self, '_tray'):
            self._tray.showMessage("Drive Toggler", f"Position {s}.", QSystemTrayIcon.Information, 1500)
        self._btn.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_locked:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and not self.is_locked:
            self.move(event.globalPos() - self.drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event): event.accept()
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.populate_menu(menu)
        menu.exec_(event.globalPos())

    def populate_menu(self, menu):
        for vol_id, letter in self.settings.items():
            if letter == 'C:':
                continue
            mount_points = self.volumes.get(vol_id, [])
            is_hidden = letter not in mount_points
            
            action_text = f"Restore Drive {letter}" if is_hidden else f"Hide Drive {letter}"
            action = QAction(action_text, self)
            
            if is_hidden:
                action.triggered.connect(lambda checked, v=vol_id, l=letter: (self.restore_drive(v, l), self.refresh_drives()))
            else:
                action.triggered.connect(lambda checked, l=letter: (self.hide_drive(l), self.refresh_drives()))
            menu.addAction(action)

        if not self.settings:
            a = QAction("No toggleable drives", self)
            a.setEnabled(False)
            menu.addAction(a)

        menu.addSeparator()

        tv = QAction("Hide / Show", self)
        tv.triggered.connect(self._toggle_vis)
        menu.addAction(tv)

        la = QAction("Toggle Lock", self)
        la.triggered.connect(self.toggle_lock)
        menu.addAction(la)
        
        menu.addSeparator()

        qa = QAction("Quit", self)
        qa.triggered.connect(QApplication.quit)
        menu.addAction(qa)

    def _setup_tray(self):
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        pp = QPainter(pix)
        pp.setRenderHint(QPainter.Antialiasing)
        pp.setBrush(QBrush(QColor(230, 80, 50)))
        pp.setPen(Qt.NoPen)
        pp.drawEllipse(2, 2, 12, 12)
        pp.end()

        self._tray = QSystemTrayIcon(QIcon(pix), self)
        self._tray.setToolTip("Drive Toggler")

        self.tray_menu = QMenu()
        self._tray.setContextMenu(self.tray_menu)
        
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_vis()
        elif reason == QSystemTrayIcon.Context:
            self.tray_menu.clear()
            self.populate_menu(self.tray_menu)

    def _toggle_vis(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

def main():
    if not is_admin():
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([script] + sys.argv[1:])
        try:
            if getattr(sys, 'frozen', False):
                executable = sys.executable
                params = ' '.join(sys.argv[1:])
            else:
                executable = sys.executable
            ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        except Exception as e:
            print(f"Failed to elevate privileges: {e}")
        sys.exit()

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setQuitOnLastWindowClosed(False)

    w = DriveTogglerWidget()
    scr = QApplication.primaryScreen().geometry()
    w.move(scr.width() - 80, scr.height() - 250)
    w.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
