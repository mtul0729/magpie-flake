# magpie-flake

Standalone Nix package for [yetone/magpie](https://github.com/yetone/magpie) —
"every agent's model, one place" — built from source.

Upstream ships no Linux `.desktop` and no Nix support, and its `install.sh`
drops an FHS binary that cannot run on NixOS. Here it is a `buildGoModule`
package on GTK 4 / WebKitGTK 6, which is what Wails v3 uses on Linux (the
Makefile's `gtk3` tag exists for old distros and is deliberately not used).

One thing is patched: magpie writes its own `~/.local/share/applications/
magpie.desktop` with `Exec` set to `os.Executable()`, i.e. a `/nix/store`
path. XDG prefers the user directory over the system one, so after any update
the launcher would keep starting the old, still-present store path — and that
old version rewrites the same path, so it never recovers. The patch disables
that write entirely (`no-self-desktop-file.patch`); the only desktop file is
the one this package installs, with `Exec=magpie`.

The generated file also ran `xdg-mime default` to make itself the default
handler for `magpie://`, writing to the user's `mimeapps.list`. Declaring the
type is fine and this package keeps `MimeType=x-scheme-handler/magpie`, but
choosing the default application for the user is not, so it is not replaced.

Upstream cuts a tag every few commits, so this flake tracks the newest tag
rather than a release.

## Usage

```console
nix run github:mtul0729/magpie-flake
nix profile install github:mtul0729/magpie-flake
```

As a flake input:

```nix
inputs.magpie-flake = {
  url = "github:mtul0729/magpie-flake";
  inputs.nixpkgs.follows = "nixpkgs";
};

# then either
environment.systemPackages = [ inputs.magpie-flake.packages.${pkgs.system}.magpie ];
# or via the overlay
nixpkgs.overlays = [ inputs.magpie-flake.overlays.default ]; # provides pkgs.magpie
```

Follow your own nixpkgs: without `follows`, gtk4 and webkitgtk come from this
flake's own nixpkgs pin and you download a second toolchain for no reason.

Builds are pushed to the `mtul` cachix cache; `flake.nix`'s `nixConfig` already
advertises it, so `nix build --accept-flake-config` picks it up.

## Updating

`./update.py` moves `version`, `rev`, the source hash and `vendorHash` in
`package.nix` together:

```bash
./update.py                # newest tag
./update.py 0.1.735        # pin a specific version
./update.py --check        # report drift, write nothing (exit 1 when behind)
./update.py --dry-run      # print the planned changes, write nothing
```

It reads tags with `git ls-remote` (no token, no API pagination) and gets both
hashes from nix itself: `nix flake prefetch` for the tarball, and a real
`go mod vendor` run with `lib.fakeHash` for the vendor hash.

## Auto-update workflows

- `.github/workflows/update-package.yml` — hourly: `--check`, bump, build, then
  push to `main`. `--check` is a `git ls-remote` with no nix involved, so a
  hour without a new tag costs nothing; upstream tags several times a day. The
  build runs before the push, so a broken tag stops in CI instead of landing on
  `main`.
- `.github/workflows/update-flake-lock.yml` — weekly: `nix flake update`, build,
  push `flake.lock`.
- `.github/workflows/build.yml` — build on every push and PR.

Set the `CACHIX_AUTH_TOKEN` repository secret to push builds to the `mtul`
cache; without it the cache step is skipped. `--check` needs no credentials.
