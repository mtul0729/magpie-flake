#!/usr/bin/env python3
"""Update the magpie pins in package.nix.

Upstream cuts a tag every few commits (600+ tags and counting), so the version
moves far too often to bump by hand.  A bump touches four things: version, the
commit a tag points at, the source narHash and the Go vendor hash.

The commit comes from `git ls-remote`: no GitHub token, no pagination, no
60-requests-per-hour limit, which matters because the tag list is long and the
API would need several pages.

The two hashes need nix, and both are the documented procedures:

  * the source narHash is what `nix flake prefetch` hashes the tarball to;
  * the vendor hash can only come from actually running `go mod vendor`, so
    `vendorHash` is set to `lib.fakeHash` and the package is built once to make
    nix print the real hash.  nixpkgs' Go section documents exactly this shape
    (`.overrideAttrs { vendorHash = sha256; }`).  `nix-prefetch` would print it
    directly but is not installed here.

Usage:
    ./update.py                # bump to the newest tag
    ./update.py 0.1.600        # pin a specific version (v prefix optional, downgrades allowed)
    ./update.py --check        # report drift without touching package.nix
    ./update.py --dry-run      # print the planned changes without writing

`--check` compares version and rev only.  It is the cheap half of the contract:
resolving the two hashes means downloading the tarball and building goModules
(~30s), so that happens after the `--check` branch.  Both hashes are a pure
function of the commit, so they cannot drift on their own.

Exit codes: 0 = up to date or written, 1 = `--check` found drift, 2 = error.
The GitHub Actions workflow runs `--check` first and only pays for the build
when there is something to bump.

Invariants, so it is safe to run unattended:
  * a failure to resolve version or hashes aborts before the file is touched;
  * every rewrite is anchored on the *old* literal and refuses to guess;
  * the rewritten file is re-parsed and compared against the target;
  * the write is atomic (temp file in the same directory + os.replace).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_URL = "https://github.com/yetone/magpie"
GITHUB_REPO = "yetone/magpie"
OWNER = "yetone"
REPO = "magpie"

# update.py and package.nix live side by side at the repo root, which is also
# the flake the vendor probe gets its nixpkgs from.
REPO_DIR = Path(__file__).resolve().parent
FLAKE_DIR = REPO_DIR
NIX_FILE = REPO_DIR / "package.nix"

TAG_RE = re.compile(r"v[0-9][0-9A-Za-z.+_-]*")
VERSION_RE = re.compile(r"v?[0-9][0-9A-Za-z.+_-]*")
# `git ls-remote` prints "<sha>\t<ref>"; annotated tags appear twice, the
# peeled `^{}` line being the commit rather than the tag object.
LS_REMOTE_RE = re.compile(r"^([0-9a-f]{40})\trefs/tags/(\S+)$", re.MULTILINE)
GOT_HASH_RE = re.compile(r"got:\s+(sha256-[A-Za-z0-9+/=]+)")
# nix's patchPhase prints this when a patch hunk no longer matches the source.
PATCH_FAIL_RE = re.compile(r"Hunk #\d+ FAILED")

NIX_EXTRA = ["--extra-experimental-features", "nix-command flakes"]
GIT_TIMEOUT = 60
NIX_TIMEOUT = 600
# 大下载（源码 tarball、go 模块的 .zip）在这台机器上会被中途重置：报的是
# `unexpected EOF` / `Truncated tar archive`，而不是 hash 不对。原样重跑一次
# 通常就过，所以两步网络操作都允许重试。
FETCH_ATTEMPTS = 3


class UpdateError(Exception):
    """A failure that must abort before package.nix is touched."""


class NotRetryable(UpdateError):
    """A failure a retry can only repeat, e.g. a patch that no longer applies."""


@dataclass(frozen=True)
class Pins:
    version: str
    rev: str
    src_hash: str
    vendor_hash: str


###############################################################################
# upstream
###############################################################################


def run(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as err:
        raise UpdateError(f"{argv[0]} is not on PATH") from err
    except subprocess.TimeoutExpired as err:
        raise UpdateError(f"{' '.join(argv[:2])} timed out after {timeout}s") from err


def remote_tags() -> dict[str, str]:
    """Map every tag name to its commit, preferring the peeled ref."""
    result = run(["git", "ls-remote", "--tags", REPO_URL], GIT_TIMEOUT)
    if result.returncode != 0:
        raise UpdateError(f"git ls-remote failed: {result.stderr.strip()}")

    peeled: dict[str, str] = {}
    direct: dict[str, str] = {}
    for sha, ref in LS_REMOTE_RE.findall(result.stdout):
        name, _, suffix = ref.partition("^{}")
        if suffix:
            peeled[name] = sha
        else:
            direct.setdefault(name, sha)
    return {name: peeled.get(name, sha) for name, sha in direct.items()}


def resolve_commit(version: str | None) -> tuple[str, str]:
    """Return (version, rev) for the requested version, or the newest tag."""
    tags = remote_tags()
    if version:
        tag = version if version.startswith("v") else f"v{version}"
        if tag not in tags:
            raise UpdateError(f"{tag} is not a tag of {GITHUB_REPO}")
        return version.lstrip("v"), tags[tag]

    candidates = [name for name in tags if TAG_RE.fullmatch(name)]
    if not candidates:
        raise UpdateError(f"no version-like tags found on {GITHUB_REPO}")
    tag = max(candidates, key=lambda name: version_key(name.lstrip("v")))
    return tag.lstrip("v"), tags[tag]


def vendor_probe_expr(rev: str, src_hash: str) -> str:
    """The package with a new src and a throwaway vendorHash.

    nixpkgs' Go section suggests probing `<pkg>.overrideAttrs { ... }.goModules`,
    but on this nixpkgs `goModules` is gone after `overrideAttrs`, so the whole
    package is probed instead.  goModules is a fixed-output dependency and fails
    before anything compiles, so it costs the same `go mod vendor` run.
    """
    return f"""
