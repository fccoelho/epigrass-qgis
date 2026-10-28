# Epigrass for QGIS

[![CI](https://github.com/fccoelho/epigrass-qgis/actions/workflows/ci.yml/badge.svg)](https://github.com/fccoelho/epigrass-qgis/actions/workflows/ci.yml)

**Epigrass** is a QGIS plugin that turns any loaded vector layer into a working
metapopulation epidemic model — build it, simulate it and watch the outbreak
spread on your map, without leaving QGIS.

It is built on top of [Epigrass](https://epigrass.readthedocs.io), the
Epidemiological Geo-Referenced Analysis and Simulation System, and drives it in
an **isolated Python environment** so your QGIS installation is never modified.

![Epigrass](epigrass_qgis/icons/egicon.png)

## Features

- **Model Builder wizard** — create a model from any polygon/point layer:
  - map columns to *site name*, *population* and *geocode* (auto-derived from
    feature ids when your layer has none)
  - build the connectivity network four ways: shared-border adjacency,
    k-nearest neighbours, distance threshold, or flow columns from the
    attribute table; live network preview on the map
  - compartmental models: SIR, SEIR, SEIS, SIS, SIpR, SIpRpS, SIRS and their
    continuous variants (+ `CustomModel.py`), with parameter presets for
    influenza, COVID-19, measles and dengue
  - **seed the outbreak by clicking a feature on the map**; optional
    vaccination campaigns
  - transportation model options (deterministic/stochastic, travel speed)
- **Simulation runner** — runs `epirunner` as a background QGIS task with a
  live log and cancellation support
- **Results** — `Data.gpkg` (prevalence, total cases, arrivals per site) is
  loaded back as a styled choropleth layer, and the SQLite time series becomes
  a **temporal layer**: animate the epidemic with the QGIS Temporal Controller
  (the network `Nodes.gpkg`/`Edges.gpkg` files produced by Epigrass's
  dashboard are loaded too when present)
- **Environment Doctor** — one-click provisioning:
  - finds a Python ≥ 3.12 (or uses one you point it to)
  - creates a dedicated virtualenv (`~/.epigrass-qgis/env`) and installs
    Epigrass into it
  - checks that the [Redis](https://redis.io) server required by the Epigrass
    engine is reachable and starts one automatically when a `redis-server`
    binary is available

## Installation

1. Install the plugin (Plugin Manager → *Install from ZIP*, or from the QGIS
   plugin repository once published).
2. Open **Epigrass → Environment Doctor** and click *Provision / Fix
   environment*. This downloads/installs Epigrass into its own environment
   (one time, a few minutes depending on your connection).
3. Windows users: Redis has no official build — see the Doctor's guidance
   (Memurai, WSL2 or Docker).

### Requirements

- QGIS ≥ 3.34
- Python ≥ 3.12 available on the system (for the managed simulation
  environment; QGIS's own Python is never used)
- A reachable Redis server (started automatically by the plugin when possible)

## Quick start

1. Load a polygon layer of your study area (e.g. municipalities with
   population and geocode fields).
2. Toolbar → **Build Model from Layer...** and follow the 5 steps.
3. When the wizard finishes (with *Run simulation* checked), the simulation
   starts; when it completes, result layers are added to a `Epigrass: <model>`
   group.
4. Open **View → Panels → Temporal Controller**, press play, and watch the
   epidemic spread across your map.

## How it works

```
QGIS layer ──► wizard ──► map.gpkg + sites.csv + edges.csv + model.epg
                                  │
                                  ▼
              managed venv: epirunner model.epg --backend sqlite
                                  │
                                  ▼
        outdata-model/{Data.gpkg, Epigrass.sqlite, epistats.csv, ...}
                                  │
                                  ▼
              styled layers + temporal animation layer in QGIS
```

The plugin never imports Epigrass into QGIS's Python process — simulations run
in a subprocess of the managed environment, which keeps QGIS safe from
dependency conflicts and lets simulations fail without taking QGIS down.

## Development

```bash
uv sync --group dev     # or: pip install pytest ruff
uv run pytest           # unit tests (no QGIS required)
uv run ruff check .
```

Integration tests that execute a real simulation against Epigrass run
automatically when `Epigrass` is importable (and a Redis server is up):

```bash
uv run pytest tests/test_integration_epigrass.py
```

To try the plugin in QGIS, symlink or copy this folder into your QGIS profile:

```bash
ln -s "$(pwd)/epigrass_qgis" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/epigrass
```

## License

GPL-3.0-or-later — same as Epigrass. See [LICENSE](LICENSE).
