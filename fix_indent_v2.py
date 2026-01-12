import os

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []

for i, line in enumerate(lines):
    line_num = i + 1
    # Line 205: with main_tabs[0]:
    # Line 208: if not config.app.get("hide_config", False):
    # We need to indent lines 209 to 483 by 4 EXTRA spaces (total 8)
    if 209 <= line_num <= 483:
        if line.strip():
            new_lines.append("    " + line)
        else:
            new_lines.append(line)
    else:
        new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Fixed indentation for lines 209-483")
