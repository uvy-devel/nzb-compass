# NZB Compass

NZB Compass is a native Linux desktop application for searching all enabled
Usenet indexers in Prowlarr and sending selected NZBs to SABnzbd. It uses GTK 4
and Libadwaita, follows the system light/dark theme, and keeps network work off
the interface thread.

This is primarily a personal project that I am making public because it may be
useful to other Prowlarr and SABnzbd users. Development has been heavily
AI-assisted (or "vibe-coded"). I am not a professional software developer, so
compatibility with every Linux distribution and environment is not guaranteed.
The software is provided as-is under the MIT license.

## Features

- Search selected Usenet indexers through Prowlarr.
- Filter and sort results by content type, source, age, and size.
- Send authenticated Prowlarr download URLs directly to SABnzbd.
- Choose SABnzbd category, priority, and post-processing defaults.
- Monitor SABnzbd bandwidth, queue progress, remaining size, and ETA.
- Pause, resume, retry, or remove individual jobs.
- Review recent history and SABnzbd-provided failure reasons.
- Support reverse-proxy subpaths and Docker-host URL rebasing.
- Store local connection settings with user-only file permissions (`0600`).

## Install on Arch Linux or CachyOS

NZB Compass has a small unsigned Pacman repository hosted with GitHub Pages.
Add this block to `/etc/pacman.conf`:

```ini
[nzb-compass]
SigLevel = Optional TrustAll
Server = https://uvy-devel.github.io/nzb-compass/$arch
```

Refresh Pacman and install the application:

```bash
sudo pacman -Syu
sudo pacman -S nzb-compass
```

Once installed, future releases arrive through the normal system update:

```bash
sudo pacman -Syu
```

The repository is initially unsigned. `Optional TrustAll` allows Pacman to
install those unsigned packages, which means package authenticity depends on
HTTPS, this GitHub account, and the repository's GitHub Actions workflow rather
than a personal signing key. Package and database signing can be added later
without changing the application itself.

## Configure and run

Launch **NZB Compass** from the desktop application menu, then open Settings and
enter:

1. The base URL and API key from Prowlarr → Settings → General.
2. The base URL and API key from SABnzbd → Config → General.
3. Optionally, a SABnzbd category, priority, and post-processing mode.

The defaults expect Prowlarr at `http://localhost:9696` and SABnzbd at
`http://localhost:8080`. Reverse-proxy subpaths are supported. Personal settings
remain in `~/.config/nzb-compass/config.json` and are never part of this source
repository.

## Develop or run from source

Required runtime components are Python 3.11+, GTK 4, Libadwaita, and PyGObject.
On Arch Linux/CachyOS, install the development and packaging dependencies with:

```bash
sudo pacman -S --needed base-devel git python python-gobject gtk4 libadwaita \
  desktop-file-utils python-build python-installer python-wheel
```

Run directly from the source checkout:

```bash
PYTHONPATH=src python3 -m nzb_compass
```

Run the tests:

```bash
make test
```

Build and install a local Arch package from the current commit:

```bash
make package-arch
sudo pacman -U output/nzb-compass-*-any.pkg.tar.zst
```

See [packaging/README.md](packaging/README.md) for maintainer details and the
one-time GitHub Pages setup.

## Limitations

- The graphical application targets Linux systems with GTK 4 and Libadwaita.
- The automated binary package targets Arch Linux and Arch-derived systems.
- Prowlarr and SABnzbd API compatibility can change in future upstream releases.
- No requests are made to third-party metadata services; displayed release
  information comes from the configured Prowlarr indexers.
