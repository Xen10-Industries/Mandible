"""User skins and themes: storage, safe import, export (Task 17)."""
from __future__ import annotations

import json

import pytest

from mandible.ui import look as look_mod
from mandible.ui import user_looks as UL
from mandible.ui.elements import registry
from mandible.ui.look import (BUILTIN_PALETTES, BUILTIN_SKINS, PALETTE_TOKENS, Look, Palette, Skin,
                              current_look, set_look)
from mandible.ui.stylesheet import build_qss


@pytest.fixture(autouse=True)
def looks_dirs(tmp_path, monkeypatch):
    """Per-test skins/themes folders (never the real profile)."""
    monkeypatch.setattr(UL, "SKINS_DIR", tmp_path / "skins")
    monkeypatch.setattr(UL, "THEMES_DIR", tmp_path / "themes")
    return tmp_path


@pytest.fixture
def restore_look(qapp):
    before = current_look()
    set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    yield
    set_look(before)


def skin_doc(**over):
    base = BUILTIN_SKINS["vintage"]
    doc = {"format": "Mandible.Skin", "version": 1, "name": "My Skin",
           "elements": dict(base.elements), "shape": dict(base.shape)}
    doc.update(over)
    return doc


def theme_doc(**over):
    base = BUILTIN_PALETTES["cyan"]
    doc = {"format": "Mandible.Theme", "version": 1, "name": "My Theme", "dark": True,
           "source": None, "colors": dict(base.colors)}
    doc.update(over)
    return doc


def write(tmp_path, doc, name="f.json"):
    p = tmp_path / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return p


def user_skin(name="Mine", ident="user:mine", **elements):
    base = BUILTIN_SKINS["minimal"]
    return Skin(ident, name, {**base.elements, **elements}, dict(base.shape))


def user_palette(name="Mine", ident="user:mine", **kw):
    base = BUILTIN_PALETTES["amber"]
    args = dict(dark=True, colors=dict(base.colors), source=None)
    args.update(kw)
    return Palette(ident, name, **args)


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


# --------------------------------------------------------------------- slugify

@pytest.mark.parametrize("name,expected", [
    ("My Cool Skin", "my-cool-skin"),
    ("../../evil", "evil"),
    ("..\\..\\evil", "evil"),
    ("C:\\Windows\\win.ini", "c-windows-win-ini"),
    ("Caf\u00e9 Noir", "cafe-noir"),
    ("  spaced   out  ", "spaced-out"),
])
def test_slugify(name, expected):
    assert UL.slugify(name) == expected


@pytest.mark.parametrize("name", ["CON", "nul", "Aux", "com1", "LPT9", "prn", "\uff23\uff2f\uff2e"])
def test_slugify_avoids_windows_device_names(name):
    slug = UL.slugify(name)
    assert slug.upper() not in _RESERVED
    assert UL.slugify(slug) == slug


@pytest.mark.parametrize("name", ["", "   ", "...", "///", "\u2603\u2603", "\x00\x01"])
def test_slugify_never_returns_empty(name):
    assert UL.slugify(name)


def test_slugify_output_is_always_a_safe_file_stem():
    for name in ["a" * 500, "x/../y", "tab\there", "a.b.c", "~$weird"]:
        slug = UL.slugify(name)
        assert 0 < len(slug) <= 48
        assert all((c.isascii() and c.islower()) or c.isdigit() or c == "-" for c in slug)
        assert not slug.startswith("-") and not slug.endswith("-")


# ------------------------------------------------------------- save / load / delete

def test_skin_round_trip():
    s = user_skin("Hot Rod", "user:hot-rod", knob="flat_ring")
    path = UL.save_skin(s)
    assert path.parent == UL.SKINS_DIR and path.name == "hot-rod.json"
    loaded, notices = UL.load_user_skins()
    assert notices == []
    assert loaded["user:hot-rod"] == s
    assert list(UL.all_skins())[: len(BUILTIN_SKINS)] == list(BUILTIN_SKINS)
    assert UL.all_skins()["user:hot-rod"] == s


def test_simple_mode_palette_round_trip_keeps_source():
    p = user_palette("Sunset", "user:sunset", source={"accent": "#ff8800", "tint": "warm"})
    UL.save_palette(p)
    loaded, notices = UL.load_user_palettes()
    got = loaded["user:sunset"]
    assert got == p and got.source == {"accent": "#ff8800", "tint": "warm"}


def test_advanced_palette_may_have_no_source_and_light_is_allowed():
    UL.save_palette(user_palette("Plain", "user:plain", source=None, dark=False))
    got = UL.load_user_palettes()[0]["user:plain"]
    assert got.source is None and got.dark is False


