"""The "Build model from layer" wizard."""

from __future__ import annotations

import os

from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..builder import layer_export, presets
from ..builder.network_builder import (
    build_adjacency,
    build_distance_threshold,
    build_from_records,
    build_knn,
    network_summary,
)
from ..defs import SETTING_LAST_PROJECT_DIR
from ..writer.epg_writer import (
    ModelSpec,
    SeedEvent,
    VaccinationEvent,
    render_epg,
    validate_spec,
)
from .seed_picker import SeedPickerTool

PAGE_SITES, PAGE_NETWORK, PAGE_MODEL, PAGE_EVENTS, PAGE_REVIEW = range(5)

METHOD_ADJACENCY = 0
METHOD_KNN = 1
METHOD_DISTANCE = 2
METHOD_ATTRIBUTES = 3


def _form(widget: QWidget) -> QFormLayout:
    layout = QFormLayout(widget)
    layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return layout


class SitesPage(QWizardPage):
    """Step 1 - choose the layer and map its columns to site attributes."""

    def __init__(self, wizard: ModelWizard):
        super().__init__()
        self.wizard = wizard
        self.setTitle("1. Layer and sites")
        self.setSubTitle(
            "Choose the vector layer representing your study area and map its "
            "columns to the site name, population and geocode.")
        layout = _form(self)

        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._populate_fields)
        layout.addRow("Map layer:", self.layer_combo)
        refresh_btn = QPushButton("Refresh layer list")
        refresh_btn.clicked.connect(self.refresh_layers)
        layout.addRow("", refresh_btn)

        self.name_combo = QComboBox()
        layout.addRow("Site name column:", self.name_combo)
        self.pop_combo = QComboBox()
        layout.addRow("Population column:", self.pop_combo)
        self.geocode_combo = QComboBox()
        layout.addRow("Geocode column:", self.geocode_combo)
        self.auto_geocode = QCheckBox("Generate geocodes from feature ids")
        self.auto_geocode.setChecked(True)
        self.auto_geocode.toggled.connect(self._toggle_geocode)
        layout.addRow("", self.auto_geocode)

        self.summary = QLabel("")
        layout.addRow(self.summary)

    # ------------------------------------------------------------------
    def refresh_layers(self):
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in layer_export.vector_layers(QgsProject.instance()):
            self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.blockSignals(False)
        self._populate_fields()

    def _current_layer(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        return layer if isinstance(layer, QgsVectorLayer) else None

    def _populate_fields(self):
        layer = self._current_layer()
        for combo in (self.name_combo, self.pop_combo, self.geocode_combo):
            combo.clear()
            if layer:
                combo.addItems(layer.fields().names())
            combo.setEnabled(layer is not None)
        self._suggest_fields(layer)
        self._toggle_geocode()

    def _suggest_fields(self, layer):
        if layer is None:
            return
        hints = {
            self.name_combo: ("nome", "name", "munic", "city", "zona", "region", "dist"),
            self.pop_combo: ("pop", "habit", "pob", "population"),
            self.geocode_combo: ("geocod", "cod", "cd_", "ibge", "id"),
        }
        names = [n.lower() for n in layer.fields().names()]
        for combo, keys in hints.items():
            for key in keys:
                for name, lower in zip(layer.fields().names(), names, strict=False):
                    if key in lower:
                        combo.setCurrentText(name)
                        break
                else:
                    continue
                break

    def _toggle_geocode(self):
        self.geocode_combo.setEnabled(
            not self.auto_geocode.isChecked() and self._current_layer() is not None)

    def geocode_field(self) -> str:
        return "" if self.auto_geocode.isChecked() else self.geocode_combo.currentText()

    def isComplete(self) -> bool:
        layer = self._current_layer()
        if layer is None:
            self.summary.setText("Select a map layer to continue.")
            return False
        return bool(self.name_combo.currentText() and self.pop_combo.currentText())

    def validatePage(self) -> bool:
        layer = self._current_layer()
        if layer is None:
            return False
        try:
            sites, warnings = layer_export.extract_sites(
                layer,
                name_field=self.name_combo.currentText(),
                pop_field=self.pop_combo.currentText(),
                geocode_field=self.geocode_field(),
            )
        except (ValueError, RuntimeError) as exc:
            self.summary.setText(f"Error reading layer: {exc}")
            return False
        if not sites:
            self.summary.setText(
                "No valid sites extracted. Check the name/population columns.")
            return False
        message = f"{len(sites)} sites extracted from '{layer.name()}'."
        if warnings:
            message += "\n".join(["", *warnings])
        self.summary.setText(message)
        self.wizard.set_layer(layer)
        self.wizard.set_sites(sites)
        return True


class NetworkPage(QWizardPage):
    """Step 2 - how sites connect to each other."""

    def __init__(self, wizard: ModelWizard):
        super().__init__()
        self.wizard = wizard
        self.setTitle("2. Connectivity network")
        self.setSubTitle(
            "Define how sites are connected. The network determines how the "
            "disease spreads between locations.")
        layout = QVBoxLayout(self)
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            "Shared-border adjacency (polygons)",
            "K nearest neighbours",
            "Distance threshold",
            "Flows from attribute table",
        ])
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        layout.addWidget(self.method_combo)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Adjacency: nothing to configure
        self.stack.addWidget(QWidget())
        # kNN
        knn_page = QWidget()
        knn_form = _form(knn_page)
        self.k_spin = QSpinBox()
        self.k_spin.setRange(1, 100)
        self.k_spin.setValue(4)
        knn_form.addRow("Neighbours per site (k):", self.k_spin)
        self.stack.addWidget(knn_page)
        # Distance threshold
        dist_page = QWidget()
        dist_form = _form(dist_page)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 20000.0)
        self.threshold_spin.setValue(100.0)
        self.threshold_spin.setSuffix(" km")
        dist_form.addRow("Maximum distance:", self.threshold_spin)
        self.stack.addWidget(dist_page)
        # Attribute flows
        attr_page = QWidget()
        self.attr_form = _form(attr_page)
        self.from_combo = QComboBox()
        self.to_combo = QComboBox()
        self.flowsd_combo = QComboBox()
        self.flowds_combo = QComboBox()
        self.dist_combo = QComboBox()
        for label, combo in (
            ("Origin geocode column:", self.from_combo),
            ("Destination geocode column:", self.to_combo),
            ("Flow origin->dest column (optional):", self.flowsd_combo),
            ("Flow dest->origin column (optional):", self.flowds_combo),
            ("Distance column, km (optional):", self.dist_combo),
        ):
            self.attr_form.addRow(label, combo)
        self.stack.addWidget(attr_page)
        self._method_changed(0)

        self.preview_btn = QPushButton("Preview network on the map")
        self.preview_btn.clicked.connect(self._preview)
        layout.addWidget(self.preview_btn)
        self.summary = QLabel("")
        layout.addWidget(self.summary)

    def _method_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == METHOD_ATTRIBUTES:
            layer = self.wizard.layer
            for combo in (self.from_combo, self.to_combo, self.flowsd_combo,
                          self.flowds_combo, self.dist_combo):
                combo.clear()
                combo.addItem("")  # optional/none
                if layer:
                    combo.addItems(layer.fields().names())

    def _build_edges(self):
        sites = self.wizard.sites
        method = self.method_combo.currentIndex()
        if method == METHOD_ADJACENCY:
            pairs = layer_export.touching_pairs(
                self.wizard.layer, self.wizard.sites_page.geocode_field())
            return build_adjacency(sites, pairs)
        if method == METHOD_KNN:
            return build_knn(sites, self.k_spin.value())
        if method == METHOD_DISTANCE:
            return build_distance_threshold(sites, self.threshold_spin.value())
        return build_from_records(sites, self._attribute_records())

    def _attribute_records(self):
        layer = self.wizard.layer
        from_f, to_f = self.from_combo.currentText(), self.to_combo.currentText()
        fields = layer.fields().names()
        if not from_f or not to_f or from_f not in fields or to_f not in fields:
            raise ValueError("Origin and destination geocode columns are required.")
        flowsd_f = self.flowsd_combo.currentText()
        flowds_f = self.flowds_combo.currentText()
        dist_f = self.dist_combo.currentText()
        records = []
        for feature in layer.getFeatures():
            try:
                src, dst = int(feature[from_f]), int(feature[to_f])
                flow_sd = float(feature[flowsd_f]) if flowsd_f else None
                flow_ds = float(feature[flowds_f]) if flowds_f else None
                dist = float(feature[dist_f]) if dist_f else None
            except (TypeError, ValueError, KeyError):
                continue
            records.append((src, dst, flow_sd, flow_ds, dist))
        return records

    def _preview(self):
        try:
            edges = self._build_edges()
        except ValueError as exc:
            self.summary.setText(f"Error: {exc}")
            return
        if not edges:
            self.summary.setText("No edges were generated with these settings.")
            return
        self.summary.setText(network_summary(self.wizard.sites, edges))
        self.wizard.set_edges(edges)
        self.wizard.show_edge_preview(edges)

    def validatePage(self) -> bool:
        try:
            edges = self._build_edges()
        except ValueError as exc:
            self.summary.setText(f"Error: {exc}")
            return False
        if not edges:
            self.summary.setText(
                "No edges were generated. Adjust the settings and preview again.")
            return False
        self.wizard.set_edges(edges)
        self.summary.setText(network_summary(self.wizard.sites, edges))
        return True


