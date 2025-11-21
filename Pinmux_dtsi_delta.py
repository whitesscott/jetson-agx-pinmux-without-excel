#!/usr/bin/env python3
"""
Create a DTSI that contains only the pin blocks that are changed
in the `common { ... }` section between BEFORE and AFTER DTS/DTSI files.

Designed to work with output from gen_pinmux_dt_from_xlsx.py (clean),
and to annotate *only the changed pins* with validator comments from
pinmux_validator.validate_pin_by_node().

Now also preserves the "header" from the AFTER file:
  - Top comment (/* Auto-generated ... */)
  - #include "t264-pinctrl-tegra.h"
  - #include "tegra264-gpio.h"

And wraps the delta `common { ... }` inside:

    pinmux@ac281000 {
        common {
            ...
        };
    };
"""

from __future__ import annotations

import re
import argparse
from pathlib import Path

try:
    from pinmux_validator import validate_pin_by_node
except Exception:
    validate_pin_by_node = None

TAB = "\t"
T2, T3, T4 = TAB * 2, TAB * 3, TAB * 4


# Helpers to isolate the `common { ... }` section
def extract_common_body(text: str) -> str:
    """
    Extract the body of the outermost `common { ... }` block (without the `common {`
    line and the closing `};` line). Returns empty string if not found.
    """
    m = re.search(r'\bcommon\s*\{', text)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return ""


def parse_pin_blocks_with_comments(body: str):
    """
    Parse the `common { ... }` body into blocks keyed by pin/node name.

    Returns:
        dict[name] = (full_text, normalized_body)

    full_text: comments + pin block exactly as in the input.
    normalized_body: body text with comments removed and whitespace squashed,
                     for comparison between BEFORE and AFTER.
    """
    lines = body.splitlines()
    blocks = {}
    i = 0

    while i < len(lines):
        # Collect any leading comments / blank lines
        comment_lines = []
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("/*") or stripped.startswith("//") or stripped == "":
                comment_lines.append(lines[i])
                i += 1
            else:
                break
        if i >= len(lines):
            break

        # Look for <name> { on this line
        line = lines[i]
        m = re.match(r'\s*([A-Za-z0-9_]+)\s*\{', line)
        if not m:
            # Not a pin block, skip this line
            i += 1
            continue

        name = m.group(1)
        block_lines = [line]
        depth = line.count("{") - line.count("}")
        i += 1
        while i < len(lines) and depth > 0:
            block_lines.append(lines[i])
            depth += lines[i].count("{") - lines[i].count("}")
            i += 1

        full_lines = comment_lines + block_lines
        full_text = "\n".join(full_lines)

        # Normalized body: drop comments & blank lines, squash whitespace
        body_no_comments = []
        for bl in block_lines:
            s = bl.strip()
            if s.startswith("/*") or s.startswith("//") or s == "":
                continue
            body_no_comments.append(bl)
        norm = re.sub(r"\s+", " ", "\n".join(body_no_comments)).strip()

        blocks[name] = (full_text, norm)

    return blocks


# Header extraction
def extract_header(text: str) -> str:
    """
    Extract a simple "header" from the top of the AFTER file:
      - Optional leading blank lines
      - Top comment (/* ... */)
      - Any #include lines
    Stops as soon as it hits a non-comment, non-include, non-blank line.

    This matches BEFORE/AFTER style, :

        /* Auto-generated from Jetson Thor pinmux spreadsheet */
        #include "t264-pinctrl-tegra.h"
        #include "tegra264-gpio.h"
    """
    lines = text.splitlines()
    header_lines = []
    in_block_comment = False

    for line in lines:
        stripped = line.strip()

        if stripped == "":
            # Preserve leading blank lines until we see real content
            if not header_lines:
                header_lines.append(line)
                continue
            # If we've already collected something (comment/includes), keep one more blank
            header_lines.append(line)
            continue

        # Block comments (/* ... */), only at top
        if stripped.startswith("/*"):
            header_lines.append(line)
            if not stripped.endswith("*/"):
                in_block_comment = True
            continue

        if in_block_comment:
            header_lines.append(line)
            if "*/" in stripped:
                in_block_comment = False
            continue

        # Single-line comment starting with //
        if stripped.startswith("//"):
            header_lines.append(line)
            continue

        # Includes
        if stripped.startswith("#include"):
            header_lines.append(line)
            continue

        # First "real" line reached -> stop
        break

    # Trim trailing blank lines from header if any
    while header_lines and header_lines[-1].strip() == "":
        header_lines.pop()

    if header_lines:
        return "\n".join(header_lines) + "\n\n"
    return ""


# Delta builder
def build_delta_common(before_text: str, after_text: str) -> str:
    """
    Build the delta `common { ... }` section containing only changed pins,
    preserving comments from AFTER and adding validator comments (if available).
    """
    before_body = extract_common_body(before_text)
    after_body = extract_common_body(after_text)

    before_blocks = parse_pin_blocks_with_comments(before_body)
    after_blocks = parse_pin_blocks_with_comments(after_body)

    changed_pins = []

    all_pins = sorted(set(before_blocks.keys()) | set(after_blocks.keys()))
    for pin in all_pins:
        b = before_blocks.get(pin)
        a = after_blocks.get(pin)

        if a is None:
            # Pin removed in AFTER; ignore for overlay
            continue

        if b is None:
            # New pin in AFTER
            changed_pins.append(pin)
            continue

        # Compare normalized bodies (excluding comments)
        if a[1] != b[1]:
            changed_pins.append(pin)

    if not changed_pins:
        return ""

    lines = []
    lines.append(f"{T2}common {{")

    for pin in sorted(changed_pins):
        full_text, _norm = after_blocks[pin]

        # Add validator comments only here (not in BEFORE/AFTER)
        if validate_pin_by_node is not None:
            try:
                errs, warns = validate_pin_by_node(pin)
            except Exception as e:
                errs = [f"Validator exception for node '{pin}': {e!r}"]
            for e in errs:
                lines.append(f"{T3}/* ERROR: {e} */")
            # If you want WARNs too, uncomment:
            # for w in warns:
            #     lines.append(f"{T3}/* WARN:  {w} */")

        # Then append the full AFTER block (comments + body) as-is
        lines.append(full_text)

    lines.append(f"{T2}}};")
    lines.append("")  # final newline
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Create a DTSI that contains only changed pin blocks in common{} between BEFORE and AFTER."
    )
    ap.add_argument("before", help="BEFORE DTS/DTSI file")
    ap.add_argument("after", help="AFTER DTS/DTSI file")
    ap.add_argument(
        "-o",
        "--out",
        default="pinmux-thor-DELTA.dtsi",
        help="Output DTSI file",
    )
    args = ap.parse_args()

    before_text = Path(args.before).read_text(encoding="utf-8")
    after_text = Path(args.after).read_text(encoding="utf-8")

    header = extract_header(after_text)
    delta_common = build_delta_common(before_text, after_text)

    out_path = Path(args.out)

    if delta_common.strip():
        # Wrap the delta common{} in pinmux@ac281000 { ... };
        body = "pinmux@ac281000 {\n" + delta_common + "};\n"
        out_text = header + body
        out_path.write_text(out_text, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        out_path.write_text("", encoding="utf-8")
        print("No pinmux differences detected (no changes to common{} pin blocks).")


if __name__ == "__main__":
    main()
