"""Shared constants and QSettings keys for the Epigrass QGIS plugin."""

ORGANIZATION = "Epigrass"
PLUGIN_NAME = "epigrass"
PLUGIN_KEY = "epigrass_qgis"

# QSettings keys (all under the plugin key)
SETTING_PYTHON_PATH = f"{PLUGIN_KEY}/env/python_path"      # explicit python >= 3.12 (optional)
SETTING_ENV_DIR = f"{PLUGIN_KEY}/env/venv_dir"             # managed virtualenv location
SETTING_REDIS_HOST = f"{PLUGIN_KEY}/redis/host"
SETTING_REDIS_PORT = f"{PLUGIN_KEY}/redis/port"
SETTING_REDIS_BINARY = f"{PLUGIN_KEY}/redis/binary"        # explicit redis-server path (optional)
SETTING_STOP_REDIS_ON_EXIT = f"{PLUGIN_KEY}/redis/stop_on_exit"
SETTING_LAST_PROJECT_DIR = f"{PLUGIN_KEY}/builder/last_project_dir"

DEFAULT_ENV_DIR = ".epigrass-qgis/env"
DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

#: Python version required by the Epigrass package (pyproject: requires-python >= 3.12)
MIN_PYTHON = (3, 12)

#: Model types understood by Epigrass (Epigrass.models.vnames) that the wizard supports.
#: All of them take the same three initial conditions (S, E, I).
SUPPORTED_MODELS = [
    "SIR",
    "SIR_cont",
    "SEIR",
    "SEIR_cont",
    "SEIS",
    "SIS",
    "SIpR",
    "SIpRpS",
    "SIRS",
    "Custom",
]

CONTINUOUS_MODELS = ("SIR_cont", "SEIR_cont")
