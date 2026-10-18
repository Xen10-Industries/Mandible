"""User skins and themes: storage, import and export.

User looks live as JSON files: ``<APP_DIR>\\skins\\<slug>.json`` (``Mandible.Skin``) and
``<APP_DIR>\\themes\\<slug>.json`` (``Mandible.Theme``). Their ids are ``user:<slug>``; the id of a
loaded look always comes from the *file name*, never from the file's contents.

Files are untrusted data (they get shared between people). Importing only ever parses JSON, checks
the type and range of every field it keeps, ignores everything else, and writes under
``SKINS_DIR`` / ``THEMES_DIR`` using a name this module derives (``slugify``); nothing inside a file
is evaluated, followed as a path, or interpolated into a path.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path

from ..paths import APP_DIR
from . import palette_gen
from .elements import registry
from .look import BUILTIN_PALETTES, BUILTIN_SKINS, PALETTE_TOKENS, SHAPE_TOKENS, SKIN_SLOTS, Palette, Skin

__all__ = [
    "SKINS_DIR", "THEMES_DIR", "MAX_IMPORT_BYTES", "LookFileError", "slugify", "save_skin", "save_palette",
    "load_user_skins", "load_user_palettes", "delete_user_look", "all_skins", "all_palettes",
    "export_skin", "export_palette", "import_skin", "import_palette", "new_skin", "new_palette",
    "migrate_appearance",
]

SKINS_DIR = Path(APP_DIR) / "skins"
THEMES_DIR = Path(APP_DIR) / "themes"
MAX_IMPORT_BYTES = 256 * 1024

SKIN_FORMAT = "Mandible.Skin"
THEME_FORMAT = "Mandible.Theme"
FORMAT_VERSION = 1
SKIN_EXT = ".mandibleskin"
THEME_EXT = ".mandibletheme"

_MAX_NAME = 60
_MAX_SLUG = 48
_MAX_VARIANT = 64
_ID_PREFIX = "user:"
_ID_RE = re.compile(r"user:([a-z0-9]+(?:-[a-z0-9]+)*)")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
# Sane ranges for shape tokens (px, px, px, 0..2 levels).
_SHAPE_RANGES = {"radius.control": (0.0, 24.0), "radius.panel": (0.0, 32.0),
                 "border.width": (0.0, 4.0), "shadow.depth": (0.0, 2.0)}
_STRIP_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


class LookFileError(Exception):
    """A skin/theme file that cannot be used. The message is a single line fit for a dialog."""


# ------------------------------------------------------------------ small helpers

def _one_line(text: object) -> str:
    return " ".join(str(text).split())[:200]


def _dir(kind: str) -> Path:
    return SKINS_DIR if kind == "skin" else THEMES_DIR


def slugify(name: str) -> str:
    """A safe file stem for ``name``: lowercase ``a-z0-9`` words joined by ``-``, at most 48 chars,
    never empty, never a Windows device name, never containing a path separator or dot."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:_MAX_SLUG].strip("-")
    if not slug:
        slug = "look"
    if slug.upper() in _RESERVED:
        slug += "-look"
    return slug


def _slug_of_id(look_id: object) -> str:
    """The slug of a ``user:`` id; ValueError for anything else (built-in ids, path tricks)."""
    m = _ID_RE.fullmatch(look_id) if isinstance(look_id, str) else None
    if not m or len(m.group(1)) > _MAX_SLUG or m.group(1).upper() in _RESERVED:
        raise ValueError(f"not a user look id: {look_id!r}")
    return m.group(1)


def _clean_name(value: object) -> str:
    if not isinstance(value, str):
        raise LookFileError("name must be text")
    kept = "".join(c for c in value if unicodedata.category(c) not in _STRIP_CATEGORIES)
    name = " ".join(kept.split())[:_MAX_NAME].strip()
    if not name:
        raise LookFileError("name is empty")
    return name


def _reject_constant(token: str):
    raise ValueError(f"{token} is not a valid number")


