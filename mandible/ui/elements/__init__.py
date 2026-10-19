"""Skin element variants (frame, switch, knob, meter, panel, screws, density).

Importing this package registers every variant with ``registry``.
"""
from . import frames, knobs, meters, panels, registry, screws, switches

__all__ = ["frames", "knobs", "meters", "panels", "registry", "screws", "switches"]
