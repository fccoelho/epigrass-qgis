# Changelog

All notable changes to the Epigrass QGIS plugin are documented here.

## 0.1.2 — 2026-10-28

Environment Doctor fixes:

- **Fixed**: Python discovery never succeeded — the version probe printed
  `sys.version` (bare `3.12.7 (...)`) but the parser expected
  `Python 3.12.7`. Probes now run `python --version` and the parser accepts
  both formats; guarded by real end-to-end probe tests.
- Interpreter preference now favours Python 3.12 then 3.13 (widest wheel
  availability for Epigrass dependencies) over the newest system Python,
  and discovers **uv-managed interpreters** (`~/.local/share/uv/python`)
  even when they are not on PATH.
- The managed environment is rebuilt automatically if it was created with
  a Python for which Epigrass dependencies cannot be installed.
- Child-process probes run with a sanitised environment (QGIS's
  `PYTHONHOME`/`PYTHONPATH` cannot break discovery).

## 0.1.1 — 2026-10-28

Security hardening (static-analysis clean):

- SQLite result-table names are validated and properly quoted before
  building queries (`sqlite_utils.quoted_identifier`).
- Model names derived from layer names are sanitized (they flow into
  output directories and SQLite table names).
- Python interpreter candidates are resolved to absolute paths via
  `shutil.which` before execution (PATH-hijacking protection).
- All subprocess call sites audited: argv lists only, no shell, no
  user-controlled strings; annotated accordingly (`bandit` clean).

## 0.1.0 — 2026-10-28

Initial release.

- Environment Doctor: Python ≥ 3.12 discovery, managed virtualenv creation,
  Epigrass installation, Redis detection/auto-start.
- Model Builder wizard (5 steps): layer + column mapping, four network
  builders (adjacency, kNN, distance threshold, attribute flows), model &
  parameter presets, seed picking on the map, vaccination events, transport
  options, review + project generation (model.epg, sites.csv, edges.csv,
  map.gpkg, model_spec.json).
- Simulation runner: QgsTask + epirunner subprocess with live log and cancel.
- Results loading: Nodes/Edges/Data GeoPackages with graduated styling,
  SQLite time series as a temporal layer for the Temporal Controller.