class ModelPage(QWizardPage):
    """Step 3 - epidemiological model, parameters and simulation settings."""

    def __init__(self, wizard: ModelWizard):
        super().__init__()
        self.wizard = wizard
        self.setTitle("3. Epidemiological model")
        self.setSubTitle(
            "Choose the compartmental model and its parameters, or start from a "
            "disease preset.")
        layout = _form(self)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(presets.preset_names())
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        self.preset_note = QLabel("")
        layout.addRow("Disease preset:", self.preset_combo)
        layout.addRow("", self.preset_note)

        self.model_combo = QComboBox()
        from ..defs import SUPPORTED_MODELS
        self.model_combo.addItems(SUPPORTED_MODELS)
        layout.addRow("Model type:", self.model_combo)

        self.param_edits = {}
        params_box = QWidget()
        params_form = _form(params_box)
        for key, label in (
            ("beta", "beta (transmission):"),
            ("alpha", "alpha (non-linear exponent):"),
            ("e", "e (latent rate, 1/latent):"),
            ("r", "r (recovery rate, 1/infectious):"),
            ("delta", "delta (immunity loss):"),
            ("B", "B (birth rate):"),
            ("w", "w (immunity waning):"),
            ("p", "p (relapse probability):"),
        ):
            edit = QLineEdit()
            self.param_edits[key] = edit
            params_form.addRow(label, edit)
        layout.addRow("Parameters:", params_box)

        inits_box = QWidget()
        inits_form = _form(inits_box)
        self.inits_edits = {}
        for key, label, default in (
            ("S", "S (susceptible):", "N"),
            ("E", "E (exposed):", "10"),
            ("I", "I (infectious):", "0"),
        ):
            edit = QLineEdit(default)
            self.inits_edits[key] = edit
            inits_form.addRow(label, edit)
        layout.addRow("Initial conditions (N = population):", inits_box)

        transport_box = QWidget()
        transport_form = _form(transport_box)
        self.transport_check = QCheckBox("Include transportation of infectious individuals")
        self.transport_check.setChecked(True)
        self.stochastic_check = QCheckBox("Stochastic transportation")
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0, 10000)
        self.speed_spin.setValue(0)
        self.speed_spin.setSuffix(" km/step")
        transport_form.addRow(self.transport_check)
        transport_form.addRow(self.stochastic_check)
        transport_form.addRow("Average travel speed:", self.speed_spin)
        layout.addRow("Transport:", transport_box)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 100000)
        self.steps_spin.setValue(365)
        layout.addRow("Simulation steps (days):", self.steps_spin)

    def _apply_preset(self, name: str):
        preset = presets.get_preset(name)
        self.preset_note.setText(preset["description"])
        self.model_combo.setCurrentText(preset["model"])
        for key, value in preset["params"].items():
            if key in self.param_edits:
                self.param_edits[key].setText(str(value))
        for key, value in preset["inits"].items():
            if key in self.inits_edits:
                self.inits_edits[key].setText(str(value))


