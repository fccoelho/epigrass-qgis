#!/usr/bin/env python3
"""Build the distributable QGIS plugin zip.

Creates ``dist/epigrass.v<version>.zip`` containing a single ``epigrass/``
folder (the layout QGIS expects when installing from zip):

    epigrass/
        metadata.txt
        LICENSE
        README.md
        __init__.py
        ... (package modules and icons)

The ``epigrass_qgis`` development package is renamed to ``epigrass`` inside
the zip; all internal imports are relative, so this is safe.

Usage: python scripts/build_zip.py [--out dist]
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

PLUGIN_FOLDER = "epigrass"
SOURCE_PACKAGE = "epigrass_qgis"
METADATA = "metadata.txt"
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def read_version(repo: Path) -> str:
    text = (repo / SOURCE_PACKAGE / METADATA).read_text(encoding="utf-8")
    match = re.search(r"^version=(.+)$", text, flags=re.MULTILINE)
    if not match:
        sys.exit(f"ERROR: 'version=' not found in {SOURCE_PACKAGE}/{METADATA}")
    return match.group(1).strip()


def collect_files(repo: Path) -> list:
    """Files to pack: package contents (filtered) + top-level docs."""
    files = []
    for path in sorted((repo / SOURCE_PACKAGE).rglob("*")):
        if path.is_dir():
            continue
        if EXCLUDE_PARTS & set(path.parts) or path.suffix in EXCLUDE_SUFFIXES:
            continue
        files.append(path)
    for extra in ("LICENSE", "README.md"):
        if (repo / extra).is_file():
            files.append(repo / extra)
    return files


def arcname_for(repo: Path, path: Path) -> str:
    relative = path.relative_to(repo)
    if relative.parts[0] == SOURCE_PACKAGE:
        # epigrass_qgis/... -> epigrass/...
        return str(Path(PLUGIN_FOLDER, *relative.parts[1:]))
    return str(Path(PLUGIN_FOLDER, relative.name))


def build(repo: Path, out_dir: Path) -> Path:
    version = read_version(repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{PLUGIN_FOLDER}.v{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in collect_files(repo):
            zf.write(path, arcname_for(repo, path))
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", help="output directory")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    zip_path = build(repo, Path(args.out))
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    has_metadata = f"{PLUGIN_FOLDER}/{METADATA}" in names
    has_init = f"{PLUGIN_FOLDER}/__init__.py" in names
    print(f"Built {zip_path} ({len(names)} files)")
    if not (has_metadata and has_init):
        sys.exit("ERROR: zip is missing metadata.txt or __init__.py at its root")


if __name__ == "__main__":
    main()
