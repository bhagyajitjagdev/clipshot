# Clipshot

A native Wayland screenshot tool for GNOME. No hacks, no X11 fallbacks — just the XDG Desktop Portal and GTK.

Clipshot gives you a ShareX/ksnip-style workflow on Wayland: press a shortcut, drag to select, pick an action.

## Features

- **Drag-to-select** — freeze the screen, drag a region, get a context menu
- **Copy or save** — copy image to clipboard, save to disk, or both
- **System tray** — always accessible, configure from the tray menu
- **Keyboard shortcut** — `Super+U` by default, changeable from the tray
- **Autostart** — starts on login automatically
- **Native Wayland** — uses the XDG Desktop Portal, works without any workarounds

### Context Menu Actions

After selecting a region, a menu appears at your cursor:

| Action | What it does |
|--------|-------------|
| Save | Save cropped PNG to `~/Pictures/Screenshots/` |
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

That's it. The tray icon appears, the keyboard shortcut is registered, and autostart is enabled.

## Usage

### Take a screenshot

1. Press `Super+U` (or click the tray icon → Take Screenshot)
2. The screen freezes with a slight dim overlay
3. Drag to select a region
4. Pick an action from the context menu
5. Done — a notification confirms the action

### Cancel

Press `Escape` at any time to cancel. You can also dismiss the context menu and re-drag to select a different region.

### Change settings

Click the tray icon to access:

- **Save to:** — change where screenshots are saved
- **Shortcut:** — press a new key combination to rebind
- **Start on login** — toggle autostart

Settings are stored in `~/.config/clipshot/config.toml`.

## How it Works

Clipshot uses the **XDG Desktop Portal** (`org.freedesktop.portal.Screenshot`) with `interactive: false` to silently capture the screen. The capture is loaded into a fullscreen GTK4 overlay where you select a region. The cropped image is saved/copied via `wl-copy`.

The app runs as two processes:
- **Tray** (GTK3 + AppIndicator3) — persistent, manages settings and shortcuts
- **Capture** (GTK4) — spawned per screenshot, exits after action

This split exists because AppIndicator3 requires GTK3, while the overlay uses GTK4 for native Wayland support. GTK3 and GTK4 can't coexist in one process.

For more details on the architecture and design decisions, see the project's issue tracker and discussions.

## Configuration

Config file: `~/.config/clipshot/config.toml`

```toml
save_directory = "/home/you/Pictures/Screenshots"
shortcut = "<Super>u"
```

## Roadmap

Upcoming:

- Selection dimensions display while dragging
- Crosshair guides for alignment
- Fullscreen and window capture modes
- Delay/timer capture
- Multi-monitor support
- Annotation tools
- Capture history

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## License

[MIT](LICENSE)
