#!/usr/bin/env python3
"""
Shared pinmux validator for Jetson Thor.

- Reads Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm
- Sheet: "Jetson Thor_DevKit"
- Rows: 13..479
- Provides: validate_pin_by_node(node_name) -> (errors, warnings)

Updates:
- Incorporated VBA logic for Resistor conflicts, Initial State validation,
  Wake validation, and RCV_SEL (3.3V tolerance) checks.
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SHEET_NAME = "Jetson Thor_DevKit"
ROW_DATA_START = 13
ROW_DATA_END = 479

# Hard-coded path; adjust if needed.
WORKBOOK_PATH = Path("Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm")

def col_to_idx_1b(col_letters: str) -> int:
    acc = 0
    for ch in col_letters.strip().upper():
        if "A" <= ch <= "Z":
            acc = acc * 26 + (ord(ch) - ord("A") + 1)
    return acc

# Column Mappings (Based on Template v1.4 standard layout)
COL_A_PINNUM      = col_to_idx_1b("A")
COL_B_SIGNAL      = col_to_idx_1b("B")
COL_C_MPIO        = col_to_idx_1b("C")
COL_L_ALLOWED_DIR = col_to_idx_1b("L")

# User Configuration Columns
COL_AS_USAGE      = col_to_idx_1b("AS") # Customer Usage
COL_AT_PIN_DIR    = col_to_idx_1b("AT") # Pin Direction
COL_AU_INIT_STATE = col_to_idx_1b("AU") # Req. Initial State (used for Int PU/PD checks)
COL_AV_WAKE       = col_to_idx_1b("AV") # Wake Pin
COL_AX_E_IO_OD    = col_to_idx_1b("AX") # E_IO_OD / 3.3V Tolerance
COL_BC_EXT_PU     = col_to_idx_1b("BC") # Ext Pull Up Value
COL_BD_EXT_PD     = col_to_idx_1b("BD") # Ext Pull Down Value


def _st(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _read_sheet_xml_and_shared(xlsx_path: Path):
    with zipfile.ZipFile(xlsx_path) as z:
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
        name_to_rid = {}
        for s in wb_xml.iter():
            if _st(s.tag) == "sheet":
                nm = s.attrib.get("name")
                rid = s.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                if nm and rid:
                    name_to_rid[nm] = rid
        if SHEET_NAME not in name_to_rid:
            raise RuntimeError(f"Sheet {SHEET_NAME!r} not found in workbook.")

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {}
        for r in rels.iter():
            if _st(r.tag) == "Relationship":
                rid_to_target[r.attrib["Id"]] = r.attrib["Target"]

        target = rid_to_target[name_to_rid[SHEET_NAME]]
        sheet_xml = ET.fromstring(z.read(f"xl/{target}"))

        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst.iter():
                if _st(si.tag) == "si":
                    parts = []
                    for t in si.iter():
                        if _st(t.tag) == "t" and t.text is not None:
                            parts.append(t.text)
                    shared.append("".join(parts))
    return sheet_xml, shared


def _read_cells(sheet_xml, shared_strings, row_min, row_max):
    vals = {}
    for c in sheet_xml.iter():
        if _st(c.tag) != "c":
            continue
        r = c.attrib.get("r")
        if not r:
            continue
        m = re.match(r"([A-Z]+)(\d+)$", r)
        if not m:
            continue
        col_letters, row_s = m.group(1), m.group(2)
        row = int(row_s)
        if row < row_min or row > row_max:
            continue
        col_idx = col_to_idx_1b(col_letters)

        t = c.attrib.get("t")
        v_node = c.find("{*}v")
        v = None
        if v_node is not None and v_node.text is not None:
            v = v_node.text
            if t == "s":
                try:
                    v = shared_strings[int(v)]
                except Exception:
                    pass
        else:
            is_node = c.find("{*}is/{*}t")
            if is_node is not None and is_node.text is not None:
                v = is_node.text

        vals[(row, col_idx)] = v
    return vals


def _norm_text(v):
    return "" if v is None else str(v).strip()


def _norm_dir(v):
    # Handle Not_Assigned / not assigned / N/A all as "none".
    s = _norm_text(v).lower().replace("_", " ")
    if s in ("", "n/a", "na", "not assigned", "none"):
        return "none"
    if s in ("i", "input", "in"):
        return "input"
    if s in ("o", "output", "out"):
        return "output"
    if s in ("io", "i/o", "bidir", "bidirectional", "in/out"):
        return "bidir"
    return s


def _norm_allowed_dir(v):
    s = _norm_text(v).lower()
    if s in ("i", "input"):
        return "input"
    if s in ("o", "output"):
        return "output"
    if s in ("io", "i/o", "bidir", "bidirectional", "in/out"):
        return "bidir"
    if s == "":
        return "any"
    return s


def _is_wake_enabled(v):
    s = _norm_text(v).lower()
    if s in ("", "n/a", "na", "none"):
        return False
    if s in ("enable", "enabled", "yes", "y", "1", "true"):
        return True
    if s in ("disable", "disabled", "no", "n", "0", "false"):
        return False
    return True

_INDEX = None   # node_name_l -> row_idx
_CELLS = None   # dict[(row, col_idx)] -> value
_DT_COL = None  # column index for "Device Tree Pin Name"


def _build_index():
    global _INDEX, _CELLS, _DT_COL
    if _INDEX is not None:
        return
    if not WORKBOOK_PATH.exists():
        raise RuntimeError(f"Pinmux workbook not found at {WORKBOOK_PATH}")

    sheet_xml, shared = _read_sheet_xml_and_shared(WORKBOOK_PATH)
    _CELLS = _read_cells(sheet_xml, shared, ROW_DATA_START, ROW_DATA_END)

    # Find Device Tree Pin Name column index from header row 7
    header = _read_cells(sheet_xml, shared, row_min=7, row_max=7)
    dt_col_idx = None
    for (r, c), v in header.items():
        if isinstance(v, str) and v.strip() == "Device Tree Pin Name":
            dt_col_idx = c
            break
    if dt_col_idx is None:
        dt_col_idx = col_to_idx_1b("U")  # fallback
    _DT_COL = dt_col_idx

    idx = {}
    for r in range(ROW_DATA_START, ROW_DATA_END + 1):
        dt_pin = _CELLS.get((r, _DT_COL))
        mpio   = _CELLS.get((r, COL_C_MPIO))
        pin = _norm_text(dt_pin or mpio)
        if not pin:
            continue
        idx[pin.lower()] = r

    _INDEX = idx


def validate_pin_by_node(node_name: str):
    """
    Given a DTS node name (e.g. 'sf_pwr_soc_en'), look up the corresponding
    row in the pinmux workbook and apply validation logic mirroring the VBA.
    """
    _build_index()
    node_l = node_name.strip().lower()
    if node_l not in _INDEX:
        return [f"Node '{node_name}' not found in pinmux workbook index."], []

    row = _INDEX[node_l]
    cells = _CELLS

    # Fetch Cell Values
    pin_num   = _norm_text(cells.get((row, COL_A_PINNUM)))
    signal    = _norm_text(cells.get((row, COL_B_SIGNAL)))
    mpio      = _norm_text(cells.get((row, COL_C_MPIO)))

    usage_raw = cells.get((row, COL_AS_USAGE))
    allow_raw = cells.get((row, COL_L_ALLOWED_DIR))
    dir_raw   = cells.get((row, COL_AT_PIN_DIR))
    wake_raw  = cells.get((row, COL_AV_WAKE))
    init_raw  = cells.get((row, COL_AU_INIT_STATE)) # Req. Initial State
    ext_pu    = _norm_text(cells.get((row, COL_BC_EXT_PU)))
    ext_pd    = _norm_text(cells.get((row, COL_BD_EXT_PD)))
    eio_od    = _norm_text(cells.get((row, COL_AX_E_IO_OD))) # RCV_SEL check

    # Normalize basic fields
    usage   = _norm_text(usage_raw)
    usage_l = usage.lower()
    allow   = _norm_allowed_dir(allow_raw)
    pin_dir = _norm_dir(dir_raw)
    wake_on = _is_wake_enabled(wake_raw)
    init_st = _norm_text(init_raw)

    label = f"row {row} (Pin {pin_num or '?'}, {signal or '?'}, {mpio or '?'})"
    errs = []

    # --- 1. IsCustomerUsageNotBlank ---
    if usage == "":
        errs.append(f"{label}: Customer Usage (AS) cannot be blank.")

    # --- 2. IsPinDirectionValid ---
    # "Error Check: A pin direction should not be set for an unused pin."
    if usage_l.startswith("unused_") and pin_dir != "none":
        errs.append(f"{label}: Cannot assign a pin direction ('{dir_raw}') for an unused pin.")

    # Check allowed direction vs selected direction
    if allow == "input" and pin_dir not in ("none", "input"):
        errs.append(f"{label}: Allowed direction is INPUT, but set to '{dir_raw}'.")
    elif allow == "output" and pin_dir not in ("none", "output"):
        errs.append(f"{label}: Allowed direction is OUTPUT, but set to '{dir_raw}'.")
    # Note: VBA logic for 'bidir' allows input/output, handled by nature of drop-downs usually.

    # --- 3. IsWakeValid ---
    if wake_on:
        if usage_l.startswith("unused_"):
            errs.append(f"{label}: Wake cannot be enabled on an Unused Pin.")

        if pin_dir == "output":
            errs.append(f"{label}: Wake cannot be enabled on an Output pin.")
        elif pin_dir == "none":
            errs.append(f"{label}: Wake cannot be enabled on an Unassigned pin.")

    # --- 4. IsResistorConfigurationGood ---
    # "Internal pull up cannot be enabled if there is an external pull up/down."
    if init_st == "Int PU":
        if ext_pu != "":
            errs.append(f"{label}: Internal PU cannot be enabled if there is an external PU ({ext_pu}).")
        if ext_pd != "":
            errs.append(f"{label}: Internal PU cannot be enabled if there is an external PD ({ext_pd}).")
    elif init_st == "Int PD":
        if ext_pu != "":
            errs.append(f"{label}: Internal PD cannot be enabled if there is an external PU ({ext_pu}).")
        if ext_pd != "":
            errs.append(f"{label}: Internal PD cannot be enabled if there is an external PD ({ext_pd}).")

    # --- 5. IsInitialStateValid ---
    # "Initial State for an Unused Pin cannot be assigned" (except Z or N/A)
    if usage_l.startswith("unused_"):
        if init_st not in ("", "Z", "N/A", "n/a"):
            errs.append(f"{label}: Initial State for an Unused Pin cannot be assigned to '{init_st}'.")

    # --- 6. IsRCVSELValid (3.3V Tolerance) ---
    # E_IO_OD column often maps to "3.3V Tolerance" or RCV_SEL in these templates.
    if eio_od.lower() == "enable" and usage_l.startswith("unused_"):
        errs.append(f"{label}: 3.3V Tolerance (RCV_SEL) cannot be enabled on an Unused Pin.")

    return errs, []


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("node", help="DTS node name, e.g. sf_pwr_soc_en")
    args = ap.parse_args()
    e, w = validate_pin_by_node(args.node)
    for x in e:
        print("[ERROR]", x)
    if not e:
        print("OK.")
