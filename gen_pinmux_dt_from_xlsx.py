#!/usr/bin/env python3
# Generate DTS from Jetson Thor pinmux template (.xlsm/.xlsx)
# Sheet: "Jetson Thor_DevKit"
# Pin name: Column C ("MPIO")
# Customer block: AS:BI, data rows 13..479

import argparse, re, xml.etree.ElementTree as ET
from pathlib import Path
import zipfile

SHEET_NAME = "Jetson Thor_DevKit"
ROW_DATA_START = 13
ROW_DATA_END   = 479

# Columns we need (1-based indices via letters)
def col_to_idx_1b(col_letters: str) -> int:
    acc = 0
    for ch in col_letters.strip().upper():
        if 'A' <= ch <= 'Z':
            acc = acc * 26 + (ord(ch) - ord('A') + 1)
    return acc

COL_A_PINNUM   = col_to_idx_1b("A")   # Pin #
COL_B_SIGNAL   = col_to_idx_1b("B")   # Signal Name
COL_C_MPIO     = col_to_idx_1b("C")   # MPIO (pin identifier)

# “Filled in by Customers” mapping
ASSUME_FIELDS = {
    "function"    : "AS",
    "pull"        : "AT",
    "tristate"    : "AU",
    "enable-input": "AV",
    "drv-type"    : "AX",
    "lock"        : "BD",
    "open-drain"  : "BE",
    "ddc"         : "BF",
    "rcvsel"      : "BG",
    "has-eqos"    : "BH",
    "eqos"        : "BI",
}
USED_COL_LETTERS = list(ASSUME_FIELDS.values())
USED_COLS_1B     = {c: col_to_idx_1b(c) for c in USED_COL_LETTERS}

# ---------------- core XLSX (.xlsm) reader (no pandas) ----------------
def _st(tag: str) -> str:  # strip namespace
    return tag.split("}", 1)[-1] if "}" in tag else tag

def read_sheet_xml(xlsx_path: Path):
    with zipfile.ZipFile(xlsx_path) as z:
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
        # map sheet name -> relId
        name_to_rid = {}
        for s in wb_xml.iter():
            if _st(s.tag) == "sheet":
                nm = s.attrib.get("name")
                rid = s.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                if nm and rid:
                    name_to_rid[nm] = rid
        if SHEET_NAME not in name_to_rid:
            raise SystemExit(f"Sheet '{SHEET_NAME}' not found. Available: {list(name_to_rid.keys())}")

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {r.attrib["Id"]: r.attrib["Target"]
                         for r in rels.iter() if _st(r.tag) == "Relationship"}
        target = rid_to_target[name_to_rid[SHEET_NAME]]  # e.g. "worksheets/sheet1.xml"
        sheet_xml = ET.fromstring(z.read(f"xl/{target}"))

        # shared strings (for t="s")
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

def read_cells(sheet_xml, shared_strings, col_filter_1b=None, row_min=None, row_max=None):
    vals = {}
    for c in sheet_xml.iter():
        if _st(c.tag) != "c":
            continue
        r = c.attrib.get("r")   # e.g., "AS13"
        if not r:
            continue
        m = re.match(r"([A-Z]+)(\d+)$", r)
        if not m:
            continue
        col_letters, row_s = m.group(1), m.group(2)
        row = int(row_s)
        col_idx = col_to_idx_1b(col_letters)

        if row_min and row < row_min: continue
        if row_max and row > row_max: continue
        if col_filter_1b and col_idx not in col_filter_1b: continue

        t = c.attrib.get("t")
        v_node = c.find("{*}v")
        v = None
        if v_node is not None and v_node.text is not None:
            v = v_node.text
            if t == "s":  # shared string
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

# ---------------- helpers ----------------
def as_int(v, default=0):
    try:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default

