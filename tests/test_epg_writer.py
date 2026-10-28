"""Tests for the .epg / sites.csv / edges.csv writers.

The generated project must be parseable exactly the way Epigrass parses it:
ConfigParser with lowercased keys and eval()-ed values.
"""

import configparser

import pytest

from epigrass_qgis.writer.epg_writer import (
    Edge,
    ModelSpec,
    SeedEvent,
    Site,
    VaccinationEvent,
    edges_csv_text,
    render_epg,
    sites_csv_text,
    spec_to_dict,
    validate_spec,
    write_project,
)


def make_spec() -> ModelSpec:
    sites = [
        Site("Sao Paulo", 12_000_000, 3550308, -23.55, -46.63),
        Site("Rio de Janeiro", 6_700_000, 3304557, -22.91, -43.17),
        Site("Belo Horizonte", 2_300_000, 3106200, -19.92, -43.94),
    ]
    edges = [
        Edge(3550308, 3304557, 500, 480, 358.5),
        Edge(3550308, 3106200, 200, 210, 500.0),
        Edge(3304557, 3106200, 90, 95, 440.0),
    ]
    return ModelSpec(
        name="test_model",
        model_type="SEIR",
        sites=sites,
        edges=edges,
        params={"beta": "0.4", "alpha": "1", "e": "0.2", "r": "0.14",
                "delta": "0", "B": "0", "w": "0", "p": "0"},
        inits={"S": "N", "E": "100", "I": "0"},
        seed=[SeedEvent(3550308, "I", 10)],
        vaccinate=[VaccinationEvent("all", [30, 60], [0.5, 0.8])],
        steps=200,
    )


def parse_epg(text: str) -> dict:
    """Mimic Epigrass.manager.loadModelScript."""
    cp = configparser.ConfigParser()
    cp.read_string(text)
    config = {}
    for section in cp.sections():
        for option in cp.options(section):
            config[f"{section.lower()}.{option.lower()}"] = cp.get(section, option).strip()
    return config


def test_render_epg_is_parseable_and_evaluable():
    config = parse_epg(render_epg(make_spec()))
    assert config["the world.sites"] == "sites.csv"
    assert config["the world.edges"] == "edges.csv"
    assert eval(config["the world.shapefile"]) == ["map.gpkg", "name", "geocode"]
    assert config["epidemiological model.modtype"] == "SEIR"
    assert config["model parameters.beta"] == "0.4"
    assert config["model parameters.b"] == "0"  # B lowercased by ConfigParser
    assert eval(config["epidemic events.seed"]) == [(3550308, "I", 10)]
    assert eval(config["epidemic events.vaccinate"]) == [("all", [30, 60], [0.5, 0.8])]
    assert eval(config["simulation and output.steps"]) == 200
    assert eval(config["transportation model.dotransp"]) == 1
    assert config["initial conditions.s"] == "N"
    assert config["initial conditions.e"] == "100"


def test_inits_evaluable_like_epigrass():
    """instSites does inits[k.lower()] = eval(v) for each initial condition."""
    config = parse_epg(render_epg(make_spec()))
    inits = {}
    for key, value in config.items():
        if key.startswith("initial conditions."):
            k = key.split(".")[-1].lower()
            inits[k] = eval(value, {"N": 1_000})
    assert inits == {"s": 1000, "e": 100, "i": 0}


def test_sites_csv_positional_columns():
    text = sites_csv_text(make_spec())
    lines = text.strip().split("\n")
    assert lines[0] == "lat,long,City,Pop,Geocode"
    first = lines[1].split(",")
    # lat, long, name, pop, geocode (positional, matching manager.instSites)
    assert first[2] == "Sao Paulo"
    assert first[4] == "3550308"
    assert float(first[0]) == pytest.approx(-23.55)
    assert float(first[1]) == pytest.approx(-46.63)


def test_sites_csv_quotes_names_with_commas():
    spec = make_spec()
    spec.sites[0].name = "City, with comma"
    text = sites_csv_text(spec)
    # csv quoting keeps the row parseable by pandas (Epigrass data_io)
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1][2] == "City, with comma"
    assert rows[1][4] == "3550308"


def test_edges_csv_positional_columns():
    text = edges_csv_text(make_spec())
    lines = text.strip().split("\n")
    assert lines[0] == "Source,Dest,flowSD,flowDS,Distance,geoSource,geoDest"
    first = lines[1].split(",")
    assert first[0] == "Sao Paulo"
    assert first[5] == "3550308"  # geocode source (index 5, per instEdges)
    assert first[6] == "3304557"  # geocode dest (index 6)
    assert float(first[4]) == 358.5


def test_validate_spec_reports_problems():
    spec = make_spec()
    assert validate_spec(spec) == []
    spec.sites.append(Site("Dup", 1000, 3550308, 0.0, 0.0))  # duplicated geocode
    spec.edges.append(Edge(1, 2, 0, 0, 0))  # unknown geocodes
    problems = validate_spec(spec)
    assert any("Duplicated geocode" in p for p in problems)
    assert any("not a site" in p for p in problems)


def test_write_project_creates_all_files(tmp_path):
    paths = write_project(make_spec(), tmp_path / "project")
    for key in ("epg", "sites", "edges", "json"):
        assert paths[key]
        assert __import__("pathlib").Path(paths[key]).exists()
    config = parse_epg((tmp_path / "project" / "model.epg").read_text())
    assert config["the world.sites"] == "sites.csv"


def test_write_project_rejects_invalid_spec(tmp_path):
    spec = make_spec()
    spec.sites = []  # no sites
    with pytest.raises(ValueError):
        write_project(spec, tmp_path / "invalid")


def test_spec_to_dict_is_serialisable():
    import json

    data = spec_to_dict(make_spec())
    assert json.loads(json.dumps(data))["name"] == "test_model"
    assert len(data["sites"]) == 3
    assert data["edges"][0]["source"] == 3550308
