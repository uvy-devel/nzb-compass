"""Ensure release-facing version declarations agree."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def declared_versions() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (ROOT / "src/nzb_compass/__init__.py").read_text(encoding="utf-8")
    pkgbuild = (ROOT / "packaging/arch/PKGBUILD").read_text(encoding="utf-8")

    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    pkgbuild_match = re.search(r"^pkgver=([^\s]+)", pkgbuild, re.MULTILINE)
    if not init_match or not pkgbuild_match:
        raise RuntimeError("Could not read every version declaration")

    return {
        "pyproject.toml": str(project["project"]["version"]),
        "src/nzb_compass/__init__.py": init_match.group(1),
        "packaging/arch/PKGBUILD": pkgbuild_match.group(1),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_version.py VERSION", file=sys.stderr)
        return 2

    expected = sys.argv[1].removeprefix("v")
    mismatches = {
        source: version
        for source, version in declared_versions().items()
        if version != expected
    }
    if mismatches:
        print(f"Expected version {expected}, but found:", file=sys.stderr)
        for source, version in mismatches.items():
            print(f"  {source}: {version}", file=sys.stderr)
        return 1

    print(f"All version declarations match {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
