#!/usr/bin/env python3
"""
Shared pinmux validator for Jetson Thor.

- Reads Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm
- Sheet: "Jetson Thor_DevKit"
- Rows: 13..479
- Provides: validate_pin_by_node(node_name) -> (errors, warnings)
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

COL_A_PINNUM      = col_to_idx_1b("A")
COL_B_SIGNAL      = col_to_idx_1b("B")
COL_C_MPIO        = col_to_idx_1b("C")
COL_L_ALLOWED_DIR = col_to_idx_1b("L")
COL_AS_USAGE      = col_to_idx_1b("AS")
COL_AT_PIN_DIR    = col_to_idx_1b("AT")
COL_AU_TRISTATE   = col_to_idx_1b("AU")
COL_AV_WAKE       = col_to_idx_1b("AV")


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


def _as_int(v, default=0):
    try:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def _encode_tristate(val: int) -> str:
    # Match the generator’s encode_tristate() behavior:
    #  0 -> DISABLE, non-zero -> ENABLE
    return "TEGRA_PIN_ENABLE" if val else "TEGRA_PIN_DISABLE"

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
    row in the pinmux workbook and apply Excel-like validation:
      - Customer Usage present
      - unused_* rules
      - Allowed Pin Direction vs chosen direction
      - Wake vs direction
      - Special per-pin rules (e.g. EXTPERIPH2_CLK not tristated)
    Returns (errors, warnings), each a list of human-readable strings.
    """
    _build_index()
    node_l = node_name.strip().lower()
    if node_l not in _INDEX:
        return [f"Node '{node_name}' not found in pinmux workbook index."], []

    row = _INDEX[node_l]
    cells = _CELLS

    pin_num   = _norm_text(cells.get((row, COL_A_PINNUM)))
    signal    = _norm_text(cells.get((row, COL_B_SIGNAL)))
    mpio      = _norm_text(cells.get((row, COL_C_MPIO)))
    usage_raw = cells.get((row, COL_AS_USAGE))
    allow_raw = cells.get((row, COL_L_ALLOWED_DIR))
    dir_raw   = cells.get((row, COL_AT_PIN_DIR))
    wake_raw  = cells.get((row, COL_AV_WAKE))
    tri_raw   = cells.get((row, COL_AU_TRISTATE))

    # Normalize basic fields
    usage   = _norm_text(usage_raw)
    usage_l = usage.lower()
    allow   = _norm_allowed_dir(allow_raw)
    pin_dir = _norm_dir(dir_raw)
    wake_on = _is_wake_enabled(wake_raw)

    # tristate (AU)
    tri_val        = _as_int(tri_raw, 0)
    tristate_macro = _encode_tristate(tri_val)

    label = f"row {row} (Pin {pin_num or '?'}, {signal or '?'}, {mpio or '?'})"
    errs = []
    #warns = []

    # If tristate == ENABLE for this specific node, it's an error.
    if node_l == "extperiph2_clk_pk5" and tristate_macro == "TEGRA_PIN_ENABLE":
        errs.append(
            f"{label}: EXTPERIPH2_CLK must not be tristated (TEGRA_PIN_ENABLE)."
        )

    # Basic presence
    if usage == "":
        errs.append(f"{label}: Customer Usage (AS) is blank.")

    # unused_* rules
    if usage_l.startswith("unused_"):
        if pin_dir != "none":
            errs.append(
                f"{label}: usage '{usage}' is unused_* but Pin Direction is '{dir_raw}'."
            )
        if wake_on:
            errs.append(
                f"{label}: usage '{usage}' is unused_* but Wake is enabled."
            )

    # Allowed direction logic
    if allow != "any":
        if allow == "input":
            if pin_dir not in ("none", "input"):
                errs.append(
                    f"{label}: Allowed direction is INPUT-only, but Pin Direction is '{dir_raw}'."
                )
        elif allow == "output":
            if pin_dir not in ("none", "output"):
                errs.append(
                    f"{label}: Allowed direction is OUTPUT-only, but Pin Direction is '{dir_raw}'."
                )
        else allow == "bidir":
            if pin_dir not in ("none", "input", "output", "bidir"):
                errs.append(
                    f"{label}: Allowed direction is BIDIRECTIONAL, but Pin Direction is '{dir_raw}'."
                )

    # Wake rules
    if wake_on and not usage_l.startswith("unused_"):
        if pin_dir not in ("input", "bidir"):
            errs.append(
                f"{label}: Wake enabled but Pin Direction is '{dir_raw}' "
                "(only input/bidir pins should have wake)."
            )

    return errs


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("node", help="DTS node name, e.g. sf_pwr_soc_en")
    args = ap.parse_args()
    e, w = validate_pin_by_node(args.node)
    for x in e:
        print("[ERROR]", x)
    #for x in w:
        #print("[WARN ]", x)
    if not e:
        print("OK.")

