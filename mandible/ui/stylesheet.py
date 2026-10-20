"""Application stylesheet generated from a Look (Palette + Skin).

``build_qss`` is the single place where colour tokens and skin shape tokens become QSS.
Widgets never set inline styles; they set an ``objectName`` or one of the dynamic
properties below and let this sheet style them:

* ``tier``    on QPushButton: ``primary`` | ``secondary`` | ``quiet`` | ``danger``;
  on QToolButton (split buttons such as the header's Hotkeys): ``secondary``
* ``state``   on ``QLabel#statusPill``: ``off`` | ``on`` | ``warn`` | ``danger``
* ``surface`` on QFrame: ``panel`` | ``raised`` | ``inset``

Rules keep the selectors and object names of the old ``gui.build_stylesheet``; values come
from palette tokens and the skin's shape tokens / element slots. The module is the only
one (with ``look.py`` and ``palette_gen.py``) allowed to contain colour literals.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .look import font_px

if TYPE_CHECKING:
    from .look import Look

__all__ = ["build_qss"]


def _px(value: float) -> str:
    return f"{value:g}px"


@lru_cache(maxsize=32)
def build_qss(look: "Look") -> str:
    """Return the application stylesheet for ``look`` (cached per Look)."""
    t = look.palette.color
    shape = look.skin.shape
    panel = look.skin.elements.get("panel")
    flat = panel == "flat"
    lacquer = panel == "lacquer"
    frameless = look.skin.elements.get("frame") == "frameless"

    # ---- palette tokens (old gui.THEMES key in the comment)
    win = t("bg.window")            # bg_win
    card = t("bg.panel")            # bg_card
    alt = t("bg.raised")            # bg_card_alt
    inset = t("bg.inset")           # bg_input
    overlay = t("bg.overlay")
    line = t("line.subtle")         # border
    strong = t("line.strong")
    ring = t("focus.ring")          # border_focus
    text = t("text.primary")        # text
    muted = t("text.secondary")     # text_muted
    dim = t("text.disabled")
    on_accent = t("text.on_accent")
    accent = t("accent")
    accent_hover = t("accent.hover")
    accent_pressed = t("accent.pressed")
    accent_subtle = t("accent.subtle")  # chip_bg
    ok = t("status.ok")             # active
    ok_bg = t("status.ok.subtle")   # active_bg
    warn = t("status.warn")
    warn_bg = t("status.warn.subtle")
    danger = t("status.danger")
    danger_bg = t("status.danger.subtle")
    chip_text = accent_hover        # chip_text: a light tint of the accent
    readout = t("readout.text")     # signal-blue family: informational badges

    # ---- skin shape tokens
    r_ctl = _px(shape["radius.control"])
    r_pnl = _px(shape["radius.panel"])
    r_sm = _px(min(shape["radius.control"], 4))     # badges, chips, tool buttons
    bw_n = shape["border.width"]
    bw = _px(bw_n)                                  # hairline border
    bw2 = _px(bw_n * 1.5)                           # emphasised border

    # ---- type scale (px)
    f_small = _px(font_px("small"))
    f_body = _px(font_px("body"))
    f_title = _px(font_px("title"))

    # ---- skin element slot "panel": flat skins drop gradients and keep one surface
    head_bg = card if flat else f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {alt}, stop:1 {win})"
    bay_bg = card if flat else win
    raised_bg = alt if flat else f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {alt}, stop:1 {card})"
    if lacquer:
        # Lacquer: a thin glossy band (bg.overlay) at the top of raised surfaces and a deeper
        # finish towards the bottom (bg.inset); brushed metal keeps the plain card gradient.
        # Every stop is a palette surface that body text clears 4.5:1 on.
        head_bg = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {overlay}, stop:0.12 {alt}, "
                   f"stop:1 {win})")
        raised_bg = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {overlay}, stop:0.08 {alt}, "
                     f"stop:0.6 {card}, stop:1 {inset})")

    # Frameless: the console strip sits flush at the bottom of the window outline (frame
    # margins 0; the chassis strokes the outline over it), so it takes the panel radius there.
    console_radius = (f"border-bottom-left-radius: {r_pnl}; border-bottom-right-radius: {r_pnl};"
                      if frameless else "")

    # Button tiers: rules of equal specificity go base, checked, status state, hover, pressed,
    # focus, disabled, so focus and disabled always show whatever else is set. No button has
    # an object-name rule (an ID selector would out-rank the tier's state rules).
    return f"""
