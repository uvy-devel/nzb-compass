"""Download retained GitHub release packages for the Pages Pacman repository."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any


PROTECTED_VERSION = (0, 4, 0)
RECENT_VERSIONS_TO_KEEP = 2
VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
PACKAGE_PATTERN = re.compile(r"^nzb-compass-\d+\.\d+\.\d+-[^/]+\.pkg\.tar\.zst$")
API_VERSION = "2022-11-28"


def release_version(release: dict[str, Any]) -> tuple[int, int, int] | None:
    if release.get("draft"):
        return None
    match = VERSION_PATTERN.fullmatch(str(release.get("tag_name") or ""))
    return tuple(int(part) for part in match.groups()) if match else None


def retained_release_ids(releases: list[dict[str, Any]]) -> set[int]:
    versioned = [
        (version, release)
        for release in releases
        if (version := release_version(release)) is not None
    ]
    versioned.sort(key=lambda item: item[0], reverse=True)
    recent = [
        release
        for version, release in versioned
        if version != PROTECTED_VERSION
    ][:RECENT_VERSIONS_TO_KEEP]
    protected = [
        release for version, release in versioned if version == PROTECTED_VERSION
    ]
    return {int(release["id"]) for release in [*protected, *recent]}


def package_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        asset
        for asset in release.get("assets") or []
        if PACKAGE_PATTERN.fullmatch(str(asset.get("name") or ""))
    ]


class GitHubApi:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def request(self, url: str, accept: str = "application/vnd.github+json") -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "nzb-compass-release-workflow",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    def releases(self) -> list[dict[str, Any]]:
        releases: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = json.loads(
                self.request(
                    f"https://api.github.com/repos/{self.repository}/releases"
                    f"?per_page=100&page={page}"
                )
            )
            releases.extend(payload)
            if len(payload) < 100:
                return releases
            page += 1

    def download_asset(self, asset: dict[str, Any], destination: Path) -> None:
        contents = self.request(
            f"https://api.github.com/repos/{self.repository}/releases/assets/{asset['id']}",
            accept="application/octet-stream",
        )
        (destination / str(asset["name"])).write_bytes(contents)

    def delete_asset(self, asset: dict[str, Any]) -> None:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/releases/assets/{asset['id']}",
            method="DELETE",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "nzb-compass-release-workflow",
            },
        )
        with urllib.request.urlopen(request, timeout=60):
            pass


def write_index(site_root: Path, repository: str) -> None:
    owner, name = repository.split("/", 1)
    site_root.mkdir(parents=True, exist_ok=True)
    (site_root / ".nojekyll").touch()
    (site_root / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NZB Compass Pacman repository</title>
<style>body{{max-width:48rem;margin:4rem auto;padding:0 1rem;font:16px system-ui;line-height:1.55}}code,pre{{background:#eee;padding:.15rem .35rem}}pre{{padding:1rem;overflow:auto}}</style>
<h1>NZB Compass Pacman repository</h1>
<p>This is the unsigned Arch Linux/CachyOS package repository for
<a href="https://github.com/{repository}">{repository}</a>.</p>
<pre>[nzb-compass]
SigLevel = Optional TrustAll
Server = https://{owner}.github.io/{name}/$arch</pre>
<p>After adding that block to <code>/etc/pacman.conf</code>, run
<code>sudo pacman -Syu nzb-compass</code>.</p>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--prune", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN is required")

    api = GitHubApi(args.repository, token)
    releases = api.releases()
    retained = retained_release_ids(releases)
    args.destination.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for release in releases:
        assets = package_assets(release)
        if int(release["id"]) in retained:
            for asset in assets:
                api.download_asset(asset, args.destination)
                downloaded += 1
        elif args.prune:
            for asset in assets:
                api.delete_asset(asset)
                print(f"Removed obsolete release asset: {asset['name']}")

    if not downloaded:
        raise SystemExit("No retained .pkg.tar.zst release assets were found")

    write_index(args.destination.parent, args.repository)
    print(f"Downloaded {downloaded} retained package artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
