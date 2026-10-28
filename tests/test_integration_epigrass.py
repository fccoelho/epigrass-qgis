"""Round-trip test against the real Epigrass engine.

Runs only when Epigrass is importable (e.g. inside the Epigrass dev
environment).  A reachable Redis server is required by the engine.

It validates the exact project the plugin generates: model.epg + sites.csv +
edges.csv + map.gpkg (written here with geopandas, the way the QGIS side
writes it), then runs a small simulation to completion.
"""

import os

import pytest

from epigrass_qgis.writer.epg_writer import (
    Edge,
    ModelSpec,
    SeedEvent,
    Site,
    write_project,
)

epigrass = pytest.importorskip("Epigrass")
gpd = pytest.importorskip("geopandas")

pytestmark = pytest.mark.integration

SQUARES = [
    # name, geocode, min x, min y (1 degree squares)
    ("Alpha", 1, 0.0, 0.0),
    ("Beta", 2, 0.0, 0.5),
    ("Gamma", 3, 0.5, 0.0),
    ("Delta", 4, 0.5, 0.5),
    ("Epsilon", 5, 1.0, 0.0),
]


def write_map_gpkg(folder, filename="map.gpkg"):
    from shapely.geometry import box

    records = [
        {"name": name, "geocode": geocode, "geometry": box(x, y, x + 0.4, y + 0.4)}
        for name, geocode, x, y in SQUARES
    ]
    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    gdf.to_file(os.path.join(folder, filename), driver="GPKG")


@pytest.fixture(scope="module")
def tiny_project(tmp_path_factory):
    folder = tmp_path_factory.mktemp("tiny") / "tiny"
    spec = ModelSpec(
        name="tiny",
        model_type="SIR",
        sites=[
            Site(name, 10000, geocode, y + 0.2, x + 0.2)  # centroid lat, lon
            for name, geocode, x, y in SQUARES
        ],
        edges=[
            Edge(1, 2, 100, 100, 55.0),
            Edge(2, 3, 80, 80, 60.0),
            Edge(3, 4, 60, 60, 55.0),
            Edge(4, 5, 50, 50, 60.0),
            Edge(5, 1, 40, 40, 120.0),
        ],
        params={"beta": "0.4", "alpha": "1", "e": "0", "r": "0.2",
                "delta": "0", "B": "0", "w": "0", "p": "0"},
        inits={"S": "N", "E": "0", "I": "0"},
        seed=[SeedEvent(1, "I", 10)],
        steps=30,
        shapefile=("map.gpkg", "name", "geocode"),
    )
    paths = write_project(spec, folder)
    write_map_gpkg(str(folder))
    # Epigrass resolves sites/edges/map relative to the CWD (the plugin's
    # runner sets cwd=project_dir; do the same here).
    monkeypatch_cwd = folder
    old_cwd = os.getcwd()
    os.chdir(monkeypatch_cwd)
    yield folder, paths, spec
    os.chdir(old_cwd)


def test_epigrass_runs_generated_project(tiny_project):
    folder, paths, spec = tiny_project
    from Epigrass.manager import Simulate

    # Constructing Simulate parses the .epg, sites.csv, edges.csv and map.gpkg
    sim = Simulate(fname=str(paths["epg"]), backend="csv", silent=True)
    assert len(sim.g.site_dict) == len(spec.sites)
    assert len(sim.g.edges()) == len(spec.edges)
    assert sim.modtype == spec.model_type
    assert sim.steps == spec.steps

    # Full simulation run
    sim.start()
    # The plugin always names the script model.epg, so Epigrass derives
    # outdata-model from it (the plugin locates outdata-* dynamically).
    outdir = os.path.join(str(folder), "outdata-model")
    assert os.path.isdir(outdir)
    # Data.gpkg is the main georeferenced output (Nodes/Edges.gpkg are only
    # created lazily by the dashboard, so the plugin treats them as optional).
    assert os.path.isfile(os.path.join(outdir, "Data.gpkg"))
    data = gpd.read_file(os.path.join(outdir, "Data.gpkg"))
    assert len(data) == len(spec.sites)
    assert "prevalence" in data.columns