def test_saved_file_has_the_documented_format():
    UL.save_skin(user_skin("A", "user:a"))
    UL.save_palette(user_palette("B", "user:b", source={"accent": "#112233", "tint": "#445566"}))
    sk = json.loads((UL.SKINS_DIR / "a.json").read_text(encoding="utf-8"))
    th = json.loads((UL.THEMES_DIR / "b.json").read_text(encoding="utf-8"))
    assert sk["format"] == "Mandible.Skin" and sk["version"] == 1 and sk["name"] == "A"
    assert set(sk["elements"]) == set(look_mod.SKIN_SLOTS) and set(sk["shape"]) == set(look_mod.SHAPE_TOKENS)
    assert th["format"] == "Mandible.Theme" and th["version"] == 1 and th["dark"] is True
    assert th["source"] == {"accent": "#112233", "tint": "#445566"}
    assert set(th["colors"]) == set(PALETTE_TOKENS)


def test_delete_user_look_removes_the_file():
    UL.save_skin(user_skin("A", "user:a"))
    UL.save_palette(user_palette("B", "user:b"))
    UL.delete_user_look("user:a")
    assert not (UL.SKINS_DIR / "a.json").exists() and (UL.THEMES_DIR / "b.json").exists()
    assert "user:a" not in UL.all_skins()
    UL.delete_user_look("user:b")
    assert "user:b" not in UL.all_palettes()
    UL.delete_user_look("user:b")  # already gone: not an error


def test_delete_can_target_one_kind():
    UL.save_skin(user_skin("Same", "user:same"))
    UL.save_palette(user_palette("Same", "user:same"))
    UL.delete_user_look("user:same", kind="theme")
    assert (UL.SKINS_DIR / "same.json").exists() and not (UL.THEMES_DIR / "same.json").exists()


@pytest.mark.parametrize("bad", ["scarlet", "skeuomorphic", "user:", "user:../../evil", "user:CON",
                                 "user:a/b", "user:Upper", "", "user:a" + "b" * 100])
def test_save_and_delete_reject_non_user_or_unsafe_ids(bad, tmp_path):
    with pytest.raises(ValueError):
        UL.save_skin(user_skin("X", bad))
    with pytest.raises(ValueError):
        UL.save_palette(user_palette("X", bad))
    with pytest.raises(ValueError):
        UL.delete_user_look(bad)
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.iterdir())
    assert not list(tmp_path.glob("**/evil*"))


def test_saving_a_builtin_raises_value_error():
    with pytest.raises(ValueError):
        UL.save_skin(BUILTIN_SKINS["minimal"])
    with pytest.raises(ValueError):
        UL.save_palette(BUILTIN_PALETTES["scarlet"])


def test_save_is_atomic_and_leaves_no_temp_files(monkeypatch):
    UL.save_skin(user_skin("A", "user:a"))
    before = (UL.SKINS_DIR / "a.json").read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(UL.os, "replace", boom)
    with pytest.raises(OSError):
        UL.save_skin(user_skin("A", "user:a", knob="flat_ring"))
    assert (UL.SKINS_DIR / "a.json").read_text(encoding="utf-8") == before
    assert [p.name for p in UL.SKINS_DIR.iterdir()] == ["a.json"]


def test_saving_a_name_used_by_another_look_is_refused():
    UL.save_skin(user_skin("Taken", "user:taken"))
    with pytest.raises(ValueError):
        UL.save_skin(user_skin("taken", "user:other"))
    with pytest.raises(ValueError):
        UL.save_skin(user_skin("Minimal", "user:other"))  # built-in name
    UL.save_skin(user_skin("Taken", "user:taken", knob="flat_ring"))  # re-saving itself is fine


def test_new_skin_and_palette_pick_unique_names_and_ids():
    UL.save_skin(user_skin("Mine", "user:mine"))
    s = UL.new_skin("Mine", BUILTIN_SKINS["minimal"].elements, BUILTIN_SKINS["minimal"].shape)
    assert s.name == "Mine (2)" and s.id == "user:mine-2"
    UL.save_skin(s)
    assert UL.new_skin("Minimal", {}, BUILTIN_SKINS["minimal"].shape).name == "Minimal (2)"
    p = UL.new_palette("Scarlet", True, BUILTIN_PALETTES["scarlet"].colors)
    assert p.name == "Scarlet (2)" and p.id.startswith("user:")


def test_all_lists_put_builtins_first_then_user_items_sorted_by_name():
    for n in ("zebra", "Apple", "mango"):
        UL.save_skin(user_skin(n.title(), f"user:{n.lower()}"))
        UL.save_palette(user_palette(n.title(), f"user:{n.lower()}"))
    assert list(UL.all_skins()) == [*BUILTIN_SKINS, "user:apple", "user:mango", "user:zebra"]
    assert list(UL.all_palettes()) == [*BUILTIN_PALETTES, "user:apple", "user:mango", "user:zebra"]


def test_load_skips_bad_files_with_notices_and_keeps_good_ones():
    UL.save_skin(user_skin("Good", "user:good"))
    (UL.SKINS_DIR / "broken.json").write_text("{nope", encoding="utf-8")
    (UL.SKINS_DIR / "Bad Name.json").write_text(json.dumps(skin_doc()), encoding="utf-8")
    (UL.SKINS_DIR / "notes.txt").write_text("hi", encoding="utf-8")
    loaded, notices = UL.load_user_skins()
    assert list(loaded) == ["user:good"]
    assert len(notices) == 2 and any("broken.json" in n for n in notices)
    assert all("\n" not in n for n in notices)