QWidget {{
    font-family: "Segoe UI", -apple-system, system-ui, Roboto, sans-serif;
    font-size: {f_body};
    color: {text};
}}
QMainWindow, QDialog {{
    background-color: {win};
}}

QToolTip {{
    background-color: {overlay};
    color: {text};
    border: {bw} solid {strong};
    border-radius: {r_sm};
    padding: 4px 8px;
    font-family: "Segoe UI", sans-serif;
    font-size: {f_small};
    font-weight: 500;
}}

QFrame#rackChassis {{
    background-color: transparent;
    border: none;
}}
QFrame#masterHeadStrip {{
    background: {head_bg};
    border-bottom: {bw2} solid {line};
    border-top-left-radius: {r_pnl};
    border-top-right-radius: {r_pnl};
}}
QFrame#telemetryDisplay {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#signalMatrix {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#sideRackBay {{
    background: transparent;
    border: none;
}}
QFrame#modularBay, QFrame#presetModularBay {{
    background: {bay_bg};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#prefxModule, QFrame#limiterModule {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#prefxModule[active="true"], QFrame#limiterModule[active="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {ok_bg}, stop:1 {inset});
    border: {bw2} solid {ok};
}}
QFrame#prefxModule[active="true"]:hover, QFrame#limiterModule[active="true"]:hover {{
    background: {ok_bg};
    border-color: {ok};
}}
QFrame#prefxModule[active="false"]:hover, QFrame#limiterModule[active="false"]:hover {{
    border-color: {strong};
    background: {alt};
}}

QFrame#signalFlowStrip {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QLabel#flowBusLabel {{
    color: {muted};
    font-size: {f_small};
    font-weight: bold;
    font-family: Consolas, monospace;
}}
QLabel#flowArrow {{
    color: {muted};
    font-size: {f_small};
    font-weight: bold;
}}
QFrame#signalFlowStrip[mode="hidden"] {{
    background: transparent;
    border: none;
}}
QSplitter#bodySplitter::handle {{
    background: transparent;
}}
QComboBox#idleCombo {{
    font-size: {f_small};
    padding: 2px 6px;
}}
QToolButton[tier="secondary"] {{
    background-color: transparent;
    border: {bw} solid {strong};
    border-radius: {r_ctl};
    color: {text};
    font-weight: 500;
    padding: 3px 8px;
    padding-right: 20px;
}}
QToolButton[small="true"] {{
    font-size: {f_small};
}}
QToolButton[tier="secondary"]::menu-button {{
    border-left: {bw} solid {strong};
    width: 16px;
}}
QToolButton[tier="secondary"]:checked {{
    background-color: {ok_bg};
    border-color: {ok};
    color: {ok};
}}
QToolButton[tier="secondary"]:hover {{
    background-color: {alt};
    border-color: {accent_hover};
}}
QToolButton[tier="secondary"]:pressed {{
    background-color: {accent_subtle};
    border-color: {accent};
}}
QToolButton[tier="secondary"]:focus {{
    border: {bw2} solid {ring};
}}
QToolButton[tier="secondary"]:disabled {{
    background-color: transparent;
    border-color: {line};
    color: {dim};
}}
QLabel#rackPluginName {{
    font-weight: bold;
    font-size: {f_body};
    color: {text};
}}

QListWidget#chainList {{
    background-color: transparent;
    border: none;
    padding: 0px;
    outline: none;
}}
QListWidget#chainList::item {{
    border-radius: {r_pnl};
    padding: 2px;
    margin-bottom: 4px;
}}
QListWidget#chainList::item:selected {{
    background-color: transparent;
}}
QFrame#chainCard {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#chainCard:hover {{
    background-color: {alt};
    border-color: {strong};
}}
QFrame#chainCard[selected="true"] {{
    background-color: {inset};
    border: {bw2} solid {ring};
}}
QFrame#chainCard[active="true"] {{
    background-color: {ok_bg};
    border: {bw2} solid {ok};
}}
QFrame#chainCard[active="true"][selected="true"] {{
    background-color: {ok_bg};
    border: {bw2} solid {ok};
}}
QLabel#rackInspLabel {{
    color: {muted};
    font-size: {f_small};
    font-weight: 800;
    letter-spacing: 0.8px;
    border: none;
    background: transparent;
    padding: 0px;
    margin: 0px;
}}
QLabel#cardHotkey {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 0px 6px;
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    color: {muted};
    min-height: 18px;
    max-height: 18px;
    qproperty-alignment: 'AlignCenter';
}}
QLabel#cardHotkey[active="true"] {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    color: {ok};
}}
QLabel#chainName {{
    color: {text};
    font-weight: bold;
}}
QLabel#chainName[active="true"] {{
    font-weight: 800;
}}
QLabel#chainSub {{
    color: {muted};
    font-size: {f_small};
}}
QLabel#chainSub[active="true"] {{
    color: {ok};
    font-weight: bold;
}}
QLabel#chainWet {{
    color: {muted};
    font-size: {f_small};
    font-weight: bold;
    font-family: Consolas, monospace;
    margin: 0px;
    padding: 0px;
}}
QLabel#chainWet[active="true"] {{
    color: {ok};
}}

