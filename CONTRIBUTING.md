# Contributing to Clipshot

Thanks for your interest in contributing to Clipshot! This guide will help you get started.

## Development Setup

### Prerequisites

- Fedora 43+ (or any distro with GNOME 48+ on Wayland)
- Python 3.13+
- System packages:

```bash
# Fedora
sudo dnf install python3-gobject gtk4 gtk3 libappindicator-gtk3 wl-clipboard

# Ubuntu/Debian (untested)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 wl-clipboard
```

- GNOME Shell extension: [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/)

### Running Locally

```bash
git clone https://github.com/bhagyajitjagdev/clipshot.git
cd clipshot

# Start the tray app
python3 main.py

# Or run capture directly (without tray)
python3 clipshot.py
```

No virtual environment needed — Clipshot uses system PyGObject packages which aren't pip-installable.

## Project Structure

```
clipshot/
├── main.py        # Entry point — launches the tray
├── tray.py        # System tray (GTK3 + AppIndicator3)
├── clipshot.py    # Capture overlay (GTK4)
├── config.py      # Shared configuration
└── clipshot.sh    # Shell wrapper for GNOME keybinding
```

Key architectural constraint: **GTK3 and GTK4 cannot coexist in the same process.** The tray (AppIndicator3) requires GTK3, while the overlay uses GTK4. This is why there are two separate processes.

The two-process split is the most important architectural detail to understand before contributing.

## How to Contribute

### Reporting Bugs

- Open an issue with steps to reproduce
- Include your distro, GNOME version, and Wayland compositor
- Paste any terminal output from running `python3 main.py`

### Suggesting Features

- Open an issue describing the feature and why it's useful
- If it's a capture mode or UI change, a mockup/sketch helps

### Submitting Code

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test manually — run `python3 main.py` and verify the full flow:
   - Tray icon appears
   - Take Screenshot works (drag, select action, verify result)
   - Keyboard shortcut works
   - Settings changes persist
5. Commit with a clear message
6. Open a pull request

### Code Style

- Standard Python — no formatter enforced yet, just keep it clean
- No external pip dependencies — everything must work with system packages + stdlib
- Keep the two-process boundary clean: tray (GTK3) never imports GTK4, capture (GTK4) never imports GTK3
- `config.py` is the shared module between both processes

### Areas Where Help is Wanted

Good first contributions:

- **Selection dimensions display** (Phase 1.1) — show W×H while dragging
- **Crosshair guides** (Phase 1.2) — cursor guidelines before drag
- **Fullscreen capture** (Phase 2.1) — capture without selection overlay
- **Testing on other distros** — Ubuntu, Arch, openSUSE with GNOME Wayland
- **Bug reports** — especially around multi-monitor setups

## Questions?

Open an issue or start a discussion. No question is too small.
