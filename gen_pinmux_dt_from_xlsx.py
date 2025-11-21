#!/usr/bin/env python3
"""
Generate DTS pinmux from Jetson Thor pinmux template (.xlsm/.xlsx).

Integrates logic inspired by generate_pinmux.py and the original
Excel/VBA "ConfigBits" engine.

Updates:
- Uses safe_function_logic.py to determine default pin function (RSVD logic).
- Validates 'Customer Usage' against available functions (F0-F3). 
  If Usage is invalid (e.g. "GPIO3_PH.06"), falls back to Safe Function.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Tuple, List

from openpyxl import load_workbook

# ConfigBits-style macro computation
try:
    from pinmux_configbits import compute_pin_macros
except ImportError:
    # Fallback mock if file missing during partial testing
    print("Warning: pinmux_configbits not found. Using dummy.")
    def compute_pin_macros(**kwargs): return {"pull": "0", "tristate": "0", "enable_input": "0", "drv_type": "0", "lock": False, "open_drain": False, "eio": None, "elpbk": None}

# Safe Function Logic (VBA Port)
try:
    from safe_function_logic import get_safe_function_name
except ImportError:
    print("Warning: safe_function_logic not found. Defaulting to simple fallback.")
    def get_safe_function_name(funcs): return funcs[0] if funcs else ""


# Normalization & mapping helpers
def _norm_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_upper(v) -> str:
    return _norm_str(v).upper()


# Header row discovery & column mapping
def find_header_rows(ws) -> Tuple[int, int]:
    """
    Find:
      - hdr_row: the row containing 'Pin #', 'Signal Name', 'MPIO'
      - labels_row: the row just above hdr_row, containing semantic titles
    """
    max_row = ws.max_row
    for r in range(1, max_row + 1):
        a = _norm_str(ws.cell(row=r, column=1).value)
        b = _norm_str(ws.cell(row=r, column=2).value)
        c = _norm_str(ws.cell(row=r, column=3).value)
        if a == "Pin #" and b == "Signal Name" and c == "MPIO":
            hdr_row = r
            labels_row = r - 1
            if labels_row < 1:
                raise RuntimeError(
                    "Found 'Pin # / Signal Name / MPIO' at row 1; "
                    "cannot locate labels row above."
                )
            return hdr_row, labels_row

    raise RuntimeError("Could not find 'Pin # / Signal Name / MPIO' header row.")


def build_column_map(ws, labels_row: int) -> Dict[str, int]:
    """
    Build a semantic column map from the label row.
    Now includes Safe Function determination and validation.
    """
    col_map: Dict[str, int] = {}

    max_col = ws.max_column
    for c in range(1, max_col + 1):
        title = ws.cell(row=labels_row, column=c).value
        t = _norm_str(title)

        if t == "Device Tree Pin Name":
            col_map["dt_name"] = c
        elif t == "Customer Usage":
            col_map["cust_usage"] = c
        elif t == "Pin Direction":
            col_map["pin_dir"] = c
        elif t == "Req. Initial State":
            col_map["init_state"] = c
        elif t == "Lock":
            col_map["lock"] = c
        elif t.startswith("E_IO_OD"):
            col_map["eio_od"] = c
        elif t.startswith("DRV_TYPE"):
            col_map["drv_type"] = c
        elif t.startswith("E_LPBK"):
            col_map["elpbk"] = c
        elif t == "PUPD":
            col_map["pupd"] = c
        elif t == "Tristate":
            col_map["tristate"] = c
        elif t == "E_Input":
            col_map["einput"] = c
        # Function columns for VBA Logic fallback/validation
        elif t == "F0":
            col_map["f0"] = c
        elif t == "F1":
            col_map["f1"] = c
        elif t == "F2":
            col_map["f2"] = c
        elif t == "F3":
            col_map["f3"] = c

    # Pin # / Signal Name / MPIO come from the header row itself (row below labels)
    col_map.setdefault("pin_num", 1)
    col_map.setdefault("signal_name", 2)
    col_map.setdefault("mpio", 3)

    required = [
        "dt_name",
        "pupd",
        "tristate",
        "einput",
        "cust_usage",
        "pin_dir",
        "eio_od",
        "drv_type",
    ]
    missing = [k for k in required if k not in col_map]
    if missing:
        raise RuntimeError(
            f"Missing required columns in labels row {labels_row}: {missing}"
        )

    return col_map


# DTS generation
def generate_pinmux(ws, hdr_row: int, labels_row: int) -> str:
    """
    Generate full DTS text.
    Returns: (dts_text, emitted_count)
    """
    col = build_column_map(ws, labels_row)

    first_data_row = hdr_row + 1
    last_row = ws.max_row

    lines = []

    # Excel-like includes at top
    lines.append('/* Auto-generated from Jetson Thor pinmux spreadsheet */')
    lines.append('#include "t264-pinctrl-tegra.h"')
    lines.append('#include "tegra264-gpio.h"')
    lines.append("")
    lines.append("/ {")
    lines.append('\tpinmux@ac281000 {')
    lines.append('\t\tpinctrl-names = "default", "drive", "unused";')
    lines.append('\t\tpinctrl-0 = <&pinmux_default>;')
    lines.append('\t\tpinctrl-1 = <&drive_default>;')
    lines.append('\t\tpinctrl-2 = <&pinmux_unused_lowpower>;')
    lines.append("")
    lines.append("\t\tpinmux_default: common {")
    lines.append("\t\t\t/* SFIO + GPIO Pin Configuration (auto-generated) */")

    emitted = 0

    for r in range(first_data_row, last_row + 1):
        dt_name = _norm_str(ws.cell(row=r, column=col["dt_name"]).value)
        if not dt_name:
            continue

        # Skip power-rail rows (e.g. VDDIO_SYS)
        if dt_name.upper().startswith("VDDIO_"):
            continue

        pin_num     = _norm_str(ws.cell(row=r, column=col["pin_num"]).value)
        signal_name = _norm_str(ws.cell(row=r, column=col["signal_name"]).value)
        mpio        = _norm_str(ws.cell(row=r, column=col["mpio"]).value)

        # Configuration fields
        usage       = _norm_str(ws.cell(row=r, column=col["cust_usage"]).value)
        pin_dir     = _norm_str(ws.cell(row=r, column=col["pin_dir"]).value)
        pupd        = _norm_str(ws.cell(row=r, column=col["pupd"]).value)
        tristate    = _norm_str(ws.cell(row=r, column=col["tristate"]).value)
        einput      = _norm_str(ws.cell(row=r, column=col["einput"]).value)
        drv         = _norm_str(ws.cell(row=r, column=col["drv_type"]).value)
        lock        = _norm_str(ws.cell(row=r, column=col.get("lock", 0)).value) if "lock" in col else "Disable"
        eio_od      = _norm_str(ws.cell(row=r, column=col["eio_od"]).value)
        elpbk       = _norm_str(ws.cell(row=r, column=col.get("elpbk", 0)).value) if "elpbk" in col else ""

        # --- Function Determination Logic (Updated Validation) ---

        # 1. Fetch all available functions for this pin
        f0 = _norm_str(ws.cell(row=r, column=col.get("f0", 0)).value)
        f1 = _norm_str(ws.cell(row=r, column=col.get("f1", 0)).value)
        f2 = _norm_str(ws.cell(row=r, column=col.get("f2", 0)).value)
        f3 = _norm_str(ws.cell(row=r, column=col.get("f3", 0)).value)

        # 2. Calculate the 'Safe' (Default) function regardless
        safe_func = get_safe_function_name([f0, f1, f2, f3])

        func_name = ""

        if usage:
            # 3. Validate Customer Usage against available options
            u_low = usage.lower()
            valid_options = [x.lower() for x in [f0, f1, f2, f3] if x]

            if u_low in valid_options:
                func_name = u_low
            else:
                # Usage is not a valid mux option (e.g. user entered "GPIO3_PH.06")
                # Fallback to Safe Function (which allows GPIO usage via RSVD)
                func_name = safe_func.lower()
        else:
            # Usage is empty, use Safe Function
            func_name = safe_func.lower()


        # Map spreadsheet text -> ConfigBits-style numeric/boolean fields
        # Pull: 0 = NORMAL/NONE, 1 = PULL_DOWN, 2 = PULL_UP
        pupd_u = _norm_upper(pupd)
        if pupd_u == "PULL_DOWN":
            pull_val = 1
        elif pupd_u == "PULL_UP":
            pull_val = 2
        else:
            pull_val = 0

        # Tristate: 0 = NORMAL/DISABLE, 1 = TRISTATE/ENABLE
        tristate_val = 1 if _norm_upper(tristate) == "TRISTATE" else 0

        # E_Input: 0 = DISABLE, 1 = ENABLE
        ein_val = 1 if _norm_upper(einput) == "ENABLE" else 0

        # DRV_TYPE: 0 = DISABLE, 1 = ENABLE, 2 = DEF_1X, 3 = DEF_2X
        drv_u = _norm_upper(drv)
        if drv_u == "ENABLE":
            drv_val = 1
        elif drv_u == "DEF_1X":
            drv_val = 2
        elif drv_u == "DEF_2X":
            drv_val = 3
        else:
            drv_val = 0

        # Lock
        lock_en = _norm_upper(lock) == "ENABLE"

        # OD: Excel's VBA uses Pin Direction "Open-Drain" or E_IO_OD
        pin_dir_u = _norm_upper(pin_dir)
        eio_u = _norm_upper(eio_od)
        od_en = (pin_dir_u == "OPEN-DRAIN") or (eio_u == "ENABLE")

        # DDC / RCVSEL
        ddc_en = eio_u in ("ENABLE", "DISABLE")
        rcvsel_val = 1 if eio_u == "ENABLE" else 0

        # EQOS / LPBK
        elpbk_u = _norm_upper(elpbk)
        haseqos = elpbk_u in ("ENABLE", "DISABLE")
        eqos_val = 1 if elpbk_u == "ENABLE" else 0

        node_name = dt_name.lower()
        pins_str  = dt_name.lower()

        # Compute macros via ConfigBits engine
        macros = compute_pin_macros(
            usage=func_name, # Passed for context
            function=func_name,
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

        pull_macro     = macros["pull"]
        tristate_macro = macros["tristate"]
        einput_macro   = macros["enable_input"]
        drv_macro      = macros["drv_type"]
        lock_flag      = macros["lock"]
        od_flag        = macros["open_drain"]
        eio_macro      = macros["eio"]
        elpbk_macro    = macros["elpbk"]


        # Emit DTS node for this pin
        if pin_num or signal_name:
            comment = f"/* Pin {pin_num or '?'} - {signal_name or '?'} ({mpio or ''}) */"
            lines.append(f"\t\t\t{comment}")

        lines.append(f"\t\t\t{node_name} {{")
        lines.append(f'\t\t\t\tnvidia,pins = "{pins_str}";')

        if func_name:
            lines.append(f'\t\t\t\tnvidia,function = "{func_name}";')

        lines.append(f"\t\t\t\tnvidia,pull = <{pull_macro}>;")
        lines.append(f"\t\t\t\tnvidia,tristate = <{tristate_macro}>;")
        lines.append(f"\t\t\t\tnvidia,enable-input = <{einput_macro}>;")
        lines.append(f"\t\t\t\tnvidia,drv-type = <{drv_macro}>;")

        if eio_macro is not None:
            lines.append(f"\t\t\t\tnvidia,e-io-od = <{eio_macro}>;")

        if elpbk_macro is not None:
            lines.append(f"\t\t\t\tnvidia,e-lpbk = <{elpbk_macro}>;")

        if lock_flag:
            lines.append("\t\t\t\tnvidia,lock = <TEGRA_PIN_ENABLE>;")

        if od_flag:
            lines.append("\t\t\t\tnvidia,open-drain = <TEGRA_PIN_ENABLE>;")

        lines.append("\t\t\t};")
        emitted += 1

    lines.append("\t\t};")
    lines.append("")
    lines.append("\t\tdrive_default: drive {")
    lines.append("\t\t};")
    lines.append("")
    lines.append("\t\tpinmux_unused_lowpower: unused_lowpower {")
    lines.append("\t\t};")
    lines.append("\t};")
    lines.append("};")

    return "\n".join(lines), emitted


def main():
    ap = argparse.ArgumentParser(
        description="Generate Jetson Thor pinmux DTS from .xlsm/.xlsx (Excel-style + ConfigBits)."
    )
    ap.add_argument("excel", help="Input .xlsm/.xlsx file (Thor pinmux template)")
    ap.add_argument(
        "-s", "--sheet",
        default="Jetson Thor_DevKit",
        help="Worksheet name (default: 'Jetson Thor_DevKit')",
    )
    ap.add_argument(
        "-o", "--out",
        default="pinmux-thor.dtsi",
        help="Output DTS filename (default: pinmux-thor.dtsi)",
    )
    args = ap.parse_args()

    wb = load_workbook(args.excel, data_only=True)
    if args.sheet in wb.sheetnames:
        ws = wb[args.sheet]
    else:
        ws = wb[wb.sheetnames[0]]

    hdr_row, labels_row = find_header_rows(ws)
    dts_text, count = generate_pinmux(ws, hdr_row, labels_row)

    out_path = Path(args.out)
    out_path.write_text(dts_text, encoding="utf-8")
    print(f"Wrote {out_path} with {count} pin blocks.")


if __name__ == "__main__":
    main()
