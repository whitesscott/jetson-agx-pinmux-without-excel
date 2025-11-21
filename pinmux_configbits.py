#!/usr/bin/env python3
"""
pinmux_configbits.py

ConfigBits-style DTS macro computation for Jetson Thor pinmux.

This module reimplements, in Python, the Excel/VBA "ConfigBits"
bitfield logic from Generate_Device_Tree.bas, so the resulting
macros match what the original XLSM generator would produce
as closely as possible.

It exposes a single high-level function:

    compute_pin_macros(...)

which mirrors the *effective behavior* of the VBA sequence:

    ConfigBits = 0
    ConfigBits = SetPull(ConfigBits,   PUPD)
    ConfigBits = SetTristate(ConfigBits, Tristate)
    ConfigBits = SetEInput(ConfigBits,   EInput)
    ...
    ' RCV_SEL / DDC, OD, Lock, LPDR, EQOS, etc.
    ...
    pull      = GetPull(ConfigBits)
    tristate  = GetTristate(ConfigBits)
    einput    = GetEInput(ConfigBits)
    drvtype   = GetLPDR(ConfigBits)
    lock      = GetLock(ConfigBits)
    od        = GetOD(ConfigBits)
    eio       = GetRCVSEL(ConfigBits)  (when GetDDC(ConfigBits) = 1)
    elpbk     = GetEQOS(ConfigBits)    (when GetHasEQOS(ConfigBits) = 1)

The intent is that gen_pinmux_dt_from_xlsx.py (or similar code)
can call compute_pin_macros() instead of doing its own string
mapping, and achieve XLSM-equivalent output.
"""

from __future__ import annotations

from dataclasses import dataclass
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
# CFG_HAS_LPDR = 512       # unused in current VBA
# CFG_LPDR     = 1024      # unused in current VBA
CFG_HAS_EQOS  = 2048
CFG_EQOS      = 4096
CFG_DRV_1X    = 512
CFG_DEF_1X    = 1024


# Simple error sentinels mirroring ERR_* in VBA. We normally
# avoid returning these by validating inputs before calling
# Set* helpers, but they are kept for completeness.
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


# --- Low-level Set* helpers (bitfield mutators) ---