QListWidget#rackList {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_pnl};
    padding: 4px;
    outline: none;
}}
QListWidget#rackList::item {{
    border-radius: {r_pnl};
    padding: 2px;
    margin-bottom: 6px;
}}
QListWidget#rackList::item:selected {{
    background-color: transparent;
}}
QFrame#pluginRackCard {{
    background: {raised_bg};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#pluginRackCard:hover {{
    border-color: {strong};
}}
QFrame#pluginRackCard[bypassed="true"] {{
    border-style: dashed;
    border-color: {strong};
}}
QFrame#pluginRackCard[error="true"] {{
    border-color: {danger};
    background-color: {danger_bg};
}}

QLabel#vendorBadge {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 1px 6px;
    font-size: {f_small};
    font-weight: 600;
    color: {muted};
}}
QLabel#rackSlotIndex {{
    font-family: Consolas, monospace;
    font-size: {f_title};
    font-weight: bold;
    color: {muted};
}}
QLabel#formatBadge {{
    background-color: {inset};
    border: {bw} solid {readout};
    border-radius: {r_sm};
    padding: 1px 5px;
    font-size: {f_small};
    font-weight: bold;
    color: {readout};
}}
QLabel#builtinBadge {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 1px 5px;
    font-size: {f_small};
    font-weight: bold;
    color: {muted};
}}
QLabel#awakeBadge {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    border-radius: {r_sm};
    padding: 1px 5px;
    font-size: {f_small};
    font-weight: bold;
    color: {ok};
}}
QLabel#rackSlotError {{
    color: {danger};
    font-size: {f_small};
    font-weight: bold;
}}
QLabel#latencyChip {{
    color: {muted};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
}}
QLabel#rackBayLabel {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    color: {muted};
    letter-spacing: 0.5px;
    border: none;
    background: transparent;
}}
QFrame#rackBaySeparator {{
    color: {line};
    background: {line};
    max-width: 1px;
}}

QFrame#channelStripCard, QFrame#channelStrip {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}

QLabel#channelTitle {{
    font-weight: bold;
    font-size: {f_small};
    color: {muted};
    letter-spacing: 0.5px;
}}
QLabel#gainLabel {{
    font-size: {f_small};
    color: {muted};
}}
QLabel#gainValue {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    color: {text};
}}
QLineEdit#inlineValueEdit, QLineEdit#gainValueEdit {{
    background-color: {inset};
    border: {bw2} solid {ring};
    border-radius: {r_sm};
    color: {text};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    padding: 0px 2px;
    selection-background-color: {accent};
}}
QLineEdit#gainValueEdit {{
    font-size: {f_small};
    padding: 0px 3px;
}}

QFrame#pluginMacroBay {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_ctl};
}}

QPushButton {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_ctl};
    padding: 5px 12px;
    font-weight: 500;
    color: {text};
}}
QPushButton:hover {{
    background-color: {alt};
    border-color: {strong};
}}
QPushButton:pressed {{
    background-color: {accent};
    color: {on_accent};
}}
QPushButton:disabled {{
    color: {dim};
    border-color: {line};
}}

