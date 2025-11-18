#!/usr/bin/env python3
"""
Generate pinmux DTS from Jetson Thor pinmux template (.xlsm/.xlsx).

- Sheet: "Jetson Thor_DevKit"
- Data rows: 13..479
- Uses "Device Tree Pin Name" for node name + nvidia,pins (lowercase)
- Uses "Customer Usage" (AS) for nvidia,function (lowercase)
- Uses AS:BI customer config block for pull/tristate/enable-input/drive/lock/OD/DDC/EQOS
- Emits pin comment: /* Pin <Pin #> - <Signal Name> */
- NO validation, NO ERROR/WARN comments (safe for end users)
"""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile

SHEET_NAME = "Jetson Thor_DevKit"
ROW_DATA_START = 13
ROW_DATA_END = 479


# Column helpers
def col_to_idx_1b(col_letters: str) -> int:
    """Convert Excel letters (e.g. 'AS') to 1-based index."""
    acc = 0
    for ch in col_letters.strip().upper():
        if "A" <= ch <= "Z":
            acc = acc * 26 + (ord(ch) - ord("A") + 1)
    return acc


# Core identifying columns
COL_A_PINNUM = col_to_idx_1b("A")  # Pin #
COL_B_SIGNAL = col_to_idx_1b("B")  # Signal Name
COL_C_MPIO   = col_to_idx_1b("C")  # MPIO (internal pin ID)