def test_id_comes_from_the_file_name_not_from_file_contents():
    UL.SKINS_DIR.mkdir(parents=True)
    (UL.SKINS_DIR / "real.json").write_text(
        json.dumps(skin_doc(id="scarlet", path="../../evil")), encoding="utf-8")
    assert list(UL.load_user_skins()[0]) == ["user:real"]


# ----------------------------------------------------------- import: rejections

def test_import_valid_files_round_trip_through_export(tmp_path):
    s = user_skin("Shared", "user:shared", knob="flat_ring")
    UL.export_skin(s, tmp_path / "x.mandibleskin")
    got, notices = UL.import_skin(tmp_path / "x.mandibleskin")
    assert notices == [] and got.name == "Shared" and got.id.startswith("user:")
    assert dict(got.elements) == dict(s.elements) and dict(got.shape) == dict(s.shape)
    assert UL.all_skins()[got.id] == got

    p = user_palette("Warm", "user:warm", source={"accent": "#e11d48", "tint": "neutral"}, dark=False)
    UL.export_palette(p, tmp_path / "x.mandibletheme")
    gp, notices = UL.import_palette(tmp_path / "x.mandibletheme")
    assert gp.source == p.source and gp.dark is False and dict(gp.colors) == dict(p.colors)
    assert UL.all_palettes()[gp.id] == gp
    doc = json.loads((tmp_path / "x.mandibletheme").read_text(encoding="utf-8"))
    assert doc["format"] == "Mandible.Theme" and doc["version"] == 1 and "id" not in doc


def test_export_builtins_works(tmp_path):
    UL.export_skin(BUILTIN_SKINS["vintage"], tmp_path / "v.mandibleskin")
    UL.export_palette(BUILTIN_PALETTES["amber"], tmp_path / "a.mandibletheme")
    assert json.loads((tmp_path / "v.mandibleskin").read_text(encoding="utf-8"))["name"] == "Vintage"
    assert json.loads((tmp_path / "a.mandibletheme").read_text(encoding="utf-8"))["source"] is None


BAD_SKINS = {
    "not json": "this is not json",
    "empty file": "",
    "json list": "[1, 2]",
    "json scalar": "42",
    "nan constant": '{"format": "Mandible.Skin", "version": 1, "name": "x", "elements": {}, '
                    '"shape": {"radius.control": NaN}}',
    "inf constant": '{"format": "Mandible.Skin", "version": 1, "name": "x", "elements": {}, '
                    '"shape": {"radius.control": Infinity}}',
    "deep nesting": "[" * 100000 + "]" * 100000,
    "invalid utf8": None,  # filled in by the test (raw bytes)
    "wrong format": skin_doc(format="Mandible.Theme"),
    "missing format": {k: v for k, v in skin_doc().items() if k != "format"},
    "format not str": skin_doc(format=["Mandible.Skin"]),
    "version 2": skin_doc(version=2),
    "version str": skin_doc(version="1"),
    "version bool": skin_doc(version=True),
    "name missing": {k: v for k, v in skin_doc().items() if k != "name"},
    "name not str": skin_doc(name=7),
    "name empty": skin_doc(name="   "),
    "name only control chars": skin_doc(name="\x00\x07\n"),
    "elements not dict": skin_doc(elements=["frame"]),
    "element value list": skin_doc(elements={"switch": ["laser"]}),
    "element value number": skin_doc(elements={"knob": 3}),
    "element value huge": skin_doc(elements={"knob": "k" * 1000}),
    "shape not dict": skin_doc(shape=3),
    "shape string": skin_doc(shape={"radius.control": "4px"}),
    "shape bool": skin_doc(shape={"radius.control": True}),
    "shape huge": skin_doc(shape={"radius.panel": 1e9}),
    "shape negative": skin_doc(shape={"border.width": -1}),
    "shape shadow range": skin_doc(shape={"shadow.depth": 7}),
    "shape huge int": '{"format": "Mandible.Skin", "version": 1, "name": "x", "elements": {}, '
                      '"shape": {"radius.control": ' + "9" * 400 + "}}",
    "shape huge negative int": '{"format": "Mandible.Skin", "version": 1, "name": "x", "elements": {}, '
                               '"shape": {"radius.control": -' + "9" * 400 + "}}",
    "version huge int": '{"format": "Mandible.Skin", "version": ' + "7" * 4000 + ', "name": "x"}',
    "version huge negative": '{"format": "Mandible.Skin", "version": -' + "7" * 4000 + ', "name": "x"}',
}


@pytest.mark.parametrize("case", list(BAD_SKINS))
def test_import_skin_rejects_bad_files_and_changes_nothing(case, tmp_path):
    before = dict(UL.all_skins())
    if case == "invalid utf8":
        p = tmp_path / "f.json"
        p.write_bytes(b'{"format": "\xff\xfe\x00"}')
    else:
        p = write(tmp_path, BAD_SKINS[case])
    with pytest.raises(UL.LookFileError) as exc:
        UL.import_skin(p)
    assert str(exc.value) and "\n" not in str(exc.value) and len(str(exc.value)) <= 200
    assert UL.all_skins() == before
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.iterdir())