QPushButton[tier="primary"] {{
    background-color: {accent};
    border: {bw} solid {accent};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[tier="secondary"] {{
    background-color: transparent;
    border: {bw} solid {strong};
    color: {text};
}}
QPushButton[tier="quiet"] {{
    background-color: transparent;
    border: {bw} solid transparent;
    color: {text};
}}
QPushButton[tier="danger"] {{
    background-color: transparent;
    border: {bw} solid {danger};
    color: {danger};
    font-weight: 600;
}}
QPushButton[small="true"] {{
    font-size: {f_small};
    padding: 3px 8px;
}}
QPushButton[iconOnly="true"] {{
    padding: 0px;
}}
QPushButton[iconOnly="true"]::menu-indicator {{
    image: none;
    width: 0px;
}}

QPushButton[tier="primary"]:checked {{
    background-color: {accent_pressed};
    border-color: {accent_hover};
    color: {on_accent};
}}
QPushButton[tier="secondary"]:checked, QPushButton[tier="secondary"][state="on"],
QPushButton[tier="quiet"][state="on"] {{
    background-color: {ok_bg};
    border-color: {ok};
    color: {ok};
}}
QPushButton[tier="quiet"]:checked {{
    background-color: {accent_subtle};
    border-color: transparent;
    color: {accent_hover};
}}
QPushButton[tier="danger"]:checked {{
    background-color: {danger_bg};
    border-color: {danger};
    color: {danger};
}}
QPushButton[tier="secondary"][state="warn"], QPushButton[tier="quiet"][state="warn"] {{
    background-color: {warn_bg};
    border-color: {warn};
    color: {warn};
}}
QPushButton[tier="secondary"][state="danger"], QPushButton[tier="quiet"][state="danger"] {{
    background-color: {danger_bg};
    border-color: {danger};
    color: {danger};
}}

QPushButton[tier="primary"]:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton[tier="secondary"]:hover {{
    background-color: {alt};
    border-color: {accent_hover};
}}
QPushButton[tier="quiet"]:hover {{
    background-color: {alt};
    border-color: {line};
}}
QPushButton[tier="danger"]:hover {{
    background-color: {danger_bg};
    border-color: {danger};
}}

QPushButton[tier="primary"]:pressed {{
    background-color: {accent_pressed};
    border-color: {accent_pressed};
    color: {on_accent};
}}
QPushButton[tier="secondary"]:pressed {{
    background-color: {accent_subtle};
    border-color: {accent};
}}
QPushButton[tier="quiet"]:pressed {{
    background-color: {inset};
    border-color: {line};
}}
QPushButton[tier="danger"]:pressed {{
    background-color: {danger_bg};
    border-color: {text};
}}

QPushButton[tier="primary"]:focus {{
    border: 3px double {ring};
    background-clip: padding;
    padding: 3px 10px;
}}
QPushButton[tier="secondary"]:focus {{
    border: {bw2} solid {ring};
}}
QPushButton[tier="quiet"]:focus {{
    border: {bw2} solid {ring};
}}
QPushButton[tier="danger"]:focus {{
    border: {bw2} solid {ring};
}}
QPushButton[small="true"][tier="primary"]:focus {{
    padding: 1px 6px;
}}
QPushButton[iconOnly="true"]:focus {{
    padding: 0px;
}}

QPushButton[tier="primary"]:disabled {{
    background-color: {alt};
    border-color: {line};
    color: {dim};
}}
QPushButton[tier="secondary"]:disabled {{
    background-color: transparent;
    border-color: {line};
    color: {dim};
}}
QPushButton[tier="quiet"]:disabled {{
    background-color: transparent;
    border-color: transparent;
    color: {dim};
}}
QPushButton[tier="danger"]:disabled {{
    background-color: transparent;
    border-color: {line};
    color: {dim};
}}

QLabel#statusPill {{
    background-color: {inset};
    border: none;
    border-radius: 10px;
    padding: 3px 9px;
    font-size: {f_small};
    font-weight: 600;
    color: {muted};
}}
QLabel#statusPill[iconOnly="true"] {{
    padding: 3px 7px;
}}
QLabel#statusPill[state="off"] {{
    background-color: {inset};
    color: {muted};
}}
QLabel#statusPill[state="on"] {{
    background-color: {ok_bg};
    color: {ok};
}}
QLabel#statusPill[state="warn"] {{
    background-color: {warn_bg};
    color: {warn};
}}
QLabel#statusPill[state="danger"] {{
    background-color: {danger_bg};
    color: {danger};
}}

QFrame[surface="panel"] {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame[surface="raised"] {{
    background: {raised_bg};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame[surface="inset"] {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}

QSlider::groove:horizontal {{
    border: {bw} solid {win};
    height: 6px;
    background: {inset};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {muted}, stop:1 {strong});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {text}, stop:1 {muted});
    border: {bw} solid {strong};
    width: 14px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 2px;
}}
QSlider::handle:horizontal:hover {{
    background: {text};
    border-color: {muted};
}}

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_ctl};
    padding: 4px 8px;
    color: {text};
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: {bw2} solid {ring};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {card};
    border: {bw} solid {line};
    selection-background-color: {accent};
    selection-color: {on_accent};
    padding: 4px;
}}

