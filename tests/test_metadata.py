"""Validate metadata.txt the way QGIS and plugins.qgis.org parse it.

QGIS's plugin installer reads metadata.txt with a configparser-based
parser: multi-line values (like ``about``) MUST use indented
continuation lines, and unindented lines after a key are hard parsing
errors. This test guards against shipping an unparseable package.
"""

import configparser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
METADATA_PATH = REPO / "epigrass_qgis" / "metadata.txt"

#: fields required by plugins.qgis.org / the QGIS plugin installer
REQUIRED_FIELDS = (
    "name",
    "qgisMinimumVersion",
    "description",
    "version",
    "author",
    "email",
    "about",
    "tracker",
    "repository",
)


def parse_metadata() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # QGIS preserves the case of option names
    with open(METADATA_PATH, encoding="utf-8") as fh:
        parser.read_file(fh)  # raises ParsingError on bad continuation lines
    return parser


def test_metadata_parses_without_errors():
    parser = parse_metadata()
    assert parser.has_section("general")


def test_metadata_required_fields_present():
    parser = parse_metadata()
    general = parser["general"]
    for field in REQUIRED_FIELDS:
        assert general.get(field, "").strip(), f"metadata field '{field}' is empty"


def test_multiline_about_survives_parsing():
    about = parse_metadata()["general"]["about"]
    # all the original lines must be present in the parsed value
    assert "Turn any loaded vector layer" in about
    assert "Map layer columns to site name" in about
    assert "Temporal Controller" in about
    assert "Environment Doctor" in about


def test_version_matches_changelog_and_is_valid():
    general = parse_metadata()["general"]
    version = general["version"]
    parts = version.split(".")
    assert len(parts) >= 2 and all(p.isdigit() for p in parts), version
    assert general.get("changelog", "").startswith(version)


def test_icon_is_packaged():
    general = parse_metadata()["general"]
    icon = general.get("icon", "")
    if icon:
        assert (REPO / "epigrass_qgis" / icon).is_file(), f"icon missing: {icon}"


def test_build_zip_contains_parseable_metadata():
    """The zip built by scripts/build_zip.py must contain a metadata.txt
    that still parses (guards the repackaging logic, not just the source)."""
    import io
    import zipfile

    from scripts.build_zip import build

    zip_path = build(REPO, REPO / "dist")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "epigrass/metadata.txt" in names
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read_file(io.TextIOWrapper(zf.open("epigrass/metadata.txt"), "utf-8"))
    assert parser["general"]["name"] == "Epigrass"