BAD_THEMES = {
    "wrong format": theme_doc(format="Mandible.Skin"),
    "version 2": theme_doc(version=2),
    "dark not bool": theme_doc(dark="yes"),
    "dark missing": {k: v for k, v in theme_doc().items() if k != "dark"},
    "colors not dict": theme_doc(colors=["#000000"]),
    "colour css injection": theme_doc(colors={**theme_doc()["colors"], "accent": "red; background:url(x)"}),
    "colour named": theme_doc(colors={**theme_doc()["colors"], "accent": "red"}),
    "colour short hex": theme_doc(colors={**theme_doc()["colors"], "accent": "#fff"}),
    "colour trailing newline": theme_doc(colors={**theme_doc()["colors"], "accent": "#aabbcc\n"}),
    "colour with alpha": theme_doc(colors={**theme_doc()["colors"], "accent": "#aabbccdd"}),
    "colour not str": theme_doc(colors={**theme_doc()["colors"], "accent": 123456}),
    "colour list": theme_doc(colors={**theme_doc()["colors"], "accent": ["#aabbcc"]}),
    "token missing": theme_doc(colors={k: v for k, v in theme_doc()["colors"].items() if k != "bg.panel"}),
}


@pytest.mark.parametrize("case", list(BAD_THEMES))
def test_import_palette_rejects_bad_files_and_changes_nothing(case, tmp_path):
    before = dict(UL.all_palettes())
    with pytest.raises(UL.LookFileError) as exc:
        UL.import_palette(write(tmp_path, BAD_THEMES[case]))
    assert str(exc.value) and "\n" not in str(exc.value) and len(str(exc.value)) <= 200
    assert UL.all_palettes() == before
    assert not UL.THEMES_DIR.exists() or not list(UL.THEMES_DIR.iterdir())


def test_a_skin_file_is_not_a_theme_and_vice_versa(tmp_path):
    with pytest.raises(UL.LookFileError):
        UL.import_palette(write(tmp_path, skin_doc()))
    with pytest.raises(UL.LookFileError):
        UL.import_skin(write(tmp_path, theme_doc()))


def test_import_rejects_oversized_files(tmp_path):
    assert UL.MAX_IMPORT_BYTES == 256 * 1024
    big = skin_doc(padding="x" * (300 * 1024))
    before = dict(UL.all_skins())
    with pytest.raises(UL.LookFileError, match="too large"):
        UL.import_skin(write(tmp_path, big))
    assert UL.all_skins() == before


def test_import_reads_at_most_the_cap_plus_one(tmp_path, monkeypatch):
    """The size check reads a bounded amount; it does not stat-then-read (a file can grow)."""
    p = write(tmp_path, skin_doc())
    sizes = []
    real_open = open

    class Spy:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.fh.close()

        def read(self, n=-1):
            sizes.append(n)
            return self.fh.read(n)

    monkeypatch.setattr(UL, "open", lambda *a, **k: Spy(real_open(*a, **k)), raising=False)
    UL.import_skin(p)
    assert sizes and all(s == UL.MAX_IMPORT_BYTES + 1 for s in sizes)


def test_import_missing_file_or_directory(tmp_path):
    with pytest.raises(UL.LookFileError):
        UL.import_skin(tmp_path / "nope.mandibleskin")
    with pytest.raises(UL.LookFileError):
        UL.import_palette(tmp_path)


def test_unknown_keys_are_ignored(tmp_path):
    doc = skin_doc(author="me", extra={"a": [1, 2]}, id="scarlet")
    doc["elements"]["hologram"] = {"deep": ["x"]}
    doc["shape"]["glow.radius"] = 3
    got, notices = UL.import_skin(write(tmp_path, doc))
    assert got.id.startswith("user:") and "hologram" not in got.elements
    assert set(got.shape) == set(look_mod.SHAPE_TOKENS)
    colors = {**theme_doc()["colors"], "new.token": "#010203"}
    th, _ = UL.import_palette(write(tmp_path, theme_doc(future={"x": 1}, colors=colors), "t.json"))
    assert "new.token" not in th.colors


def test_name_is_sanitised(tmp_path):
    got, _ = UL.import_skin(write(tmp_path, skin_doc(name="  Evil\x00\x1b[31m\u202eName\n  ")))
    assert got.name == "Evil[31mName"
    long, _ = UL.import_skin(write(tmp_path, skin_doc(name="n" * 500), "l.json"))
    assert len(long.name) <= 60


@pytest.mark.parametrize("name", ["../../evil", "..\\..\\evil", "CON", "nul", "COM1", "....", "/"])
def test_hostile_names_never_write_outside_the_looks_dirs(name, tmp_path):
    p = write(tmp_path, skin_doc(name=name))
    got, _ = UL.import_skin(p)
    assert got.id.startswith("user:") and got.name.strip()
    files = [f for f in tmp_path.rglob("*.json") if f != p]
    assert len(files) == 1 and files[0].parent == UL.SKINS_DIR
    assert files[0].stem.upper() not in _RESERVED and files[0].stem


