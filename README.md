# NZB Compass

NZB Compass is a native Linux desktop app for searching all enabled **Usenet**
indexers in Prowlarr and sending selected NZBs to SABnzbd. It uses GTK 4 and
Libadwaita, follows the system light/dark theme, and keeps network work off the
interface thread.

## Current features

- Search through Prowlarr's `/api/v1/search` endpoint
- Browse all configured Usenet indexers and include or exclude them per search
- Show whether each indexer is disabled in Prowlarr or unable to search
- Filter returned releases instantly by content type or source indexer
- Group console and PC/Games categories into one convenient Games filter
- Usenet-only results with title, indexer, size, age, categories, and grab count
- Sort by newest, size, or indexer
- Detailed release panel with a link back to the source page
- Direct handoff flow: send an authenticated Prowlarr URL to SABnzbd via `addurl`
- Rebase Prowlarr download links onto the configured host for Docker and reverse proxies
- Optional SABnzbd category
- Live SABnzbd queue with progress and time remaining
- Native SABnzbd dashboard with speed, remaining size, ETA, and queue totals
- Pause/resume controls, automatic refresh, and recent download history
- Friendly connection and authentication errors
- Local settings file restricted to the current user (`0600`)

## Run it

Requirements: Python 3.11+, GTK 4, Libadwaita, and PyGObject.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/nzb-compass
```

For an offline install on a system that already has the requirements, add
`--no-build-isolation --no-deps` to the `pip install` command.

For development, it can also run without installation:

```bash
PYTHONPATH=src python3 -m nzb_compass
```

Open **Settings** and enter:

1. The base URL and API key from Prowlarr → Settings → General.
2. The base URL and API key from SABnzbd → Config → General.
3. Optionally, a SABnzbd category to apply to every download.

The defaults assume Prowlarr is at `http://localhost:9696` and SABnzbd is at
`http://localhost:8080`. Reverse-proxy subpaths are supported.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

No requests are made to third-party metadata services. The release information
shown is the metadata Prowlarr returns from your configured indexers.

## Install on Arch Linux or CachyOS

Install the packaged build once with:

```bash
sudo pacman -U nzb-compass-0.4.0-1-any.pkg.tar.zst
```

NZB Compass will then appear in the desktop application launcher. Remove it
later with `sudo pacman -R nzb-compass`; personal connection settings are kept
in `~/.config/nzb-compass` unless removed separately.

The package recipe, desktop launcher, and icon are included in the project.
Maintainers can produce a fresh package with `make package-arch`; see
`packaging/README.md` for details.
