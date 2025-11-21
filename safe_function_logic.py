#!/usr/bin/env python3
"""
safe_function_logic.py

Contains the logic to determine the "Safe" (Default) function for a pin
based on its available multiplexing options (F0-F3).

This replicates the logic from the original VBA macro (UpdateFunctions.bas).
"""

def get_safe_function_name(functions: list[str]) -> str:
    """
    Determines the 'SafeFunctionName' for a pin based on its 4 available functions.

    Logic:
      1. Scans function slots 0, 1, 2, 3 in order.
      2. The FIRST slot found that contains "RSVD" (case-insensitive) is selected.
      3. If NO slot contains "RSVD", the first function (F0) is returned as the fallback.

    Args:
        functions: A list of strings corresponding to [F0, F1, F2, F3].
                   Can contain None or empty strings.

    Returns:
        The name of the determined safe function.
    """
    if not functions:
        return ""

    # Normalize inputs: convert None to "" and ensure list has 4 elements
    funcs = [(str(f).strip() if f is not None else "") for f in functions]
    # Pad with empty strings if fewer than 4 provided
    while len(funcs) < 4:
        funcs.append("")

    safe_function_name = ""
    first_function_name = funcs[0]

    # --- VBA Logic Implementation ---

    # Check Slot 0
    if "RSVD" in funcs[0].upper():
        safe_function_name = funcs[0]

    # Check Slot 1: Only set if SafeFunction is still empty AND this contains RSVD
    if safe_function_name == "" and "RSVD" in funcs[1].upper():
        safe_function_name = funcs[1]

    # Check Slot 2: Only set if SafeFunction is still empty AND this contains RSVD
    if safe_function_name == "" and "RSVD" in funcs[2].upper():
        safe_function_name = funcs[2]

    # Check Slot 3: Only set if SafeFunction is still empty AND this contains RSVD
    if safe_function_name == "" and "RSVD" in funcs[3].upper():
        safe_function_name = funcs[3]

    # Fallback: If no RSVD function was found, default to the First Function (F0)
    if safe_function_name == "":
        safe_function_name = first_function_name

    return safe_function_name

if __name__ == "__main__":
    # Simple test block to verify logic if run directly
    print("Running self-test...")
    print(f"Test 1 (RSVD in F0): {get_safe_function_name(['RSVD1', 'UART', 'I2C', 'SPI'])}") 
    # Expected: RSVD1

    print(f"Test 2 (RSVD in F2): {get_safe_function_name(['UART', 'SPI', 'RSVD2', 'I2C'])}") 
    # Expected: RSVD2

    print(f"Test 3 (No RSVD):    {get_safe_function_name(['UART', 'SPI', 'I2C', 'GPIO'])}") 
    # Expected: UART (Fallback to F0)