def test_import_collision_gets_numbered_names_and_new_ids(tmp_path):
    p = write(tmp_path, skin_doc(name="Twin"))
    a, _ = UL.import_skin(p)
    b, _ = UL.import_skin(p)
    c, _ = UL.import_skin(p)
    assert [a.name, b.name, c.name] == ["Twin", "Twin (2)", "Twin (3)"]
    assert len({a.id, b.id, c.id}) == 3
    assert len(list(UL.SKINS_DIR.iterdir())) == 3
    # Built-in names collide too, case-insensitively.
    m, _ = UL.import_skin(write(tmp_path, skin_doc(name="MINIMAL"), "m.json"))
    assert m.name == "MINIMAL (2)"
    s1, _ = UL.import_palette(write(tmp_path, theme_doc(name="Scarlet"), "s.json"))
    assert s1.name == "Scarlet (2)"
    # Different names that slug alike must not overwrite each other's file.
    x, _ = UL.import_skin(write(tmp_path, skin_doc(name="a b"), "x.json"))
    y, _ = UL.import_skin(write(tmp_path, skin_doc(name="a-b"), "y.json"))
    assert x.id != y.id and len(UL.all_skins()) == len(BUILTIN_SKINS) + 3 + 1 + 2


def test_import_never_trusts_ids_in_the_file(tmp_path):
    got, _ = UL.import_skin(write(tmp_path, skin_doc(id="scarlet")))
    assert got.id != "scarlet" and got.id.startswith("user:")


# ------------------------------------------------- Review Focus 2: tolerant loads

def test_stored_skin_with_unknown_variant_loads_with_default_and_notice():
    UL.save_skin(user_skin("Laser", "user:laser"))
    path = UL.SKINS_DIR / "laser.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["elements"]["switch"] = "laser"
    path.write_text(json.dumps(doc), encoding="utf-8")
    loaded, notices = UL.load_user_skins()
    assert loaded["user:laser"].elements["switch"] == "bat_toggle"
    assert any("switch" in n and "laser" in n for n in notices)


def test_import_with_unknown_variant_succeeds_with_notice(tmp_path):
    doc = skin_doc()
    doc["elements"]["switch"] = "laser"
    got, notices = UL.import_skin(write(tmp_path, doc))
    assert got.elements["switch"] == "bat_toggle"
    assert any("laser" in n for n in notices)
    # The file keeps what was imported, so a newer build could still render it.
    stored = json.loads(next(UL.SKINS_DIR.iterdir()).read_text(encoding="utf-8"))
    assert stored["elements"]["switch"] == "laser"


def test_stored_skin_with_hostile_variant_value_does_not_crash_load():
    UL.save_skin(user_skin("Fine", "user:fine"))
    doc = skin_doc(name="Hostile")
    doc["elements"]["switch"] = ["laser"]
    (UL.SKINS_DIR / "hostile.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded, notices = UL.load_user_skins()
    assert "user:fine" in loaded and "user:hostile" not in loaded
    assert any("hostile.json" in n for n in notices)


def test_missing_skin_slots_and_shape_take_defaults(tmp_path):
    got, notices = UL.import_skin(write(tmp_path, skin_doc(elements={"knob": "flat_ring"}, shape={})))
    assert got.elements["knob"] == "flat_ring" and got.elements["frame"] == registry.DEFAULTS["frame"]
    assert set(got.shape) == set(look_mod.SHAPE_TOKENS)
    assert all(isinstance(v, float) for v in got.shape.values())


def test_theme_failing_contrast_loads_with_issues_as_notices(tmp_path):
    colors = {**theme_doc()["colors"], "text.primary": "#101010", "text.secondary": "#121212"}
    got, notices = UL.import_palette(write(tmp_path, theme_doc(colors=colors)))
    assert got.color("text.primary") == "#101010"
    assert any("text.primary" in n and "bg.panel" in n for n in notices)
    # And on a plain load of the stored file:
    loaded, load_notices = UL.load_user_palettes()
    assert got.id in loaded and any("text.primary" in n for n in load_notices)


def test_good_theme_has_no_notices():
    UL.save_palette(user_palette("Fine", "user:fine", colors=dict(BUILTIN_PALETTES["scarlet"].colors)))
    assert UL.load_user_palettes()[1] == []


def test_colours_are_normalised_to_lowercase(tmp_path):
    colors = {**theme_doc()["colors"], "accent": "#06B6D4"}
    got, _ = UL.import_palette(write(tmp_path, theme_doc(colors=colors)))
    assert got.color("accent") == "#06b6d4"


def test_bad_source_is_dropped_with_a_notice(tmp_path):
    got, notices = UL.import_palette(write(tmp_path, theme_doc(source={"accent": "red", "tint": 3})))
    assert got.source is None and any("source" in n for n in notices)
    got, notices = UL.import_palette(write(tmp_path, theme_doc(source=["x"]), "b.json"))
    assert got.source is None


# --------------------------------------------- carried: look ids and Settings pickers

def test_look_for_resolves_user_ids_and_falls_back_for_unknown_ones():
    UL.save_skin(user_skin("Mine", "user:mine", knob="flat_ring"))
    UL.save_palette(user_palette("Mine", "user:mine"))
    look = look_mod.look_for("user:mine", "user:mine")
    assert look.palette.id == "user:mine" and look.skin.id == "user:mine"
    assert look.skin.elements["knob"] == "flat_ring"
    ghost = look_mod.look_for("user:ghost", "user:ghost")
    assert ghost.palette.id == "scarlet" and ghost.skin.id == "skeuomorphic"
    assert look_mod.look_for("scarlet", "minimal").skin.id == "minimal"


def test_look_from_config_resolves_user_ids():
    from types import SimpleNamespace

    UL.save_palette(user_palette("Mine", "user:mine"))
    UL.save_skin(user_skin("Mine", "user:mine"))
    cfg = SimpleNamespace(theme="user:mine", ui_skin="user:mine", chassis_frame="auto", switch_style=None)
    look = look_mod.look_from_config(cfg)
    assert (look.palette.id, look.skin.id) == ("user:mine", "user:mine")
    cfg.theme = "user:gone"
    assert look_mod.look_from_config(cfg).palette.id == "scarlet"


def test_settings_pickers_list_builtins_first_then_user_items():
    from mandible.ui.dialogs.settings import appearance_palettes, appearance_skins

    UL.save_skin(user_skin("Zed", "user:zed"))
    UL.save_skin(user_skin("Abe", "user:abe"))
    UL.save_palette(user_palette("Zed", "user:zed"))
    assert [s.id for s in appearance_skins()] == [*BUILTIN_SKINS, "user:abe", "user:zed"]
    assert [p.id for p in appearance_palettes()] == [*BUILTIN_PALETTES, "user:zed"]


def test_settings_live_preview_resolves_user_ids(core, restore_look):
    from mandible.ui.dialogs.settings import SettingsDialog

    UL.save_skin(user_skin("Zed", "user:zed", knob="flat_ring"))
    UL.save_palette(user_palette("Zed", "user:zed"))
    dlg = SettingsDialog(core, False, None, initial_section="appearance")
    try:
        dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("user:zed"))
        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("user:zed"))
        look = dlg._preview_look()
        assert look.skin.id == "user:zed" and look.palette.id == "user:zed"
        assert current_look().skin.id == "user:zed"
    finally:
        dlg.reject()
        dlg.hide()
        dlg.deleteLater()