def _read_doc(path: str | os.PathLike, fmt: str) -> dict:
    """Read, size-cap and parse a look file. Reads at most ``MAX_IMPORT_BYTES + 1`` bytes."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_IMPORT_BYTES + 1)
    except OSError as exc:
        raise LookFileError(f"cannot read the file ({_one_line(exc.strerror or type(exc).__name__)})") from None
    if len(data) > MAX_IMPORT_BYTES:
        raise LookFileError(f"file too large (limit {MAX_IMPORT_BYTES // 1024} KB)")
    try:
        doc = json.loads(data, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise LookFileError(f"not a valid JSON file ({_one_line(exc)})") from None
    if not isinstance(doc, dict):
        raise LookFileError("not a Mandible look file")
    if doc.get("format") != fmt:
        what = "skin" if fmt == SKIN_FORMAT else "theme"
        raise LookFileError(f"not a Mandible {what} file")
    version = doc.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise LookFileError("missing or invalid file version")
    if version != FORMAT_VERSION:
        # Never echo the value: it is untrusted and may be thousands of digits long.
        raise LookFileError("unsupported file version"
                            + (" (made by a newer Mandible)" if version > FORMAT_VERSION else ""))
    return doc


def _write_json_atomic(path: Path, doc: dict) -> None:
    """Write ``doc`` to ``path`` through a temp file in the same folder and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------- field validation

def _parse_hex(value: object, what: str) -> str:
    if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
        raise LookFileError(f"{what}: expected a #rrggbb colour")
    return value.lower()


def _parse_skin(doc: Mapping) -> tuple[str, dict[str, str], dict[str, float], list[str]]:
    """Validate a skin document -> (name, raw elements, shape, notices). Raises LookFileError."""
    notes: list[str] = []
    name = _clean_name(doc.get("name"))
    raw = doc.get("elements", {})
    if not isinstance(raw, dict):
        raise LookFileError("elements must be an object")
    elements: dict[str, str] = {}
    for slot in SKIN_SLOTS:
        if slot not in raw:
            continue
        variant = raw[slot]
        if not isinstance(variant, str) or not variant or len(variant) > _MAX_VARIANT:
            raise LookFileError(f"elements.{slot} must be a short text value")
        elements[slot] = variant
    unknown = sum(1 for k in raw if k not in SKIN_SLOTS)
    if unknown:
        notes.append(f"{unknown} unknown element slot(s) ignored")
    raw_shape = doc.get("shape", {})
    if not isinstance(raw_shape, dict):
        raise LookFileError("shape must be an object")
    shape: dict[str, float] = {k: float(v) for k, v in BUILTIN_SKINS["skeuomorphic"].shape.items()}
    for token in SHAPE_TOKENS:
        if token not in raw_shape:
            continue
        v = raw_shape[token]
        lo, hi = _SHAPE_RANGES[token]
        # Range check first and on the raw value: int/float comparison is exact (no float() of a
        # huge int, which would overflow), and NaN / infinities fail it.
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise LookFileError(f"shape.{token} must be a number from {lo:g} to {hi:g}")
        shape[token] = float(v)
    return name, elements, shape, notes


def _parse_source(value: object, notes: list[str]) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        if not isinstance(value, dict):
            raise LookFileError("not an object")
        accent = _parse_hex(value.get("accent"), "accent")
        tint = value.get("tint")
        if isinstance(tint, str) and tint in palette_gen.TINTS:
            return {"accent": accent, "tint": tint}
        return {"accent": accent, "tint": _parse_hex(tint, "tint")}
    except LookFileError:
        notes.append("source: not valid, ignored (colours are used as saved)")
        return None


def _parse_palette(doc: Mapping) -> tuple[str, bool, dict | None, dict[str, str], list[str]]:
    """Validate a theme document -> (name, dark, source, colors, notices). Raises LookFileError."""
    notes: list[str] = []
    name = _clean_name(doc.get("name"))
    dark = doc.get("dark")
    if not isinstance(dark, bool):
        raise LookFileError("dark must be true or false")
    raw = doc.get("colors")
    if not isinstance(raw, dict):
        raise LookFileError("colors must be an object")
    colors: dict[str, str] = {}
    for token in PALETTE_TOKENS:
        if token not in raw:
            raise LookFileError(f"colors.{token} is missing")
        colors[token] = _parse_hex(raw[token], f"colors.{token}")
    return name, dark, _parse_source(doc.get("source"), notes), colors, notes


# ------------------------------------------------------------------- building

def _build_skin(look_id: str, name: str, elements: Mapping, shape: Mapping) -> tuple[Skin, list[str]]:
    resolved, notes = registry.resolve(elements)
    return Skin(look_id, name, resolved, dict(shape)), [f"{name}: {n}" for n in notes]


