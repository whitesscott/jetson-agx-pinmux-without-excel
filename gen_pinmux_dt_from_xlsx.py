"""
Generate Jetson Thor pinmux DTSI from Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm

Sheet: "Jetson Thor_DevKit"

Rows (1-based Excel):
  13..479   = data rows

Columns:
  A  = "Pin #"
  B  = "Signal Name"
  C  = "MPIO"          (pin identifier in DTS)
  AS = Function        (SFIO / unused_* / etc.)
  AT = Direction       ("Not Assigned" / "Input" / "Output" / "N/A")
  AU = Pull/Drive      ("Z" / "Int PU" / "Int PD" / "Drive 0" / "Drive 1" / "N/A")
  AV = Enable-input    ("Yes" / "No" / blank)
  AX = Output-enable   ("Enable" / "Disable")

Only AS–AX are used to derive config bits; BD–BI, BK, etc. are ignored.
"""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile


# BallConfig bits (mirroring Nvida's vba Enum BallConfig)

CFG_RCV_SEL    = 1
CFG_LOCK       = 2
CFG_OD         = 4
CFG_E_INPUT    = 8
CFG_TRISTATE   = 16
CFG_PULL_DOWN  = 32
CFG_PULL_UP    = 64
CFG_I2C        = 128
CFG_DDC        = 256
# CFG_HAS_LPDR = 512
# CFG_LPDR     = 1024
CFG_HAS_EQOS   = 2048
CFG_EQOS       = 4096
CFG_DRV_1X     = 512
CFG_DEF_1X     = 1024

ERR_PULL = -1
ERR_LPDR = -1

TAB = "\t"
DOUBLE_TAB = TAB * 2
TRIPLE_TAB = TAB * 3
QUAD_TAB = TAB * 4


def get_pull(config_bits: int) -> str:
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
        return str(checker)