def test_editing_a_user_palette_under_the_same_id_changes_the_stylesheet():
    skin = BUILTIN_SKINS["skeuomorphic"]
    p1 = user_palette("Mine", "user:mine")
    p2 = Palette("user:mine", "Mine", True, {**p1.colors, "accent": "#12ab34"})
    assert hash(Look(p1, skin)) == hash(Look(p2, skin))  # same id: same hash...
    assert build_qss(Look(p1, skin)) != build_qss(Look(p2, skin))  # ...but not the same cached QSS
    s2 = Skin(skin.id, skin.name, skin.elements, {**skin.shape, "radius.control": 9})
    assert build_qss(Look(p1, skin)) != build_qss(Look(p1, s2))


def test_huge_int_file_in_the_skins_folder_is_skipped_not_fatal():
    from types import SimpleNamespace

    UL.save_skin(user_skin("Fine", "user:fine"))
    UL.SKINS_DIR.joinpath("huge.json").write_text(
        '{"format": "Mandible.Skin", "version": 1, "name": "Huge", "elements": {}, '
        '"shape": {"radius.panel": ' + "9" * 400 + "}}", encoding="utf-8")
    UL.SKINS_DIR.joinpath("hugever.json").write_text(
        '{"format": "Mandible.Skin", "version": ' + "7" * 4000 + ', "name": "V"}', encoding="utf-8")
    loaded, notices = UL.load_user_skins()
    assert list(loaded) == ["user:fine"]
    assert sum("huge.json" in n for n in notices) == 1 and any("hugever.json" in n for n in notices)
    assert all("\n" not in n and len(n) <= 300 for n in notices)
    assert "user:fine" in UL.all_skins()
    assert look_mod.look_for("scarlet", "user:huge").skin.id == "skeuomorphic"
    assert look_mod.look_for("scarlet", "user:fine").skin.id == "user:fine"
    cfg = SimpleNamespace(theme="scarlet", ui_skin="user:fine", chassis_frame="auto", switch_style=None)
    assert look_mod.look_from_config(cfg).skin.id == "user:fine"


def test_unexpected_error_while_parsing_one_file_skips_only_that_file(monkeypatch):
    UL.save_skin(user_skin("Alpha", "user:alpha"))
    UL.save_skin(user_skin("Beta", "user:beta"))
    UL.save_skin(user_skin("Gamma", "user:gamma"))
    real = UL._parse_skin

    def flaky(doc):
        if doc.get("name") == "Beta":
            raise RuntimeError("unexpected\nboom "+ "x" * 1000)
        return real(doc)

    monkeypatch.setattr(UL, "_parse_skin", flaky)
    loaded, notices = UL.load_user_skins()
    assert list(loaded) == ["user:alpha", "user:gamma"]
    assert len(notices) == 1 and "beta.json" in notices[0] and "RuntimeError" in notices[0]
    assert "\n" not in notices[0] and len(notices[0]) <= 300
    assert list(UL.all_skins())[-2:] == ["user:alpha", "user:gamma"]