QLabel#hotkeyLabel {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 4px 8px;
    font-family: Consolas, monospace;
    color: {chip_text};
}}
QLabel#activeLabel {{
    font-size: {f_title};
    font-weight: bold;
    padding: 4px 12px;
    border-radius: {r_ctl};
    background-color: {card};
    color: {muted};
}}
QLabel#activeLabel[on="true"] {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    color: {ok};
}}
QLabel#statusLabel {{
    color: {muted};
    padding-left: 8px;
    font-size: {f_body};
}}
QLabel#statusLabel[on="true"] {{
    color: {ok};
    font-weight: bold;
}}
QLabel#diagLabel {{
    color: {muted};
    font-family: Consolas, monospace;
    font-size: {f_small};
}}

QFrame#waveformPanel {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
    padding: 6px;
}}
QLabel#waveformClipName {{
    font-weight: bold;
    font-size: {f_small};
    color: {text};
}}
QLabel#waveformTiming {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    color: {muted};
}}
QLabel#waveformHint {{
    color: {muted};
    font-size: {f_small};
    font-style: italic;
}}
QLabel#rackBusLabel {{
    font-weight: 800;
    font-size: {f_small};
    color: {muted};
    letter-spacing: 0.8px;
}}
QLineEdit#rackBusNameEdit {{
    background: {inset};
    border: {bw} dashed {strong};
    border-radius: {r_sm};
    padding: 3px 8px;
    color: {text};
    font-family: "Segoe UI", sans-serif;
    font-weight: 800;
    font-size: {f_body};
    letter-spacing: 0.5px;
}}
QLineEdit#rackBusNameEdit:hover {{
    border: {bw} solid {strong};
    background: {card};
}}
QLineEdit#rackBusNameEdit:focus {{
    border: {bw2} solid {ring};
    background: {alt};
}}
QFrame#inspectorBox {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
    padding: 4px 8px;
}}
QFrame#inspectorSeparator {{
    color: {line};
}}
QLabel#rackLatency {{
    color: {muted};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
}}

QLabel#vfdStat {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    color: {muted};
}}
QLabel#vfdStat[running="true"] {{
    color: {ok};
}}
QLabel#vfdValue {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    color: {muted};
}}
QLabel#vfdLatency {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    color: {readout};
}}
QLabel#vfdDriver {{
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    color: {text};
}}
QLabel#moduleTitle {{
    font-weight: 800;
    font-size: {f_small};
    color: {muted};
    letter-spacing: 0.8px;
}}
QLabel#bankTitle {{
    font-weight: 800;
    font-size: {f_small};
    color: {muted};
    letter-spacing: 0.8px;
}}
QLabel#limiterThreshold {{
    color: {muted};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    margin-right: 4px;
}}
QLabel#limiterThreshold[active="true"] {{
    color: {text};
}}
QFrame#consoleFrame {{
    background: {inset};
    border-top: {bw} solid {line};
    {console_radius}
}}
QFrame#consoleFrame QFrame#condensedStrip {{
    background: {inset};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 4px 8px;
}}
QLabel#condensedLabel {{
    font-weight: bold;
    font-size: {f_small};
    color: {muted};
}}

QLabel#hint {{
    color: {muted};
    font-size: {f_small};
}}
QLabel#paramMapTitle {{
    font-weight: bold;
    font-size: {f_title};
    color: {text};
}}
QLabel#paramMapBadge {{
    background-color: {inset};
    border: {bw} solid {readout};
    border-radius: {r_sm};
    color: {readout};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
    padding: 2px 8px;
}}
QLabel#hotkeyPrompt, QLabel#settingsSectionTitle {{
    font-size: {f_title};
    font-weight: bold;
    color: {text};
}}
QLabel#settingsGroupLabel {{
    color: {muted};
    font-size: {f_small};
    font-weight: 800;
    letter-spacing: 1px;
}}
QListWidget#settingsSections {{
    background-color: transparent;
    border: {bw2} solid transparent;
    border-radius: {r_pnl};
    outline: none;
    padding: 4px;
}}
QListWidget#settingsSections:focus {{
    border: {bw2} solid {ring};
}}
QListWidget#settingsSections::item {{
    color: {muted};
    padding: 8px 12px;
    margin-bottom: 2px;
    border: {bw} solid transparent;
    border-radius: {r_ctl};
}}
QListWidget#settingsSections::item:hover {{
    background-color: {alt};
    color: {text};
}}
QListWidget#settingsSections::item:selected {{
    background-color: {accent_subtle};
    border: {bw} solid {accent};
    color: {text};
}}
QFrame#duckStrip {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QLabel#duckLabel {{
    color: {muted};
    font-size: {f_small};
}}
QLabel#duckValue {{
    color: {readout};
    font-family: Consolas, monospace;
    font-size: {f_small};
    font-weight: bold;
}}

