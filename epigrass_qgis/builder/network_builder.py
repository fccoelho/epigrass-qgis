"""Network (edge) generation algorithms.

Pure Python — operates on :class:`epigrass_qgis.writer.epg_writer.Site` records
and produces :class:`epigrass_qgis.writer.epg_writer.Edge` records.

Edges follow Epigrass convention: one row per *ordered* pair with both
directional flows (flowSD = source->dest, flowDS = dest->source).
"""

from __future__ import annotations

import math
from collections import defaultdict

from ..writer.epg_writer import Edge

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def default_flow(distance_km: float) -> int:
    """Distance-decay heuristic flow used when no real flow data is available."""
    return max(10, int(1000 / (distance_km + 1)))


def _pair_key(a: int, b: int) -> tuple:
    return (a, b) if a <= b else (b, a)


class EdgeBuilder:
    """Accumulates one Edge per unordered site pair with symmetric flows.

    Directional flows set later by attribute-based builders can be applied on
    top of the symmetric default.
    """

    def __init__(self) -> None:
        self._pairs: dict = {}

    def add(self, source: int, dest: int, distance_km: float,
            flow_sd: float | None = None, flow_ds: float | None = None) -> None:
        if source == dest:
            return
        key = _pair_key(source, dest)
        if key in self._pairs:
            return
        if flow_sd is None:
            flow = default_flow(distance_km)
            flow_sd = flow_ds = flow
        self._pairs[key] = Edge(
            source=key[0], dest=key[1],
            flow_sd=flow_sd if key[0] == source else flow_ds,
            flow_ds=flow_ds if key[0] == source else flow_sd,
            distance_km=distance_km,
        )

    def edges(self) -> list:
        return list(self._pairs.values())


def build_knn(sites: list, k: int = 4) -> list:
    """Connect each site to its *k* nearest neighbours."""
    if k < 1:
        raise ValueError("k must be >= 1")
    builder = EdgeBuilder()
    for i, site in enumerate(sites):
        dists = sorted(
            (
                haversine_km(site.lat, site.lon, other.lat, other.lon), other.geocode
            )
            for j, other in enumerate(sites) if j != i
        )
        for distance, geocode in dists[:k]:
            builder.add(site.geocode, geocode, distance)
    return builder.edges()


def build_distance_threshold(sites: list, threshold_km: float) -> list:
    """Connect every pair of sites within *threshold_km* of each other."""
    if threshold_km <= 0:
        raise ValueError("threshold_km must be positive")
    builder = EdgeBuilder()
    for i, a in enumerate(sites):
        for b in sites[i + 1:]:
            d = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if d <= threshold_km:
                builder.add(a.geocode, b.geocode, d)
    return builder.edges()


def build_adjacency(sites: list, neighbour_pairs: list) -> list:
    """Build edges from *neighbour_pairs*, an iterable of (geocode_a, geocode_b).

    The pairs (e.g. polygons sharing a border) are computed on the QGIS side;
    here we only compute distances and flows.
    """
    coords = {s.geocode: (s.lat, s.lon) for s in sites}
    builder = EdgeBuilder()
    for a, b in neighbour_pairs:
        if a not in coords or b not in coords:
            continue
        d = haversine_km(*coords[a], *coords[b])
        builder.add(a, b, d)
    return builder.edges()


def build_from_records(sites: list, records: list) -> list:
    """Build edges from attribute-table flow *records*.

    Each record is a tuple ``(source_geocode, dest_geocode, flow_sd, flow_ds,
    distance_km_or_None)``.  When no distance is available it is computed from
    the site coordinates.  Duplicate pairs keep their *last* record (latest
    values win), which lets users override heuristic flows with real ones.
    """
    coords = {s.geocode: (s.lat, s.lon) for s in sites}
    by_pair: dict = {}
    for src, dst, flow_sd, flow_ds, dist in records:
        src, dst = int(src), int(dst)
        if src == dst or src not in coords or dst not in coords:
            continue
        if dist is None:
            dist = haversine_km(*coords[src], *coords[dst])
        by_pair[_pair_key(src, dst)] = Edge(
            source=_pair_key(src, dst)[0], dest=_pair_key(src, dst)[1],
            flow_sd=float(flow_sd or 0), flow_ds=float(flow_ds or 0),
            distance_km=float(dist),
        )
    # Orient each edge according to the dominant flow direction.
    edges = []
    for _key, e in by_pair.items():
        if e.flow_ds > e.flow_sd:
            edges.append(Edge(e.dest, e.source, e.flow_ds, e.flow_sd, e.distance_km))
        else:
            edges.append(e)
    return edges


def network_summary(sites: list, edges: list) -> str:
    """Human-readable one-line summary of a network."""
    deg = defaultdict(int)
    for e in edges:
        deg[e.source] += 1
        deg[e.dest] += 1
    isolated = sum(1 for s in sites if deg.get(s.geocode, 0) == 0)
    return (
        f"{len(sites)} sites, {len(edges)} edges "
        f"(avg degree {2 * len(edges) / len(sites):.1f})"
        + (f", {isolated} isolated sites!" if isolated else "")
    )