# --------------------------------------------------------- appearance migration (Task 18)

def _cfg(**kw):
    from mandible.config import AppConfig

    cfg = AppConfig()
    for key, value in kw.items():
        setattr(cfg, key, value)
    return cfg


def test_migrate_default_config_creates_nothing_and_sets_flag():
    cfg = _cfg()
    assert cfg.appearance_migrated is False
    assert UL.migrate_appearance(cfg) is None
    assert cfg.appearance_migrated is True
    assert (cfg.ui_skin, cfg.chassis_frame, cfg.switch_style) == ("skeuomorphic", "auto", "bat_toggle")
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.glob("*.json"))


def test_migrate_frame_override_creates_user_skin():
    cfg = _cfg(ui_skin="skeuomorphic", chassis_frame="wood_cheeks")
    skin_id = UL.migrate_appearance(cfg)
    assert skin_id and skin_id.startswith("user:")
    skin = UL.all_skins()[skin_id]
    assert skin.name == "Skeuomorphic (my settings)"
    base = BUILTIN_SKINS["skeuomorphic"]
    assert skin.elements["frame"] == "wood_cheeks"
    assert {k: v for k, v in skin.elements.items() if k != "frame"} == \
        {k: v for k, v in base.elements.items() if k != "frame"}
    assert dict(skin.shape) == dict(base.shape)
    assert cfg.ui_skin == skin_id and cfg.appearance_migrated is True
    assert cfg.chassis_frame == "auto"           # the user skin now carries the frame
    assert cfg.switch_style == "bat_toggle"
    assert look_mod.look_from_config(cfg).skin.elements["frame"] == "wood_cheeks"


def test_migrate_twice_creates_nothing_the_second_time():
    cfg = _cfg(chassis_frame="wood_cheeks")
    first = UL.migrate_appearance(cfg)
    files = sorted(p.name for p in UL.SKINS_DIR.glob("*.json"))
    assert first and len(files) == 1
    assert UL.migrate_appearance(cfg) is None
    assert sorted(p.name for p in UL.SKINS_DIR.glob("*.json")) == files
    assert cfg.ui_skin == first


def test_migrate_switch_style_only_applies_to_skeuomorphic():
    cfg = _cfg(ui_skin="skeuomorphic", switch_style="rocker")
    skin_id = UL.migrate_appearance(cfg)
    assert skin_id and UL.all_skins()[skin_id].elements["switch"] == "rocker"
    assert UL.all_skins()[skin_id].elements["frame"] == "metal_rack"
    # other built-in skins ignored the legacy switch_style before, so it is not baked in
    other = _cfg(ui_skin="minimal", switch_style="rocker")
    assert UL.migrate_appearance(other) is None
    assert other.ui_skin == "minimal" and other.appearance_migrated is True


def test_migrate_settings_equal_to_skin_defaults_is_a_noop():
    # frame is "the skin default" when it equals the skin's own frame
    cfg = _cfg(ui_skin="vintage", chassis_frame="wood_cheeks", switch_style="rocker")
    assert UL.migrate_appearance(cfg) is None
    assert cfg.ui_skin == "vintage" and cfg.appearance_migrated is True
    # an unknown frame value never overrode anything
    odd = _cfg(chassis_frame="chrome_plated")
    assert UL.migrate_appearance(odd) is None and odd.ui_skin == "skeuomorphic"
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.glob("*.json"))


def test_migrate_frame_on_another_builtin_skin():
    cfg = _cfg(ui_skin="minimal", chassis_frame="metal_rack")
    skin_id = UL.migrate_appearance(cfg)
    skin = UL.all_skins()[skin_id]
    assert skin.name == "Minimal (my settings)"
    assert skin.elements["frame"] == "metal_rack" and skin.elements["switch"] == "pill"
    assert dict(skin.shape) == dict(BUILTIN_SKINS["minimal"].shape)


@pytest.mark.parametrize("skin", ["no-such-skin", "user:whatever", "user:mine", ""])
def test_migrate_unknown_or_user_skin_only_sets_the_flag(skin):
    UL.save_skin(user_skin("Mine", "user:mine"))
    cfg = _cfg(ui_skin=skin, chassis_frame="wood_cheeks", switch_style="rocker")
    assert UL.migrate_appearance(cfg) is None
    assert cfg.appearance_migrated is True
    assert cfg.ui_skin == skin and cfg.chassis_frame == "wood_cheeks"
    assert sorted(p.name for p in UL.SKINS_DIR.glob("*.json")) == ["mine.json"]


def test_migrate_reuses_matching_skin_when_the_flag_was_lost():
    first = UL.migrate_appearance(_cfg(chassis_frame="wood_cheeks"))
    again = _cfg(chassis_frame="wood_cheeks")        # flag lost, e.g. hand-edited config
    assert UL.migrate_appearance(again) == first
    assert again.ui_skin == first and again.appearance_migrated is True
    assert len(list(UL.SKINS_DIR.glob("*.json"))) == 1


