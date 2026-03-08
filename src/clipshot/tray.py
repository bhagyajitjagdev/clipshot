import gi
import subprocess
import sys
import os

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, AppIndicator3, Gio, GLib

from clipshot.config import Config, KEYBIND_BASE, KEYBIND_PATH_REGION, KEYBIND_PATH_FULLSCREEN

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
        # Follow system dark/light theme
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            result = bus.call_sync(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings",
                "Read",
                GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                None, Gio.DBusCallFlags.NONE, 500, None,
            )
            # 1 = prefer dark, 2 = prefer light, 0 = no preference
            scheme = result.unpack()[0]
            is_dark = scheme == 1
        except Exception:
            is_dark = False
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", is_dark)

        self._config = Config.load()
        self._setup_indicator()
        self._sync_keybindings()
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

        # Region screenshot
        region_shortcut = self._format_shortcut(self._config.shortcut_region)
        item_region = Gtk.MenuItem(label=f"Take Region Screenshot ({region_shortcut})")
        item_region.connect("activate", self._on_take_region)
        menu.append(item_region)

        # Fullscreen capture
        fullscreen_shortcut = self._format_shortcut(self._config.shortcut_fullscreen)
        item_fullscreen = Gtk.MenuItem(label=f"Fullscreen Capture ({fullscreen_shortcut})")
        item_fullscreen.connect("activate", self._on_take_fullscreen)
        menu.append(item_fullscreen)

        menu.append(Gtk.SeparatorMenuItem())

        # Open save folder
        item_open_dir = Gtk.MenuItem(label="Open Screenshots Folder")
        item_open_dir.connect("activate", self._on_open_save_dir)
        menu.append(item_open_dir)

        # Save location
        item_save_dir = Gtk.MenuItem(
            label=f"Save to: {self._config.save_directory}"
        )
        item_save_dir.connect("activate", self._on_change_save_dir)
        menu.append(item_save_dir)

        # Shortcuts
        item_shortcuts = Gtk.MenuItem(label="Keyboard Shortcuts")
        item_shortcuts.connect("activate", self._on_edit_shortcuts)
        menu.append(item_shortcuts)

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

    def _on_take_region(self, _):
        subprocess.Popen(
            [CAPTURE_SHELL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _on_take_fullscreen(self, _):
        subprocess.Popen(
            [CAPTURE_SHELL, "--fullscreen"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _on_open_save_dir(self, _):
        path = str(self._config.save_directory)
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    def _on_edit_shortcuts(self, _):
        dialog = Gtk.Dialog(
            title="Keyboard Shortcuts",
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.set_default_size(420, 200)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK,
        )

        box = dialog.get_content_area()
        box.set_spacing(16)
        box.set_margin_top(16)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)

        shortcuts = {
            "region": self._config.shortcut_region,
            "fullscreen": self._config.shortcut_fullscreen,
        }

        # Region shortcut row
        row_region = self._shortcut_row(
            "Region Screenshot", shortcuts, "region"
        )
        box.add(row_region)

        # Fullscreen shortcut row
        row_fullscreen = self._shortcut_row(
            "Fullscreen Capture", shortcuts, "fullscreen"
        )
        box.add(row_fullscreen)

        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.OK:
            self._config.shortcut_region = shortcuts["region"]
            self._config.shortcut_fullscreen = shortcuts["fullscreen"]
            self._config.save()
            self._sync_keybindings()
            self._rebuild_menu()

        dialog.destroy()

    def _shortcut_row(self, label_text, shortcuts_dict, key):
        """Create a row with label and a button to capture a shortcut."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        row.pack_start(label, True, True, 0)

        btn = Gtk.Button(label=self._format_shortcut(shortcuts_dict[key]))
        btn.set_size_request(160, -1)

        def on_clicked(button):
            self._capture_shortcut(button, shortcuts_dict, key)

        btn.connect("clicked", on_clicked)
        row.pack_end(btn, False, False, 0)

        return row

    def _capture_shortcut(self, button, shortcuts_dict, key):
        """Replace button label with 'Press a key...' and capture next keypress."""
        button.set_label("Press a key...")
        button.set_sensitive(False)

        def on_key(widget, event):
            mods = event.state & Gtk.accelerator_get_default_mod_mask()
            keyval = event.keyval
            # Ignore bare modifier keys
            if keyval in (
                65505, 65506,  # Shift
                65507, 65508,  # Ctrl
                65513, 65514,  # Alt
                65515, 65516,  # Super
            ):
                return False

            accel = Gtk.accelerator_name(keyval, mods)
            if accel:
                shortcuts_dict[key] = accel
                button.set_label(self._format_shortcut(accel))

            button.set_sensitive(True)
            dialog.disconnect(handler_id)
            return True

        dialog = button.get_toplevel()
        handler_id = dialog.connect("key-press-event", on_key)

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

    # --- Keybindings ---

    def _sync_keybindings(self):
        """Register/update all GNOME custom keybindings."""
        try:
            settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
            current = settings.get_strv("custom-keybindings")
            changed = False
            for path in (KEYBIND_PATH_REGION, KEYBIND_PATH_FULLSCREEN):
                if path not in current:
                    current.append(path)
                    changed = True
            if changed:
                settings.set_strv("custom-keybindings", current)

            # Region
            kb = Gio.Settings.new_with_path(
                "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
                KEYBIND_PATH_REGION,
            )
            kb.set_string("name", "Clipshot Region")
            kb.set_string("command", CAPTURE_SHELL)
            kb.set_string("binding", self._config.shortcut_region)

            # Fullscreen
            kb = Gio.Settings.new_with_path(
                "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
                KEYBIND_PATH_FULLSCREEN,
            )
            kb.set_string("name", "Clipshot Fullscreen")
            kb.set_string("command", f"{CAPTURE_SHELL} --fullscreen")
            kb.set_string("binding", self._config.shortcut_fullscreen)

            Gio.Settings.sync()
        except Exception:
            pass


def main():
    tray = ClipshotTray()
    Gtk.main()


if __name__ == "__main__":
    main()