# “Filled in by Customers” numeric/config block (AS..BI)
ASSUME_FIELDS = {
    "function"    : "AS",  # Customer Usage (we also use it as the function name)
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


# XLSX/XLSM reader
def _st(tag: str) -> str:
    """Strip XML namespace from a tag."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def read_sheet_xml_and_shared(xlsx_path: Path):
    """Open .xlsx/.xlsm and return (sheet_xml, shared_strings_list)."""
    with zipfile.ZipFile(xlsx_path) as z:
        # Map sheet name -> relId
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
        name_to_rid = {}
        for s in wb_xml.iter():
            if _st(s.tag) == "sheet":
                nm = s.attrib.get("name")
                rid = s.attrib.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                if nm and rid:
                    name_to_rid[nm] = rid

        if SHEET_NAME not in name_to_rid:
            raise SystemExit(
                f"Sheet '{SHEET_NAME}' not found. Available sheets: {list(name_to_rid.keys())}"
            )

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {}
        for r in rels.iter():
            if _st(r.tag) == "Relationship":
                rid_to_target[r.attrib["Id"]] = r.attrib["Target"]

        target = rid_to_target[name_to_rid[SHEET_NAME]]  # e.g. "worksheets/sheet3.xml"
        sheet_xml = ET.fromstring(z.read(f"xl/{target}"))

        # shared strings
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


def read_cells(sheet_xml, shared_strings,
               row_min=None, row_max=None,
               col_min=None, col_max=None,
               col_filter_1b=None):
    """
    Read Excel cells into dict[(row, col_idx_1b)] = value (string or None).
    - row_min / row_max: optional row bounds
    - col_min / col_max: optional column index bounds
    - col_filter_1b: optional set of column indices to include
    """
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
        if row_min is not None and row < row_min:
            continue
        if row_max is not None and row > row_max:
            continue
        col_idx = col_to_idx_1b(col_letters)
        if col_min is not None and col_idx < col_min:
            continue
        if col_max is not None and col_idx > col_max:
            continue
        if col_filter_1b is not None and col_idx not in col_filter_1b:
            continue

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


# Helpers
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
    if s in ("1", "true", "yes", "y", "enable", "enabled"):
        return True
    if s in ("0", "false", "no", "n", "disable", "disabled", ""):
        return False
    try:
        return float(s) != 0.0
    except Exception:
        return True


def norm_text(v):
    if v is None:
        return ""
    return str(v).strip()


# Encoding helpers (map numbers to TEGRA_PIN_* macros)
def encode_pull(val: int) -> str:
    """Map numeric pull value to TEGRA_PIN_PULL_*."""
    if val == 0:
        return "TEGRA_PIN_PULL_NONE"
    elif val == 1:
        return "TEGRA_PIN_PULL_DOWN"
    elif val == 2:
        return "TEGRA_PIN_PULL_UP"
    return str(val)


def encode_tristate(val: int) -> str:
    return "TEGRA_PIN_ENABLE" if val else "TEGRA_PIN_DISABLE"


def encode_einput(val: int) -> str:
    return "TEGRA_PIN_ENABLE" if val else "TEGRA_PIN_DISABLE"


def encode_drvtype(val: int) -> str:
    """
    Map drive-strength encoding to TEGRA_PIN_* macros.
    """
    if val == 0:
        return "TEGRA_PIN_1X_DRIVER"
    elif val == 1:
        return "TEGRA_PIN_2X_DRIVER"
    elif val == 2:
        return "TEGRA_PIN_DEFAULT_DRIVE_1X"
    elif val == 3:
        return "TEGRA_PIN_DEFAULT_DRIVE_2X"
    return "TEGRA_PIN_COMP"


def encode_rcvsel(val: int) -> str:
    return "TEGRA_PIN_ENABLE" if val else "TEGRA_PIN_DISABLE"


def encode_eqos(val: int) -> str:
    return "TEGRA_PIN_ENABLE" if val else "TEGRA_PIN_DISABLE"


# Main DTS generator
def main():
    ap = argparse.ArgumentParser(
        description="Generate pinmux DTS from Jetson Thor pinmux template (no validation)."
    )
    ap.add_argument("workbook", help=".xlsm/.xlsx path")
    ap.add_argument("-o", "--out", default="pinmux-thor.dtsi", help="Output DTS file")
    args = ap.parse_args()

    xlsx = Path(args.workbook)
    if not xlsx.exists():
        raise SystemExit(f"File not found: {xlsx}")

    sheet_xml, shared = read_sheet_xml_and_shared(xlsx)

    # Discover "Device Tree Pin Name" column from header row (row 7)
    header_cells = read_cells(sheet_xml, shared, row_min=7, row_max=7)
    dt_col_idx = None
    for (r, c), v in header_cells.items():
        if isinstance(v, str) and v.strip() == "Device Tree Pin Name":
            dt_col_idx = c
            break
    if dt_col_idx is None:
        # Fallback to column U if header not found
        dt_col_idx = col_to_idx_1b("U")

    # Read Pin#, Signal, MPIO, Device Tree Pin Name, Customer Usage
    pin_cols = {
        COL_A_PINNUM,
        COL_B_SIGNAL,
        COL_C_MPIO,
        dt_col_idx,
        col_to_idx_1b("AS"),  # Customer Usage
    }

    pin_cells = read_cells(
        sheet_xml,
        shared,
        row_min=ROW_DATA_START,
        row_max=ROW_DATA_END,
        col_filter_1b=pin_cols,
    )

    # Read AS..BI customer config block
    used_cols_1b = {col_to_idx_1b(c) for c in USED_COL_LETTERS}
    used_cells = read_cells(
        sheet_xml,
        shared,
        row_min=ROW_DATA_START,
        row_max=ROW_DATA_END,
        col_filter_1b=used_cols_1b,
    )

    def get_used(row, letter):
        return used_cells.get((row, col_to_idx_1b(letter)))

    def get_dt_pin(row):
        return pin_cells.get((row, dt_col_idx))

    TAB = "\t"
    T2, T3, T4 = TAB * 2, TAB * 3, TAB * 4
    lines: list[str] = []

    lines.append(f"{T2}common {{")
    lines.append(f"{T3}/* SFIO/GPIO Pin Configuration (Jetson Thor, AS:BI + Device Tree Pin Name) */")

    emitted = 0

    for r in range(ROW_DATA_START, ROW_DATA_END + 1):
        pin_num = pin_cells.get((r, COL_A_PINNUM))
        signal  = pin_cells.get((r, COL_B_SIGNAL))
        mpio    = pin_cells.get((r, COL_C_MPIO))
        dt_pin  = get_dt_pin(r)

        pin = (dt_pin or mpio or "").strip()
        if not pin:
            continue

        usage_raw = pin_cells.get((r, col_to_idx_1b("AS")))
        usage     = norm_text(usage_raw)
        if not usage:
            # blank "Customer Usage" → skip row
            continue

        # Lowercase node name & function in DTS
        pin_l = pin.lower()
        func_l = usage.lower()

        # Numeric config from AS..BI
        pull_val = as_int(get_used(r, ASSUME_FIELDS["pull"]), 0)
        tri_val  = as_int(get_used(r, ASSUME_FIELDS["tristate"]), 0)
        ein_val  = as_int(get_used(r, ASSUME_FIELDS["enable-input"]), 0)
        drv_val  = as_int(get_used(r, ASSUME_FIELDS["drv-type"]), 0)

        lock_en = as_boolish(get_used(r, ASSUME_FIELDS["lock"]))
        od_en   = as_boolish(get_used(r, ASSUME_FIELDS["open-drain"]))
        ddc_en  = as_boolish(get_used(r, ASSUME_FIELDS["ddc"]))
        rcvsel_val = as_int(get_used(r, ASSUME_FIELDS["rcvsel"]), 0)
        haseqos = as_boolish(get_used(r, ASSUME_FIELDS["has-eqos"]))
        eqos_val = as_int(get_used(r, ASSUME_FIELDS["eqos"]), 0)

        pull_macro     = encode_pull(pull_val)
        tristate_macro = encode_tristate(tri_val)
        einput_macro   = encode_einput(ein_val)
        drv_macro      = encode_drvtype(drv_val)
        rcvsel_macro   = encode_rcvsel(rcvsel_val) if ddc_en else None
        eqos_macro     = encode_eqos(eqos_val) if haseqos else None

        # --- Emit DTS block ---
        if pin_num or signal:
            lines.append(f"{T3}/* Pin {pin_num or '?'} - {signal or '?'} */")

        lines.append(f"{T3}{pin_l} {{")
        lines.append(f'{T4}nvidia,pins = "{pin_l}";')
        lines.append(f'{T4}nvidia,function = "{func_l}";')
        lines.append(f"{T4}nvidia,pull = <{pull_macro}>;")
        lines.append(f"{T4}nvidia,tristate = <{tristate_macro}>;")
        lines.append(f"{T4}nvidia,enable-input = <{einput_macro}>;")
        lines.append(f"{T4}nvidia,drv-type = <{drv_macro}>;")
        if lock_en:
            lines.append(f"{T4}nvidia,lock = <TEGRA_PIN_ENABLE>;")
        if od_en:
            lines.append(f"{T4}nvidia,open-drain = <TEGRA_PIN_ENABLE>;")
        if ddc_en and rcvsel_macro is not None:
            lines.append(f"{T4}nvidia,e-io-od = <{rcvsel_macro}>;")
        if haseqos and eqos_macro is not None:
            lines.append(f"{T4}nvidia,e-lpbk = <{eqos_macro}>;")
        lines.append(f"{T3}}};")
        emitted += 1

    # Footer blocks (kept minimal)
    lines.append(f"{T2}}};")
    lines.append("")
    lines.append(f"{T2}pinmux_unused_lowpower: unused_lowpower {{")
    lines.append(f"{T2}}};")
    lines.append("")
    lines.append(f"{T2}drive_default: drive {{")
    lines.append(f"{T2}}};")

    out_path = Path(args.out)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {out_path} with {emitted} pin blocks.")

if __name__ == "__main__":
    main()