def test_migrate_name_collision_with_different_content_gets_a_unique_name_and_keeps_the_file():
    mine = Skin("user:old", "Skeuomorphic (my settings)", dict(BUILTIN_SKINS["vintage"].elements),
                dict(BUILTIN_SKINS["vintage"].shape))
    path = UL.save_skin(mine)
    before = path.read_bytes()
    cfg = _cfg(chassis_frame="frameless")
    skin_id = UL.migrate_appearance(cfg)
    assert skin_id and skin_id != "user:old"
    assert path.read_bytes() == before                # the user's file is never touched
    skins = UL.all_skins()
    assert skins[skin_id].name == "Skeuomorphic (my settings) (2)"
    assert skins[skin_id].elements["frame"] == "frameless"
    assert len(list(UL.SKINS_DIR.glob("*.json"))) == 2
    # and a re-run with a lost flag reuses the second one instead of creating a third
    again = _cfg(chassis_frame="frameless")
    assert UL.migrate_appearance(again) == skin_id and again.ui_skin == skin_id
    assert len(list(UL.SKINS_DIR.glob("*.json"))) == 2


@pytest.mark.parametrize("error", [OSError("disk full"), UL.LookFileError("nope"), ValueError("bad")])
def test_migrate_save_failure_does_not_raise_or_set_the_flag(monkeypatch, capsys, looks_dirs, error):
    def boom(skin):
        raise error

    cfg = _cfg(chassis_frame="wood_cheeks")
    with pytest.MonkeyPatch.context() as mp:      # only the stub is undone, not looks_dirs
        mp.setattr(UL, "save_skin", boom)
        assert UL.migrate_appearance(cfg) is None
    assert cfg.appearance_migrated is False
    assert (cfg.ui_skin, cfg.chassis_frame) == ("skeuomorphic", "wood_cheeks")
    out = capsys.readouterr()
    assert len((out.out + out.err).strip().splitlines()) == 1
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.glob("*.json"))
    # next launch retries and really creates the skin (in the per-test folder)
    skin_id = UL.migrate_appearance(cfg)
    assert skin_id is not None and cfg.appearance_migrated is True
    assert [p.name for p in (looks_dirs / "skins").glob("*.json")] == ["skeuomorphic-my-settings.json"]


@pytest.mark.parametrize("skin,frame,switch", [
    ("skeuomorphic", "auto", "rocker"),
    ("skeuomorphic", "wood_cheeks", "rocker"),
    ("skeuomorphic", "frameless", "bat_toggle"),
    ("vintage", "metal_rack", "bat_toggle"),
    ("vintage", "frameless", "rocker"),
    ("minimal", "wood_cheeks", "rocker"),
])
def test_migration_keeps_the_rendered_look_identical(skin, frame, switch):
    cfg = _cfg(ui_skin=skin, chassis_frame=frame, switch_style=switch)
    before = look_mod.look_from_config(cfg)
    skin_id = UL.migrate_appearance(cfg)
    after = look_mod.look_from_config(cfg)
    assert dict(after.skin.elements) == dict(before.skin.elements)
    assert dict(after.skin.shape) == dict(before.skin.shape)
    assert after.palette == before.palette
    if skin_id:                                  # built-in Skeuomorphic is pristine again
        assert cfg.switch_style == BUILTIN_SKINS["skeuomorphic"].elements["switch"]
        assert cfg.chassis_frame == "auto"


def test_look_for_docstring_marks_legacy_overrides_as_unmigrated_only():
    assert "unmigrated" in look_mod.look_for.__doc__


def test_startup_migration_loads_migrates_and_saves_config(tmp_path, monkeypatch):
    from mandible import __main__ as entry
    from mandible import config

    monkeypatch.setattr(config, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app" / "config.json"))
    config.save_config(_cfg(chassis_frame="wood_cheeks"))
    entry._migrate_appearance()
    cfg = config.load_config()
    assert cfg.appearance_migrated is True and cfg.ui_skin.startswith("user:")
    assert cfg.chassis_frame == "auto"
    assert cfg.ui_skin in UL.all_skins()
    saves = []
    real_save = config.save_config
    monkeypatch.setattr(config, "save_config", lambda c: (saves.append(c), real_save(c)))
    entry._migrate_appearance()                        # already migrated -> nothing is rewritten
    assert saves == []
    config.save_config(_cfg())                         # fresh default config: flag flips, saved once
    saves.clear()
    entry._migrate_appearance()
    assert len(saves) == 1 and config.load_config().appearance_migrated is True


def test_startup_migration_never_raises(tmp_path, monkeypatch, capsys):
    from mandible import __main__ as entry
    from mandible import config

    def boom():
        raise RuntimeError("config exploded")

    monkeypatch.setattr(config, "load_config", boom)
    entry._migrate_appearance()
    out = capsys.readouterr()
    assert "config exploded" in out.out + out.err
