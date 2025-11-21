#!/usr/bin/env python3
"""
pinmux_configbits.py

ConfigBits-style DTS macro computation for Jetson Thor pinmux.

This module reimplements, in Python, the Excel/VBA "ConfigBits"
bitfield logic so the resulting macros match what the original 
XLSM generator would produce.
"""

from __future__ import annotations
from typing import Optional, Dict, Any

# Bit definitions – copied from the Excel/VBA Enum BallConfig
CFG_RCV_SEL   = 1
CFG_LOCK      = 2
CFG_OD        = 4
CFG_E_INPUT   = 8
CFG_TRISTATE  = 16
CFG_PULL_DOWN = 32
CFG_PULL_UP   = 64
CFG_I2C       = 128
CFG_DDC       = 256
CFG_HAS_EQOS  = 2048
CFG_EQOS      = 4096
CFG_DRV_1X    = 512
CFG_DEF_1X    = 1024

# Error sentinels
ERR_PULL      = -1
ERR_TRISTATE  = -2
ERR_E_INPUT   = -3
ERR_RCV_SEL   = -4
ERR_LPDR      = -5
ERR_EQOS      = -6
ERR_LOCK      = -7

def _norm_text(v) -> str:
    if v is None:
        return ""
    return str(v).strip()

# Low-level Set* helpers (bitfield mutators)
def set_pull(config_bits: int, pupd: str) -> int:
    v = _norm_text(pupd).upper()
    if v == "NORMAL" or v == "":
        new_bits = config_bits & ~CFG_PULL_UP & ~CFG_PULL_DOWN
    elif v == "PULL_DOWN":
        new_bits = (config_bits & ~CFG_PULL_UP) | CFG_PULL_DOWN
    elif v == "PULL_UP":
        new_bits = (config_bits | CFG_PULL_UP) & ~CFG_PULL_DOWN
    else:
        return ERR_PULL
    return new_bits