def _build_palette(look_id: str, name: str, dark: bool, source: dict | None,
                   colors: Mapping) -> tuple[Palette, list[str]]:
    notes = [f"{name}: {i.token} on {i.partner} has contrast {i.ratio:.1f}:1 (wants {i.target:g}:1)"
             for i in palette_gen.check_colors(colors)]
    return Palette(look_id, name, dark, dict(colors), dict(source) if source else None), notes


def _skin_doc(name: str, elements: Mapping, shape: Mapping) -> dict:
    return {"format": SKIN_FORMAT, "version": FORMAT_VERSION, "name": name,
            "elements": dict(elements), "shape": dict(shape)}


def _palette_doc(name: str, dark: bool, source: Mapping | None, colors: Mapping) -> dict:
    return {"format": THEME_FORMAT, "version": FORMAT_VERSION, "name": name, "dark": dark,
            "source": dict(source) if source else None, "colors": dict(colors)}


def _checked_skin_doc(skin: Skin) -> dict:
    """The file document for ``skin``, validated so that whatever we write can be loaded again."""
    doc = _skin_doc(skin.name, skin.elements, skin.shape)
    try:
        name, elements, shape, _ = _parse_skin(doc)
    except LookFileError as exc:
        raise ValueError(f"cannot save skin: {exc}") from None
    return _skin_doc(name, elements, shape)


def _checked_palette_doc(p: Palette) -> dict:
    doc = _palette_doc(p.name, p.dark, p.source, {t: p.colors[t] for t in PALETTE_TOKENS if t in p.colors})
    try:
        name, dark, source, colors, _ = _parse_palette(doc)
    except LookFileError as exc:
        raise ValueError(f"cannot save theme: {exc}") from None
    return _palette_doc(name, dark, source, colors)


# ----------------------------------------------------------------- load / list

def _load_dir(kind: str) -> tuple[dict, list[str]]:
    directory = _dir(kind)
    fmt = SKIN_FORMAT if kind == "skin" else THEME_FORMAT
    found: list = []
    notices: list[str] = []
    if not directory.is_dir():
        return {}, notices
    for file in sorted(directory.glob("*.json")):
        if not file.is_file():
            continue
        look_id = _ID_PREFIX + file.stem
        try:
            _slug_of_id(look_id)
        except ValueError:
            notices.append(f"{file.name}: skipped (file name is not a valid look name)")
            continue
        try:
            doc = _read_doc(file, fmt)
            if kind == "skin":
                name, elements, shape, notes = _parse_skin(doc)
                look, extra = _build_skin(look_id, name, elements, shape)
            else:
                name, dark, source, colors, notes = _parse_palette(doc)
                look, extra = _build_palette(look_id, name, dark, source, colors)
        except LookFileError as exc:
            notices.append(f"{file.name}: skipped ({exc})")
            continue
        except Exception as exc:  # backstop: no single file may ever break loading
            notices.append(f"{file.name}: skipped ({_one_line(type(exc).__name__ + ': ' + str(exc))[:120]})")
            continue
        found.append(look)
        notices.extend(f"{name}: {n}" for n in notes)
        notices.extend(extra)
    found.sort(key=lambda lk: (lk.name.casefold(), lk.id))
    return {lk.id: lk for lk in found}, notices


def load_user_skins() -> tuple[dict[str, Skin], list[str]]:
    """User skins by id (sorted by name) and notices for skipped or adjusted files."""
    return _load_dir("skin")


def load_user_palettes() -> tuple[dict[str, Palette], list[str]]:
    """User themes by id (sorted by name) and notices for skipped files or contrast problems."""
    return _load_dir("theme")


def all_skins() -> dict[str, Skin]:
    """Built-in skins first (insertion order), then user skins sorted by name."""
    return {**BUILTIN_SKINS, **load_user_skins()[0]}


def all_palettes() -> dict[str, Palette]:
    """Built-in themes first (insertion order), then user themes sorted by name."""
    return {**BUILTIN_PALETTES, **load_user_palettes()[0]}


# ------------------------------------------------------------- names and ids

def _taken_names(kind: str) -> set[str]:
    builtin = BUILTIN_SKINS if kind == "skin" else BUILTIN_PALETTES
    user = _load_dir(kind)[0]
    return {lk.name.casefold() for lk in (*builtin.values(), *user.values())}


