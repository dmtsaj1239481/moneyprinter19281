import os

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []

for i, line in enumerate(lines):
    line_num = i + 1
    # Let's fix the block 208 to 483 specifically
    # If the line is between 209 and 483, we make sure it has at least 8 spaces of indentation
    # if it was inside the if block, and 4 if it was the if itself.
    if 209 <= line_num <= 483:
        # Original level was 4, now 8?
        # Let's just strip and add exactly 8 spaces for block level 1
        stripped = line.lstrip()
        indent_len = len(line) - len(stripped)
        # If the original line had X spaces, it now should have X spaces + 4.
        # But wait, my fix_indent.py already added 4.
        # So if it was "    config_panels", it became "        config_panels".
        new_lines.append(line)
    else:
        new_lines.append(line)

# Let's check for any line that might have 4 spaces but should have more
# e.g. lines inside if should have 8, lines inside expander should have 12.

# Actually, I'll just use a more professional approach: rewrite the first few lines manually
# to break the deadlock and then see.

lines[207] = "    if not config.app.get(\"hide_config\", False):\n"
lines[208] = "        with st.expander(tr(\"Basic Settings\"), expanded=False):\n"
lines[209] = "            config_panels = st.columns(3)\n"
lines[210] = "            left_config_panel = config_panels[0]\n"
lines[211] = "            middle_config_panel = config_panels[1]\n"
lines[212] = "            right_config_panel = config_panels[2]\n"

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
