from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Settings:
    prowlarr_url: str = "http://localhost:9696"
    prowlarr_api_key: str = ""
    sabnzbd_url: str = "http://localhost:8080"
    sabnzbd_api_key: str = ""
    sabnzbd_category: str = ""
    sabnzbd_priority: int = -100
    sabnzbd_post_processing: int = -1
    disabled_indexer_ids: list[int] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in values.items() if key in allowed})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "nzb-compass" / "config.json"
