# Changelog

All notable changes to the Epigrass QGIS plugin are documented here.

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
