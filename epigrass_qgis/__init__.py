"""Epigrass for QGIS - build and simulate metapopulation epidemic models."""

def classFactory(iface):
    from .plugin import EpigrassPlugin

    return EpigrassPlugin(iface)
