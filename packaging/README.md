# Packaging and release maintenance

## Local Arch package

From the repository root:

```bash
make package-arch
```

This validates the project versions and desktop file, runs the tests, creates a
source archive from the current Git commit, and invokes `makepkg` as the current
user. The package is written to `output/`.

The `PKGBUILD` installs the Python wheel, desktop launcher, application icon,
MIT license, and README in standard system locations. It declares Python,
PyGObject, GTK 4, and Libadwaita as runtime dependencies.

## Release versions

Keep these declarations synchronized:

- `pyproject.toml`
- `src/nzb_compass/__init__.py`
- `packaging/arch/PKGBUILD`

Update all three with:

```bash
make set-version VERSION=0.4.5
```

`make check-version` verifies them. The release workflow also requires the Git
tag, such as `v0.4.5`, to match.

## GitHub repository setup

The repository is designed for `https://github.com/uvy-devel/nzb-compass`.
After the initial push:

1. Open **Settings → Pages** in GitHub.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Push normal commits as often as needed; only `v*` tags publish releases.

The first commit is tagged `v0.4.0`. Because the workflow did not exist in that
historical commit, publish its protected package once from **Actions → Release
and publish Pacman repository → Run workflow**, entering `v0.4.0`. Later tags
publish automatically.

## Repository retention

The Pages repository and GitHub Release package assets retain:

- `v0.4.0` permanently.
- The two newest versions after `v0.4.0`.

Older GitHub Releases and source tags remain available, but their compiled
package assets are removed. This keeps historical source while preventing the
binary repository from growing without limit.

## Signing

The initial repository is unsigned and documented with `SigLevel = Optional
TrustAll`. This is intentionally the simplest first setup. A later signing
upgrade should sign each package and repository database, publish the public
key, and replace that client policy with signature verification.
