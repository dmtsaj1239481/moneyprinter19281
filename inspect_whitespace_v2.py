import os

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

l208 = lines[207]
l209 = lines[208]

def get_info(name, line):
    spaces = len(line) - len(line.lstrip())
    hexes = " ".join([f"{ord(c):02x}" for c in line[:12]])
    return f"{name}: Indent={spaces}, Content={repr(line[:40])}, Hex={hexes}"

print(get_info("Line 208", l208))
print(get_info("Line 209", l209))
