import tomllib
import os
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_DIR = Path.home() / ".config" / "clipshot"
CONFIG_FILE = CONFIG_DIR / "config.toml"

KEYBIND_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
KEYBIND_PATH_REGION = f"{KEYBIND_BASE}/clipshot-region/"
KEYBIND_PATH_FULLSCREEN = f"{KEYBIND_BASE}/clipshot-fullscreen/"


@dataclass
class Config:
    save_directory: Path = field(
        default_factory=lambda: Path.home() / "Pictures" / "Screenshots"
    )
    shortcut_region: str = "<Super>u"
    shortcut_fullscreen: str = "<Super>i"

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
            return cls(
                save_directory=Path(
                    data.get("save_directory", str(Path.home() / "Pictures" / "Screenshots"))
                ),
                shortcut_region=data.get("shortcut_region", "<Super>u"),
                shortcut_fullscreen=data.get("shortcut_fullscreen", "<Super>i"),
            )
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return cls()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            f.write(f'save_directory = "{self.save_directory}"\n')
            f.write(f'shortcut_region = "{self.shortcut_region}"\n')
            f.write(f'shortcut_fullscreen = "{self.shortcut_fullscreen}"\n')