let
  system = builtins.currentSystem;
  pkgs = (builtins.getFlake "{FLAKE_DIR}").inputs.nixpkgs.legacyPackages.${{system}};
in
  (pkgs.callPackage "{NIX_FILE}" {{ }}).overrideAttrs {{
    src = pkgs.fetchFromGitHub {{
      owner = "{OWNER}";
      repo = "{REPO}";
      rev = "{rev}";
      hash = "{src_hash}";
    }};
    vendorHash = pkgs.lib.fakeHash;
  }}
"""


def retry(label: str, action: Callable[[], str]) -> str:
    """Re-run a network step that fails by truncation rather than by being wrong."""
    last = ""
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            return action()
        except NotRetryable:
            raise
        except UpdateError as err:
            last = str(err)
            print(f"note: {label} failed (attempt {attempt}/{FETCH_ATTEMPTS})", file=sys.stderr)
    raise UpdateError(f"{label} failed after {FETCH_ATTEMPTS} attempts: {last}")


def prefetch_src(rev: str) -> str:
    def once() -> str:
        result = run(
            ["nix", "flake", "prefetch", *NIX_EXTRA, "--json", f"github:{GITHUB_REPO}/{rev}"],
            NIX_TIMEOUT,
        )
        if result.returncode != 0:
            raise UpdateError(result.stderr.strip().splitlines()[-1] or "no output")
        try:
            return str(json.loads(result.stdout)["hash"])
        except (json.JSONDecodeError, KeyError) as err:
            raise UpdateError(f"could not read a hash out of: {result.stdout!r}") from err

    return retry(f"nix flake prefetch for {rev}", once)


def prefetch_vendor(rev: str, src_hash: str) -> str:
    """Run `go mod vendor` for real and read the hash nix prints back.

    Retried because the module downloads get reset mid-transfer here: the error
    is `unexpected EOF` on some .zip, never a wrong hash.  A retry re-runs the
    whole fetch, which is why this is the slowest step of the script.

    The probe can also fail before vendoring starts: a source patch that no
    longer applies dies in patchPhase.  That is permanent, so it is raised as
    NotRetryable and named for what it is instead of being retried (and, worse,
    reported) as a `go mod vendor` failure.
    """

    def once() -> str:
        result = run(
            [
                "nix",
                "build",
                "--impure",
                *NIX_EXTRA,
                "--no-link",
                "--expr",
                vendor_probe_expr(rev, src_hash),
            ],
            NIX_TIMEOUT,
        )
        if result.returncode == 0:
            raise UpdateError("built with a fake vendorHash, so nix printed no hash")
        match = GOT_HASH_RE.search(result.stderr)
        if not match:
            patch_failure = [
                line.strip()
                for line in result.stderr.splitlines()
                if "applying patch" in line or PATCH_FAIL_RE.search(line)
            ]
            if patch_failure:
                raise NotRetryable(
                    "a source patch no longer applies; regenerate it -- nix said: "
                    + " | ".join(patch_failure)
                )
            raise UpdateError(result.stderr.strip().splitlines()[-1] or "no output")
        return match.group(1)

    return retry("go mod vendor", once)


###############################################################################
# package.nix: read and rewrite
###############################################################################


def read_solo(text: str, pattern: str, label: str) -> str:
    values = re.findall(pattern, text, flags=re.MULTILINE)
    if len(values) != 1:
        raise UpdateError(f"expected exactly one {label} in {NIX_FILE.name}, found {len(values)}")
    return values[0]


def parse_pins(text: str) -> Pins:
    return Pins(
        version=read_solo(text, r'^\s*version\s*=\s*"([^"]*)";', "version assignment"),
        rev=read_solo(text, r'^\s*rev\s*=\s*"([^"]*)";', "rev assignment"),
        src_hash=read_solo(text, r'^\s*hash\s*=\s*"([^"]*)";', "hash assignment"),
        vendor_hash=read_solo(text, r'^\s*vendorHash\s*=\s*"([^"]*)";', "vendorHash assignment"),
    )


def replace_solo(text: str, pattern: str, new: str, label: str) -> str:
    """Replace one anchored occurrence, refusing to guess when the anchor is ambiguous."""
    compiled = re.compile(pattern, flags=re.MULTILINE)
    result, count = compiled.subn(lambda match: match.group(1) + new + match.group(2), text)
    if count != 1:
        raise UpdateError(f"expected exactly one {label} to rewrite, matched {count}")
    return result


def apply_pins(text: str, old: Pins, new: Pins) -> str:
    # Every pattern embeds the *old* literal, so a stale assumption fails loudly
    # instead of rewriting a line nobody asked it to touch.
    for label, pattern, before, after in (
        ("version assignment", r"(^\s*version\s*=\s*\")", old.version, new.version),
        ("rev assignment", r"(^\s*rev\s*=\s*\")", old.rev, new.rev),
        ("hash assignment", r"(^\s*hash\s*=\s*\")", old.src_hash, new.src_hash),
        ("vendorHash assignment", r"(^\s*vendorHash\s*=\s*\")", old.vendor_hash, new.vendor_hash),
    ):
        text = replace_solo(text, pattern + re.escape(before) + r"(\";)", after, label)
    return text


def write_atomic(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


###############################################################################
# reporting
###############################################################################


def version_key(value: str) -> list[tuple[int, object]]:
    parts: list[tuple[int, object]] = []
    for part in re.split(r"[.+-]", value):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return parts


def diff_lines(old: Pins, new: Pins) -> list[str]:
    return [
        f"{label}: {before} -> {after}"
        for label, before, after in (
            ("version", old.version, new.version),
            ("rev", old.rev, new.rev),
            ("src hash", old.src_hash, new.src_hash),
            ("vendor hash", old.vendor_hash, new.vendor_hash),
        )
        if before != after
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update the magpie version, rev and hashes in package.nix."
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="exact version to pin (e.g. 0.1.600); defaults to the newest tag",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether package.nix is out of date; never writes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned changes without writing",
    )
    args = parser.parse_args()
    if args.check and args.version:
        parser.error("--check compares against the newest tag and takes no version argument")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.version and not VERSION_RE.fullmatch(args.version):
            raise UpdateError(f"{args.version!r} is not an exact version")

        text = NIX_FILE.read_text(encoding="utf-8")
        current = parse_pins(text)

        # The cheap half first: --check must not download or build anything.
        version, rev = resolve_commit(args.version)
        if args.check:
            drift = [
                f"{label}: {before} -> {after}"
                for label, before, after in (("version", current.version, version), ("rev", current.rev, rev))
                if before != after
            ]
            if not drift:
                print("up to date")
                return 0
            print("\n".join(drift))
            return 1

        src_hash = prefetch_src(rev)
        target = Pins(
            version=version,
            rev=rev,
            src_hash=src_hash,
            vendor_hash=prefetch_vendor(rev, src_hash),
        )
        changes = diff_lines(current, target)

        if not changes:
            print("up to date, nothing to do")
            return 0
        if version_key(target.version) < version_key(current.version):
            print(f"note: {current.version} -> {target.version} is a downgrade", file=sys.stderr)

        updated = apply_pins(text, current, target)
        if parse_pins(updated) != target:
            raise UpdateError("rewritten file does not carry the expected pins, refusing to write")

        if args.dry_run:
            print("\n".join(changes))
            print("dry run: package.nix left untouched")
            return 0

        write_atomic(NIX_FILE, updated)
        print("\n".join(changes))
        print(f"updated {NIX_FILE.name}; review with jj diff, then nix build")
        return 0
    except UpdateError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
