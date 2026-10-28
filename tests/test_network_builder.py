"""Unit tests for the network builder algorithms (pure Python)."""

import math

import pytest

from epigrass_qgis.builder.network_builder import (
    EdgeBuilder,
    build_adjacency,
    build_distance_threshold,
    build_from_records,
    build_knn,
    default_flow,
    haversine_km,
    network_summary,
)
from epigrass_qgis.writer.epg_writer import Site


def make_sites():
    # Square of ~111 km sides + one far away site
    return [
        Site("A", 1000, 1, 0.0, 0.0),
        Site("B", 1000, 2, 0.0, 1.0),
        Site("C", 1000, 3, 1.0, 0.0),
        Site("D", 1000, 4, 1.0, 1.0),
        Site("Far", 1000, 5, 40.0, 40.0),
    ]


def test_haversine_known_distances():
    # Same point
    assert haversine_km(0, 0, 0, 0) == 0.0
    # One degree of latitude ~ 111.2 km
    assert 111.0 < haversine_km(0, 0, 1, 0) < 112.0
    # At the equator one degree of longitude ~ 111.3 km
    assert 111.0 < haversine_km(0, 0, 0, 1) < 112.0
    # Pole to pole is half the Earth's circumference ~ 20 015 km
    assert 20_000 < haversine_km(-90, 0, 90, 0) < 20_030


def test_default_flow():
    assert default_flow(0) == 1000
    assert default_flow(100) == max(10, 1000 // 101)
    assert default_flow(100000) == 10  # floor


def test_knn_connects_closest_sites():
    edges = build_knn(make_sites(), k=2)
    pairs = {(min(e.source, e.dest), max(e.source, e.dest)) for e in edges}
    # The square sites each connect to their 2 nearest (the square edges).
    assert (1, 2) in pairs and (1, 3) in pairs and (2, 4) in pairs and (3, 4) in pairs
    # 'Far' (geocode 5) is nobody's nearest neighbour, but it connects to its
    # own k=2 nearest sites (kNN is per-site, not mutual).
    degree_of_far = sum(1 for e in edges if 5 in (e.source, e.dest))
    assert degree_of_far == 2


def test_distance_threshold_includes_only_close_pairs():
    edges = build_distance_threshold(make_sites(), threshold_km=200)
    pairs = {(min(e.source, e.dest), max(e.source, e.dest)) for e in edges}
    assert (1, 2) in pairs
    assert (1, 5) not in pairs  # Far site beyond 200 km
    for edge in edges:
        assert edge.distance_km <= 200


def test_adjacency_uses_given_pairs():
    edges = build_adjacency(make_sites(), [(1, 2), (2, 3), (5, 5), (1, 99)])
    pairs = {(min(e.source, e.dest), max(e.source, e.dest)) for e in edges}
    assert (1, 2) in pairs and (2, 3) in pairs
    assert (1, 5) not in pairs  # self loop and unknown geocode dropped


def test_flows_from_records_symmetrised_and_oriented():
    records = [
        (1, 2, 10, 50, None),  # dominant flow is 2 -> 1
        (2, 3, 30, 30, 5.0),   # symmetric
        (3, 99, 10, 10, 1.0),  # unknown geocode dropped
        (4, 4, 10, 10, 1.0),   # self loop dropped
    ]
    edges = build_from_records(make_sites(), records)
    by_pair = {(min(e.source, e.dest), max(e.source, e.dest)): e for e in edges}
    e12 = by_pair[(1, 2)]
    assert (e12.source, e12.dest) == (2, 1)
    assert e12.flow_sd == 50 and e12.flow_ds == 10
    e23 = by_pair[(2, 3)]
    assert e23.flow_sd == 30 and e23.flow_ds == 30
    assert e23.distance_km == 5.0


def test_edge_builder_deduplicates():
    builder = EdgeBuilder()
    builder.add(2, 1, 10.0)
    builder.add(1, 2, 99.0)  # same pair, must be ignored
    edges = builder.edges()
    assert len(edges) == 1
    assert edges[0].distance_km == 10.0


def test_summary_counts_isolated_sites():
    sites = make_sites()
    summary = network_summary(sites, build_knn(sites, k=1))
    assert "isolated" not in summary
    summary = network_summary(sites, [])
    assert "5 isolated" in summary


def test_knn_requires_positive_k():
    with pytest.raises(ValueError):
        build_knn(make_sites(), k=0)


def test_threshold_requires_positive():
    with pytest.raises(ValueError):
        build_distance_threshold(make_sites(), threshold_km=0)
    assert math.isfinite(haversine_km(-23.5, -46.6, 23.5, 46.6))
