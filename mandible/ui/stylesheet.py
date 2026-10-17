"""Application stylesheet generated from a Look (Palette + Skin).

``build_qss`` is the single place where colour tokens and skin shape tokens become QSS.
Widgets never set inline styles; they set an ``objectName`` or one of the dynamic
properties below and let this sheet style them:

* ``tier``    on QPushButton: ``primary`` | ``secondary`` | ``quiet`` | ``danger``
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
    flat = look.skin.elements.get("panel") == "flat"

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
    toggle_bg = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {alt}, stop:1 {inset})"

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

QPushButton#hardwareMasterToggle, QPushButton#powerButton {{
    background: {toggle_bg};
    border: {bw2} solid {line};
    border-radius: {r_ctl};
    color: {text};
    font-weight: 800;
    font-size: {f_small};
    letter-spacing: 0.5px;
    padding: 6px 14px;
}}
QPushButton#hardwareMasterToggle:hover, QPushButton#powerButton:hover {{
    border-color: {ok};
    background: {alt};
}}
QPushButton#hardwareMasterToggle:checked, QPushButton#powerButton:checked {{
    background: {ok};
    border: {bw2} solid {ok};
    color: {win};
}}

QPushButton#hardwareMonitorToggle, QPushButton#monitorButton {{
    background: {toggle_bg};
    border: {bw2} solid {line};
    border-radius: {r_ctl};
    color: {text};
    font-weight: 700;
    font-size: {f_small};
    padding: 6px 14px;
}}
QPushButton#hardwareMonitorToggle:hover, QPushButton#monitorButton:hover {{
    border-color: {accent};
}}
QPushButton#hardwareMonitorToggle:checked, QPushButton#monitorButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent}, stop:1 {accent_pressed});
    border: {bw2} solid {accent_hover};
    color: {on_accent};
}}

QPushButton#hardwarePanicCut, QPushButton#panicTopButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {danger_bg}, stop:1 {inset});
    border: {bw2} solid {danger};
    border-radius: {r_ctl};
    color: {danger};
    font-weight: 800;
    font-size: {f_small};
    letter-spacing: 0.5px;
    padding: 6px 14px;
}}
QPushButton#hardwarePanicCut:hover, QPushButton#panicTopButton:hover {{
    background: {danger};
    color: {win};
}}

QPushButton#hardwareConfigBtn {{
    background: {card};
    border: {bw2} solid {line};
    color: {muted};
    font-weight: bold;
    font-size: {f_small};
    padding: 6px 12px;
    border-radius: {r_ctl};
}}
QPushButton#hardwareConfigBtn:hover {{
    background: {alt};
    color: {text};
}}

QFrame#signalFlowStrip {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}
QLabel#flowBusLabel {{
    color: {muted};
    font-size: 7.5pt;
    font-weight: bold;
    font-family: Consolas, monospace;
}}
QLabel#flowArrow {{
    color: {muted};
    font-size: 8.5pt;
    font-weight: bold;
}}
QLabel#flowPill {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_ctl};
    padding: 4px 10px;
    font-weight: 600;
    font-size: {f_small};
    color: {text};
}}
QLabel#flowPill[active="true"] {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    color: {ok};
}}
QPushButton#flowBtn {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_ctl};
    padding: 4px 10px;
    font-weight: 600;
    font-size: {f_small};
    color: {text};
}}
QPushButton#flowBtn:hover {{
    background-color: {alt};
    border-color: {accent};
    color: {text};
}}
QPushButton#flowBtn[active="true"] {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    color: {ok};
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
    font-size: 7.5pt;
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
    font-size: 7.5pt;
    padding-left: 17px;
}}
QLabel#chainSub[active="true"] {{
    color: {ok};
    font-weight: bold;
}}
QLabel#chainWet {{
    color: {muted};
    font-size: 7.5pt;
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

QPushButton#rackPowerBtn {{
    background-color: {alt};
    border: {bw} solid {line};
    border-radius: 15px;
    font-weight: bold;
    font-size: {f_title};
    color: {muted};
}}
QPushButton#rackPowerBtn:checked {{
    background: {ok};
    border: {bw} solid {ok};
    color: {win};
}}
QPushButton#rackPowerBtn:hover {{
    border-color: {ok};
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
QPushButton#rackHotkeyBtn {{
    background-color: {win};
    border: {bw} solid {line};
    border-radius: {r_sm};
    padding: 2px 6px;
    font-family: Consolas, monospace;
    font-size: {f_small};
    color: {chip_text};
}}
QPushButton#rackHotkeyBtn:hover {{
    border-color: {accent};
    color: {text};
}}
QPushButton#rackKnobsBtn {{
    background-color: {card};
    border: {bw} solid {strong};
    border-radius: {r_sm};
    padding: 3px 7px;
    font-family: Consolas, monospace;
    font-size: 7.5pt;
    font-weight: bold;
    color: {text};
}}
QPushButton#rackMapBtn {{
    background-color: {inset};
    border: {bw} solid {strong};
    border-radius: {r_sm};
    padding: 3px 7px;
    font-family: Consolas, monospace;
    font-size: 7.5pt;
    font-weight: bold;
    color: {muted};
}}
QPushButton#rackMapBtn[mapped="true"] {{
    border-color: {readout};
    color: {readout};
}}
QLabel#rackSlotIndex {{
    font-family: Consolas, monospace;
    font-size: 10.5pt;
    font-weight: bold;
    color: {muted};
}}
QLabel#formatBadge {{
    background-color: {inset};
    border: {bw} solid {readout};
    border-radius: {r_sm};
    padding: 1px 5px;
    font-size: 7.5pt;
    font-weight: bold;
    color: {readout};
}}
QLabel#awakeBadge {{
    background-color: {ok_bg};
    border: {bw} solid {ok};
    border-radius: {r_sm};
    padding: 1px 5px;
    font-size: 7.5pt;
    font-weight: bold;
    color: {ok};
}}
QLabel#rackSlotError {{
    color: {danger};
    font-size: 8pt;
    font-weight: bold;
}}
QLabel#latencyChip {{
    color: {muted};
    font-family: Consolas, monospace;
    font-size: 7.5pt;
    font-weight: bold;
}}
QLabel#rackBayLabel {{
    font-family: Consolas, monospace;
    font-size: 6.5pt;
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
QPushButton#rackUiBtn {{
    background-color: {accent};
    border: {bw} solid {accent_hover};
    border-radius: {r_ctl};
    padding: 5px 12px;
    font-weight: bold;
    font-size: {f_small};
    color: {on_accent};
}}
QPushButton#rackUiBtn:hover {{
    background-color: {accent_hover};
}}
QPushButton#rackToolBtn {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_sm};
    color: {text};
    font-size: {f_body};
    padding: 0px;
    margin: 0px;
    min-width: 0px;
    min-height: 0px;
}}
QPushButton#rackToolBtn:hover {{
    background-color: {alt};
    color: {text};
}}
QPushButton#rackRemoveBtn {{
    background-color: {danger_bg};
    border: {bw} solid {line};
    border-radius: {r_sm};
    color: {danger};
    font-size: {f_body};
    font-weight: bold;
    padding: 0px;
    margin: 0px;
    min-width: 0px;
    min-height: 0px;
}}
QPushButton#rackRemoveBtn:hover {{
    background-color: {danger};
    color: {win};
}}

QFrame#channelStripCard, QFrame#channelStrip {{
    background-color: {card};
    border: {bw} solid {line};
    border-radius: {r_pnl};
}}

QLabel#channelTitle {{
    font-weight: bold;
    font-size: 8pt;
    color: {muted};
    letter-spacing: 0.5px;
}}
QLabel#gainLabel {{
    font-size: 8.5pt;
    color: {muted};
}}
QLabel#gainValue {{
    font-family: Consolas, monospace;
    font-size: 8.5pt;
    color: {text};
}}
QLineEdit#inlineValueEdit, QLineEdit#gainValueEdit {{
    background-color: {inset};
    border: {bw2} solid {ring};
    border-radius: {r_sm};
    color: {text};
    font-family: Consolas, monospace;
    font-size: 8pt;
    font-weight: bold;
    padding: 0px 2px;
    selection-background-color: {accent};
}}
QLineEdit#gainValueEdit {{
    font-size: 8.5pt;
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
QPushButton#testButton:pressed {{
    background-color: {ok};
    border-color: {ok};
    color: {win};
}}

QPushButton[tier="primary"] {{
    background-color: {accent};
    border: {bw} solid {accent};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[tier="primary"]:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton[tier="primary"]:pressed {{
    background-color: {accent_pressed};
    border-color: {accent_pressed};
    color: {on_accent};
}}
QPushButton[tier="primary"]:focus {{
    border: 3px double {ring};
    background-clip: padding;
    padding: 3px 10px;
}}
QPushButton[tier="primary"]:disabled {{
    background-color: {alt};
    border-color: {line};
    color: {dim};
}}
QPushButton[tier="primary"]:checked {{
    background-color: {accent_pressed};
    border-color: {accent_hover};
    color: {on_accent};
}}

QPushButton[tier="secondary"] {{
    background-color: transparent;
    border: {bw} solid {strong};
    color: {text};
}}
QPushButton[tier="secondary"]:hover {{
    background-color: {alt};
    border-color: {accent_hover};
}}
QPushButton[tier="secondary"]:pressed {{
    background-color: {accent_subtle};
    border-color: {accent};
    color: {text};
}}
QPushButton[tier="secondary"]:focus {{
    border: {bw2} solid {ring};
}}
QPushButton[tier="secondary"]:disabled {{
    background-color: transparent;
    border-color: {line};
    color: {dim};
}}
QPushButton[tier="secondary"]:checked {{
    background-color: {accent_subtle};
    border-color: {accent};
    color: {accent_hover};
}}

QPushButton[tier="quiet"] {{
    background-color: transparent;
    border: {bw} solid transparent;
    color: {muted};
}}
QPushButton[tier="quiet"]:hover {{
    background-color: {alt};
    border-color: {line};
    color: {text};
}}
QPushButton[tier="quiet"]:pressed {{
    background-color: {inset};
    border-color: {line};
    color: {text};
}}
QPushButton[tier="quiet"]:focus {{
    border: {bw2} solid {ring};
    color: {text};
}}
QPushButton[tier="quiet"]:disabled {{
    background-color: transparent;
    border-color: transparent;
    color: {dim};
}}
QPushButton[tier="quiet"]:checked {{
    background-color: {accent_subtle};
    border-color: transparent;
    color: {accent_hover};
}}

QPushButton[tier="danger"] {{
    background-color: transparent;
    border: {bw} solid {danger};
    color: {danger};
    font-weight: 600;
}}
QPushButton[tier="danger"]:hover {{
    background-color: {danger};
    border-color: {danger};
    color: {win};
}}
QPushButton[tier="danger"]:pressed {{
    background-color: {danger_bg};
    border-color: {danger};
    color: {danger};
}}
QPushButton[tier="danger"]:focus {{
    border: {bw2} solid {ring};
}}
QPushButton[tier="danger"]:disabled {{
    background-color: transparent;
    border-color: {line};
    color: {dim};
}}
QPushButton[tier="danger"]:checked {{
    background-color: {danger_bg};
    border-color: {danger};
    color: {danger};
}}

QLabel#statusPill {{
    background-color: {inset};
    border: {bw} solid {line};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {f_small};
    font-weight: 600;
    color: {muted};
}}
QLabel#statusPill[state="off"] {{
    background-color: {inset};
    border-color: {line};
    color: {muted};
}}
QLabel#statusPill[state="on"] {{
    background-color: {ok_bg};
    border-color: {ok};
    color: {ok};
}}
QLabel#statusPill[state="warn"] {{
    background-color: {warn_bg};
    border-color: {warn};
    color: {warn};
}}
QLabel#statusPill[state="danger"] {{
    background-color: {danger_bg};
    border-color: {danger};
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
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_hover}, stop:1 {accent});
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

QGroupBox {{
    border: {bw} solid {line};
    border-radius: {r_pnl};
    margin-top: 14px;
    padding-top: 10px;
    background-color: {card};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    font-weight: bold;
    color: {accent};
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
QHeaderView::section {{
    background-color: {win};
    border: {bw} solid {line};
    padding: 6px;
    font-weight: bold;
    color: {text};
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
