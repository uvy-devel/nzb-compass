# Packaging NZB Compass

The packaging files are maintained as part of the main project.

## CachyOS and Arch Linux

From the project root, build and validate the native package with:

```bash
make package-arch
```

The finished package is written to `outputs/`. Install or update it with:

```bash
sudo pacman -U outputs/nzb-compass-0.4.0-1-any.pkg.tar.zst
```

The package installs the Python application under `/usr/lib/nzb-compass`, a
launcher under `/usr/bin`, and the desktop entry and scalable icon under
`/usr/share`.

