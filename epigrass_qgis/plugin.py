"""Plugin entry point: toolbar, menus and controllers."""

from __future__ import annotations

import logging
import os

from qgis.core import QgsApplication, QgsProject, QgsSettings, QgsTask
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .defs import PLUGIN_KEY
from .env.doctor import Doctor, DoctorConfig
from .results import loader, temporal
from .runner.task import SimulationTask
from .settings import OptionsFactory

log = logging.getLogger(__name__)

ICON = os.path.join(os.path.dirname(__file__), "icons", "egicon.png")


class DoctorDialog(QDialog):
    """The Environment Doctor dialog: checks, fixes and a live log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Epigrass - Environment Doctor")
        self.setMinimumWidth(640)
        self.doctor = Doctor(DoctorConfig.from_settings(QgsSettings()))
        layout = QVBoxLayout(self)
        self.status = QLabel("Checking environment...")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self.fix_btn = QPushButton("Provision / Fix environment")
        self.fix_btn.clicked.connect(self._run_provision)
        buttons.addButton(self.fix_btn, QDialogButtonBox.ActionRole)
        layout.addWidget(buttons)
        self._run_checks()

    # ------------------------------------------------------------------
    def _run_checks(self):
        results = self.doctor.check_all()
        text = "\n".join(str(r) for r in results)
        self.status.setText(text)
        ok = all(r.ok for r in results)
        self.fix_btn.setEnabled(not ok)
        self.log_view.appendPlainText(f"Checks complete. All ready: {ok}")

    def _run_provision(self):
        self.fix_btn.setEnabled(False)

        def on_line(line: str):
            self.log_view.appendPlainText(line)

        # Provisioning is a long job (pip install); run it as a QGIS task.
        doctor = self.doctor

        class ProvisionTask(QgsTask):
            def run(self):
                results = doctor.provision(on_line=on_line)
                self.ok = all(r.ok for r in results)
                self.text = "\n".join(str(r) for r in results)
                return True

        self._task = ProvisionTask("Epigrass: provisioning environment", QgsTask.CanCancel)

        def on_done():
            self.status.setText(self._task.text)
            self.fix_btn.setEnabled(not self._task.ok)
            self.log_view.appendPlainText("Provisioning finished.")

        self._task.taskCompleted.connect(on_done)
        self._task.taskTerminated.connect(
            lambda: self.log_view.appendPlainText("Provisioning failed."))
        QgsApplication.taskManager().addTask(self._task)

    def closeEvent(self, event):
        self.doctor.shutdown()
        super().closeEvent(event)


class EpigrassPlugin:
    """Main plugin object (see ``classFactory`` in ``__init__.py``)."""

    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu = "&Epigrass"
        self.toolbar = None
        self.wizard = None
        self.sim_task = None
        self.doctor_dialog = None

    # ------------------------------------------------------------- setup
    def initGui(self):
        self.toolbar = self.iface.addToolBar("Epigrass")
        self.toolbar.setObjectName("EpigrassToolbar")
        icon = QIcon(ICON)
        self._add_action(
            icon, "Environment Doctor",
            "Check/provision Python environment, Epigrass and Redis",
            self.show_doctor)
        self._add_action(
            icon, "Build Model from Layer...",
            "Create an Epigrass model from a loaded vector layer",
            self.show_wizard)
        self._add_action(
            icon, "Load Results...",
            "Load the results of a previous simulation into the project",
            self.load_results_dialog)
        for action in self.actions:
            self.iface.addPluginToMenu(self.menu, action)
        self.options_factory = OptionsFactory()
        self.iface.registerOptionsWidgetFactory(self.options_factory)

    def _add_action(self, icon, text, tip, callback, checkable=False):
        from qgis.PyQt.QtWidgets import QAction

        action = QAction(icon, text, self.iface.mainWindow())
        action.setToolTip(tip)
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)
        return action

    def unload(self):
        self.iface.unregisterOptionsWidgetFactory(self.options_factory)
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        self.actions.clear()
        del self.toolbar
        if self.doctor_dialog:
            self.doctor_dialog.close()

    # ---------------------------------------------------------- actions
    def show_doctor(self):
        if self.doctor_dialog is None:
            self.doctor_dialog = DoctorDialog(self.iface.mainWindow())
        self.doctor_dialog.show()
        self.doctor_dialog.raise_()
        self.doctor_dialog.activateWindow()

    def show_wizard(self):
        self.wizard = WizardController(self.iface, self)
        self.wizard.dialog.show()

    # ------------------------------------------------------ simulation
    def run_simulation(self, project_dir: str, model_name: str):
        """Ensure the environment then run epirunner on *project_dir*."""
        doctor = Doctor(DoctorConfig.from_settings(QgsSettings()))
        if not doctor.ensure_ready(
                on_line=lambda line: log.info("doctor: %s", line)):
            self.show_doctor()
            self.iface.messageBar().pushWarning(
                "Epigrass",
                "The environment is not ready. Fix the issues in the Doctor "
                "and run the simulation again.")
            return
        try:
            command = doctor.epirunner_command(os.path.join(project_dir, "model.epg"))
        except RuntimeError as exc:
            self.iface.messageBar().pushCritical("Epigrass", str(exc))
            return
        self._start_task(project_dir, command, model_name, doctor)

    def _start_task(self, project_dir, command, model_name, doctor):
        # A running task? refuse to stack simulations for now.
        if self.sim_task and not self.sim_task.isActive():
            self.sim_task = None
        if self.sim_task:
            self.iface.messageBar().pushWarning(
                "Epigrass", "A simulation is already running.")
            return
        task = SimulationTask(
            f"Epigrass: simulating {model_name}", project_dir, command,
            redis_config=doctor.redis or self._managed_redis(doctor))
        task.signals.log_line.connect(self._log_to_message_log)
        task.signals.finished.connect(
            lambda ok, message: self._on_simulation_done(
                ok, message, project_dir, model_name))
        self.sim_task = task
        self.iface.messageBar().pushMessage(
            "Epigrass", f"Simulation of '{model_name}' started.", duration=5)
        QgsApplication.taskManager().addTask(task)

    @staticmethod
    def _managed_redis(doctor):
        doctor.check_redis()
        return doctor.redis

    @staticmethod
    def _log_to_message_log(line: str):
        log.info("epirunner: %s", line.rstrip())

    def _on_simulation_done(self, ok: bool, message: str, project_dir: str,
                            model_name: str):
        if not ok:
            if message != "cancelled":
                self.iface.messageBar().pushCritical(
                    "Epigrass", f"Simulation failed: {message}")
            return
        try:
            result = loader.load_results(QgsProject.instance(), project_dir, model_name)
            temporal.build_temporal_layer(
                QgsProject.instance(), result["outdir"], model_name)
        except (RuntimeError, OSError) as exc:
            self.iface.messageBar().pushCritical(
                "Epigrass", f"Could not load results: {exc}")
            return
        self.iface.messageBar().pushMessage(
            "Epigrass",
            f"Simulation complete. {len(result['layers'])} result layers loaded "
            "- open the Temporal Controller to animate the epidemic.",
            duration=8)

    def load_results_dialog(self):
        """Manually load results from a previously generated project folder."""
        from qgis.PyQt.QtWidgets import QFileDialog

        settings = QgsSettings()
        last = settings.value(f"{PLUGIN_KEY}/builder/last_project_dir",
                              os.path.expanduser("~"), str)
        folder = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(), "Select Epigrass project folder", last)
        if not folder:
            return
        model_name = os.path.basename(os.path.normpath(folder)) or "model"
        try:
            result = loader.load_results(QgsProject.instance(), folder, model_name)
            temporal.build_temporal_layer(
                QgsProject.instance(), result["outdir"], model_name)
        except (RuntimeError, OSError) as exc:
            self.iface.messageBar().pushCritical(
                "Epigrass", f"Could not load results: {exc}")
            return
        self.iface.messageBar().pushSuccess(
            "Epigrass", f"Results loaded from {result['outdir']}")


class WizardController:
    """Creates the wizard and wires it to the simulation runner."""

    def __init__(self, iface, plugin: EpigrassPlugin):
        from .builder.wizard import ModelWizard

        self.plugin = plugin
        self.dialog = ModelWizard(iface, iface.mainWindow())
        self.dialog.run_requested.connect(plugin.run_simulation)
