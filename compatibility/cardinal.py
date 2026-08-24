"""Backward-compatible Cardinal plugin API shim."""

from plata_core import Cardinal, Plata, PluginData, get_cardinal, get_plata

# Explicit aliases remain visible to reflection-based legacy plugins.
Plata = Cardinal
get_cardinal = get_plata
__all__ = ("Cardinal", "Plata", "PluginData", "get_cardinal", "get_plata")
