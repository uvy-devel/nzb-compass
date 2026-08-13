"""Apply the bounded build-artifact retention policy."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


PROTECTED_VERSION = (0, 4, 0)
RECENT_VERSIONS_TO_KEEP = 2
ARTIFACT_PATTERN = re.compile(
    r"^nzb-compass-(\d+)\.(\d+)\.(\d+)(?:[-.].*)?$"
)


def artifact_version(path: Path) -> tuple[int, int, int] | None:
    match = ARTIFACT_PATTERN.fullmatch(path.name)
    if not match or not path.is_file():
        return None
    return tuple(int(part) for part in match.groups())


def obsolete_artifacts(output_dir: Path) -> list[Path]:
    versions: dict[tuple[int, int, int], list[Path]] = defaultdict(list)
    if not output_dir.exists():
        return []

    for path in output_dir.iterdir():
        version = artifact_version(path)
        if version is not None:
            versions[version].append(path)

    recent = sorted(
        (version for version in versions if version != PROTECTED_VERSION),
        reverse=True,
    )[:RECENT_VERSIONS_TO_KEEP]
    retained = {PROTECTED_VERSION, *recent}
    return sorted(
        path
        for version, paths in versions.items()
        if version not in retained
        for path in paths
    )


def prune_output(output_dir: Path) -> list[Path]:
    removed = obsolete_artifacts(output_dir)
    for path in removed:
        path.unlink()
    return removed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: prune_output.py OUTPUT_DIR", file=sys.stderr)
        return 2

    output_dir = Path(sys.argv[1]).resolve()
    if output_dir.name != "output":
        print("refusing to prune a directory not named 'output'", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in prune_output(output_dir):
        print(f"Removed old build artifact: {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
