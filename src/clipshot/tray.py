import gi
import subprocess
import sys
import os

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, AppIndicator3, Gio, GLib

from clipshot.config import Config, KEYBIND_BASE, KEYBIND_PATH

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPTURE_SHELL = os.path.join(PROJECT_ROOT, "clipshot.sh")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "clipshot.desktop")
DESKTOP_ENTRY = f"""[Desktop Entry]
Type=Application
Name=Clipshot
Comment=Screenshot tool for Wayland
Exec={sys.executable} {os.path.join(PROJECT_ROOT, 'main.py')}
Icon=camera-photo-symbolic
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
"""


class ClipshotTray:
    def __init__(self):
        self._config = Config.load()
        self._setup_indicator()
        self._sync_keybinding()
        self._ensure_autostart()

    def _setup_indicator(self):
        self._indicator = AppIndicator3.Indicator.new(
            "clipshot",
            "camera-photo-symbolic",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title("Clipshot")
        self._rebuild_menu()

    def _rebuild_menu(self):
        menu = Gtk.Menu()

        # Take Screenshot
        item_capture = Gtk.MenuItem(label="Take Screenshot")
        item_capture.connect("activate", self._on_take_screenshot)
        menu.append(item_capture)

        menu.append(Gtk.SeparatorMenuItem())

        # Save location
        item_save_dir = Gtk.MenuItem(
            label=f"Save to: {self._config.save_directory}"
        )
        item_save_dir.connect("activate", self._on_change_save_dir)
        menu.append(item_save_dir)

        # Shortcut
        item_shortcut = Gtk.MenuItem(
            label=f"Shortcut: {self._format_shortcut(self._config.shortcut)}"
        )
        item_shortcut.connect("activate", self._on_change_shortcut)
        menu.append(item_shortcut)

        menu.append(Gtk.SeparatorMenuItem())

        # Autostart toggle
        item_autostart = Gtk.CheckMenuItem(label="Start on login")
        item_autostart.set_active(os.path.exists(AUTOSTART_FILE))
        item_autostart.connect("toggled", self._on_toggle_autostart)
        menu.append(item_autostart)

        menu.append(Gtk.SeparatorMenuItem())

        # Quit
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        menu.append(item_quit)

        menu.show_all()
        self._indicator.set_menu(menu)

    def _format_shortcut(self, shortcut):
        return (
            shortcut.replace("<Ctrl>", "Ctrl+")
            .replace("<Shift>", "Shift+")
            .replace("<Alt>", "Alt+")
            .replace("<Super>", "Super+")
            .replace("Print", "PrtSc")
        )

    # --- Actions ---

    def _on_take_screenshot(self, _):
        subprocess.Popen(
            [CAPTURE_SHELL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _on_change_save_dir(self, _):
        dialog = Gtk.FileChooserDialog(
            title="Choose save directory",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        dialog.set_current_folder(str(self._config.save_directory))

        if dialog.run() == Gtk.ResponseType.OK:
            self._config.save_directory = dialog.get_filename()
            self._config.save()
            self._rebuild_menu()

        dialog.destroy()

    def _on_change_shortcut(self, _):
        dialog = Gtk.Dialog(
            title="Set Shortcut",
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.set_default_size(350, 120)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        )

        box = dialog.get_content_area()
        box.set_spacing(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label = Gtk.Label(label="Press the desired key combination...")
        label.set_halign(Gtk.Align.CENTER)
        box.add(label)

        current_label = Gtk.Label()
        current_label.set_markup(
            f"<small>Current: {self._format_shortcut(self._config.shortcut)}</small>"
        )
        current_label.set_halign(Gtk.Align.CENTER)
        box.add(current_label)

        captured = {}

        def on_key(widget, event):
            mods = event.state & Gtk.accelerator_get_default_mod_mask()
            keyval = event.keyval
            if keyval in (
                65505, 65506,  # Shift
                65507, 65508,  # Ctrl
                65513, 65514,  # Alt
                65515, 65516,  # Super
            ):
                return False

            accel = Gtk.accelerator_name(keyval, mods)
            if accel:
                captured["shortcut"] = accel
                label.set_text(
                    f"Captured: {self._format_shortcut(accel)}"
                )
                dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
            return True

        dialog.connect("key-press-event", on_key)
        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.OK and "shortcut" in captured:
            self._config.shortcut = captured["shortcut"]
            self._config.save()
            self._sync_keybinding()
            self._rebuild_menu()

        dialog.destroy()

    def _on_toggle_autostart(self, widget):
        if widget.get_active():
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            with open(AUTOSTART_FILE, "w") as f:
                f.write(DESKTOP_ENTRY)
        else:
            try:
                os.unlink(AUTOSTART_FILE)
            except OSError:
                pass

    def _ensure_autostart(self):
        if not os.path.exists(AUTOSTART_FILE):
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            with open(AUTOSTART_FILE, "w") as f:
                f.write(DESKTOP_ENTRY)

    def _on_quit(self, _):
        Gtk.main_quit()

    # --- Keybinding ---

    def _sync_keybinding(self):
        """Register/update the GNOME custom keybinding."""
        try:
            settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
            current = settings.get_strv("custom-keybindings")
            if KEYBIND_PATH not in current:
                current.append(KEYBIND_PATH)
                settings.set_strv("custom-keybindings", current)

            kb = Gio.Settings.new_with_path(
                "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
                KEYBIND_PATH,
            )
            kb.set_string("name", "Clipshot")
            kb.set_string("command", CAPTURE_SHELL)
            kb.set_string("binding", self._config.shortcut)
            Gio.Settings.sync()
        except Exception:
            pass


def main():
    tray = ClipshotTray()
    Gtk.main()


if __name__ == "__main__":
    main()
