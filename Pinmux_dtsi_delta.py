#!/usr/bin/env python3
"""
Create a DTSI that contains only the pin blocks that are changed
in the `common { ... }` section between BEFORE and AFTER DTS/DTSI files.

Designed to work with output from gen_pinmux_dt_from_xlsx.py, preserving
the leading "/* Pin # - Signal Name */" comments from the AFTER file.
"""

import re
import argparse
from pathlib import Path


# Helpers to isolate the `common { ... }` section

def extract_common_section(text: str) -> str:
    """
    Extract the body of the first `common { ... }` section, excluding
    the outer braces themselves.
    """
    m = re.search(r'\bcommon\s*\{', text)
    if not m:
        return ""
    # Position of the '{' that opens "common {"
    start_brace = text.find("{", m.end() - 1)
    if start_brace == -1:
        return ""

    depth = 0
    start_inner = start_brace + 1
    end_inner = None

    for i, ch in enumerate(text[start_brace:], start=start_brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_inner = i
                break

    if end_inner is None or end_inner <= start_inner:
        return ""

    return text[start_inner:end_inner]



# Parse pin blocks + optional preceding "/* Pin .. */" comments

def parse_pin_blocks_with_comments(common_body: str):
    """
    Parse `common_body` (inner text of the common { ... } section) into
    per-pin blocks.

    We expect patterns like:

        \t\t\t/* Pin J57 - SPI1_CLK */
        \t\t\tGP115_SPI1_CLK {
        \t\t\t    ...
        \t\t\t};

    Returns:
        dict[pin_name] = (block_text, normalized_text_for_compare)
    """
    blocks = {}
    if not common_body:
        return blocks

    lines = common_body.splitlines()
    comment_re = re.compile(r'^\s*/\*.*\*/\s*$')
    pin_re = re.compile(r'^\s*([A-Za-z0-9_]+)\s*\{')

    pending_comment_idx = None
    i = 0
    while i < len(lines):
        line = lines[i]

        # Track possible "/* Pin ... */" comment
        if comment_re.match(line):
            pending_comment_idx = i
            i += 1
            continue

        m = pin_re.match(line)
        if not m:
            i += 1
            continue

        pin = m.group(1)
        # Start of block: include comment if immediately preceding (or last seen)
        start_idx = pending_comment_idx if pending_comment_idx is not None else i

        # Find end of block by brace balancing
        depth = 0
        j = i
        while j < len(lines):
            depth += lines[j].count("{")
            depth -= lines[j].count("}")
            if depth == 0:
                end_idx = j
                break
            j += 1
        else:
            # Unterminated block; stop parsing
            break

        block_lines = lines[start_idx:end_idx + 1]
        block_text = "\n".join(block_lines)

        # Build a normalized version for comparison:
        # - strip leading/trailing spaces on each line
        # - drop the "/* Pin ... */" comment line from the normalization
        norm_lines = []
        for l in block_lines:
            if comment_re.match(l):
                continue
            norm_lines.append(l.strip())
        norm_text = " ".join(norm_lines)

        blocks[pin] = (block_text, norm_text)

        # Reset pending comment; move past this block
        pending_comment_idx = None
        i = end_idx + 1

    return blocks



# Main delta computation

def build_delta_common(before_text: str, after_text: str) -> str:
    """
    Build the delta `common { ... }` section containing only changed pins,
    preserving comments from AFTER.
    """
    before_body = extract_common_section(before_text)
    after_body = extract_common_section(after_text)

    before_blocks = parse_pin_blocks_with_comments(before_body)
    after_blocks = parse_pin_blocks_with_comments(after_body)

    changed_pins = []

    all_pins = sorted(set(before_blocks.keys()) | set(after_blocks.keys()))
    for pin in all_pins:
        b = before_blocks.get(pin)
        a = after_blocks.get(pin)

        if a is None:
            # Pin removed in AFTER; typically ignore removals for overlays
            continue

        if b is None:
            # New pin in AFTER
            changed_pins.append(pin)
            continue

        # Compare normalized bodies (excluding pin comment differences)
        if a[1] != b[1]:
            changed_pins.append(pin)

    if not changed_pins:
        return ""

    lines = []
    T2 = "\t" * 2
    T3 = "\t" * 3

    lines.append(f"{T2}/* Auto-generated: delta of changed pins only */")
    lines.append(f"{T2}common {{")
    lines.append(f"{T3}/* Only pins that changed vs. BEFORE */")

    first = True
    for pin in changed_pins:
        block_text = after_blocks[pin][0]  # includes /* Pin ... */ comment from AFTER
        if not first:
            lines.append("")  # blank line between blocks
        first = False
        lines.append(block_text.rstrip())

    lines.append(f"{T2}}};")
    lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Produce delta DTSI with only changed pin blocks from the common{} section."
    )
    ap.add_argument("before", help="Before DTSI")
    ap.add_argument("after", help="After DTSI")
    ap.add_argument("-o", "--out", default="pinmux-thor-DELTA.dtsi", help="Output DTSI path")
    args = ap.parse_args()

    before_text = Path(args.before).read_text(encoding="utf-8")
    after_text = Path(args.after).read_text(encoding="utf-8")

    delta_common = build_delta_common(before_text, after_text)

    out_path = Path(args.out)
    out_path.write_text(delta_common, encoding="utf-8")

    if delta_common.strip():
        print(f"Wrote {out_path}")
    else:
        print("No pinmux differences detected (no changes to common{} pin blocks).")


if __name__ == "__main__":
    main()
