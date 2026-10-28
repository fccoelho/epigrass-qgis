"""QGIS options page for the Epigrass plugin (environment settings)."""

from __future__ import annotations

import os

from qgis.core import QgsSettings
from qgis.gui import QgsFileWidget, QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .defs import (
    DEFAULT_ENV_DIR,
    PLUGIN_KEY,
    SETTING_ENV_DIR,
    SETTING_PYTHON_PATH,
    SETTING_REDIS_BINARY,
)

ICON = os.path.join(os.path.dirname(__file__), "icons", "egicon.png")


class OptionsPage(QgsOptionsPageWidget):
    """'Epigrass' tab in QGIS Preferences."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        settings = QgsSettings()
        self.python_edit = QLineEdit(settings.value(SETTING_PYTHON_PATH, "", str))
        python_layout = QHBoxLayout()
        python_layout.addWidget(self.python_edit)
        browse = QPushButton("...")
        browse.setMaximumWidth(32)
        browse.clicked.connect(self._browse_python)
        python_layout.addWidget(browse)
        form.addRow("Python >= 3.12 (blank = autodetect):", python_layout)

        self.env_widget = QgsFileWidget()
        self.env_widget.setStorageMode(QgsFileWidget.GetDirectory)
        self.env_widget.setFilePath(
            settings.value(SETTING_ENV_DIR, f"~/{DEFAULT_ENV_DIR}", str))
        form.addRow("Managed environment:", self.env_widget)

        self.host_edit = QLineEdit(
            settings.value(f"{PLUGIN_KEY}/redis/host", "localhost", str))
        form.addRow("Redis host:", self.host_edit)
        self.port_edit = QLineEdit(
            str(settings.value(f"{PLUGIN_KEY}/redis/port", 6379, int) or 6379))
        form.addRow("Redis port:", self.port_edit)
        self.redis_edit = QLineEdit(
            settings.value(SETTING_REDIS_BINARY, "", str))
        form.addRow("redis-server binary (blank = autodetect):", self.redis_edit)
        self.stop_check = QCheckBox("Stop plugin-started Redis when QGIS exits")
        self.stop_check.setChecked(
            bool(settings.value(f"{PLUGIN_KEY}/redis/stop_on_exit", True, bool)))
        form.addRow("", self.stop_check)

        note = QLabel(
            "Epigrass runs in its own Python environment, separate from QGIS. "
            "Use the Environment Doctor toolbar button to provision it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _browse_python(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Python interpreter", self.python_edit.text() or "/usr/bin")
        if path:
            self.python_edit.setText(path)

    def apply(self):
        settings = QgsSettings()
        settings.setValue(SETTING_PYTHON_PATH, self.python_edit.text().strip())
        settings.setValue(SETTING_ENV_DIR, self.env_widget.filePath())
        settings.setValue(f"{PLUGIN_KEY}/redis/host", self.host_edit.text().strip())
        try:
            port = int(self.port_edit.text())
        except ValueError:
            port = 6379
        settings.setValue(f"{PLUGIN_KEY}/redis/port", port)
        settings.setValue(SETTING_REDIS_BINARY, self.redis_edit.text().strip())
        settings.setValue(f"{PLUGIN_KEY}/redis/stop_on_exit", self.stop_check.isChecked())


class OptionsFactory(QgsOptionsWidgetFactory):
    """Registers the Epigrass page with the QGIS options dialog."""

    def __init__(self):
        super().__init__("Epigrass", QIcon(ICON))

    def createWidget(self, parent):
        return OptionsPage(parent)
