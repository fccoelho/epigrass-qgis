"""Map tool that lets the user pick the seed site by clicking on the map."""

from __future__ import annotations

from qgis.core import (
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgsMapToolEmitPoint


class SeedPickerTool(QgsMapToolEmitPoint):
    """Click a feature of *layer* on the canvas; calls back with (geocode, name).

    ``geocode`` is derived from *geocode_field* (or the feature id when empty).
    """

    def __init__(self, canvas, layer: QgsVectorLayer, name_field: str,
                 geocode_field: str, on_picked):
        super().__init__(canvas)
        self.layer = layer
        self.name_field = name_field
        self.geocode_field = geocode_field
        self.on_picked = on_picked

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        feature = self._nearest_feature(point)
        if feature is None:
            self.on_picked(None, "No feature found at the clicked location")
            return
        geocode = (
            int(feature.id())
            if not self.geocode_field or self.geocode_field not in self.layer.fields().names()
            else int(feature[self.geocode_field])
        )
        name = str(feature[self.name_field]) if self.name_field in self.layer.fields().names() else str(feature.id())
        self.on_picked(geocode, name)

    def _nearest_feature(self, map_point: QgsPointXY):
        layer_crs_point = QgsCoordinateTransform(
            QgsProject.instance().crs(), self.layer.crs(), QgsProject.instance()
        ).transform(map_point)
        dist_area = QgsDistanceArea()
        best, best_dist = None, None
        request = self.layer.getFeatures()
        for feature in request:
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            distance = dist_area.measureLine(
                layer_crs_point, geom.nearestPoint(layer_crs_point))
            if best_dist is None or distance < best_dist:
                best, best_dist = feature, distance
        return best
