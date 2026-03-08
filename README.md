# Clipshot

A native Wayland screenshot tool for GNOME. No hacks, no X11 fallbacks — just the XDG Desktop Portal and GTK.

Clipshot gives you a ShareX/ksnip-style workflow on Wayland: press a shortcut, drag to select, pick an action.

## Features

- **Drag-to-select** — freeze the screen, drag a region, get a context menu
- **Fullscreen capture** — capture the entire screen with one shortcut
- **Copy or save** — copy image to clipboard, save to disk, or both
- **Selection helpers** — crosshair guides for alignment, live W×H dimensions while dragging
- **System tray** — always accessible, configure from the tray menu
- **Keyboard shortcuts** — `Super+U` for region, `Super+I` for fullscreen, all configurable
- **Autostart** — starts on login automatically
- **Native Wayland** — uses the XDG Desktop Portal, works without any workarounds

### Context Menu Actions

After selecting a region (or on fullscreen capture), a menu appears:

| Action | What it does |
|--------|-------------|
| Save | Save PNG to `~/Pictures/Screenshots/` |
| Save and copy path | Save + copy file path to clipboard |
| Save and copy image | Save + copy image to clipboard |
| Copy image | Copy image to clipboard (no file saved) |

## Install

### Prerequisites

Fedora 43+ with GNOME on Wayland (other distros may work but are untested).

```bash
# Install system dependencies
sudo dnf install python3-gobject gtk4 gtk3 libappindicator-gtk3 wl-clipboard
```

You also need the [AppIndicator GNOME extension](https://extensions.gnome.org/extension/615/appindicator-support/) for the system tray icon.

### Setup

```bash
git clone https://github.com/bhagyajitjagdev/clipshot.git
cd clipshot

# Start Clipshot
python3 main.py
```

That's it. The tray icon appears, keyboard shortcuts are registered, and autostart is enabled.

## Usage

### Region screenshot

1. Press `Super+U` (or click the tray icon → Take Region Screenshot)
2. The screen freezes — crosshair guides follow your cursor
3. Drag to select a region (dimensions shown while dragging)
4. Pick an action from the context menu
5. Done — a notification confirms the action

### Fullscreen capture

1. Press `Super+I` (or click the tray icon → Fullscreen Capture)
2. The screen captures and a context menu appears at center
3. Pick an action

### Cancel

Press `Escape` at any time to cancel. You can also dismiss the context menu and re-drag to select a different region.

### Tray menu

Click the tray icon to access:

- **Take Region Screenshot (Super+U)** — drag to select
- **Fullscreen Capture (Super+I)** — capture entire screen
- **Open Screenshots Folder** — open save directory in file manager
- **Save to:** — change where screenshots are saved
- **Keyboard Shortcuts** — edit all shortcuts in one dialog
- **Start on login** — toggle autostart
- **Quit**

## Configuration

Config file: `~/.config/clipshot/config.toml`

```toml
save_directory = "/home/you/Pictures/Screenshots"
shortcut_region = "<Super>u"
shortcut_fullscreen = "<Super>i"
```

## How it Works

Clipshot uses the **XDG Desktop Portal** (`org.freedesktop.portal.Screenshot`) with `interactive: false` to silently capture the screen. The capture is loaded into a fullscreen GTK4 overlay where you select a region. The cropped image is saved/copied via `wl-copy`.

The app runs as two processes:
- **Tray** (GTK3 + AppIndicator3) — persistent, manages settings and shortcuts
- **Capture** (GTK4) — spawned per screenshot, exits after action

This split exists because AppIndicator3 requires GTK3, while the overlay uses GTK4 for native Wayland support. GTK3 and GTK4 can't coexist in one process.

## Roadmap

Upcoming:

- Delay/timer capture
- Active window capture
- Multi-monitor support
- Annotation tools
- Capture history

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## License

[MIT](LICENSE)
