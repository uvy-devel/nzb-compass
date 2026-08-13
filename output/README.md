# Build output

Compiled release artifacts are written to this directory by
`make package-arch`.

Retention policy:

- Version `0.4.0` is always preserved.
- The two newest versions other than `0.4.0` are preserved.
- Every artifact belonging to a retained version is kept together.
- Unrelated files are ignored by automatic cleanup.

Run `make prune-output` to apply the policy manually.