class EventsPage(QWizardPage):
    """Step 4 - epidemic events: initial seed and vaccination campaigns."""

    def __init__(self, wizard: ModelWizard):
        super().__init__()
        self.wizard = wizard
        self.setTitle("4. Epidemic events")
        self.setSubTitle("Where and how the outbreak starts, plus optional vaccination.")
        layout = QVBoxLayout(self)

        seed_box = QGroupBox("Initial seed")
        seed_form = _form(seed_box)
        row = QHBoxLayout()
        self.pick_btn = QPushButton("Pick seed site on the map...")
        self.pick_btn.clicked.connect(self._start_picking)
        row.addWidget(self.pick_btn)
        self.seed_info = QLabel("No seed selected")
        row.addWidget(self.seed_info, 1)
        seed_form.addRow(row)
        self.seed_state = QComboBox()
        self.seed_state.addItems(["I", "E", "S"])
        seed_form.addRow("Add to state:", self.seed_state)
        self.seed_amount = QSpinBox()
        self.seed_amount.setRange(1, 10_000_000)
        self.seed_amount.setValue(10)
        seed_form.addRow("Number of individuals:", self.seed_amount)
        layout.addWidget(seed_box)

        vacc_box = QGroupBox("Vaccination campaigns (optional)")
        vacc_layout = QVBoxLayout(vacc_box)
        self.vacc_table = QTableWidget(0, 3)
        self.vacc_table.setHorizontalHeaderLabels(
            ["Geocode (or 'all')", "Times (t1,t2,...)", "Coverages (c1,c2,...)"])
        self.vacc_table.horizontalHeader().setStretchLastSection(True)
        self.vacc_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        vacc_layout.addWidget(self.vacc_table)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add campaign")
        add_btn.clicked.connect(self._add_vacc_row)
        del_btn = QPushButton("Remove selected")
        del_btn.clicked.connect(self._del_vacc_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        vacc_layout.addLayout(btn_row)
        layout.addWidget(vacc_box)
        layout.addStretch(1)

    def _add_vacc_row(self):
        self.vacc_table.insertRow(self.vacc_table.rowCount())

    def _del_vacc_row(self):
        rows = sorted({i.row() for i in self.vacc_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.vacc_table.removeRow(row)

    def _start_picking(self):
        self.wizard.start_seed_picking(self._on_seed_picked)

    def _on_seed_picked(self, geocode, detail):
        if geocode is None:
            self.seed_info.setText(detail or "No site picked")
            self.wizard.seed_geocode = None
            return
        self.wizard.seed_geocode = geocode
        self.seed_info.setText(f"Seed site: {detail} (geocode {geocode})")

    def validatePage(self) -> bool:
        if self.wizard.seed_geocode is None:
            self.seed_info.setText("Pick a seed site on the map to continue.")
            return False
        return True


class ReviewPage(QWizardPage):
    """Step 5 - review the generated model script and choose the output folder."""

    def __init__(self, wizard: ModelWizard):
        super().__init__()
        self.wizard = wizard
        self.setTitle("5. Review and generate")
        self.setSubTitle("Check the model script and choose where to save the project.")
        layout = QVBoxLayout(self)
        self.folder_widget = QgsFileWidget()
        self.folder_widget.setStorageMode(QgsFileWidget.GetDirectory)
        self.folder_widget.setDialogTitle("Select model project folder")
        layout.addWidget(QLabel("Project folder:"))
        layout.addWidget(self.folder_widget)
        layout.addWidget(QLabel("model.epg preview:"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.run_now = QCheckBox("Run the simulation right after generating")
        self.run_now.setChecked(True)
        layout.addWidget(self.run_now)

    def initializePage(self):
        spec = self.wizard.build_spec()
        errors = validate_spec(spec)
        text = render_epg(spec)
        if errors:
            text = "!! FIX THESE PROBLEMS BEFORE GENERATING:\n- " + \
                "\n- ".join(errors) + "\n\n" + text
        self.preview.setPlainText(text)

    def validatePage(self) -> bool:
        spec = self.wizard.build_spec()
        errors = validate_spec(spec)
        if errors:
            self.preview.setPlainText(
                "!! FIX THESE PROBLEMS:\n- " + "\n- ".join(errors))
            return False
        folder = self.folder_widget.filePath()
        if not folder:
            self.preview.setPlainText("Choose a project folder first.")
            return False
        self.wizard.output_folder = folder
        self.wizard.run_after_build = self.run_now.isChecked()
        return True


class ModelWizard(QWizard):
    """Guided creation of an Epigrass project from a QGIS layer.

    Emits ``project_generated(project_dir, model_name)`` after the files are
    written (and ``run_requested`` when the user wants to simulate right away).
    """

    project_generated = pyqtSignal(str, str)
    run_requested = pyqtSignal(str, str)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Epigrass - Build model from layer")
        self.setWizardStyle(QWizard.ClassicStyle)

        self.layer = None
        self.sites = []
        self.edges = []
        self.seed_geocode = None
        self.output_folder = ""
        self.run_after_build = False
        self._preview_layer = None
        self._seed_tool = None

        self.sites_page = SitesPage(self)
        self.network_page = NetworkPage(self)
        self.model_page = ModelPage(self)
        self.events_page = EventsPage(self)
        self.review_page = ReviewPage(self)
        self.addPage(self.sites_page)
        self.addPage(self.network_page)
        self.addPage(self.model_page)
        self.addPage(self.events_page)
        self.addPage(self.review_page)

        settings_dir = self._last_dir()
        if settings_dir:
            self.review_page.folder_widget.setFilePath(settings_dir)

    # ------------------------------------------------------------ state
    def set_layer(self, layer):
        self.layer = layer

    def set_sites(self, sites):
        self.sites = sites

    def set_edges(self, edges):
        self.edges = edges

    def _last_dir(self) -> str:
        from qgis.core import QgsSettings

        settings = QgsSettings()
        return settings.value(SETTING_LAST_PROJECT_DIR, "", str) or os.path.expanduser("~")

    # ---------------------------------------------------------- previews
    def show_edge_preview(self, edges):
        """Draw *edges* as a temporary memory layer on the map canvas."""
        from qgis.core import (
            QgsFeature,
            QgsGeometry,
            QgsLineString,
            QgsPointXY,
            QgsVectorLayer,
        )

        # remove previous preview
        if self._preview_layer:
            QgsProject.instance().removeMapLayer(self._preview_layer.id())
            self._preview_layer = None

        uri = "LineString?crs=EPSG:4326&field=flow:double"
        layer = QgsVectorLayer(uri, "Epigrass network preview", "memory")
        provider = layer.dataProvider()
        coords = {s.geocode: (s.lon, s.lat) for s in self.sites}
        features = []
        for edge in edges:
            src, dst = coords.get(edge.source), coords.get(edge.dest)
            if not src or not dst:
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry(
                QgsLineString([QgsPointXY(*src), QgsPointXY(*dst)])))
            feature.setAttribute("flow", float(edge.flow_sd + edge.flow_ds))
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()
        QgsProject.instance().addMapLayer(layer)
        self._preview_layer = layer

    # ------------------------------------------------------------- seed
    def start_seed_picking(self, on_picked):
        canvas = self.iface.mapCanvas()
        geocode_field = self.sites_page.geocode_field()
        name_field = self.sites_page.name_combo.currentText()
        self._seed_tool = SeedPickerTool(
            canvas, self.layer, name_field, geocode_field, on_picked)
        canvas.setMapTool(self._seed_tool)

    def stop_seed_picking(self):
        if self._seed_tool:
            self.iface.mapCanvas().unsetMapTool(self._seed_tool)
            self._seed_tool = None

    # ------------------------------------------------------------ build
    def build_spec(self) -> ModelSpec:
        from ..writer.epg_writer import sanitize_model_name

        model_page = self.model_page
        spec = ModelSpec(
            name=sanitize_model_name(
                self.layer.name() if self.layer else "model"),
            model_type=model_page.model_combo.currentText(),
            sites=list(self.sites),
            edges=list(self.edges),
            params={k: e.text().strip() or "0" for k, e in
                    model_page.param_edits.items()},
            inits={k: e.text().strip() or "0" for k, e in
                   model_page.inits_edits.items()},
            do_transp=model_page.transport_check.isChecked(),
            stochastic=model_page.stochastic_check.isChecked(),
            speed=model_page.speed_spin.value(),
            steps=model_page.steps_spin.value(),
        )
        if self.seed_geocode is not None:
            spec.seed = [SeedEvent(
                geocode=self.seed_geocode,
                state=self.events_page.seed_state.currentText(),
                amount=self.events_page.seed_amount.value(),
            )]
            spec.site_rep = [self.seed_geocode]
        table = self.events_page.vacc_table
        for row in range(table.rowCount()):
            geocode_raw = (table.item(row, 0).text() if table.item(row, 0) else "").strip()
            times_raw = (table.item(row, 1).text() if table.item(row, 1) else "").strip()
            cover_raw = (table.item(row, 2).text() if table.item(row, 2) else "").strip()
            if not geocode_raw or not times_raw:
                continue
            try:
                times = [int(t) for t in times_raw.split(",") if t.strip()]
                coverages = [float(c) for c in cover_raw.split(",") if c.strip()] or [0.0]
            except ValueError:
                continue
            geocode = "all" if geocode_raw.lower() == "all" else geocode_raw
            spec.vaccinate.append(VaccinationEvent(geocode, times, coverages))
        geocode_field = self.sites_page.geocode_field()
        spec.shapefile = (
            "map.gpkg",
            self.sites_page.name_combo.currentText() or "name",
            geocode_field or "geocode",
        )
        return spec

    # ------------------------------------------------------------ accept
    def accept(self):
        from qgis.core import QgsSettings

        from ..builder.layer_export import export_map_gpkg
        from ..writer.epg_writer import write_project

        spec = self.build_spec()
        folder = self.output_folder
        ok = True
        try:
            os.makedirs(folder, exist_ok=True)
            export_map_gpkg(
                self.layer, os.path.join(folder, "map.gpkg"),
                self.sites_page.name_combo.currentText(),
                self.sites_page.geocode_field(),
            )
            write_project(spec, folder)
        except (OSError, RuntimeError, ValueError) as exc:
            ok = False
            self.iface.messageBar().pushCritical(
                "Epigrass", f"Failed to generate model project: {exc}")
        self.stop_seed_picking()
        if not ok:
            return
        settings = QgsSettings()
        settings.setValue(SETTING_LAST_PROJECT_DIR, folder)
        self.iface.messageBar().pushSuccess(
            "Epigrass", f"Model project generated in {folder}")
        self.project_generated.emit(folder, spec.name)
        if self.run_after_build:
            self.run_requested.emit(folder, spec.name)
        super().accept()
