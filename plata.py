"""Public PLATA API with backward-compatible plugin exports."""

import sys

from plata_core import Cardinal, Plata, PluginData, get_cardinal, get_plata
from compatibility import cardinal as _cardinal_compat

# Existing plugins import a top-level module named ``cardinal``. Register the
# hidden compatibility module before PLATA starts loading plugins.
sys.modules.setdefault("cardinal", _cardinal_compat)

PlataPluginData = PluginData

__all__ = (
    "Plata",
    "get_plata",
    "PlataPluginData",
    "Cardinal",
    "get_cardinal",
    "PluginData",
)