def get_tristate(config_bits: int) -> str:
    checker = config_bits & CFG_TRISTATE
    checker = (checker // CFG_TRISTATE) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def get_einput(config_bits: int) -> str:
    checker = config_bits & CFG_E_INPUT
    checker = (checker // CFG_E_INPUT) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def get_lpdr(config_bits: int) -> str:
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


def get_lock(config_bits: int) -> str:
    checker = config_bits & CFG_LOCK
    checker = (checker // CFG_LOCK) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def get_od(config_bits: int) -> str:
    checker = config_bits & CFG_OD
    checker = (checker // CFG_OD) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def get_ddc(config_bits: int) -> int:
    checker = config_bits & CFG_DDC
    checker = (checker // CFG_DDC) % 2
    return checker


def get_rcvsel(config_bits: int) -> str:
    checker = config_bits & CFG_RCV_SEL
    checker = (checker // CFG_RCV_SEL) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def get_has_eqos(config_bits: int) -> int:
    checker = config_bits & CFG_HAS_EQOS
    checker = (checker // CFG_HAS_EQOS) % 2
    return checker


def get_eqos(config_bits: int) -> str:
    checker = config_bits & CFG_EQOS
    checker = (checker // CFG_EQOS) % 2
    return "TEGRA_PIN_ENABLE" if checker != 0 else "TEGRA_PIN_DISABLE"


def print_pinmux_dt(
    mpio_name,
    sfio_name,
    mpio_config_value,
    pin_num,
    signal_name,
    max_sfio_index: int,
    max_gpio_index: int,
    max_unused_index: int,
) -> str:
    """
    Python equivalent of VBA PrintPinmuxDT(), with extra comments using
    pin number and signal name from columns A/B.

    Arrays are 1-based: index 0 unused.
    """

    def cfg(idx: int) -> int:
        return int(mpio_config_value[idx])

    max_used_index = max_sfio_index + max_gpio_index
    max_index = max_used_index + max_unused_index

    lines = []

    # common { ... }
    lines.append(f"{DOUBLE_TAB}common {{")
    lines.append(f"{TRIPLE_TAB}/* SFIO Pin Configuration */")

    current = 1
    while current <= max_used_index:
        pin = mpio_name[current]
        func = sfio_name[current]
        pnum = pin_num[current]
        sig  = signal_name[current]

        # Optional comment: /* Pin <A> - <B> */
        comment_parts = []
        if pnum:
            comment_parts.append(str(pnum))
        if sig:
            comment_parts.append(sig)
        if comment_parts:
            lines.append(f"{TRIPLE_TAB}/* Pin " + " - ".join(comment_parts) + " */")

        lines.append(f"{TRIPLE_TAB}{pin} {{")
        lines.append(f'{QUAD_TAB}nvidia,pins = "{pin}";')
        lines.append(f'{QUAD_TAB}nvidia,function = "{func}";')
        lines.append(f"{QUAD_TAB}nvidia,pull = <{get_pull(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,tristate = <{get_tristate(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,enable-input = <{get_einput(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,drv-type = <{get_lpdr(cfg(current))}>;")

        if get_lock(cfg(current)) == "TEGRA_PIN_ENABLE":
            lines.append(f"{QUAD_TAB}nvidia,lock = <{get_lock(cfg(current))}>;")
        if get_od(cfg(current)) == "TEGRA_PIN_ENABLE":
            lines.append(f"{QUAD_TAB}nvidia,open-drain = <{get_od(cfg(current))}>;")
        if get_ddc(cfg(current)):
            lines.append(f"{QUAD_TAB}nvidia,e-io-od = <{get_rcvsel(cfg(current))}>;")
        if get_has_eqos(cfg(current)):
            lines.append(f"{QUAD_TAB}nvidia,e-lpbk = <{get_eqos(cfg(current))}>;")

        lines.append(f"{TRIPLE_TAB}}};")

        if current < max_used_index:
            lines.append("")

        current += 1

    lines.append(f"{DOUBLE_TAB}}};")
    lines.append("")

    # pinmux_unused_lowpower
    lines.append(f"\tpinmux_unused_lowpower: unused_lowpower {{")

    while current <= max_index:
        pin = mpio_name[current]
        func = sfio_name[current]
        pnum = pin_num[current]
        sig  = signal_name[current]

        comment_parts = []
        if pnum:
            comment_parts.append(str(pnum))
        if sig:
            comment_parts.append(sig)
        if comment_parts:
            lines.append(f"{TRIPLE_TAB}/* Pin " + " - ".join(comment_parts) + " */")

        lines.append(f"{TRIPLE_TAB}{pin} {{")
        lines.append(f'{QUAD_TAB}nvidia,pins = "{pin}";')
        lines.append(f'{QUAD_TAB}nvidia,function = "{func}";')
        lines.append(f"{QUAD_TAB}nvidia,pull = <{get_pull(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,tristate = <{get_tristate(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,enable-input = <{get_einput(cfg(current))}>;")
        lines.append(f"{QUAD_TAB}nvidia,drv-type = <{get_lpdr(cfg(current))}>;")

        if get_lock(cfg(current)) == "TEGRA_PIN_ENABLE":
            lines.append(f"{QUAD_TAB}nvidia,lock = <{get_lock(cfg(current))}>;")
        if get_od(cfg(current)) == "TEGRA_PIN_ENABLE":
            lines.append(f"{QUAD_TAB}nvidia,open-drain = <{get_od(cfg(current))}>;")
        if get_ddc(cfg(current)):
            lines.append(f"{QUAD_TAB}nvidia,e-io-od = <{get_rcvsel(cfg(current))}>;")
        if get_has_eqos(cfg(current)):
            lines.append(f"{QUAD_TAB}nvidia,e-lpbk = <{get_eqos(cfg(current))}>;")

        lines.append(f"{TRIPLE_TAB}}};")

        current += 1
        if current <= max_index:
            lines.append("")

    lines.append(f"{DOUBLE_TAB}}};")
    lines.append("")
    lines.append(f"{DOUBLE_TAB}drive_default: drive {{")
    lines.append(f"{DOUBLE_TAB}}};")

    return "\n".join(lines) + "\n"



# XLSM XML helpers

SHEET_NAME = "Jetson Thor_DevKit"
ROW_DATA_START = 13
ROW_DATA_END   = 479  # inclusive Excel row

def col_to_idx_1b(col_letters: str) -> int:
    acc = 0
    for ch in col_letters.strip().upper():
        if "A" <= ch <= "Z":
            acc = acc * 26 + (ord(ch) - ord("A") + 1)
    return acc

COL_A_PINNUM = col_to_idx_1b("A")
COL_B_SIGNAL = col_to_idx_1b("B")
COL_C_MPIO   = col_to_idx_1b("C")

ASSUME_FIELDS = {
    "function"     : "AS",
    "direction"    : "AT",
    "pull_cfg"     : "AU",
    "enable-input" : "AV",
    "drv-enable"   : "AX",
}
USED_COL_LETTERS = list(ASSUME_FIELDS.values())


def _st(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def read_sheet_xml(xlsx_path: Path):
    """Return (sheet_xml_root, shared_strings_list) for SHEET_NAME."""
    with zipfile.ZipFile(xlsx_path) as z:
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
            raise SystemExit(f"Sheet '{SHEET_NAME}' not found. Available: {list(name_to_rid.keys())}")

        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in rels.iter()
            if _st(r.tag) == "Relationship"
        }

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


def read_cells(sheet_xml, shared_strings, col_filter_1b=None, row_min=None, row_max=None):
    """Return dict[(row, col_idx1)] = value for selected region."""
    vals = {}
    for c in sheet_xml.iter():
        if _st(c.tag) != "c":
            continue
        r = c.attrib.get("r")  # e.g., "AS13"
        if not r:
            continue
        m = re.match(r"([A-Z]+)(\d+)$", r)
        if not m:
            continue
        col_letters, row_s = m.group(1), m.group(2)
        row = int(row_s)
        col_idx = col_to_idx_1b(col_letters)

        if row_min and row < row_min:
            continue
        if row_max and row > row_max:
            continue
        if col_filter_1b and col_idx not in col_filter_1b:
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



# Config bits encoding from AT / AU / AV / AX

def _as_str(v):
    if v is None:
        return ""
    return str(v).strip()


def encode_config_bits_for_row(row: int, used_cells) -> int:
    """
    Build the integer ConfigBits mask from AS–AX for this row.

    AT: Not Assigned / Input / Output / N/A
    AU: Z / Int PU / Int PD / Drive 0 / Drive 1 / N/A
    AV: Yes / No / blank  (input enable hint)
    AX: Enable / Disable
    """
    bits = 0

    def col(letter: str):
        return used_cells.get((row, col_to_idx_1b(letter)))

    #  internal pull from AU 
    au_s = _as_str(col(ASSUME_FIELDS["pull_cfg"])).lower()

    if "int pu" in au_s:
        bits |= CFG_PULL_UP
    elif "int pd" in au_s:
        bits |= CFG_PULL_DOWN
    # "z" / "n/a" → no pull bits set

    #  direction + input-enable + tristate from AT / AV / AX 
    at_s = _as_str(col(ASSUME_FIELDS["direction"])).lower()
    av_s = _as_str(col(ASSUME_FIELDS["enable-input"])).lower()
    ax_s = _as_str(col(ASSUME_FIELDS["drv-enable"])).lower()

    is_input  = at_s == "input"
    is_output = at_s == "output"
    # "not assigned" / "n/a" are treated as unused by classifier

    if is_input:
        # Input-only: tristated, input enabled
        bits |= CFG_TRISTATE
        bits |= CFG_E_INPUT
    elif is_output:
        # Output-only: driving, input disabled by default
        if av_s == "yes":
            bits |= CFG_E_INPUT

    # If AX == "disable", force tristate regardless of AT
    if ax_s == "disable":
        bits |= CFG_TRISTATE

    #  drive strength from AU ("Drive 0" / "Drive 1") 
    if "drive 0" in au_s:
        bits |= CFG_DRV_1X        # 1X driver
    elif "drive 1" in au_s:
        bits |= CFG_DRV_1X | CFG_DEF_1X

    # DDC / RCVSEL / EQOS are not used in this Thor template
    return bits



def main():
    ap = argparse.ArgumentParser(description="Generate Jetson Thor pinmux DTSI from .xlsm/.xlsx template.")
    ap.add_argument("workbook", help="Path to Jetson_Thor_Series_Modules_Pinmux_Template_v1.4.xlsm/.xlsx")
    ap.add_argument("-o", "--out", default="pinmux-thor.dtsi", help="Output DTSI path")
    args = ap.parse_args()

    xlsx = Path(args.workbook)
    if not xlsx.exists():
        raise SystemExit(f"File not found: {xlsx}")

    sheet_xml, shared = read_sheet_xml(xlsx)

    # Read pin identity (A,B,C) for data rows
    pin_cols = {COL_A_PINNUM, COL_B_SIGNAL, COL_C_MPIO}
    pin_cells = read_cells(sheet_xml, shared, col_filter_1b=pin_cols,
                           row_min=ROW_DATA_START, row_max=ROW_DATA_END)

    # Read AS–AX for config
    used_cols_1b = {col_to_idx_1b(c) for c in USED_COL_LETTERS}
    used_cells = read_cells(sheet_xml, shared, col_filter_1b=used_cols_1b,
                            row_min=ROW_DATA_START, row_max=ROW_DATA_END)

    def get_used(row, letter):
        return used_cells.get((row, col_to_idx_1b(letter)))

    used_rows = []
    unused_rows = []

    for r in range(ROW_DATA_START, ROW_DATA_END + 1):
        mpio = pin_cells.get((r, COL_C_MPIO))
        mpio_str = _as_str(mpio)
        if not mpio_str:
            continue

        func = _as_str(get_used(r, ASSUME_FIELDS["function"]))
        func_lower = func.lower()
        dir_s = _as_str(get_used(r, ASSUME_FIELDS["direction"])).lower()

        # Unused rules:
        #  - no function at all
        #  - function starts with "unused"
        #  - direction is "not assigned" or "n/a"
        if (not func
                or func_lower.startswith("unused")
                or dir_s in ("not assigned", "n/a")):
            unused_rows.append(r)
        else:
            used_rows.append(r)

    total_used = len(used_rows)
    total_unused = len(unused_rows)
    total = total_used + total_unused

    # 1-based arrays for VBA-style logic
    mpio_name   = [""  for _ in range(total + 1)]
    sfio_name   = [""  for _ in range(total + 1)]
    mpio_cfg    = [0   for _ in range(total + 1)]
    pin_num     = [""  for _ in range(total + 1)]
    signal_name = [""  for _ in range(total + 1)]

    def get_pin(row, col_idx):
        return pin_cells.get((row, col_idx))

    idx = 1
    # Fill used pins first (common { ... })
    for r in used_rows:
        mpio = _as_str(get_pin(r, COL_C_MPIO))
        func = _as_str(get_used(r, ASSUME_FIELDS["function"]))
        cfg_bits = encode_config_bits_for_row(r, used_cells)
        pnum = _as_str(get_pin(r, COL_A_PINNUM))
        sig  = _as_str(get_pin(r, COL_B_SIGNAL))

        mpio_name[idx]   = mpio
        sfio_name[idx]   = func
        mpio_cfg[idx]    = cfg_bits
        pin_num[idx]     = pnum
        signal_name[idx] = sig
        idx += 1

    # Then unused_lowpower pins
    for r in unused_rows:
        mpio = _as_str(get_pin(r, COL_C_MPIO))
        func = _as_str(get_used(r, ASSUME_FIELDS["function"]))
        cfg_bits = encode_config_bits_for_row(r, used_cells)
        pnum = _as_str(get_pin(r, COL_A_PINNUM))
        sig  = _as_str(get_pin(r, COL_B_SIGNAL))

        mpio_name[idx]   = mpio
        sfio_name[idx]   = func if func else "unused"
        mpio_cfg[idx]    = cfg_bits
        pin_num[idx]     = pnum
        signal_name[idx] = sig
        idx += 1

    max_sfio_index   = total_used
    max_gpio_index   = 0             # no explicit SFIO vs GPIO split here
    max_unused_index = total_unused

    dtsi_text = print_pinmux_dt(
        mpio_name,
        sfio_name,
        mpio_cfg,
        pin_num,
        signal_name,
        max_sfio_index,
        max_gpio_index,
        max_unused_index,
    )

    out_path = Path(args.out)
    out_path.write_text(dtsi_text, encoding="utf-8")
    print(f"Wrote {out_path} with {total_used} used pins and {total_unused} unused pins.")


if __name__ == "__main__":
    main()
