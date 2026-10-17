"""Element registry: slot -> variant id -> class.

A skin picks one variant id per slot. Variants register themselves here, so a
variant added for one skin is automatically offered to every skin. Task 6
replaces the placeholder classes below with real painting under the same ids.
"""
from __future__ import annotations

from collections.abc import Mapping

# slot -> {variant id: (class, label)}, in registration order
_VARIANTS: dict[str, dict[str, tuple[type, str]]] = {}

# The skeuomorphic skin's choice for every slot; also the fallback for unknown ids.
DEFAULTS: dict[str, str] = {
    "frame": "metal_rack",
    "switch": "bat_toggle",
    "knob": "machined",
    "meter": "led_segments",
    "panel": "brushed",
    "screws": "corners_only",
    "density": "comfortable",
}


def register(slot: str, variant: str, cls: type, label: str) -> None:
    """Register (or replace) ``variant`` of ``slot``."""
    _VARIANTS.setdefault(slot, {})[variant] = (cls, label)


def variants(slot: str) -> list[str]:
    """Variant ids registered for ``slot`` in registration order (empty if unknown)."""
    return list(_VARIANTS.get(slot, {}))


def get(slot: str, variant: str) -> type:
    """The class registered for ``slot``/``variant``; KeyError if there is none."""
    return _VARIANTS[slot][variant][0]


def label(slot: str, variant: str) -> str:
    """Human-readable name of a variant; KeyError if there is none."""
    return _VARIANTS[slot][variant][1]


def resolve(elements: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Complete and validate a slot -> variant mapping.

    Missing slots take their default silently. An unknown variant (a skin file
    from a newer build) falls back to the slot default with a notice such as
    ``"switch: 'laser' not available, using bat_toggle"``. An unknown slot is
    dropped with a notice. Never raises.
    """
    resolved: dict[str, str] = {}
    notices: list[str] = []
    for slot, default in DEFAULTS.items():
        variant = elements.get(slot, default)
        if variant in _VARIANTS.get(slot, {}):
            resolved[slot] = variant
        else:
            resolved[slot] = default
            notices.append(f"{slot}: {variant!r} not available, using {default}")
    for slot in elements:
        if slot not in DEFAULTS:
            notices.append(f"{slot}: unknown element slot, ignored")
    return resolved, notices


# ------------------------------------------------------- placeholder variants

class PlaceholderElement:
    """Stand-in for a variant until its real painting lands (Task 6)."""

    slot = ""
    variant = ""


_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "frame": ("metal_rack", "wood_cheeks", "frameless"),
    "switch": ("bat_toggle", "rocker", "pill"),
    "knob": ("machined", "vintage_bakelite", "flat_ring"),
    "meter": ("led_segments", "smooth_bar"),
    "panel": ("brushed", "lacquer", "flat"),
    "screws": ("corners_only", "none"),
    "density": ("compact", "comfortable"),
}

for _slot, _ids in _PLACEHOLDERS.items():
    for _id in _ids:
        _name = "".join(part.title() for part in (_slot, *_id.split("_")))
        register(_slot, _id,
                 type(_name, (PlaceholderElement,), {"slot": _slot, "variant": _id}),
                 _id.replace("_", " ").capitalize())
