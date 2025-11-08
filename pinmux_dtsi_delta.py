#!/usr/bin/env python3
# Create a minimal DTSI that contains only the pin blocks that changed.
# Compares two generated DTSI files (Before vs After), both with:
#   common { ...pin blocks... }
#
# Usage:
#   python3 pinmux_dtsi_delta.py pinmux-thor-Before.dtsi pinmux-thor-After.dtsi -o pinmux-thor-Delta.dtsi

import re, argparse
from pathlib import Path

PIN_BLOCK_RE = re.compile(
    r'(?P<indent>\s*)'          # capture indentation
    r'(?P<pin>[A-Za-z0-9_]+)\s*\{\s*'   # pin name {
    r'(?P<body>.*?)'            # body
    r'\}\s*;?',                 # }
    re.DOTALL
)

def extract_common_section(text: str) -> str:
    # Extract between "common {" and its matching "};"
    # naive but robust for our generator’s format
    m = re.search(r'\bcommon\s*\{', text)
    if not m:
        return ""
    start = m.end()
    # Find the matching closing brace balancing
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return ""

def parse_pin_blocks(common_body: str) -> dict:
    blocks = {}
    for m in PIN_BLOCK_RE.finditer(common_body):
        pin = m.group('pin').strip()
        # Normalize whitespace inside body for stable compare
        body = re.sub(r'\s+', ' ', m.group('body').strip())
        blocks[pin] = body
    return blocks

def main():
    ap = argparse.ArgumentParser(description="Produce minimal delta DTSI with only changed pin blocks.")
    ap.add_argument("before", help="Before DTSI")
    ap.add_argument("after", help="After DTSI")
    ap.add_argument("-o", "--out", default="pinmux-thor-Delta.dtsi", help="Output DTSI path")
    args = ap.parse_args()

    t_before = Path(args.before).read_text(encoding="utf-8")
    t_after  = Path(args.after).read_text(encoding="utf-8")

    c_before = extract_common_section(t_before)
    c_after  = extract_common_section(t_after)

    if not c_before or not c_after:
        raise SystemExit("Could not find 'common { ... }' in one or both input files.")

    b_blocks = parse_pin_blocks(c_before)
    a_blocks = parse_pin_blocks(c_after)

    changed = []
    for pin, a_body_norm in a_blocks.items():
        b_body_norm = b_blocks.get(pin)
        if b_body_norm != a_body_norm:
            # Re-extract pretty body from AFTER text for nicer formatting
            # Find the raw block again in the AFTER common section
            m = re.search(rf'(^|\n)\s*{re.escape(pin)}\s*\{{(.*?)\}}\s*;?', c_after, flags=re.DOTALL)
            pretty_body = m.group(2).strip() if m else ""
            changed.append((pin, pretty_body))

    if not changed:
        print("No changes detected between DTSIs. Nothing to write.")
        return

    TAB = "\t"
    T2, T3, T4 = TAB*2, TAB*3, TAB*4
    lines = []
    lines.append("/* Auto-generated: minimal delta of changed pins only */")
    lines.append(f"{T2}common {{")
    lines.append(f"{T3}/* Only pins that changed vs. BEFORE */")
    for pin, body in changed:
        lines.append(f"{T3}{pin} {{")
        # indent inner lines
        for ln in body.splitlines():
            lines.append(f"{T4}{ln.rstrip()}")
        lines.append(f"{T3}}};")
    lines.append(f"{T2}}};")
    outp = Path(args.out)
    outp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {outp} with {len(changed)} changed pin blocks.")

if __name__ == "__main__":
    main()