def _slug_in_use(slug: str) -> bool:
    return any((d / f"{slug}.json").exists() for d in (SKINS_DIR, THEMES_DIR))


def _claim(name: str, kind: str) -> tuple[str, str]:
    """A name no other look of this kind uses (``Name (2)``, ``Name (3)``...) and a free ``user:`` id."""
    name = _clean_name(name)
    taken = _taken_names(kind)
    unique, n = name, 1
    while unique.casefold() in taken:
        n += 1
        suffix = f" ({n})"
        unique = name[: _MAX_NAME - len(suffix)].rstrip() + suffix
    base = slugify(unique)
    slug, n = base, 1
    while _slug_in_use(slug):
        n += 1
        slug = f"{base[: _MAX_SLUG - len(str(n)) - 1].rstrip('-')}-{n}"
    return unique, _ID_PREFIX + slug


def new_skin(name: str, elements: Mapping[str, str], shape: Mapping[str, float]) -> Skin:
    """A not-yet-saved user skin with a collision-free name and id (for "Save as new")."""
    try:
        unique, look_id = _claim(name, "skin")
    except LookFileError as exc:
        raise ValueError(str(exc)) from None
    return Skin(look_id, unique, dict(elements), dict(shape))


def new_palette(name: str, dark: bool, colors: Mapping[str, str], source: dict | None = None) -> Palette:
    """A not-yet-saved user theme with a collision-free name and id."""
    try:
        unique, look_id = _claim(name, "theme")
    except LookFileError as exc:
        raise ValueError(str(exc)) from None
    return Palette(look_id, unique, dark, dict(colors), source)


# --------------------------------------------------------------- save / delete

def _save(kind: str, look, doc: dict) -> Path:
    slug = _slug_of_id(look.id)
    builtin = BUILTIN_SKINS if kind == "skin" else BUILTIN_PALETTES
    others = {lk.name.casefold() for lk in builtin.values()}
    others |= {lk.name.casefold() for i, lk in _load_dir(kind)[0].items() if i != look.id}
    if doc["name"].casefold() in others:
        raise ValueError(f"the name {doc['name']!r} is already used by another {kind}")
    directory = _dir(kind)
    path = directory / f"{slug}.json"
    if path.parent != directory:  # belt and braces; the id regex already rules this out
        raise ValueError(f"unsafe look id: {look.id!r}")
    _write_json_atomic(path, doc)
    return path


def save_skin(skin: Skin) -> Path:
    """Write a user skin to ``SKINS_DIR``. ValueError for a non-``user:`` id, a name that another
    look already uses, or content that would not load back."""
    _slug_of_id(skin.id)
    return _save("skin", skin, _checked_skin_doc(skin))


def save_palette(p: Palette) -> Path:
    """Write a user theme to ``THEMES_DIR`` (same rules as ``save_skin``)."""
    _slug_of_id(p.id)
    return _save("theme", p, _checked_palette_doc(p))


def delete_user_look(look_id: str, kind: str | None = None) -> None:
    """Delete the user skin and/or theme file for ``look_id`` (``kind``: "skin", "theme" or None for
    both). A missing file is not an error; a non-``user:`` id raises ValueError."""
    slug = _slug_of_id(look_id)
    for k in ("skin", "theme") if kind is None else (kind,):
        if k not in ("skin", "theme"):
            raise ValueError(f"unknown look kind {k!r}")
        try:
            (_dir(k) / f"{slug}.json").unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------- export / import

def export_skin(skin: Skin, path: str | os.PathLike) -> None:
    """Write ``skin`` (built-in or user) as a ``.mandibleskin`` file; the id is not exported."""
    _write_json_atomic(Path(path), _checked_skin_doc(skin))


def export_palette(p: Palette, path: str | os.PathLike) -> None:
    """Write ``p`` (built-in or user) as a ``.mandibletheme`` file; the id is not exported."""
    _write_json_atomic(Path(path), _checked_palette_doc(p))


def import_skin(path: str | os.PathLike) -> tuple[Skin, list[str]]:
    """Import a ``.mandibleskin`` file as a new user skin. Raises LookFileError (nothing is written)
    for anything that is not a well-formed skin file. Returns the saved skin and notices (unknown
    element variants fall back to defaults, noted)."""
    name, elements, shape, notes = _parse_skin(_read_doc(path, SKIN_FORMAT))
    unique, look_id = _claim(name, "skin")
    skin, extra = _build_skin(look_id, unique, elements, shape)
    # The file keeps the imported variant ids (a newer build may know them); loading resolves them.
    _write_json_atomic(SKINS_DIR / f"{_slug_of_id(look_id)}.json", _skin_doc(unique, elements, shape))
    return skin, [f"{unique}: {n}" for n in notes] + extra