QLabel#wizardStep {{
    color: {accent_hover};
    font-weight: 800;
    font-size: {f_small};
    letter-spacing: 1px;
}}
QLabel#wizardTitle {{
    font-size: {f_title};
    font-weight: bold;
    color: {text};
}}
QLabel#wizardDesc {{
    color: {muted};
    font-size: {f_body};
}}
QLabel#wizardFieldLabel {{
    color: {muted};
    font-size: {f_small};
    font-weight: bold;
}}
QLabel#wizardMicStatus {{
    color: {muted};
    font-size: {f_small};
    font-family: Consolas, monospace;
}}
QLabel#wizardMicStatus[ok="true"] {{
    color: {ok};
    font-weight: bold;
    font-size: {f_body};
}}
QFrame#wizardCard {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QFrame#wizardCard[state="ok"] {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
}}
QFrame#wizardCard[state="warn"] {{
    background-color: {warn_bg};
    border: {bw} solid {warn};
}}
QLabel#wizardCardTitle {{
    font-weight: bold;
    font-size: {f_body};
}}
QLabel#wizardCardTitle[state="ok"] {{
    color: {ok};
}}
QLabel#wizardCardTitle[state="warn"] {{
    color: {warn};
}}
QLabel#wizardCardDesc {{
    color: {muted};
    font-size: {f_small};
}}
QFrame#wizardGuideCard {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QLabel#wizardGuideTitle {{
    font-weight: 800;
    font-size: {f_small};
    color: {readout};
    letter-spacing: 0.8px;
}}
QLabel#wizardGuideNum {{
    font-weight: bold;
    color: {text};
    font-size: {f_small};
}}
QLabel#wizardGuideText {{
    color: {muted};
    font-size: {f_small};
}}

QWidget#customizeBody {{
    background-color: {card};
}}
QWidget#customizeTitleBar {{
    background-color: {alt};
    border-bottom: {bw} solid {line};
}}
QLabel#customizeTitle {{
    font-size: {f_title};
    font-weight: bold;
    color: {text};
}}
QLabel#customizeSlotLabel {{
    color: {muted};
    font-size: {f_small};
    font-weight: 600;
}}
QLabel#customizeMessage {{
    color: {muted};
    font-size: {f_small};
}}
QLabel#customizeMessage[state="warn"], QLabel#customizeNotice {{
    color: {warn};
    font-size: {f_small};
    font-weight: 600;
}}
QLabel#customizeMessage[state="danger"] {{
    color: {danger};
    font-weight: 600;
}}
QFrame#customizeBanner {{
    background-color: {warn_bg};
    border: {bw} solid {warn};
    border-radius: {r_pnl};
}}
QFrame#customizeBanner[state="danger"] {{
    background-color: {danger_bg};
    border-color: {danger};
}}
QLabel#tokenName, QLabel#tokenRatio, QLineEdit#hexEdit {{
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: {f_small};
}}
QLabel#tokenRatio {{
    color: {muted};
}}
QPushButton[tier="secondary"][chip="true"]:checked {{
    background-color: {accent_subtle};
    color: {text};
}}

QTabWidget::pane {{
    border: {bw} solid {line};
    border-radius: {r_pnl};
    background-color: {card};
}}
QTabBar::tab {{
    background-color: {win};
    border: {bw} solid {line};
    padding: 8px 16px;
    border-top-left-radius: {r_ctl};
    border-top-right-radius: {r_ctl};
    margin-right: 2px;
    color: {muted};
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background-color: {card};
    border-bottom-color: {card};
    color: {text};
    font-weight: bold;
}}

QTableWidget {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
    gridline-color: {line};
}}
QTableWidget::item {{
    padding: 6px;
}}
QTableWidget#soundboardTable::item {{
    padding: 2px 6px;
}}
QHeaderView::section {{
    background-color: {win};
    border: {bw} solid {line};
    padding: 6px;
    font-weight: bold;
    color: {text};
}}

QProgressBar {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: {r_ctl};
    text-align: center;
    color: {text};
    font-size: {f_small};
    font-weight: bold;
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: {r_sm};
}}

QScrollBar:vertical {{
    border: none;
    background-color: {win};
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {line};
    min-height: 20px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {strong};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
