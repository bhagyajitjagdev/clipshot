import gi
import subprocess
import os
import sys
import secrets
import shutil
import tempfile
from datetime import datetime

TMP_DIR = os.path.join(tempfile.gettempdir(), "clipshot")

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib

from clipshot.config import Config


def capture_screen(callback):
    """Silently capture screen via XDG portal, invoke callback(path) on success."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    token = "clipshot_" + secrets.token_hex(8)
    sender = bus.get_unique_name().replace(".", "_").lstrip(":")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    def on_response(conn, sender_name, obj_path, iface, signal, params):
        bus.signal_unsubscribe(sub_id)
        response, results = params.unpack()
        if response == 0:
            uri = results.get("uri", "")
            portal_path = uri.replace("file://", "") if uri.startswith("file://") else None
            if portal_path and os.path.exists(portal_path):
                os.makedirs(TMP_DIR, exist_ok=True)
                tmp_path = os.path.join(TMP_DIR, os.path.basename(portal_path))
                shutil.move(portal_path, tmp_path)
                callback(tmp_path)
            else:
                callback(portal_path)
        else:
            callback(None)

    sub_id = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop",
        "org.freedesktop.portal.Request",
        "Response",
        request_path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )

    bus.call_sync(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Screenshot",
        "Screenshot",
        GLib.Variant(
            "(sa{sv})",
            (
                "",
                {
                    "interactive": GLib.Variant("b", False),
                    "handle_token": GLib.Variant("s", token),
                },
            ),
        ),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )


class OverlayWindow(Gtk.Window):
    def __init__(self, app, config):
        super().__init__(application=app)
        self._config = config
        self._pixbuf = None
        self._screenshot_path = None
        self._start = None
        self._end = None
        self._saved_rect = None  # locked-in selection for actions
        self._action_taken = False

        self.set_decorated(False)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)
        self.set_child(self._drawing_area)

        # Drag gesture for selection
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._drawing_area.add_controller(drag)

        # Escape to cancel
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Context menu
        self._build_menu()

    def _build_menu(self):
        menu = Gio.Menu()
        menu.append("Save", "win.save")
        menu.append("Save and copy path", "win.save-copy-path")
        menu.append("Save and copy image", "win.save-copy-image")
        menu.append("Copy image", "win.copy-image")

        action_group = Gio.SimpleActionGroup()
        actions = [
            ("save", self._action_save),
            ("save-copy-path", self._action_save_copy_path),
            ("save-copy-image", self._action_save_copy_image),
            ("copy-image", self._action_copy_image),
        ]
        for name, handler in actions:
            action = Gio.SimpleAction(name=name)
            action.connect("activate", lambda a, p, h=handler: h())
            action_group.add_action(action)
        self.insert_action_group("win", action_group)

        self._popover = Gtk.PopoverMenu(menu_model=menu)
        self._popover.set_parent(self._drawing_area)
        self._popover.set_has_arrow(False)
        self._popover.connect("closed", self._on_popover_closed)

    def show_with_screenshot(self, path):
        if path is None:
            self.get_application().quit()
            return
        self._screenshot_path = path
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        self._drawing_area.set_content_width(self._pixbuf.get_width())
        self._drawing_area.set_content_height(self._pixbuf.get_height())
        self.fullscreen()
        self.present()

    def _on_draw(self, area, cr, width, height):
        if not self._pixbuf:
            return

        # Paint full screenshot
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()

        if self._start and self._end:
            rect = self._get_selection_rect()
            if rect:
                x, y, w, h = rect

                # Dark overlay
                cr.set_source_rgba(0, 0, 0, 0.45)
                cr.paint()

                # Punch through: re-paint screenshot in selection area
                cr.save()
                cr.rectangle(x, y, w, h)
                cr.clip()
                Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
                cr.paint()
                cr.restore()

                # Selection border
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.set_line_width(1.5)
                cr.set_dash([6, 4])
                cr.rectangle(x, y, w, h)
                cr.stroke()
        else:
            # Subtle dim to indicate ready state
            cr.set_source_rgba(0, 0, 0, 0.15)
            cr.paint()

    def _on_drag_begin(self, gesture, start_x, start_y):
        self._popover.popdown()
        self._start = (start_x, start_y)
        self._end = (start_x, start_y)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        self._end = (self._start[0] + offset_x, self._start[1] + offset_y)
        self._drawing_area.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        self._end = (self._start[0] + offset_x, self._start[1] + offset_y)
        self._drawing_area.queue_draw()

        rect = self._get_selection_rect()
        if not rect or rect[2] < 5 or rect[3] < 5:
            self._start = None
            self._end = None
            self._drawing_area.queue_draw()
            return

        # Lock in selection before showing menu
        self._saved_rect = rect
        self._action_taken = False

        # Show context menu at mouse release position
        mx, my = int(self._end[0]), int(self._end[1])
        r = Gdk.Rectangle()
        r.x, r.y, r.width, r.height = mx, my, 1, 1
        self._popover.set_pointing_to(r)
        self._popover.popup()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self._cleanup_tmp()
            self.get_application().quit()
            return True
        return False

    def _on_popover_closed(self, popover):
        if self._action_taken:
            return
        # No action picked — reset so user can drag again
        self._start = None
        self._end = None
        self._drawing_area.queue_draw()
        # Defer clearing saved_rect so actions can still use it
        GLib.idle_add(self._maybe_clear_saved_rect)

    def _maybe_clear_saved_rect(self):
        if not self._action_taken:
            self._saved_rect = None
        return False

    def _get_selection_rect(self):
        if not self._start or not self._end:
            return None
        x1, y1 = self._start
        x2, y2 = self._end
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return (int(x), int(y), int(w), int(h))

    def _get_cropped_pixbuf(self):
        rect = self._saved_rect or self._get_selection_rect()
        if not rect:
            return None
        x, y, w, h = rect
        # Clamp to pixbuf bounds
        pw, ph = self._pixbuf.get_width(), self._pixbuf.get_height()
        x = max(0, min(x, pw - 1))
        y = max(0, min(y, ph - 1))
        w = min(w, pw - x)
        h = min(h, ph - y)
        if w <= 0 or h <= 0:
            return None
        return self._pixbuf.new_subpixbuf(x, y, w, h)

    def _generate_filepath(self):
        self._config.save_directory.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._config.save_directory / f"clipshot_{ts}.png"

    def _save_cropped(self):
        cropped = self._get_cropped_pixbuf()
        if not cropped:
            return None
        path = self._generate_filepath()
        cropped.savev(str(path), "png", [], [])
        return path

    def _get_cropped_png_bytes(self):
        cropped = self._get_cropped_pixbuf()
        if not cropped:
            return None
        success, buf = cropped.save_to_bufferv("png", [], [])
        return buf if success else None

    def _notify(self, title, body=""):
        subprocess.Popen(
            ["notify-send", "-a", "Clipshot", "-i", "camera-photo-symbolic", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _cleanup_tmp(self):
        if self._screenshot_path:
            try:
                os.unlink(self._screenshot_path)
            except OSError:
                pass

    def _finish(self):
        self._cleanup_tmp()
        self.get_application().quit()

    def _action_save(self):
        self._action_taken = True
        path = self._save_cropped()
        if path:
            self._notify("Screenshot saved", str(path))
        self._finish()

    def _copy_to_clipboard(self, data, mime_type=None):
        """Copy data to clipboard via wl-copy. Runs detached so it outlives us."""
        cmd = ["wl-copy"]
        if mime_type:
            cmd += ["--type", mime_type]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(data, str):
            data = data.encode()
        proc.stdin.write(data)
        proc.stdin.close()

    def _action_save_copy_path(self):
        self._action_taken = True
        path = self._save_cropped()
        if path:
            self._copy_to_clipboard(str(path))
            self._notify("Saved & path copied", str(path))
        self._finish()

    def _action_save_copy_image(self):
        self._action_taken = True
        path = self._save_cropped()
        png_bytes = self._get_cropped_png_bytes()
        if png_bytes:
            self._copy_to_clipboard(png_bytes, "image/png")
        if path:
            self._notify("Saved & image copied", str(path))
        self._finish()

    def _action_copy_image(self):
        self._action_taken = True
        png_bytes = self._get_cropped_png_bytes()
        if png_bytes:
            self._copy_to_clipboard(png_bytes, "image/png")
            self._notify("Image copied", "Copied to clipboard as PNG")
        self._finish()


class ClipshotApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="dev.clipshot.app",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )

    def do_activate(self):
        config = Config.load()
        window = OverlayWindow(self, config)
        capture_screen(window.show_with_screenshot)


def run():
    app = ClipshotApp()
    app.run(None)


if __name__ == "__main__":
    run()
