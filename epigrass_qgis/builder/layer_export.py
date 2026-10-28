"""Extract sites from a QGIS layer and export the map GeoPackage for Epigrass."""

from __future__ import annotations

import logging

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType

from ..writer.epg_writer import Site

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"
MAX_FEATURES_WARN = 5000


def vector_layers(project: QgsProject) -> list:
    """Loaded polygon or point vector layers that can serve as a model map."""
    ok_types = {Qgis.GeometryType.Polygon, Qgis.GeometryType.Point}
    return [
        layer for layer in project.mapLayers().values()
        if isinstance(layer, QgsVectorLayer) and layer.geometryType() in ok_types
    ]


def _transform_to_wgs84(layer: QgsVectorLayer) -> QgsCoordinateTransform:
    dest = QgsCoordinateReferenceSystem(WGS84)
    return QgsCoordinateTransform(layer.crs(), dest, QgsProject.instance())


def _centroid_wgs84(geom: QgsGeometry, transform: QgsCoordinateTransform):
    centroid = geom.centroid()
    if centroid.isNull() or centroid.isEmpty():
        centroid = geom.pointOnSurface()
    point = transform.transform(centroid.asPoint())
    return point.y(), point.x()  # lat, lon


def extract_sites(layer: QgsVectorLayer, name_field: str, pop_field: str,
                  geocode_field: str | None = None) -> tuple:
    """Extract :class:`Site` records from *layer*.

    Coordinates are re-projected to WGS84 decimal degrees (what the sites.csv
    format expects).  When *geocode_field* is empty/None the feature id is used.

    Returns ``(sites, warnings)``.
    """
    warnings = []
    count = layer.featureCount()
    if count > MAX_FEATURES_WARN:
        warnings.append(
            f"Layer has {count} features; building the network may take a while.")
    fields = layer.fields()
    missing = [f for f in (name_field, pop_field) if f not in fields.names()]
    if missing:
        raise ValueError(f"Fields not found on layer: {', '.join(missing)}")
    use_fid = not geocode_field or geocode_field not in fields.names()
    transform = _transform_to_wgs84(layer)
    sites, skipped = [], 0
    for feature in layer.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            skipped += 1
            continue
        try:
            lat, lon = _centroid_wgs84(geom, transform)
            name = str(feature[name_field])
            population = float(feature[pop_field] or 0)
            geocode = int(feature.id()) if use_fid else int(feature[geocode_field])
        except (ValueError, TypeError, KeyError) as exc:
            skipped += 1
            log.debug("Skipping feature %s: %s", feature.id(), exc)
            continue
        if not name or population <= 0:
            skipped += 1
            continue
        sites.append(Site(name=name, population=population, geocode=geocode,
                          lat=lat, lon=lon))
    if skipped:
        warnings.append(
            f"{skipped} features skipped (empty geometry, missing population or "
            "invalid geocode).")
    return sites, warnings


def export_map_gpkg(layer: QgsVectorLayer, gpkg_path: str, name_field: str,
                    geocode_field: str | None = None) -> str:
    """Export *layer* to a GeoPackage re-projected to WGS84 (Epigrass background map).

    Returns the path written.  When *geocode_field* is empty the OGR feature id
    is stored in a ``geocode`` column so the .epg ``shapefile`` entry can
    reference it.
    """
    use_fid = not geocode_field or geocode_field not in layer.fields().names()
    transform = _transform_to_wgs84(layer)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "map"
    options.fileEncoding = "UTF-8"
    options.ct = transform
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(gpkg_path), QgsProject.instance().transformContext(), options)
    if result[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Failed to export map: {result[1] or result[0]}")
    # When geocodes come from fids we must write them into the gpkg.
    if use_fid:
        _write_geocodes_from_fid(gpkg_path)
    return str(gpkg_path)


def _geocode_field() -> QgsField:
    return QgsField("geocode", QMetaType.Type.LongLong)


def _write_geocodes_from_fid(gpkg_path: str) -> None:
    """Populate the 'geocode' column of map.gpkg from OGR feature ids."""
    layer = QgsVectorLayer(f"{gpkg_path}|layername=map", "map_tmp", "ogr")
    if not layer.isValid():
        raise RuntimeError("Could not reopen exported map for geocode fill")
    idx = layer.fields().lookupField("geocode")
    if idx < 0:
        return
    layer.startEditing()
    for feature in layer.getFeatures():
        layer.changeAttributeValue(feature.id(), idx, int(feature.id()))
    if not layer.commitChanges():
        raise RuntimeError("Failed to write geocodes into the exported map")


def touching_pairs(layer: QgsVectorLayer, geocode_field: str | None = None) -> list:
    """Return pairs of geocodes whose polygons share a border.

    Uses a spatial index; adjacency is true geometry contact (shared boundary
    or slight overlap), not just bounding-box contact.
    """
    use_fid = not geocode_field or geocode_field not in layer.fields().names()

    def geocode_of(feature):
        return int(feature.id()) if use_fid else int(feature[geocode_field])

    index = QgsSpatialIndex(layer.getFeatures())
    geocodes, geoms = {}, {}
    for feature in layer.getFeatures():
        geocodes[feature.id()] = geocode_of(feature)
        geoms[feature.id()] = feature.geometry()
    pairs = set()
    for fid, geom in geoms.items():
        if geom is None or geom.isEmpty():
            continue
        bbox = geom.boundingBox()
        for candidate in index.intersects(bbox):
            if candidate <= fid:
                continue  # each pair once
            other = geoms.get(candidate)
            if other is None or other.isEmpty():
                continue
            if _are_neighbours(geom, other):
                pairs.add(tuple(sorted((geocodes[fid], geocodes[candidate]))))
    return sorted(pairs)


def _are_neighbours(a: QgsGeometry, b: QgsGeometry) -> bool:
    """True when two polygons share a boundary (or overlap marginally)."""
    if a.touches(b):
        return True
    if not a.intersects(b):
        return False
    # Overlap: count as adjacent only if it is negligible (digitising noise).
    area = a.area() or 1.0
    return a.intersection(b).area() <= 1e-6 * area