def get_pull(config_bits: int) -> str:
    checker = config_bits & (CFG_PULL_UP | CFG_PULL_DOWN)
    checker = (checker // CFG_PULL_DOWN) % 4
    if checker > 2:
        return "TEGRA_PIN_PULL_NONE" # Error fallback

    if checker == 0:
        return "TEGRA_PIN_PULL_NONE"
    elif checker == 1:
        return "TEGRA_PIN_PULL_DOWN"
    elif checker == 2:
        return "TEGRA_PIN_PULL_UP"
    return "TEGRA_PIN_PULL_NONE"

def set_tristate(config_bits: int, tristate: str) -> int:
    v = _norm_text(tristate).upper()
    if v == "NORMAL" or v == "":
        new_bits = config_bits & ~CFG_TRISTATE
    elif v == "TRISTATE":
        new_bits = config_bits | CFG_TRISTATE
    else:
        return ERR_TRISTATE
    return new_bits

def get_tristate(config_bits: int) -> str:
    checker = config_bits & CFG_TRISTATE
    checker = (checker // CFG_TRISTATE) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

def set_einput(config_bits: int, einput: str) -> int:
    v = _norm_text(einput).upper()
    if v == "DISABLE" or v == "":
        new_bits = config_bits & ~CFG_E_INPUT
    elif v == "ENABLE":
        new_bits = config_bits | CFG_E_INPUT
    else:
        return ERR_E_INPUT
    return new_bits

def get_einput(config_bits: int) -> str:
    checker = config_bits & CFG_E_INPUT
    checker = (checker // CFG_E_INPUT) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

def set_od(config_bits: int, od: str) -> int:
    v = _norm_text(od).upper()
    if v == "ENABLE":
        return config_bits | CFG_OD
    else:
        return config_bits & ~CFG_OD

def get_od(config_bits: int) -> str:
    checker = config_bits & CFG_OD
    checker = (checker // CFG_OD) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

def set_lock(config_bits: int, locked: str) -> int:
    v = _norm_text(locked).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_LOCK
    elif v == "ENABLE":
        new_bits = config_bits | CFG_LOCK
    else:
        return ERR_LOCK
    return new_bits

def get_lock(config_bits: int) -> str:
    checker = config_bits & CFG_LOCK
    checker = (checker // CFG_LOCK) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

def set_lpdr(config_bits: int, lpdr: str) -> int:
    v = _norm_text(lpdr).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_DEF_1X & ~CFG_DRV_1X
    elif v == "ENABLE":
        new_bits = (config_bits & ~CFG_DEF_1X) | CFG_DRV_1X
    elif v == "DEF_1X":
        new_bits = (config_bits | CFG_DEF_1X) & ~CFG_DRV_1X
    elif v == "DEF_2X":
        new_bits = config_bits | CFG_DRV_1X | CFG_DEF_1X
    else:
        return ERR_LPDR
    return new_bits

def get_lpdr(config_bits: int) -> str:
    checker = config_bits & (CFG_DRV_1X | CFG_DEF_1X)
    checker = (checker // CFG_DRV_1X) % 4

    if checker == 0:
        return "TEGRA_PIN_1X_DRIVER"
    elif checker == 1:
        return "TEGRA_PIN_2X_DRIVER"
    elif checker == 2:
        return "TEGRA_PIN_DEFAULT_DRIVE_1X"
    elif checker == 3:
        return "TEGRA_PIN_DEFAULT_DRIVE_2X"
    else:
        return "TEGRA_PIN_1X_DRIVER"

def set_ddc(config_bits: int) -> int:
    return config_bits | CFG_DDC

def get_ddc(config_bits: int) -> int:
    checker = config_bits & CFG_DDC
    checker = (checker // CFG_DDC) % 2
    return checker

def set_rcvsel(config_bits: int, rcvsel: str) -> int:
    v = _norm_text(rcvsel).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_RCV_SEL
    elif v == "ENABLE":
        new_bits = config_bits | CFG_RCV_SEL
    else:
        return ERR_RCV_SEL
    return new_bits

def get_rcvsel(config_bits: int) -> str:
    checker = config_bits & CFG_RCV_SEL
    checker = (checker // CFG_RCV_SEL) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

def set_has_eqos(config_bits: int) -> int:
    return config_bits | CFG_HAS_EQOS

def get_has_eqos(config_bits: int) -> int:
    checker = config_bits & CFG_HAS_EQOS
    checker = (checker // CFG_HAS_EQOS) % 2
    return checker

def set_eqos(config_bits: int, eqos: str) -> int:
    v = _norm_text(eqos).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_EQOS
    elif v == "ENABLE":
        new_bits = config_bits | CFG_EQOS
    else:
        return ERR_EQOS
    return new_bits

def get_eqos(config_bits: int) -> str:
    checker = config_bits & CFG_EQOS
    checker = (checker // CFG_EQOS) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"

# --- Main Computation Function ---

def compute_pin_macros(
    *,
    usage: str,
    function: str,
    pull_val: int,
    tristate_val: int,
    ein_val: int,
    drv_val: int,
    lock_en: bool,
    od_en: bool,
    ddc_en: bool,
    haseqos: bool,
    rcvsel_val: int,
    eqos_val: int,
    node_name: str,
) -> Dict[str, Any]:
    """
    Compute DTS macros for a single pin, using a ConfigBits bitfield
    that mimics the original Excel/VBA generator.
    """

    # 1) Build ConfigBits bitfield
    config_bits = 0

    # Pull up/down
    pupd_str = {0: "NORMAL", 1: "PULL_DOWN", 2: "PULL_UP"}.get(pull_val, "NORMAL")
    config_bits = set_pull(config_bits, pupd_str)

    # Tristate
    tri_str = "TRISTATE" if tristate_val else "NORMAL"
    config_bits = set_tristate(config_bits, tri_str)

    # Enable-input
    ein_str = "ENABLE" if ein_val else "DISABLE"
    config_bits = set_einput(config_bits, ein_str)

    # Open Drain
    if od_en:
        config_bits = set_od(config_bits, "ENABLE")

    # Lock
    lock_str = "ENABLE" if lock_en else "DISABLE"
    config_bits = set_lock(config_bits, lock_str)

    # Drive Strength (LPDR)
    lpdr_str = {0: "DISABLE", 1: "ENABLE", 2: "DEF_1X", 3: "DEF_2X"}.get(drv_val, "DISABLE")
    config_bits = set_lpdr(config_bits, lpdr_str)

    # DDC + RCVSEL
    if ddc_en:
        config_bits = set_ddc(config_bits)
        rcvsel_str = "ENABLE" if rcvsel_val else "DISABLE"
        config_bits = set_rcvsel(config_bits, rcvsel_str)

    # EQOS
    if haseqos:
        config_bits = set_has_eqos(config_bits)
        eqos_str = "ENABLE" if eqos_val else "DISABLE"
        config_bits = set_eqos(config_bits, eqos_str)

    # 2) Decode macros from ConfigBits via VBA-style Get* helpers
    pull_macro     = get_pull(config_bits)
    tristate_macro = get_tristate(config_bits)
    einput_macro   = get_einput(config_bits)
    drv_macro      = get_lpdr(config_bits)
    lock_macro     = get_lock(config_bits)
    od_macro       = get_od(config_bits)

    eio_macro: Optional[str]
    if get_ddc(config_bits):
        eio_macro = get_rcvsel(config_bits)
    else:
        eio_macro = None

    elpbk_macro: Optional[str]
    if get_has_eqos(config_bits):
        elpbk_macro = get_eqos(config_bits)
    else:
        elpbk_macro = None

    return {
        "pull":         pull_macro,
        "tristate":     tristate_macro,
        "enable_input": einput_macro,
        "drv_type":     drv_macro,
        "lock":         (lock_macro == "TEGRA_PIN_ENABLE"),
        "open_drain":   (od_macro == "TEGRA_PIN_ENABLE"),
        "eio":          eio_macro,
        "elpbk":        elpbk_macro,
    }