def as_boolish(v):
    if v is None:
        return False
    s = str(v).strip().lower()
    if s in ("1","true","yes","y","enable","enabled"):   return True
    if s in ("0","false","no","n","disable","disabled",""): return False
    try:
        return float(s) != 0.0
    except Exception:
        return True

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="Generate DTS from Jetson Thor pinmux template.")
    ap.add_argument("workbook", help=".xlsm/.xlsx path")
    ap.add_argument("-o", "--out", default="pinmux-thor.dtsi", help="Output DTS")
    args = ap.parse_args()

    xlsx = Path(args.workbook)
    if not xlsx.exists():
        raise SystemExit(f"File not found: {xlsx}")

    sheet_xml, shared = read_sheet_xml(xlsx)

    # Read column C (MPIO pin identifier), A, B for reference
    pin_cols = {COL_A_PINNUM, COL_B_SIGNAL, COL_C_MPIO}
    pin_cells = read_cells(sheet_xml, shared, col_filter_1b=pin_cols,
                           row_min=ROW_DATA_START, row_max=ROW_DATA_END)

    # Read AS..BI (customer filled)
    used_cols_1b = {col_to_idx_1b(c) for c in USED_COL_LETTERS}
    used_cells = read_cells(sheet_xml, shared, col_filter_1b=used_cols_1b,
                            row_min=ROW_DATA_START, row_max=ROW_DATA_END)

    def get_used(row, letter):
        return used_cells.get((row, col_to_idx_1b(letter)))

    TAB = "\t"
    T2, T3, T4 = TAB*2, TAB*3, TAB*4
    lines = []
    lines.append(f"{T2}common {{")
    lines.append(f"{T3}/* SFIO/GPIO Pin Configuration (Jetson Thor, AS:BI + MPIO) */")

    emitted = 0
    for r in range(ROW_DATA_START, ROW_DATA_END + 1):
        pin_num = pin_cells.get((r, COL_A_PINNUM))   # not used in DTS, but could be for comments
        signal  = pin_cells.get((r, COL_B_SIGNAL))   # not used now; available if needed
        pin     = pin_cells.get((r, COL_C_MPIO))     # <-- DTS pin identifier

        pin = (pin or "").strip()
        if not pin:
            continue

        func = (get_used(r, ASSUME_FIELDS["function"]) or "").strip()
        if not func:
            # No function selected → skip row (treat as unused)
            continue

        pull     = as_int(get_used(r, ASSUME_FIELDS["pull"]), 0)
        tristate = as_int(get_used(r, ASSUME_FIELDS["tristate"]), 0)
        einput   = as_int(get_used(r, ASSUME_FIELDS["enable-input"]), 0)
        drvtype  = as_int(get_used(r, ASSUME_FIELDS["drv-type"]), 0)
        lock_en  = as_boolish(get_used(r, ASSUME_FIELDS["lock"]))
        od_en    = as_boolish(get_used(r, ASSUME_FIELDS["open-drain"]))
        ddc_en   = as_boolish(get_used(r, ASSUME_FIELDS["ddc"]))
        rcvsel   = as_int(get_used(r, ASSUME_FIELDS["rcvsel"]), 0)
        haseqos  = as_boolish(get_used(r, ASSUME_FIELDS["has-eqos"]))
        eqos     = as_int(get_used(r, ASSUME_FIELDS["eqos"]), 0)

        lines.append(f"{T3}{pin} {{")
        lines.append(f'{T4}nvidia,pins = "{pin}";')
        lines.append(f'{T4}nvidia,function = "{func}";')
        lines.append(f"{T4}nvidia,pull = <{pull}>;")
        lines.append(f"{T4}nvidia,tristate = <{tristate}>;")
        lines.append(f"{T4}nvidia,enable-input = <{einput}>;")
        lines.append(f"{T4}nvidia,drv-type = <{drvtype}>;")
        if lock_en:
            lines.append(f"{T4}nvidia,lock = <TEGRA_PIN_ENABLE>;")
        if od_en:
            lines.append(f"{T4}nvidia,open-drain = <TEGRA_PIN_ENABLE>;")
        if ddc_en:
            lines.append(f"{T4}nvidia,e-io-od = <{rcvsel}>;")
        if haseqos:
            lines.append(f"{T4}nvidia,e-lpbk = <{eqos}>;")
        lines.append(f"{T3}}};")
        emitted += 1

    lines.append(f"{T2}}};")
    lines.append("")  # blank
    lines.append(f"{T2}pinmux_unused_lowpower: unused_lowpower {{")
    lines.append(f"{T2}}};")
    lines.append("")
    lines.append(f"{T2}drive_default: drive {{")
    lines.append(f"{T2}}};")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out} with {emitted} pin blocks.")

if __name__ == "__main__":
    main()