def import_palette(path: str | os.PathLike) -> tuple[Palette, list[str]]:
    """Import a ``.mandibletheme`` file as a new user theme (same rules as ``import_skin``);
    contrast problems are reported in the notices, not rejected."""
    name, dark, source, colors, notes = _parse_palette(_read_doc(path, THEME_FORMAT))
    unique, look_id = _claim(name, "theme")
    palette, extra = _build_palette(look_id, unique, dark, source, colors)
    _write_json_atomic(THEMES_DIR / f"{_slug_of_id(look_id)}.json", _palette_doc(unique, dark, source, colors))
    return palette, [f"{unique}: {n}" for n in notes] + extra


# ------------------------------------------------------------ appearance migration

def migrate_appearance(cfg) -> str | None:
    """One-time migration of the old per-setting frame / switch options into a saved user skin.

    Returns the ``user:`` id of the skin created (or reused) and points ``cfg.ui_skin`` at it, or
    None when there was nothing to migrate. ``cfg.appearance_migrated`` is set in every outcome
    except a failed save, so a failure is retried on the next launch. Never raises.

    ``chassis_frame == "auto"`` means "the skin's own frame". A skin is only created when the old
    settings differ from the selected built-in skin: a frame other than that skin's, or (skeuomorphic
    only, as ``look_for`` always did) a different switch style. An unknown or ``user:`` ``ui_skin`` is
    left alone. Once a user skin carries the old settings, ``cfg.chassis_frame`` is reset to ``"auto"``
    and ``cfg.switch_style`` to the built-in Skeuomorphic skin's own switch, so the legacy overrides
    add nothing on top of it and the built-in skin is pristine again.
    """
    if getattr(cfg, "appearance_migrated", False):
        return None
    try:
        return _migrate_appearance(cfg)
    except Exception as exc:  # startup must never fail on this; retry next launch
        print(f"[Mandible] could not migrate appearance settings ({_one_line(f'{type(exc).__name__}: {exc}')})")
        return None


def _migrate_appearance(cfg) -> str | None:
    base = BUILTIN_SKINS.get(cfg.ui_skin) if isinstance(cfg.ui_skin, str) else None
    overrides: dict[str, str] = {}
    if base is not None:
        frame = cfg.chassis_frame
        if frame != "auto" and frame in registry.variants("frame") and frame != base.elements["frame"]:
            overrides["frame"] = frame
        switch = cfg.switch_style
        if (base.id == "skeuomorphic" and switch in registry.variants("switch")
                and switch != base.elements["switch"]):
            overrides["switch"] = switch
    if not overrides:
        cfg.appearance_migrated = True
        return None

    elements = {**base.elements, **overrides}
    shape = dict(base.shape)
    name = f"{base.name} (my settings)"
    skin_id = _existing_migrated_skin(name, elements, shape)
    if skin_id is None:
        try:
            skin = new_skin(name, elements, shape)
            save_skin(skin)
        except (OSError, LookFileError, ValueError) as exc:
            print(f"[Mandible] could not save the migrated skin ({_one_line(f'{type(exc).__name__}: {exc}')})")
            return None
        skin_id = skin.id
    cfg.ui_skin = skin_id
    cfg.chassis_frame = "auto"
    # The old switch now lives in the user skin; the built-in Skeuomorphic goes back to its own.
    cfg.switch_style = BUILTIN_SKINS["skeuomorphic"].elements["switch"]
    cfg.appearance_migrated = True
    return skin_id


def _existing_migrated_skin(name: str, elements: Mapping, shape: Mapping) -> str | None:
    """A saved user skin called ``name`` (or ``name (2)``, ``name (3)``... from an earlier collision)
    with exactly these elements and shape, so a lost flag never produces a duplicate."""
    pattern = re.compile(re.escape(name.casefold()) + r"(?: \(\d+\))?")
    for skin in load_user_skins()[0].values():
        if (pattern.fullmatch(skin.name.casefold()) and dict(skin.elements) == dict(elements)
                and dict(skin.shape) == dict(shape)):
            return skin.id
    return None
