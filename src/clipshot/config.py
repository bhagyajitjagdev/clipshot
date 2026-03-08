import tomllib
import os
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_DIR = Path.home() / ".config" / "clipshot"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULTS = {
    "save_directory": str(Path.home() / "Pictures" / "Screenshots"),
    "shortcut": "<Super>u",
}

KEYBIND_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
KEYBIND_PATH = f"{KEYBIND_BASE}/clipshot/"


@dataclass
class Config:
    save_directory: Path = field(
        default_factory=lambda: Path.home() / "Pictures" / "Screenshots"
    )
    shortcut: str = "<Super>u"

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
            return cls(
                save_directory=Path(
                    data.get("save_directory", DEFAULTS["save_directory"])
                ),
                shortcut=data.get("shortcut", DEFAULTS["shortcut"]),
            )
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return cls()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            f.write(f'save_directory = "{self.save_directory}"\n')
            f.write(f'shortcut = "{self.shortcut}"\n')
