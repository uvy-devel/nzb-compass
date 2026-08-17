# NZB Compass

NZB Compass is a native Linux desktop application for searching all enabled
Usenet indexers in Prowlarr and sending selected NZBs to SABnzbd. It uses GTK 4
and Libadwaita, follows the system light/dark theme, and keeps network work off
the interface thread.

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

## Requirements

- Arch Linux, CachyOS, or another Arch-based Linux distribution.
- A running Prowlarr instance with one or more Usenet indexers configured.
- A running SABnzbd instance.
- The base URL and API key for both services.

## Install

Add the NZB Compass package repository to `/etc/pacman.conf`:

```ini
[nzb-compass]
SigLevel = Optional TrustAll
Server = https://uvy-devel.github.io/nzb-compass/$arch
```

Refresh the package databases and install NZB Compass:

```bash
sudo pacman -Syu
sudo pacman -S nzb-compass
```

The package repository is unsigned. `Optional TrustAll` permits Pacman to
install its packages without signature verification. Package delivery relies
on HTTPS, the GitHub repository, and its GitHub Actions release workflow.

## Configure and run

Launch **NZB Compass** from the desktop application menu. Open **Settings** and
enter:

1. The base URL and API key from **Prowlarr → Settings → General**.
2. The base URL and API key from **SABnzbd → Config → General**.
3. Optionally, a SABnzbd category, priority, and post-processing mode.

The default URLs are `http://localhost:9696` for Prowlarr and
`http://localhost:8080` for SABnzbd. Reverse-proxy subpaths are supported.
Settings are stored locally in `~/.config/nzb-compass/config.json` with
user-only permissions.

## Update

NZB Compass updates through the normal system update process:

```bash
sudo pacman -Syu
```

## Uninstall

```bash
sudo pacman -Rns nzb-compass
```

Remove the `[nzb-compass]` block from `/etc/pacman.conf` if the package
repository is no longer needed. User settings can be removed separately from
`~/.config/nzb-compass/`.

## Limitations

- The graphical application targets Linux systems with GTK 4 and Libadwaita.
- The automated binary package targets Arch Linux and Arch-derived systems.
- Prowlarr and SABnzbd API compatibility can change in future upstream releases.
- No requests are made to third-party metadata services; displayed release
  information comes from the configured Prowlarr indexers.
