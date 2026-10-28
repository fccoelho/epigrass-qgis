"""Load simulation outputs (GeoPackages + SQLite time series) back into QGIS."""

from __future__ import annotations

import logging
import os

from qgis.core import (
    QgsClassificationQuantile,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGraduatedSymbolRenderer,
    QgsProject,
    QgsRendererRange,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor

log = logging.getLogger(__name__)

RESULT_GROUP_PREFIX = "Epigrass"


def find_outdir(project_dir: str, model_name: str) -> str:
    """Return the outdata directory for *model_name* (newest), or ''."""
    default = os.path.join(project_dir, f"outdata-{model_name}")
    if os.path.isdir(default):
        return default
    candidates = sorted(
        os.path.join(project_dir, name)
        for name in os.listdir(project_dir)
        if name.startswith("outdata-") and os.path.isdir(os.path.join(project_dir, name))
    )
    return candidates[-1] if candidates else ""


def _group(project: QgsProject, model_name: str):
    root = project.layerTreeRoot()
    group = root.addGroup(f"{RESULT_GROUP_PREFIX}: {model_name}")
    return group


def _add_to_group(project: QgsProject, group, layer: QgsVectorLayer):
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    return node


def _style_graduated(layer: QgsVectorLayer, field_name: str, title: str) -> bool:
    """Apply a YlOrRd graduated renderer on *field_name* (quantile classes)."""
    if field_name not in layer.fields().names():
        return False
    symbol = QgsFillSymbol.createSimple({"color": "#ffffcc", "outline_color": "grey"})
    renderer = QgsGraduatedSymbolRenderer(
        field_name,
        [QgsRendererRange(0, 0, symbol.clone(), title)],
    )
    renderer.setClassificationMethod(QgsClassificationQuantile())
    renderer.updateClasses(layer, 5)
    # warm ramp from pale yellow to dark red
    renderer.updateColorRamp(QgsGradientColorRamp(
        QColor("#ffffcc"), QColor("#7f0000")))
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return True


def load_results(project: QgsProject, project_dir: str, model_name: str) -> dict:
    """Load Nodes/Edges/Data GeoPackages from the newest outdata dir.

    Returns ``{"outdir": str, "layers": [QgsVectorLayer, ...]}``; raises
    RuntimeError when nothing could be loaded.
    """
    outdir = find_outdir(project_dir, model_name)
    if not outdir:
        raise RuntimeError(f"No outdata-... directory found in {project_dir}")
    group = _group(project, model_name)
    loaded = []
    specs = [
        ("Nodes.gpkg", "Sites", None),
        ("Edges.gpkg", "Network", None),
        ("Data.gpkg", "Results", ("prevalence", "totalcases")),
    ]
    for filename, display, style_fields in specs:
        path = os.path.join(outdir, filename)
        if not os.path.isfile(path):
            continue
        layer_name = filename.split(".")[0]
        layer = QgsVectorLayer(f"{path}|layername={layer_name}", display, "ogr")
        if not layer.isValid():
            log.warning("Invalid layer %s", path)
            continue
        if style_fields:
            for field_name in style_fields:
                if _style_graduated(layer, field_name, display):
                    break
        _add_to_group(project, group, layer)
        loaded.append(layer)
    if not loaded:
        raise RuntimeError(f"No loadable GeoPackages found in {outdir}")
    return {"outdir": outdir, "layers": loaded}
