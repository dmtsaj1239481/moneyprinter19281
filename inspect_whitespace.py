import os

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

line_208 = lines[207]
line_209 = lines[208]

print(f"Line 208 (repr): {repr(line_208)}")
print(f"Line 209 (repr): {repr(line_209)}")

# Hex dump of leading whitespace
def hex_dump(s):
    return " ".join(hex(ord(c)) for c in s[:10])

print(f"Line 208 Hex: {hex_dump(line_208)}")
print(f"Line 209 Hex: {hex_dump(line_209)}")
