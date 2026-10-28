"""Small SQLite helpers shared by the results modules.

Kept free of QGIS imports so it is unit-testable in plain CI.
"""

from __future__ import annotations

import re

#: Table names come from the simulation database (ultimately derived from the
#: user's layer name); reject anything that cannot be a sane table name.
TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def quoted_identifier(name: str) -> str:
    """Return *name* as a safely quoted SQLite identifier.

    Standard SQLite escaping: embedded double quotes are doubled.  Names with
    characters that cannot appear in an identifier at all are rejected.
    """
    if not name or "\x00" in name or not TABLE_NAME_RE.match(name):
        raise ValueError(f"Rejected unsafe or malformed table name: {name!r}")
    return f'"{name.replace(chr(34), chr(34) * 2)}"'
