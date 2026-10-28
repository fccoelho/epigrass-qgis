"""Temporal animation layer built from the simulation SQLite output.

The ``Epigrass.sqlite`` database (written by ``Simulate.outToDb``) contains one
table per run with per-site, per-step rows::

    geocode, time, name, lat, longit, <state variables...>, incidence, Arrivals

This module converts it into a memory point layer with a date field and
configures QGIS temporal properties, so the epidemic can be animated with the
Temporal Controller.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate

log = logging.getLogger(__name__)

#: Date assigned to simulation step 0 (arbitrary, purely for visualisation).
BASE_DATE = dt.date(2020, 1, 1)


def latest_result_table(sqlite_path: str, model_prefix: str) -> str:
    """Name of the most recent ``Model_<prefix>_<timestamp>`` table."""
    if not os.path.isfile(sqlite_path):
        return ""
    con = sqlite3.connect(sqlite_path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"{model_prefix}_%",),
        ).fetchall()
    finally:
        con.close()
    return rows[-1][0] if rows else ""


def build_temporal_layer(project: QgsProject, outdir: str, model_name: str):
    """Create the temporal points layer, or return None when data is missing."""
    sqlite_path = os.path.join(outdir, "Epigrass.sqlite")
    table = latest_result_table(sqlite_path, model_name)
    if not table:
        log.warning("No result table for model '%s' in %s", model_name, sqlite_path)
        return None
    con = sqlite3.connect(sqlite_path)
    try:
        columns = [c[1] for c in con.execute(f'PRAGMA table_info("{table}")')]
        rows = con.execute(
            f'SELECT * FROM "{table}" ORDER BY geocode, time'
        ).fetchall()
    finally:
        con.close()

    # Indices of the selected columns inside each row.
    col_idx = {c: i for i, c in enumerate(columns)}

    # State-variable columns (E, I, S or Exposed/Infectious/... per model).
    state_cols = [c for c in columns if c not in
                  ("geocode", "time", "name", "lat", "longit", "incidence", "Arrivals")]
    infected_idx = [col_idx[c] for c in state_cols
                    if c.lower() in ("e", "exposed", "i", "infectious")]

    uri = (
        "Point?crs=EPSG:4326"
        "&field=geocode:integer&field=step:integer&field=date:date"
        "&field=site:string&field=infected:double&field=incidence:double"
        "&field=arrivals:double"
    )
    layer = QgsVectorLayer(uri, f"Epidemic animation ({model_name})", "memory")
    provider = layer.dataProvider()
    features = []
    for row in rows:
        geocode = row[col_idx["geocode"]]
        step = row[col_idx["time"]]
        name = row[col_idx["name"]]
        lat = row[col_idx["lat"]]
        lon = row[col_idx["longit"]]
        incidence = row[col_idx["incidence"]]
        arrivals = row[col_idx["Arrivals"]]
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        date = BASE_DATE + dt.timedelta(days=int(step))
        feature.setAttributes([
            int(geocode), int(step), QDate(date.year, date.month, date.day),
            str(name), sum(float(row[idx]) for idx in infected_idx),
            float(incidence or 0), float(arrivals or 0),
        ])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    props = layer.temporalProperties()
    props.setIsActive(True)
    props.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
    props.setStartField("date")
    layer.triggerRepaint()
    project.addMapLayer(layer)
    return layer
