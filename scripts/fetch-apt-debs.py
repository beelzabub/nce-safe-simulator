#!/usr/bin/env python3
"""Fetch one apt-debs layer from the project's generic package registry.

Used by the Dockerfile's system-package layers (issue #269): downloads
manifest-<layer>-<arch>.txt from the `apt-debs` generic package and then every
.deb it lists into a target directory, ready for a single `dpkg -i *.deb`.
Stdlib-only on purpose — it runs in python:3.11-slim layers that have no curl
(and installing curl from apt is exactly the egress this replaces).

Usage: fetch-apt-debs.py PKG_PROJECT VERSION LAYER ARCH [DEST]
  PKG_PROJECT  https://<gitlab-host>/api/v4/projects/<id-or-encoded-path>
  VERSION      apt-debs package version, e.g. 2026.07.22
  LAYER        manifest layer name: graphviz | weasyprint | dev
  ARCH         dpkg architecture: amd64 | arm64
  DEST         download directory (default /tmp/debs)

The registry must allow anonymous package reads (it does on this project:
package_registry_access_level=public) — same contract as the quarto fetch,
so no token ever enters the image build or its history.
"""
import sys
import urllib.request
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 5:
        sys.stderr.write(__doc__)
        return 2
    project, version, layer, arch = sys.argv[1:5]
    dest = Path(sys.argv[5] if len(sys.argv) > 5 else "/tmp/debs")
    dest.mkdir(parents=True, exist_ok=True)
    base = f"{project}/packages/generic/apt-debs/{version}"

    manifest = f"{base}/manifest-{layer}-{arch}.txt"
    with urllib.request.urlopen(manifest) as r:
        names = r.read().decode().split()
    if not names:
        sys.stderr.write(f"empty manifest: {manifest}\n")
        return 1
    for name in names:
        urllib.request.urlretrieve(f"{base}/{name}", dest / name)
    print(f"fetched {len(names)} debs for {layer}/{arch} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