def set_pull(config_bits: int, pupd: str) -> int:
    r"""
    VBA SetPull:

        If PUPD = "NORMAL"     -> clear PULL_UP and PULL_DOWN
        If PUPD = "PULL_DOWN"  -> set PULL_DOWN, clear PULL_UP
        If PUPD = "PULL_UP"    -> set PULL_UP,   clear PULL_DOWN
    """
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
    r"""
    VBA GetPull:

        CheckerNumber = (ConfigBits And (CFG_PULL_UP Or CFG_PULL_DOWN))
        CheckerNumber = (CheckerNumber \ CFG_PULL_DOWN) Mod 4

        0 -> TEGRA_PIN_PULL_NONE
        1 -> TEGRA_PIN_PULL_DOWN
        2 -> TEGRA_PIN_PULL_UP
    """
    checker = config_bits & (CFG_PULL_UP | CFG_PULL_DOWN)
    checker = (checker // CFG_PULL_DOWN) % 4
    if checker > 2:
        checker = ERR_PULL

    if checker == 0:
        return "TEGRA_PIN_PULL_NONE"
    elif checker == 1:
        return "TEGRA_PIN_PULL_DOWN"
    elif checker == 2:
        return "TEGRA_PIN_PULL_UP"
    else:
        # propagate numeric error
        return str(checker)


def set_tristate(config_bits: int, tristate: str) -> int:
    r"""
    VBA SetTristate:

        "NORMAL"   -> clear CFG_TRISTATE
        "TRISTATE" -> set   CFG_TRISTATE
    """
    v = _norm_text(tristate).upper()
    if v == "NORMAL" or v == "":
        new_bits = config_bits & ~CFG_TRISTATE
    elif v == "TRISTATE":
        new_bits = config_bits | CFG_TRISTATE
    else:
        return ERR_TRISTATE
    return new_bits


def get_tristate(config_bits: int) -> str:
    r"""
    VBA GetTristate:

        CheckerNumber = (ConfigBits And CFG_TRISTATE) \ CFG_TRISTATE Mod 2
        0 -> DISABLE, 1 -> ENABLE
    """
    checker = config_bits & CFG_TRISTATE
    checker = (checker // CFG_TRISTATE) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


def set_einput(config_bits: int, einput: str) -> int:
    """
    VBA SetEInput:

        "DISABLE" -> clear CFG_E_INPUT
        "ENABLE"  -> set   CFG_E_INPUT
    """
    v = _norm_text(einput).upper()
    if v == "DISABLE" or v == "":
        new_bits = config_bits & ~CFG_E_INPUT
    elif v == "ENABLE":
        new_bits = config_bits | CFG_E_INPUT
    else:
        return ERR_E_INPUT
    return new_bits


def get_einput(config_bits: int) -> str:
    """
    VBA GetEInput:

        0 -> DISABLE, 1 -> ENABLE
    """
    checker = config_bits & CFG_E_INPUT
    checker = (checker // CFG_E_INPUT) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


def set_od(config_bits: int, od: str) -> int:
    """
    VBA SetOD:

        "ENABLE" -> set CFG_OD
        anything else -> clear CFG_OD
    """
    v = _norm_text(od).upper()
    if v == "ENABLE":
        return config_bits | CFG_OD
    else:
        return config_bits & ~CFG_OD


def get_od(config_bits: int) -> str:
    """
    VBA GetOD:

        0 -> DISABLE, 1 -> ENABLE
    """
    checker = config_bits & CFG_OD
    checker = (checker // CFG_OD) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


def set_lock(config_bits: int, locked: str) -> int:
    """
    VBA SetLock:

        "DISABLE" or "" -> clear CFG_LOCK
        "ENABLE"        -> set   CFG_LOCK

    Note: the original VBA used "Disable"/"Enable" with that exact
    capitalization; here we upper() and normalize.
    """
    v = _norm_text(locked).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_LOCK
    elif v == "ENABLE":
        new_bits = config_bits | CFG_LOCK
    else:
        return ERR_LOCK
    return new_bits


def get_lock(config_bits: int) -> str:
    """
    VBA GetLock:

        0 -> TEGRA_PIN_DISABLE
        1 -> TEGRA_PIN_ENABLE
    """
    checker = config_bits & CFG_LOCK
    checker = (checker // CFG_LOCK) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


def set_lpdr(config_bits: int, lpdr: str) -> int:
    """
    VBA SetLPDR:

        "DISABLE" -> clear CFG_DEF_1X and CFG_DRV_1X
        "ENABLE"  -> set   CFG_DRV_1X, clear CFG_DEF_1X
        "DEF_1X"  -> set   CFG_DEF_1X, clear CFG_DRV_1X
        "DEF_2X"  -> set   CFG_DEF_1X and CFG_DRV_1X
    """
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
    r"""
    VBA GetLPDR:

        CheckerNumber = (ConfigBits And (CFG_DRV_1X Or CFG_DEF_1X))
        CheckerNumber = (CheckerNumber \ CFG_DRV_1X) Mod 4

        0 -> TEGRA_PIN_1X_DRIVER
        1 -> TEGRA_PIN_2X_DRIVER
        2 -> TEGRA_PIN_DEFAULT_DRIVE_1X
        3 -> TEGRA_PIN_DEFAULT_DRIVE_2X
    """
    checker = config_bits & (CFG_DRV_1X | CFG_DEF_1X)
    checker = (checker // CFG_DRV_1X) % 4
    if checker > 3:
        checker = ERR_LPDR

    if checker == 0:
        return "TEGRA_PIN_1X_DRIVER"
    elif checker == 1:
        return "TEGRA_PIN_2X_DRIVER"
    elif checker == 2:
        return "TEGRA_PIN_DEFAULT_DRIVE_1X"
    elif checker == 3:
        return "TEGRA_PIN_DEFAULT_DRIVE_2X"
    else:
        return "TEGRA_PIN_COMP"


def set_ddc(config_bits: int) -> int:
    """
    VBA SetDDC simply ORs CFG_DDC.
    """
    return config_bits | CFG_DDC


def get_ddc(config_bits: int) -> int:
    r"""
    VBA GetDDC:

        (ConfigBits And CFG_DDC) \ CFG_DDC Mod 2
        returns 0 or 1
    """
    checker = config_bits & CFG_DDC
    checker = (checker // CFG_DDC) % 2
    return checker


def set_rcvsel(config_bits: int, rcvsel: str) -> int:
    """
    VBA SetRCVSEL:

        "DISABLE" -> clear CFG_RCV_SEL
        "ENABLE"  -> set   CFG_RCV_SEL
    """
    v = _norm_text(rcvsel).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_RCV_SEL
    elif v == "ENABLE":
        new_bits = config_bits | CFG_RCV_SEL
    else:
        return ERR_RCV_SEL
    return new_bits


def get_rcvsel(config_bits: int) -> str:
    """
    VBA GetRCVSEL:

        0 -> TEGRA_PIN_DISABLE
        1 -> TEGRA_PIN_ENABLE
    """
    checker = config_bits & CFG_RCV_SEL
    checker = (checker // CFG_RCV_SEL) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


def set_has_eqos(config_bits: int) -> int:
    """
    VBA SetHasEQOS simply ORs CFG_HAS_EQOS.
    """
    return config_bits | CFG_HAS_EQOS


def get_has_eqos(config_bits: int) -> int:
    r"""
    VBA GetHasEQOS:

        (ConfigBits And CFG_HAS_EQOS) \ CFG_HAS_EQOS Mod 2
        returns 0 or 1
    """
    checker = config_bits & CFG_HAS_EQOS
    checker = (checker // CFG_HAS_EQOS) % 2
    return checker


def set_eqos(config_bits: int, eqos: str) -> int:
    """
    VBA SetEQOS:

        "DISABLE" -> clear CFG_EQOS
        "ENABLE"  -> set   CFG_EQOS
    """
    v = _norm_text(eqos).upper()
    if v in ("DISABLE", ""):
        new_bits = config_bits & ~CFG_EQOS
    elif v == "ENABLE":
        new_bits = config_bits | CFG_EQOS
    else:
        return ERR_EQOS
    return new_bits


def get_eqos(config_bits: int) -> str:
    """
    VBA GetEQOS:

        0 -> TEGRA_PIN_DISABLE
        1 -> TEGRA_PIN_ENABLE
    """
    checker = config_bits & CFG_EQOS
    checker = (checker // CFG_EQOS) % 2
    if checker == 0:
        return "TEGRA_PIN_DISABLE"
    else:
        return "TEGRA_PIN_ENABLE"


# --- High-level API ---------------------------------------------------------

@dataclass
class PinConfigInputs:
    """
    High-level configuration inputs for a single pin.

    These are *not* raw Excel cells, but they are chosen so they
    can be easily derived from the Thor pinmux sheet.

    Fields:

        usage       - Customer Usage / SFIO function (string, optional)
        function    - Function name (often same as usage)
        pull_val    - integer 0/1/2 (0=NONE/NORMAL, 1=PULL_DOWN, 2=PULL_UP)
        tristate_val- integer 0/1   (0=NORMAL/DISABLE, 1=TRISTATE/ENABLE)
        ein_val     - integer 0/1   (0=DISABLE, 1=ENABLE)
        drv_val     - integer 0..3  (0=DISABLE, 1=ENABLE, 2=DEF_1X, 3=DEF_2X)
        lock_en     - bool          (True=lock ENABLE, False=DISABLE)
        od_en       - bool          (True=open-drain ENABLE)
        ddc_en      - bool          (True=3.3V tolerance / DDC present)
        haseqos     - bool          (True=EQOS LPBK present)
        rcvsel_val  - integer 0/1   (0=DISABLE, 1=ENABLE) for RCV_SEL
        eqos_val    - integer 0/1   (0=DISABLE, 1=ENABLE) for EQOS
        node_name   - DTS node name (for future per-pin tweaks; may be "")
    """
    usage: str = ""
    function: str = ""
    pull_val: int = 0
    tristate_val: int = 0
    ein_val: int = 0
    drv_val: int = 0
    lock_en: bool = False
    od_en: bool = False
    ddc_en: bool = False
    haseqos: bool = False
    rcvsel_val: int = 0
    eqos_val: int = 0
    node_name: str = ""


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

    All integer fields mirror the "Filled in by Customers" encoding
    you were using previously in pinmux_configbits.py:

        pull_val:    0 -> NORMAL / NONE
                     1 -> PULL_DOWN
                     2 -> PULL_UP

        tristate_val:0 -> NORMAL / DISABLE
                     non-zero -> TRISTATE / ENABLE

        ein_val:     0 -> DISABLE
                     non-zero -> ENABLE

        drv_val:     0 -> "DISABLE"  (TEGRA_PIN_1X_DRIVER)
                     1 -> "ENABLE"   (TEGRA_PIN_2X_DRIVER)
                     2 -> "DEF_1X"   (TEGRA_PIN_DEFAULT_DRIVE_1X)
                     3 -> "DEF_2X"   (TEGRA_PIN_DEFAULT_DRIVE_2X)

        lock_en:     True  -> lock = ENABLE
                     False -> lock = DISABLE

        od_en:       True  -> open-drain = ENABLE

        ddc_en:      True  -> DDC/RCVSEL present; emit e-io-od
                     False -> no e-io-od property

        haseqos:     True  -> EQOS present; emit e-lpbk
                     False -> no e-lpbk property

        rcvsel_val:  0 -> RCV_SEL = DISABLE
                     non-zero -> RCV_SEL = ENABLE

        eqos_val:    0 -> EQOS = DISABLE
                     non-zero -> EQOS = ENABLE

    Returns a dict:

        {
            "pull":        "TEGRA_PIN_PULL_*",
            "tristate":    "TEGRA_PIN_*",
            "enable_input":"TEGRA_PIN_*",
            "drv_type":    "TEGRA_PIN_*",
            "lock":        bool,   # True if nvidia,lock should be emitted
            "open_drain":  bool,   # True if nvidia,open-drain should be emitted
            "eio":         Optional[str],  # None => don't emit e-io-od
            "elpbk":       Optional[str],  # None => don't emit e-lpbk
        }
    """
    cfg = PinConfigInputs(
        usage=usage,
        function=function,
        pull_val=pull_val,
        tristate_val=tristate_val,
        ein_val=ein_val,
        drv_val=drv_val,
        lock_en=lock_en,
        od_en=od_en,
        ddc_en=ddc_en,
        haseqos=haseqos,
        rcvsel_val=rcvsel_val,
        eqos_val=eqos_val,
        node_name=node_name,
    )

    # 1) Build ConfigBits bitfield
    config_bits = 0

    # Pull up/down (PUPD column)
    pupd_str = {
        0: "NORMAL",
        1: "PULL_DOWN",
        2: "PULL_UP",
    }.get(cfg.pull_val, "NORMAL")
    config_bits = set_pull(config_bits, pupd_str)

    # Tristate (TRISTATE column)
    tri_str = "TRISTATE" if cfg.tristate_val else "NORMAL"
    config_bits = set_tristate(config_bits, tri_str)

    # Enable-input (E_INPUT column)
    ein_str = "ENABLE" if cfg.ein_val else "DISABLE"
    config_bits = set_einput(config_bits, ein_str)

    # OD – the VBA uses Pin Direction == "Open-Drain" to decide this.
    # Here we expose od_en directly as a boolean.
    if cfg.od_en:
        config_bits = set_od(config_bits, "ENABLE")

    # Lock
    lock_str = "ENABLE" if cfg.lock_en else "DISABLE"
    config_bits = set_lock(config_bits, lock_str)

    # LPDR / drive strength (0..3)
    lpdr_str = {
        0: "DISABLE",
        1: "ENABLE",
        2: "DEF_1X",
        3: "DEF_2X",
    }.get(cfg.drv_val, "DISABLE")
    config_bits = set_lpdr(config_bits, lpdr_str)

    # DDC + RCVSEL (3.3V tolerance)
    if cfg.ddc_en:
        config_bits = set_ddc(config_bits)
        rcvsel_str = "ENABLE" if cfg.rcvsel_val else "DISABLE"
        config_bits = set_rcvsel(config_bits, rcvsel_str)

    # EQOS
    if cfg.haseqos:
        config_bits = set_has_eqos(config_bits)
        eqos_str = "ENABLE" if cfg.eqos_val else "DISABLE"
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

    # Future place for special per-pin overrides if needed.
    # (For now we keep everything purely ConfigBits-driven.)

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


if __name__ == "__main__":
    # Tiny self-test / demonstration.
    # This is *not* exhaustive, but it gives a quick sanity check that
    # the bitfield flows through Set*/Get* as expected.
    demo = compute_pin_macros(
        usage="I2C_SCL",
        function="i2c_scl",
        pull_val=2,          # PULL_UP
        tristate_val=1,      # TRISTATE
        ein_val=1,           # enable input
        drv_val=1,           # 2X
        lock_en=True,
        od_en=False,
        ddc_en=True,
        haseqos=True,
        rcvsel_val=1,
        eqos_val=0,
        node_name="demo_node",
    )
    for k, v in demo.items():
        print(f"{k}: {v}")
