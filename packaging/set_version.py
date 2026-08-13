"""Update all release-facing version declarations."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def replace(path: Path, pattern: str, replacement: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, original, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Could not update version in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2 or not VERSION_PATTERN.fullmatch(sys.argv[1]):
        print("usage: set_version.py MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2

    version = sys.argv[1]
    replace(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace(
        ROOT / "src/nzb_compass/__init__.py",
        r'^__version__ = "[^"]+"',
        f'__version__ = "{version}"',
    )
    replace(ROOT / "packaging/arch/PKGBUILD", r"^pkgver=\S+", f"pkgver={version}")
    print(f"Updated NZB Compass to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
